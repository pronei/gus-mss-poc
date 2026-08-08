package compat

import (
	"testing"

	"github.com/faults-lab/gus/pkg/lattice"
	"github.com/faults-lab/gus/pkg/types"
)

func cfg() Config { return Config{Format: lattice.FormatJSON, Coercion: lattice.CoercionStrict} }

func lenientCfg() Config {
	return Config{Format: lattice.FormatJSON, Coercion: lattice.CoercionLenient}
}

func TestPrimLattice(t *testing.T) {
	tests := []struct {
		name    string
		left    *types.Node
		right   *types.Node
		dir     types.Direction
		lenient bool
		ok      bool
	}{
		{"int ⊑ num REQ", types.Prim("integer", ""), types.Prim("number", ""), types.DirREQ, false, true},
		{"int ⊑ int REQ", types.Prim("integer", ""), types.Prim("integer", ""), types.DirREQ, false, true},
		{"str ⊑ int REQ fail", types.Prim("string", ""), types.Prim("integer", ""), types.DirREQ, false, false},
		// Scalar-to-string coercion is NOT safe for strict decoders (Go
		// encoding/json, serde, pydantic v2) — only the lenient profile
		// (Jackson-style consumers) admits it.
		{"num ⊑ str REQ strict fail", types.Prim("number", ""), types.Prim("string", ""), types.DirREQ, false, false},
		{"bool ⊑ str REQ strict fail", types.Prim("boolean", ""), types.Prim("string", ""), types.DirREQ, false, false},
		{"num ⊑ str REQ lenient", types.Prim("number", ""), types.Prim("string", ""), types.DirREQ, true, true},
		{"bool ⊑ str REQ lenient", types.Prim("boolean", ""), types.Prim("string", ""), types.DirREQ, true, true},
		{"int ⊑ str REQ lenient", types.Prim("integer", ""), types.Prim("string", ""), types.DirREQ, true, true},
		// Response: producer (right) ≤ consumer (left).
		{"int RES num safe", types.Prim("number", ""), types.Prim("integer", ""), types.DirRES, false, true},
		{"str RES int strict fail", types.Prim("string", ""), types.Prim("integer", ""), types.DirRES, false, false},
		{"str RES int lenient", types.Prim("string", ""), types.Prim("integer", ""), types.DirRES, true, true},
		{"int RES str fail", types.Prim("integer", ""), types.Prim("string", ""), types.DirRES, false, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := cfg()
			if tt.lenient {
				c = lenientCfg()
			}
			vs := Check(tt.left, tt.right, tt.dir, c)
			got := len(vs) == 0
			if got != tt.ok {
				t.Errorf("got ok=%v, want %v (violations: %v)", got, tt.ok, vs)
			}
		})
	}
}

// The format-range check must flip variance with the direction: a producer
// widening a response int32→int64 endangers old int32 consumers, while the
// reverse narrowing is harmless to them.
func TestFormatDirection(t *testing.T) {
	i32 := types.Prim("integer", "int32")
	i64 := types.Prim("integer", "int64")

	// REQ: sender int64 into receiver int32 — overflow risk, WARN.
	if vs := Check(i64, i32, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("REQ int64 sender → int32 receiver should warn")
	}
	// REQ: sender int32 into receiver int64 — safe.
	if vs := Check(i32, i64, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("REQ int32 sender → int64 receiver should be clean, got %v", vs)
	}
	// RES: consumer expects int32, producer returns int64 — overflow risk, WARN.
	if vs := Check(i32, i64, types.DirRES, cfg()); len(vs) == 0 {
		t.Error("RES int64 producer → int32 consumer should warn")
	}
	// RES: consumer expects int64, producer returns int32 — safe.
	if vs := Check(i64, i32, types.DirRES, cfg()); len(vs) != 0 {
		t.Errorf("RES int32 producer → int64 consumer should be clean, got %v", vs)
	}
}

