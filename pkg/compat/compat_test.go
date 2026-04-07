package compat

import (
	"testing"

	"github.com/faults-lab/gus/pkg/lattice"
	"github.com/faults-lab/gus/pkg/types"
)

func cfg() Config { return Config{Format: lattice.FormatJSON} }

func TestPrimLattice(t *testing.T) {
	tests := []struct {
		name string
		old  *types.Node
		new  *types.Node
		dir  types.Direction
		ok   bool
	}{
		{"int ⊑ num REQ", types.Prim("integer", ""), types.Prim("number", ""), types.DirREQ, true},
		{"num ⊑ str REQ", types.Prim("number", ""), types.Prim("string", ""), types.DirREQ, true},
		{"str ⊑ int REQ fail", types.Prim("string", ""), types.Prim("integer", ""), types.DirREQ, false},
		{"bool ⊑ str REQ", types.Prim("boolean", ""), types.Prim("string", ""), types.DirREQ, true},
		{"int ⊑ int REQ", types.Prim("integer", ""), types.Prim("integer", ""), types.DirREQ, true},
		// Response: new ≤ old
		{"int RES num safe", types.Prim("number", ""), types.Prim("integer", ""), types.DirRES, true},
		{"str RES int fail", types.Prim("integer", ""), types.Prim("string", ""), types.DirRES, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			vs := Check(tt.old, tt.new, tt.dir, cfg())
			got := len(vs) == 0
			if got != tt.ok {
				t.Errorf("got ok=%v, want %v (violations: %v)", got, tt.ok, vs)
			}
		})
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
