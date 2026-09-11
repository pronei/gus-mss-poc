package chain

import (
	"strings"
	"testing"

	"github.com/faults-lab/gus/pkg/types"
)

// hop describes what one service sends onward: field name -> info, plus the
// x-alias declarations (new name -> previous name) the real resolver honours.
type hop struct {
	fields map[string]FieldInfo
	alias  map[string]string // renamed field -> the name it carries forward
}

type meshDB map[string]hop

// lookup mimics the resolver tiers of cmd/gus: exact name, case-normalized
// name, then a field declaring x-alias: <fieldName>.
func (db meshDB) lookup() FieldLookup {
	return func(svc, next, field string) *FieldInfo {
		h, ok := db[svc]
		if !ok {
			return nil
		}
		if fi, ok := h.fields[field]; ok {
			fi := fi
			return &fi
		}
		for name, fi := range h.fields {
			if strings.EqualFold(name, field) {
				fi := fi
				return &fi
			}
		}
		for renamed, prev := range h.alias {
			if prev == field {
				fi := h.fields[renamed]
				return &fi
			}
		}
		return nil
	}
}

func req(name string) FieldInfo { return FieldInfo{Name: name, Required: true} }

func provides(svc, field, key string, required bool) Annotation {
	return Annotation{Service: svc, Field: field, Key: key, Kind: "provides", Required: required}
}

func requires(svc, field, key string) Annotation {
	return Annotation{Service: svc, Field: field, Key: key, Kind: "requires", Required: true}
}

func only(t *testing.T, rs []ChainResult) ChainResult {
	t.Helper()
	if len(rs) != 1 {
		t.Fatalf("expected exactly 1 chain result, got %d: %v", len(rs), rs)
	}
	return rs[0]
}

func linearEdges(svcs ...string) []EdgeInfo {
	var e []EdgeInfo
	for i := 0; i+1 < len(svcs); i++ {
		e = append(e, EdgeInfo{Caller: svcs[i], Provider: svcs[i+1]})
	}
	return e
}

func TestChainIntact(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"k": req("k")}},
		"B": {fields: map[string]FieldInfo{"k": req("k")}},
		"C": {fields: map[string]FieldInfo{"k": req("k")}},
	}
	r := only(t, CheckChains(
		[]Annotation{provides("A", "k", "K", true), requires("D", "k", "K")},
		linearEdges("A", "B", "C", "D"), db.lookup()))
	if !r.OK {
		t.Fatalf("expected intact chain, got break: %s", r.Message)
	}
	if got := strings.Join(r.ChainPath, "->"); got != "A->B->C->D" {
		t.Errorf("chain path = %q, want A->B->C->D", got)
	}
}

// The source is judged by its annotation, not by name lookup.
func TestChainWeakenedAtSource(t *testing.T) {
	db := meshDB{"A": {fields: map[string]FieldInfo{"k": req("k")}}}
	r := only(t, CheckChains(
		[]Annotation{provides("A", "k", "K", false), requires("B", "k", "K")},
		linearEdges("A", "B"), db.lookup()))
	if r.OK || r.Rule != "chain-weakened" {
		t.Errorf("optional source must break as chain-weakened, got OK=%v rule=%s", r.OK, r.Rule)
	}
}

func TestChainWeakenedByOptionalHop(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"k": req("k")}},
		"B": {fields: map[string]FieldInfo{"k": {Name: "k", Required: false}}},
	}
	r := only(t, CheckChains(
		[]Annotation{provides("A", "k", "K", true), requires("C", "k", "K")},
		linearEdges("A", "B", "C"), db.lookup()))
	if r.OK || r.Rule != "chain-weakened" || !strings.Contains(r.Message, "B") {
		t.Errorf("expected chain-weakened at B, got OK=%v rule=%s msg=%q", r.OK, r.Rule, r.Message)
	}
}

func TestChainBrokenByNullableHop(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"k": req("k")}},
		"B": {fields: map[string]FieldInfo{"k": {Name: "k", Required: true, Nullable: true}}},
	}
	r := only(t, CheckChains(
		[]Annotation{provides("A", "k", "K", true), requires("C", "k", "K")},
		linearEdges("A", "B", "C"), db.lookup()))
	if r.OK || r.Rule != "chain-nullable" {
		t.Errorf("expected chain-nullable, got OK=%v rule=%s", r.OK, r.Rule)
	}
}