// Enum vs Prim follows value-set semantics instead of a blanket kind-mismatch.
func TestEnumPrim(t *testing.T) {
	enum := types.Enum([]string{"a", "b"})
	str := types.Prim("string", "")

	// REQ: enum sender → string receiver: receiver admits all strings — safe.
	if vs := Check(enum, str, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("REQ enum → string should be safe widening, got %v", vs)
	}
	// REQ: string sender → enum receiver: sender may send outside the set — break.
	if vs := Check(str, enum, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("REQ string → enum should break")
	}
	// RES: string consumer ← enum producer: safe narrowing.
	if vs := Check(str, enum, types.DirRES, cfg()); len(vs) != 0 {
		t.Errorf("RES enum producer to string consumer should be safe, got %v", vs)
	}
	// RES: enum consumer ← string producer: unknown values — break.
	if vs := Check(enum, str, types.DirRES, cfg()); len(vs) == 0 {
		t.Error("RES string producer to enum consumer should break")
	}
}

func TestObjectReqOptionalToRequired(t *testing.T) {
	sender := types.Object(map[string]*types.Field{
		"id": {Schema: types.Prim("string", ""), Required: false},
	}, true)
	receiver := types.Object(map[string]*types.Field{
		"id": {Schema: types.Prim("string", ""), Required: true},
	}, true)

	vs := Check(sender, receiver, types.DirREQ, cfg())
	if len(vs) == 0 || vs[0].Rule != "REQ.2" {
		t.Fatalf("expected REQ.2 for sender-optional/receiver-required, got %v", vs)
	}
}

func TestObjectResRequiredToOptional(t *testing.T) {
	consumer := types.Object(map[string]*types.Field{
		"id": {Schema: types.Prim("string", ""), Required: true},
	}, true)
	producer := types.Object(map[string]*types.Field{
		"id": {Schema: types.Prim("string", ""), Required: false},
	}, true)

	vs := Check(consumer, producer, types.DirRES, cfg())
	if len(vs) == 0 || vs[0].Rule != "RES.4" {
		t.Fatalf("expected RES.4 for consumer-required/producer-optional, got %v", vs)
	}
}

func TestObjectResClosedConsumer(t *testing.T) {
	consumer := types.Object(map[string]*types.Field{
		"a": {Schema: types.Prim("string", ""), Required: true},
	}, false) // closed: strict consumer rejects unknown fields
	producer := types.Object(map[string]*types.Field{
		"a": {Schema: types.Prim("string", ""), Required: true},
		"b": {Schema: types.Prim("string", ""), Required: false},
	}, true)

	vs := Check(consumer, producer, types.DirRES, cfg())
	if len(vs) == 0 || vs[0].Rule != "RES.5" {
		t.Fatalf("expected RES.5 for extra field into closed consumer, got %v", vs)
	}
}

// A WARN-only variant pair must still count as a union match — wrapping a
// type in oneOf must not escalate a warning into a break.
func TestUnionWarnOnlyMatch(t *testing.T) {
	u64 := types.Union([]*types.Node{types.Prim("integer", "int64")})
	u32 := types.Union([]*types.Node{types.Prim("integer", "int32")})

	vs := Check(u64, u32, types.DirREQ, cfg())
	for _, v := range vs {
		if v.Severity == types.SevBREAK {
			t.Fatalf("WARN-only variant pair escalated to BREAK: %v", vs)
		}
	}
}

// Width subtyping: T ≤ Union{T, ...} on the request side.
func TestUnionWidth(t *testing.T) {
	str := types.Prim("string", "")
	u := types.Union([]*types.Node{types.Prim("string", ""), types.Prim("integer", "")})

	if vs := Check(str, u, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("string ≤ union{string,integer} REQ should hold, got %v", vs)
	}
	if vs := Check(u, str, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("union{string,integer} ≤ string REQ should break (integer variant unmatched)")
	}
}

