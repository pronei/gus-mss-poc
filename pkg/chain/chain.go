// Package chain implements the data-flow chain integrity checker (deck
// slides 8–9). A source declares x-provides: K on the field that originates
// identity K; a sink declares x-requires: K on the field where K must arrive.
// The checker discovers a call-graph path from source to sink and validates,
// at the given deployment state, that every hop still carries the field
// present, non-null, and type-compatible with the sink's declaration.
//
// Semantics notes (deliberate POC choices):
//   - x-requires itself IS the requirement: the sink's field may be
//     schema-optional (so every per-edge check passes — the exact bug class
//     pairwise tools miss) while the annotation demands presence end-to-end.
//   - Identity typing is strict: an identity is correlated/stored, not merely
//     parsed, so the provider's declared type must be admitted by the sink's
//     declared type under the STRICT lattice regardless of any lenient
//     coercion profile in force for edge checks.
//   - Path discovery walks forward call edges (caller→provider) only. An
//     identity carried in a response flows to the provider's caller, which a
//     forward walk cannot represent; this checker therefore only supports
//     identities that travel in request payloads hop by hop.
package chain

import (
	"fmt"
	"sort"
	"strings"

	"github.com/faults-lab/gus/pkg/compat"
	"github.com/faults-lab/gus/pkg/lattice"
	"github.com/faults-lab/gus/pkg/types"
)

// Annotation represents an x-provides or x-requires annotation found in a spec.
type Annotation struct {
	Service  string
	Version  string
	Endpoint string // "METHOD /path" the annotation was found under
	Field    string // dot-separated field path, e.g. "order.order_id"
	Key      string // the identity key, e.g. "order-identity"
	Kind     string // "provides" or "requires"
	Required bool
	Nullable bool
	Schema   *types.Node // declared type of the annotated field
}

// FieldInfo is the resolved carrier of an identity at one service.
type FieldInfo struct {
	Name     string // actual field name at this service (after alias resolution)
	Required bool
	Nullable bool
	Schema   *types.Node
}

// ChainResult holds the result of a chain integrity check.
type ChainResult struct {
	Key       string
	Provider  Annotation
	Requirer  Annotation
	OK        bool
	Rule      string // chain-no-path | chain-field-missing | chain-weakened | chain-nullable | chain-type-mismatch | ""
	Message   string
	ChainPath []string // service names on the discovered path
	Culprits  []string // upgrading services whose change broke the chain (filled by the caller)
}

func (r ChainResult) String() string {
	status := "OK"
	if !r.OK {
		status = "BREAK"
	}
	return fmt.Sprintf("Chain %s [%s]: %s -> %s: %s -- %s",
		r.Key, status, r.Provider.Service, r.Requirer.Service,
		strings.Join(r.ChainPath, " -> "), r.Message)
}

// EdgeInfo represents a directed call edge for chain discovery.
type EdgeInfo struct {
	Caller   string
	Provider string
}

// FieldLookup resolves the carrier of an identity at an intermediate hop:
// the field named fieldName in what `service` SENDS toward `next` (its
// outbound request schema for that edge), applying the resolver tiers
// (exact, case-normalized, x-alias). Implementations may fall back to
// searching all of the service's schemas when no outbound contract is
// declared. Nil means not found.
type FieldLookup func(service, next, fieldName string) *FieldInfo