func TestChainNoPath(t *testing.T) {
	db := meshDB{"A": {fields: map[string]FieldInfo{"k": req("k")}}}
	r := only(t, CheckChains(
		[]Annotation{provides("A", "k", "K", true), requires("D", "k", "K")},
		[]EdgeInfo{{Caller: "A", Provider: "B"}}, db.lookup()))
	if r.OK || r.Rule != "chain-no-path" {
		t.Errorf("expected chain-no-path, got OK=%v rule=%s", r.OK, r.Rule)
	}
}

func TestChainFieldMissingAtHop(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"k": req("k")}},
		"B": {fields: map[string]FieldInfo{}},
	}
	r := only(t, CheckChains(
		[]Annotation{provides("A", "k", "K", true), requires("C", "k", "K")},
		linearEdges("A", "B", "C"), db.lookup()))
	if r.OK || r.Rule != "chain-field-missing" {
		t.Errorf("expected chain-field-missing, got OK=%v rule=%s", r.OK, r.Rule)
	}
}

// A rename at B (traceId declares x-alias: correlationId) keeps the chain
// intact, and the carried name changes for the hops after it.
func TestChainFollowsAlias(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"correlationId": req("correlationId")}},
		"B": {fields: map[string]FieldInfo{"traceId": req("traceId")}, alias: map[string]string{"traceId": "correlationId"}},
		"C": {fields: map[string]FieldInfo{"traceId": req("traceId")}},
	}
	r := only(t, CheckChains(
		[]Annotation{provides("A", "correlationId", "K", true), requires("D", "traceId", "K")},
		linearEdges("A", "B", "C", "D"), db.lookup()))
	if !r.OK {
		t.Fatalf("alias chain should stay intact, got break: %s", r.Message)
	}
}

// Identities are strictly typed end to end, whatever the coercion profile.
func TestChainTypeMismatch(t *testing.T) {
	db := meshDB{"A": {fields: map[string]FieldInfo{"k": req("k")}}}
	p := provides("A", "k", "K", true)
	p.Schema = types.Prim("integer", "")
	q := requires("B", "k", "K")
	q.Schema = types.Prim("string", "")
	r := only(t, CheckChains([]Annotation{p, q}, linearEdges("A", "B"), db.lookup()))
	if r.OK || r.Rule != "chain-type-mismatch" {
		t.Errorf("integer provided, string required must break, got OK=%v rule=%s", r.OK, r.Rule)
	}
}

// Every simple path must carry the identity: in a diamond, a hop on the
// second route that drops the field breaks the chain even though the
// shortest route is intact.
func TestChainAllPathsValidated(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"k": req("k")}},
		"B": {fields: map[string]FieldInfo{"k": req("k")}},
		"C": {fields: map[string]FieldInfo{}}, // drops the field
	}
	edges := []EdgeInfo{{Caller: "A", Provider: "D"}, {Caller: "A", Provider: "B"}, {Caller: "B", Provider: "C"}, {Caller: "C", Provider: "D"}}
	r := only(t, CheckChains([]Annotation{provides("A", "k", "K", true), requires("D", "k", "K")}, edges, db.lookup()))
	if r.OK || r.Rule != "chain-field-missing" || !strings.Contains(r.Message, "C") {
		t.Errorf("the longer route must be validated too, got OK=%v rule=%s msg=%q", r.OK, r.Rule, r.Message)
	}
}

func TestChainOnlyProviderOrRequirerYieldsNothing(t *testing.T) {
	db := meshDB{"A": {fields: map[string]FieldInfo{"k": req("k")}}}
	if res := CheckChains([]Annotation{provides("A", "k", "K", true)}, nil, db.lookup()); len(res) != 0 {
		t.Errorf("provider-only should yield no chains, got %d", len(res))
	}
	if res := CheckChains([]Annotation{requires("A", "k", "K")}, nil, db.lookup()); len(res) != 0 {
		t.Errorf("requirer-only should yield no chains, got %d", len(res))
	}
}

func TestChainMultipleRequirersCartesian(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"k": req("k")}},
		"C": {fields: map[string]FieldInfo{"k": req("k")}},
	}
	res := CheckChains(
		[]Annotation{provides("A", "k", "K", true), requires("C", "k", "K"), requires("D", "k", "K")},
		linearEdges("A", "C", "D"), db.lookup())
	if len(res) != 2 {
		t.Fatalf("expected 2 chains (one provider x two requirers), got %d", len(res))
	}
}