// Literals must respect base types and direction.
func TestLiteralRules(t *testing.T) {
	// REQ: literal "abc" into an integer receiver must break.
	if vs := Check(types.Literal("abc"), types.Prim("integer", ""), types.DirREQ, cfg()); len(vs) == 0 {
		t.Error(`REQ literal "abc" → integer should break`)
	}
	// REQ: literal "abc" into a string receiver is fine.
	if vs := Check(types.Literal("abc"), types.Prim("string", ""), types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf(`REQ literal "abc" → string should hold, got %v`, vs)
	}
	// RES: consumer expects exactly "v1", producer returns arbitrary strings — break.
	if vs := Check(types.Literal("v1"), types.Prim("string", ""), types.DirRES, cfg()); len(vs) == 0 {
		t.Error(`RES literal-expectation vs string producer should break`)
	}
	// RES: consumer expects string, producer returns exactly "v1" — safe.
	if vs := Check(types.Prim("string", ""), types.Literal("v1"), types.DirRES, cfg()); len(vs) != 0 {
		t.Errorf("RES string consumer vs literal producer should hold, got %v", vs)
	}
}

func TestEnumSubset(t *testing.T) {
	old := types.Enum([]string{"a", "b", "c"})
	wider := types.Enum([]string{"a", "b", "c", "d"})
	narrower := types.Enum([]string{"a", "b"})

	// REQ: old ⊆ new (new accepts at least what old accepted)
	if vs := Check(old, wider, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("REQ enum widening should be safe, got %v", vs)
	}
	if vs := Check(old, narrower, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("REQ enum narrowing should break")
	}

	// RES: new ⊆ old (new only returns values old understands)
	if vs := Check(old, narrower, types.DirRES, cfg()); len(vs) != 0 {
		t.Errorf("RES enum narrowing should be safe, got %v", vs)
	}
	if vs := Check(old, wider, types.DirRES, cfg()); len(vs) == 0 {
		t.Error("RES enum widening should break")
	}
}

func TestObjectReqNewRequired(t *testing.T) {
	old := types.Object(map[string]*types.Field{
		"name": {Schema: types.Prim("string", ""), Required: true},
	}, true)
	new := types.Object(map[string]*types.Field{
		"name":  {Schema: types.Prim("string", ""), Required: true},
		"email": {Schema: types.Prim("string", ""), Required: true, HasDefault: false},
	}, true)

	vs := Check(old, new, types.DirREQ, cfg())
	if len(vs) == 0 {
		t.Fatal("new required field without default should break")
	}
	if vs[0].Rule != "REQ.1" {
		t.Errorf("expected rule REQ.1, got %s", vs[0].Rule)
	}
}

func TestObjectReqNewRequiredWithDefault(t *testing.T) {
	old := types.Object(map[string]*types.Field{
		"name": {Schema: types.Prim("string", ""), Required: true},
	}, true)
	new := types.Object(map[string]*types.Field{
		"name":  {Schema: types.Prim("string", ""), Required: true},
		"email": {Schema: types.Prim("string", ""), Required: true, HasDefault: true},
	}, true)

	vs := Check(old, new, types.DirREQ, cfg())
	if len(vs) != 0 {
		t.Errorf("new required field WITH default should be safe, got %v", vs)
	}
}

func TestObjectResRequiredRemoved(t *testing.T) {
	old := types.Object(map[string]*types.Field{
		"id":   {Schema: types.Prim("string", ""), Required: true},
		"name": {Schema: types.Prim("string", ""), Required: true},
	}, true)
	new := types.Object(map[string]*types.Field{
		"name": {Schema: types.Prim("string", ""), Required: true},
	}, true)

	vs := Check(old, new, types.DirRES, cfg())
	if len(vs) == 0 {
		t.Fatal("removing required response field should break")
	}
	if vs[0].Rule != "RES.1" {
		t.Errorf("expected rule RES.1, got %s", vs[0].Rule)
	}
}

