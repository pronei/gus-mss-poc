// Package chain implements the data-flow chain integrity checker from the GUS paper.
// It discovers x-provides/x-requires chains in the service graph and validates
// monotonicity: every hop must preserve required/non-null properties.
package chain

import (
	"fmt"
	"strings"

	"github.com/faults-lab/gus/pkg/types"
)

// Annotation represents an x-provides or x-requires annotation found in a spec.
type Annotation struct {
	Service  string
	Version  string
	Path     string // endpoint path
	Field    string // field name (dot-separated for nested, e.g., "order.order_id")
	Key      string // the identity key, e.g., "order-identity"
	Kind     string // "provides" or "requires"
	Required bool   // whether the field is required in the schema
	Nullable bool   // whether the field is nullable
}

// ChainResult holds the result of a chain integrity check.
type ChainResult struct {
	Key       string
	Provider  Annotation
	Requirer  Annotation
	OK        bool
	Message   string
	ChainPath []string // service names in the discovered chain
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

// EdgeInfo represents a directed edge for chain discovery.
type EdgeInfo struct {
	Caller   string
	Provider string
}

// FieldInfo represents a field at a specific service for chain tracing.
type FieldInfo struct {
	Name     string
	Required bool
	Nullable bool
	Alias    string // x-alias value if present
}

// CheckChains discovers and validates all x-provides/x-requires chains.
// fieldLookup returns field metadata for a given service and field name,
// or nil if the field does not exist at that service.
func CheckChains(
	annotations []Annotation,
	edges []EdgeInfo,
	fieldLookup func(service, fieldName string) *FieldInfo,
) []ChainResult {
	// Group annotations by key
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

	// Build adjacency list for BFS
	adj := make(map[string][]string)
	for _, e := range edges {
		adj[e.Caller] = append(adj[e.Caller], e.Provider)
	}

	var results []ChainResult

	// For each key that has both a provider and a requirer, check the chain
	for key, provs := range providers {
		reqs, ok := requirers[key]
		if !ok {
			continue
		}
		for _, prov := range provs {
			for _, req := range reqs {
				result := checkChain(key, prov, req, adj, fieldLookup)
				results = append(results, result)
			}
		}
	}

	return results
}

func checkChain(
	key string,
	provider, requirer Annotation,
	adj map[string][]string,
	fieldLookup func(service, fieldName string) *FieldInfo,
) ChainResult {
	result := ChainResult{
		Key:      key,
		Provider: provider,
		Requirer: requirer,
	}

	// BFS from provider to requirer
	path := bfsPath(provider.Service, requirer.Service, adj)
	if path == nil {
		result.OK = false
		result.Message = fmt.Sprintf("no path from %s to %s in the service graph",
			provider.Service, requirer.Service)
		return result
	}
	result.ChainPath = path

	// Trace the field through each hop, checking monotonicity.
	// Extract the leaf field name from a dot-separated path.
	currentFieldName := provider.Field
	parts := strings.Split(currentFieldName, ".")
	currentFieldName = parts[len(parts)-1]

	for _, svc := range path {
		fi := resolveField(fieldLookup, svc, currentFieldName)
		if fi == nil {
			result.OK = false
			result.Message = fmt.Sprintf(
				"field %q not found at service %s (chain broken -- add x-alias if renamed)",
				currentFieldName, svc)
			return result
		}

		// Monotonicity: if the requirer needs a required field,
		// every intermediate hop must also have it required.
		if !fi.Required && requirer.Required {
			result.OK = false
			result.Message = fmt.Sprintf(
				"field %q is optional at %s but required at sink %s (chain weakened)",
				currentFieldName, svc, requirer.Service)
			return result
		}

		// Nullable check: if the requirer needs non-null, hops must not be nullable.
		if fi.Nullable && requirer.Required {
			result.OK = false
			result.Message = fmt.Sprintf(
				"field %q is nullable at %s but required non-null at sink %s",
				currentFieldName, svc, requirer.Service)
			return result
		}

		// Follow alias if present (field was renamed at this service)
		if fi.Alias != "" {
			currentFieldName = fi.Alias
		}
	}

	result.OK = true
	result.Message = "chain intact"
	return result
}

// resolveField tries to find a field at a service using a 3-tier strategy:
//  1. Exact name match
//  2. Case-normalized match (lowercased)
//  3. x-alias fallback (the fieldLookup is expected to handle alias indexing)
func resolveField(
	fieldLookup func(service, fieldName string) *FieldInfo,
	service, fieldName string,
) *FieldInfo {
	// Tier 1: exact match
	fi := fieldLookup(service, fieldName)
	if fi != nil {
		return fi
	}

	// Tier 2: case-normalized match
	lower := strings.ToLower(fieldName)
	if lower != fieldName {
		fi = fieldLookup(service, lower)
		if fi != nil {
			return fi
		}
	}

	// Tier 3: the fieldLookup implementation should internally check x-alias.
	// We cannot do more here without access to the full field set,
	// so return nil and let the caller report the break.
	return nil
}

// bfsPath finds the shortest path from 'from' to 'to' in the adjacency graph.
// Returns nil if no path exists.
func bfsPath(from, to string, adj map[string][]string) []string {
	if from == to {
		return []string{from}
	}

	visited := map[string]bool{from: true}
	parent := map[string]string{}

	queue := []string{from}
	for len(queue) > 0 {
		current := queue[0]
		queue = queue[1:]

		for _, next := range adj[current] {
			if visited[next] {
				continue
			}
			visited[next] = true
			parent[next] = current

			if next == to {
				// Reconstruct path
				var path []string
				for n := to; n != ""; n = parent[n] {
					path = append([]string{n}, path...)
				}
				return path
			}

			queue = append(queue, next)
		}
	}

	return nil
}

// ScanAnnotations extracts x-provides/x-requires annotations from a types.Node tree.
// It walks the type AST recursively, collecting annotations from Object fields.
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
		for name, f := range node.Fields {
			fp := name
			if fieldPath != "" {
				fp = fieldPath + "." + name
			}

			if f.XProvides != "" {
				*out = append(*out, Annotation{
					Service:  service,
					Version:  version,
					Path:     endpoint,
					Field:    fp,
					Key:      f.XProvides,
					Kind:     "provides",
					Required: f.Required,
					Nullable: isNullable(f.Schema),
				})
			}
			if f.XRequires != "" {
				*out = append(*out, Annotation{
					Service:  service,
					Version:  version,
					Path:     endpoint,
					Field:    fp,
					Key:      f.XRequires,
					Kind:     "requires",
					Required: f.Required,
					Nullable: isNullable(f.Schema),
				})
			}

			// Recurse into the field's schema
			scanNode(f.Schema, service, version, endpoint, fp, out)
		}

	case types.KindArray:
		if node.Items != nil {
			scanNode(node.Items, service, version, endpoint, fieldPath+"[*]", out)
		}

	case types.KindNullable:
		if node.Inner != nil {
			scanNode(node.Inner, service, version, endpoint, fieldPath, out)
		}
	}
}

// isNullable checks whether a types.Node is nullable.
func isNullable(n *types.Node) bool {
	if n == nil {
		return false
	}
	return n.Kind == types.KindNullable
}
