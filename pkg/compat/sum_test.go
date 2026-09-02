package compat

import (
	"testing"

	"github.com/faults-lab/gus/pkg/types"
)

func rules(vs []types.Violation) []string {
	var out []string
	for _, v := range vs {
		out = append(out, v.Rule)
	}
	return out
}

func requireClean(t *testing.T, name string, vs []types.Violation) {
	t.Helper()
	if len(vs) != 0 {
		t.Errorf("%s: expected no violations, got %v", name, vs)
	}
}

func requireRule(t *testing.T, name string, vs []types.Violation, rule string, sev types.Severity) {
	t.Helper()
	for _, v := range vs {
		if v.Rule == rule && v.Severity == sev {
			return
		}
	}
	t.Errorf("%s: expected %s %s, got %v", name, sev, rule, rules(vs))
}

func enumOf(base string, vals ...string) *types.Node {
	n := types.Enum(vals)
	n.EnumBase = base
	return n
}

// A string enum may spell its values like numbers or booleans; the declared
// base type, not the spelling, decides whether it fits a primitive.
func TestEnumDeclaredBase(t *testing.T) {
	str := types.Prim("string", "")
	requireClean(t, "enum<string>{10,20} -> string REQ", Check(enumOf("string", "10", "20"), str, types.DirREQ, cfg()))
	requireClean(t, "string <- enum<string>{10,20} RES", Check(str, enumOf("string", "10", "20"), types.DirRES, cfg()))
	requireClean(t, "enum<string>{true,false} -> string REQ", Check(enumOf("string", "true", "false"), str, types.DirREQ, cfg()))
	// Declared integer values into a string receiver remain a strict-mode break.
	requireRule(t, "enum<integer>{10,20} -> string REQ", Check(enumOf("integer", "10", "20"), str, types.DirREQ, cfg()), "enum-prim-mismatch", types.SevBREAK)
	// Without a declared type the spelling is the only evidence (unchanged behavior).
	requireRule(t, "enum{10,20} (untyped) -> string REQ", Check(types.Enum([]string{"10", "20"}), str, types.DirREQ, cfg()), "enum-prim-mismatch", types.SevBREAK)
}

// Equal spellings under different declared bases are a type change.
func TestEnumBaseChange(t *testing.T) {
	requireRule(t, "enum<string>{1,2} -> enum<integer>{1,2} REQ",
		Check(enumOf("string", "1", "2"), enumOf("integer", "1", "2"), types.DirREQ, cfg()), "prim-mismatch", types.SevBREAK)
	// integer values into a number-typed enum receiver widen safely.
	requireClean(t, "enum<integer>{1,2} -> enum<number>{1,2} REQ",
		Check(enumOf("integer", "1", "2"), enumOf("number", "1", "2"), types.DirREQ, cfg()))
	requireRule(t, "enum<number> consumer <- enum<string> producer RES",
		Check(enumOf("number", "1", "2"), enumOf("string", "1", "2"), types.DirRES, cfg()), "prim-mismatch", types.SevBREAK)
}

// oneOf variants reached through $ref may themselves be unions; the variant
// sets compare flattened.
func TestNestedUnionFlattening(t *testing.T) {
	i32 := types.Prim("integer", "int32")
	str := types.Prim("string", "")
	b := types.Prim("boolean", "")
	nested := types.Union([]*types.Node{types.Union([]*types.Node{i32, str}), b})
	flat := types.Union([]*types.Node{i32, str, b})
	requireClean(t, "nested -> flat REQ", Check(nested, flat, types.DirREQ, cfg()))
	requireClean(t, "flat <- nested RES", Check(flat, nested, types.DirRES, cfg()))
	requireRule(t, "nested -> Union(i32,str) REQ drops boolean",
		Check(nested, types.Union([]*types.Node{i32, str}), types.DirREQ, cfg()), "union-request-narrowing", types.SevBREAK)
}

// A warning inside a union variant is reported, not swallowed, and does not
// escalate to a break.
func TestUnionCarriesWarnings(t *testing.T) {
	i32 := types.Prim("integer", "int32")
	i64 := types.Prim("integer", "int64")
	vs := Check(types.Union([]*types.Node{i64}), types.Union([]*types.Node{i32}), types.DirREQ, cfg())
	requireRule(t, "Union(int64) -> Union(int32) REQ", vs, "format-change", types.SevWARN)
	for _, v := range vs {
		if v.Severity == types.SevBREAK {
			t.Errorf("warning escalated to break: %v", v)
		}
	}
}

// Null admitted through a nullable variant of a union counts as admitted.
func TestNullableInsideUnion(t *testing.T) {
	str := types.Prim("string", "")
	i32 := types.Prim("integer", "int32")
	requireClean(t, "Nullable(str) -> Union(Nullable(str), int) REQ",
		Check(types.Nullable(str), types.Union([]*types.Node{types.Nullable(str), i32}), types.DirREQ, cfg()))
	requireClean(t, "Nullable(Union(str,int)) -> Union(Nullable(str), int) REQ",
		Check(types.Nullable(types.Union([]*types.Node{str, i32})), types.Union([]*types.Node{types.Nullable(str), i32}), types.DirREQ, cfg()))
	requireRule(t, "Nullable(str) -> Union(str,int) REQ",
		Check(types.Nullable(str), types.Union([]*types.Node{str, i32}), types.DirREQ, cfg()), "nullable-request-narrowing", types.SevBREAK)
	requireRule(t, "consumer Union(str,int) <- producer Union(Nullable(str), int) RES",
		Check(types.Union([]*types.Node{str, i32}), types.Union([]*types.Node{types.Nullable(str), i32}), types.DirRES, cfg()), "nullable-response-widening", types.SevBREAK)
	// The single-variant shortcut keeps the precise rule.
	requireRule(t, "Nullable(str) -> Nullable(int) REQ",
		Check(types.Nullable(str), types.Nullable(i32), types.DirREQ, cfg()), "prim-mismatch", types.SevBREAK)
}

// The loader qualifies Ref names by service; the two sides of an edge come
// from different documents, so the coinductive hypothesis keys on the
// component name alone.
func TestRefLocalName(t *testing.T) {
	requireClean(t, "frontend.Category vs productcatalog.Category",
		Check(types.Ref("frontend.Category"), types.Ref("productcatalog.Category"), types.DirREQ, cfg()))
	requireRule(t, "frontend.Category vs productcatalog.Node",
		Check(types.Ref("frontend.Category"), types.Ref("productcatalog.Node"), types.DirREQ, cfg()), "ref-name-mismatch", types.SevBREAK)
}