func TestObjectClosedFieldRemoval(t *testing.T) {
	old := types.Object(map[string]*types.Field{
		"a": {Schema: types.Prim("string", ""), Required: false},
		"b": {Schema: types.Prim("string", ""), Required: false},
	}, true)
	newClosed := types.Object(map[string]*types.Field{
		"a": {Schema: types.Prim("string", ""), Required: false},
	}, false) // closed
	newOpen := types.Object(map[string]*types.Field{
		"a": {Schema: types.Prim("string", ""), Required: false},
	}, true) // open

	if vs := Check(old, newClosed, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("removing field from closed schema should break")
	}
	if vs := Check(old, newOpen, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("removing field from open schema should be safe, got %v", vs)
	}
}

func TestNullable(t *testing.T) {
	nonNull := types.Prim("string", "")
	nullable := types.Nullable(types.Prim("string", ""))

	// REQ: nullable→non-null = BREAK
	if vs := Check(nullable, nonNull, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("nullable→non-null in REQ should break")
	}
	// REQ: non-null→nullable = safe
	if vs := Check(nonNull, nullable, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("non-null→nullable in REQ should be safe, got %v", vs)
	}

	// RES: non-null→nullable = BREAK
	if vs := Check(nonNull, nullable, types.DirRES, cfg()); len(vs) == 0 {
		t.Error("non-null→nullable in RES should break")
	}
	// RES: nullable→non-null = safe
	if vs := Check(nullable, nonNull, types.DirRES, cfg()); len(vs) != 0 {
		t.Errorf("nullable→non-null in RES should be safe, got %v", vs)
	}
}

func TestNullableNormalization(t *testing.T) {
	n := types.Nullable(types.Nullable(types.Prim("string", "")))
	if n.Kind != types.KindNullable {
		t.Fatal("should still be nullable")
	}
	if n.Inner.Kind != types.KindPrim {
		t.Errorf("double nullable should normalize: inner is %s, want prim", n.Inner.Kind)
	}
}

func TestUnion(t *testing.T) {
	// Use enum types so the lattice doesn't create implicit compatibility
	enumA := types.Enum([]string{"a"})
	enumB := types.Enum([]string{"b"})
	enumC := types.Enum([]string{"c"})

	old := types.Union([]*types.Node{enumA, enumB})
	wider := types.Union([]*types.Node{enumA, enumB, enumC})
	narrower := types.Union([]*types.Node{enumA})

	// REQ: old variants must all match in new (widening OK)
	if vs := Check(old, wider, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("REQ union widening should be safe, got %v", vs)
	}
	if vs := Check(old, narrower, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("REQ union narrowing should break (enum{b} has no match)")
	}

	// RES: new variants must all match in old (narrowing OK)
	if vs := Check(old, narrower, types.DirRES, cfg()); len(vs) != 0 {
		t.Errorf("RES union narrowing should be safe, got %v", vs)
	}
	if vs := Check(old, wider, types.DirRES, cfg()); len(vs) == 0 {
		t.Error("RES union widening should break (enum{c} has no match in old)")
	}
}

func TestLiteralInEnum(t *testing.T) {
	lit := types.Literal("active")
	enum := types.Enum([]string{"active", "inactive", "pending"})
	enumMissing := types.Enum([]string{"inactive", "pending"})

	// REQ: literal("active") ⊑ enum{active,inactive,pending} = true
	if vs := Check(lit, enum, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("literal in enum should be compatible, got %v", vs)
	}
	// REQ: literal("active") ⊑ enum{inactive,pending} = false
	if vs := Check(lit, enumMissing, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("literal not in enum should break")
	}
}

func TestMapKeyEquality(t *testing.T) {
	old := types.Map(types.Prim("string", ""), types.Prim("integer", ""))
	newOK := types.Map(types.Prim("string", ""), types.Prim("integer", ""))
	newBad := types.Map(types.Prim("integer", ""), types.Prim("integer", ""))

	if vs := Check(old, newOK, types.DirREQ, cfg()); len(vs) != 0 {
		t.Errorf("same key type should be safe, got %v", vs)
	}
	if vs := Check(old, newBad, types.DirREQ, cfg()); len(vs) == 0 {
		t.Error("different key type should break")
	}
}