// CheckChains discovers and validates all x-provides/x-requires chains.
func CheckChains(annotations []Annotation, edges []EdgeInfo, lookup FieldLookup) []ChainResult {
	providers := make(map[string][]Annotation)
	requirers := make(map[string][]Annotation)
	for _, a := range annotations {
		switch a.Kind {
		case "provides":
			providers[a.Key] = append(providers[a.Key], a)
		case "requires":
			requirers[a.Key] = append(requirers[a.Key], a)
		}
	}

	keys := make([]string, 0, len(providers))
	for key := range providers {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	var results []ChainResult
	for _, key := range keys {
		reqs, ok := requirers[key]
		if !ok {
			continue
		}
		for _, prov := range providers[key] {
			for _, req := range reqs {
				results = append(results, checkChain(key, prov, req, edges, lookup))
			}
		}
	}
	return results
}

// checkChain validates one (provider, requirer) pair over EVERY simple call
// path between them: statically we cannot know which route traffic takes, so
// each path must carry the identity. The first failing path (in a
// deterministic short-paths-first order) is reported; if all paths carry the
// identity, the first path's passing result is returned.
func checkChain(key string, provider, requirer Annotation, edges []EdgeInfo, lookup FieldLookup) ChainResult {
	paths := AllPaths(provider.Service, requirer.Service, edges, maxChainHops)
	if len(paths) == 0 {
		return CheckChainOnPath(key, provider, requirer, nil, lookup)
	}
	sort.Slice(paths, func(i, j int) bool {
		if len(paths[i]) != len(paths[j]) {
			return len(paths[i]) < len(paths[j])
		}
		return strings.Join(paths[i], ">") < strings.Join(paths[j], ">")
	})

	first := CheckChainOnPath(key, provider, requirer, paths[0], lookup)
	if !first.OK {
		return first
	}
	for _, p := range paths[1:] {
		if r := CheckChainOnPath(key, provider, requirer, p, lookup); !r.OK {
			return r
		}
	}
	return first
}

// maxChainHops bounds simple-path enumeration; real identity chains are
// short, and the bound keeps the enumeration linear-ish on sparse meshes.
const maxChainHops = 6

// CheckChainOnPath validates one identity along one explicit call path.
// A nil path reports chain-no-path. Exposed so callers that enumerate
// multiple upgrade paths (see AllPaths and gus evolve) can validate each
// path independently — data may flow along any of them.
func CheckChainOnPath(key string, provider, requirer Annotation, path []string, lookup FieldLookup) ChainResult {
	result := ChainResult{Key: key, Provider: provider, Requirer: requirer}

	if path == nil {
		result.Rule = "chain-no-path"
		result.Message = fmt.Sprintf("no call path from %s to %s in the service graph",
			provider.Service, requirer.Service)
		return result
	}
	result.ChainPath = path

	// Trace the identity's GUARANTEE through the emitting hops: the source's
	// annotated field itself, then each intermediate. x-requires demands the
	// identity arrive present and non-null, whatever any hop's accept schema
	// tolerates — the sink's own schema-optionality is deliberately NOT a
	// weakening (that tolerance is exactly what lets every per-edge check
	// pass while the chain still fails).
	parts := strings.Split(provider.Field, ".")
	currentField := parts[len(parts)-1]

	// Source hop: judged by the annotation, not by name lookup (the same
	// field name may appear in several of the source's schemas).
	if !provider.Required {
		result.Rule = "chain-weakened"
		result.Message = fmt.Sprintf(
			"providing field %q is optional at source %s but identity %q must arrive present at sink %s",
			currentField, provider.Service, key, requirer.Service)
		return result
	}
	if provider.Nullable {
		result.Rule = "chain-nullable"
		result.Message = fmt.Sprintf(
			"providing field %q is nullable at source %s but identity %q must arrive non-null at sink %s",
			currentField, provider.Service, key, requirer.Service)
		return result
	}

	for i := 1; i < len(path)-1; i++ {
		svc, next := path[i], path[i+1]
		fi := lookup(svc, next, currentField)
		if fi == nil {
			result.Rule = "chain-field-missing"
			result.Message = fmt.Sprintf(
				"field %q not found at intermediate %s (chain broken — declare x-alias at the renaming hop)",
				currentField, svc)
			return result
		}
		if !fi.Required {
			result.Rule = "chain-weakened"
			result.Message = fmt.Sprintf(
				"field %q is optional at %s but identity %q must arrive present at sink %s",
				fi.Name, svc, key, requirer.Service)
			return result
		}
		if fi.Nullable {
			result.Rule = "chain-nullable"
			result.Message = fmt.Sprintf(
				"field %q is nullable at %s but identity %q must arrive non-null at sink %s",
				fi.Name, svc, key, requirer.Service)
			return result
		}
		currentField = fi.Name
	}

	// Identity typing: the provider's declared type must be admitted by the
	// sink's declared type under the strict lattice.
	if provider.Schema != nil && requirer.Schema != nil {
		strict := compat.Config{Format: lattice.FormatJSON, Coercion: lattice.CoercionStrict}
		if vs := compat.Check(provider.Schema, requirer.Schema, types.DirREQ, strict); len(vs) > 0 {
			result.Rule = "chain-type-mismatch"
			result.Message = fmt.Sprintf(
				"identity %q is provided as %s by %s but required as %s by %s (identities are strictly typed)",
				key, provider.Schema.Summary(), provider.Service,
				requirer.Schema.Summary(), requirer.Service)
			return result
		}
	}

	result.OK = true
	result.Message = "chain intact"
	return result
}

// AllPaths enumerates every simple path from 'from' to 'to' up to maxHops
// edges long, in deterministic order. Multi-path meshes (diamonds) can carry
// an identity along any route; a checker that validates only the shortest
// path can miss the route the traffic actually takes.
func AllPaths(from, to string, edges []EdgeInfo, maxHops int) [][]string {
	adj := make(map[string][]string)
	for _, e := range edges {
		adj[e.Caller] = append(adj[e.Caller], e.Provider)
	}
	for k := range adj {
		sort.Strings(adj[k])
	}

	var paths [][]string
	onPath := map[string]bool{from: true}
	var walk func(node string, path []string)
	walk = func(node string, path []string) {
		if node == to {
			paths = append(paths, append([]string(nil), path...))
			return
		}
		if len(path) > maxHops {
			return
		}
		for _, next := range adj[node] {
			if onPath[next] {
				continue
			}
			onPath[next] = true
			walk(next, append(path, next))
			onPath[next] = false
		}
	}
	walk(from, []string{from})
	return paths
}

// ScanAnnotations extracts x-provides/x-requires annotations from a types.Node
// tree (one endpoint schema).
func ScanAnnotations(node *types.Node, service, version, endpoint string) []Annotation {
	var annotations []Annotation
	scanNode(node, service, version, endpoint, "", &annotations)
	return annotations
}

func scanNode(node *types.Node, service, version, endpoint, fieldPath string, out *[]Annotation) {
	if node == nil {
		return
	}
	switch node.Kind {
	case types.KindObject:
		names := make([]string, 0, len(node.Fields))
		for name := range node.Fields {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			f := node.Fields[name]
			fp := name
			if fieldPath != "" {
				fp = fieldPath + "." + name
			}
			if f.XProvides != "" {
				*out = append(*out, Annotation{
					Service: service, Version: version, Endpoint: endpoint,
					Field: fp, Key: f.XProvides, Kind: "provides",
					Required: f.Required, Nullable: isNullable(f.Schema),
					Schema: unwrap(f.Schema),
				})
			}
			if f.XRequires != "" {
				*out = append(*out, Annotation{
					Service: service, Version: version, Endpoint: endpoint,
					Field: fp, Key: f.XRequires, Kind: "requires",
					Required: f.Required, Nullable: isNullable(f.Schema),
					Schema: unwrap(f.Schema),
				})
			}
			scanNode(f.Schema, service, version, endpoint, fp, out)
		}
	case types.KindArray:
		scanNode(node.Items, service, version, endpoint, fieldPath+"[*]", out)
	case types.KindNullable:
		scanNode(node.Inner, service, version, endpoint, fieldPath, out)
	}
}

func isNullable(n *types.Node) bool {
	return n != nil && n.Kind == types.KindNullable
}

func unwrap(n *types.Node) *types.Node {
	if n != nil && n.Kind == types.KindNullable {
		return n.Inner
	}
	return n
}