func TestAllPaths(t *testing.T) {
	edges := []EdgeInfo{{Caller: "A", Provider: "B"}, {Caller: "A", Provider: "C"}, {Caller: "B", Provider: "D"}, {Caller: "C", Provider: "D"}}
	if got := AllPaths("A", "A", edges, 6); len(got) != 1 || len(got[0]) != 1 {
		t.Errorf("self path = %v, want [[A]]", got)
	}
	if got := AllPaths("A", "D", edges, 6); len(got) != 2 {
		t.Errorf("diamond A->D should have 2 simple paths, got %v", got)
	}
	if got := AllPaths("D", "A", edges, 6); len(got) != 0 {
		t.Errorf("D->A should be unreachable, got %v", got)
	}
	if got := AllPaths("A", "D", edges, 1); len(got) != 0 {
		t.Errorf("hop bound 1 must exclude the two-hop routes, got %v", got)
	}
}

func TestScanAnnotations(t *testing.T) {
	node := types.Object(map[string]*types.Field{
		"order_id": {Schema: types.Prim("string", ""), Required: true, XProvides: "order-identity"},
		"meta": {Schema: types.Object(map[string]*types.Field{
			"trace": {Schema: types.Prim("string", ""), XRequires: "trace-id"},
		}, true)},
		"items": {Schema: types.Array(types.Object(map[string]*types.Field{
			"sku": {Schema: types.Prim("string", ""), XProvides: "sku-id"},
		}, true))},
		"opt": {Schema: types.Nullable(types.Prim("string", "")), XProvides: "opt-key"},
	}, true)

	byField := map[string]Annotation{}
	for _, a := range ScanAnnotations(node, "svcA", "v1", "POST /x") {
		byField[a.Field] = a
	}
	if a, ok := byField["order_id"]; !ok || a.Kind != "provides" || a.Key != "order-identity" || !a.Required {
		t.Errorf("order_id annotation wrong: %+v", a)
	}
	if a, ok := byField["meta.trace"]; !ok || a.Kind != "requires" || a.Key != "trace-id" {
		t.Errorf("nested meta.trace annotation wrong/missing: %+v", a)
	}
	if a, ok := byField["items[*].sku"]; !ok || a.Kind != "provides" || a.Key != "sku-id" {
		t.Errorf("array items[*].sku annotation wrong/missing: %+v", a)
	}
	if a, ok := byField["opt"]; !ok || !a.Nullable || a.Schema.Kind != types.KindPrim {
		t.Errorf("nullable field annotation should be marked nullable with the inner schema: %+v", a)
	}
}

// Property names may themselves contain dots (OpenTelemetry attributes such
// as "http.request.method"); the walk must look the field up by its own
// name, not by the last dot-separated segment of the annotation path.
func TestChainDottedPropertyName(t *testing.T) {
	db := meshDB{
		"A": {fields: map[string]FieldInfo{"http.request.method": req("http.request.method")}},
		"B": {fields: map[string]FieldInfo{"http.request.method": req("http.request.method")}},
	}
	prov := provides("A", "http.request.method", "K", true)
	prov.Leaf = "http.request.method"
	r := only(t, CheckChains(
		[]Annotation{prov, requires("C", "http.request.method", "K")},
		linearEdges("A", "B", "C"), db.lookup()))
	if !r.OK {
		t.Fatalf("dotted property name must resolve at the hop, got %s: %s", r.Rule, r.Message)
	}
	// A hand-built annotation without Leaf keeps the old convention.
	if got := provides("A", "order.order_id", "K", true).LeafName(); got != "order_id" {
		t.Errorf("LeafName fallback = %q, want order_id", got)
	}
}

func TestScanAnnotationsRecordsLeaf(t *testing.T) {
	node := types.Object(map[string]*types.Field{
		"http.request.method": {Schema: types.Prim("string", ""), Required: true, XProvides: "http.server/http.request.method"},
		"meta": {Schema: types.Object(map[string]*types.Field{
			"trace.id": {Schema: types.Prim("string", ""), XRequires: "trace"},
		}, true)},
	}, true)
	byKey := map[string]Annotation{}
	for _, a := range ScanAnnotations(node, "svc", "v1", "POST /x") {
		byKey[a.Key] = a
	}
	if a := byKey["http.server/http.request.method"]; a.Leaf != "http.request.method" || a.LeafName() != "http.request.method" {
		t.Errorf("top-level dotted field: Leaf=%q Field=%q", a.Leaf, a.Field)
	}
	if a := byKey["trace"]; a.Field != "meta.trace.id" || a.Leaf != "trace.id" {
		t.Errorf("nested dotted field: Leaf=%q Field=%q", a.Leaf, a.Field)
	}
}
