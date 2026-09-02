package edge

import (
	"reflect"
	"strings"
	"testing"

	"github.com/faults-lab/gus/pkg/compat"
	"github.com/faults-lab/gus/pkg/types"
)

func enum(vals ...string) *types.Node { return types.Enum(vals) }

func cfg() compat.Config { return compat.DefaultConfig() }

func rpcEdge() Edge {
	return Edge{Name: "a->b", From: "a", To: "b", Channel: "http", Method: "POST", Path: "/x"}
}

func hasTag(vs []types.Violation, tag string) bool {
	for _, v := range vs {
		if strings.HasPrefix(v.Path, tag) {
			return true
		}
	}
	return false
}

func TestRPCAllCompatible(t *testing.T) {
	same := VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")}
	r := CheckEdgeRPC(rpcEdge(), same, same, true, cfg())
	if !r.OK || len(r.FailedConjuncts) != 0 {
		t.Fatalf("identical schemas should be OK, got %v / %v", r.FailedConjuncts, r.Violations)
	}
}

// Each conjunct is isolated: the pairing is built so exactly one of C1–C4
// fails, and the target state (new, new) is consistent.
func TestRPCConjunctIsolation(t *testing.T) {
	tests := []struct {
		name     string
		old, new VersionedSchemas
		tag      string
	}{
		{
			name: "C1 old caller -> new provider, request",
			old:  VersionedSchemas{Send: enum("a", "b"), Accept: enum("a", "b"), Return: enum("x"), Expect: enum("x")},
			new:  VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")},
			tag:  "[C1]",
		},
		{
			name: "C2 new caller -> old provider, request",
			old:  VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")},
			new:  VersionedSchemas{Send: enum("a", "b"), Accept: enum("a", "b"), Return: enum("x"), Expect: enum("x")},
			tag:  "[C2]",
		},
		{
			name: "C3 new provider -> old caller, response widening",
			old:  VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")},
			new:  VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x", "y"), Expect: enum("x", "y")},
			tag:  "[C3]",
		},
		{
			name: "C4 old provider -> new caller, response",
			old:  VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x", "y"), Expect: enum("x", "y")},
			new:  VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")},
			tag:  "[C4]",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := CheckEdgeRPC(rpcEdge(), tt.old, tt.new, true, cfg())
			if r.OK {
				t.Fatalf("expected break, got OK")
			}
			want := []string{strings.Trim(tt.tag, "[]")}
			if !reflect.DeepEqual(r.FailedConjuncts, want) {
				t.Errorf("FailedConjuncts = %v, want %v (violations %v)", r.FailedConjuncts, want, r.Violations)
			}
			for _, other := range []string{"[C1]", "[C2]", "[C3]", "[C4]", "[TGT]"} {
				if other != tt.tag && hasTag(r.Violations, other) {
					t.Errorf("unexpected tag %s present: %v", other, r.Violations)
				}
			}
		})
	}
}

// Violation labels are chronological: OldType is always the θ-side type and
// NewType the θ'-side type, also for C2/C4 where compat's positional
// arguments are the other way round.
func TestRPCChronologyLabels(t *testing.T) {
	old := VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")}
	new := VersionedSchemas{Send: enum("a", "b"), Accept: enum("a", "b"), Return: enum("x"), Expect: enum("x")}
	r := CheckEdgeRPC(rpcEdge(), old, new, true, cfg())
	for _, v := range r.Violations {
		if strings.HasPrefix(v.Path, "[C2]") {
			if v.OldType != "enum{a}" || v.NewType != "enum{a,b}" {
				t.Errorf("C2 labels not chronological: old=%q new=%q", v.OldType, v.NewType)
			}
		}
	}
}

// When several conjuncts fail, every failing one is listed, in C1..TGT order,
// and all violations are collected and tagged.
func TestRPCMultipleConjuncts(t *testing.T) {
	old := VersionedSchemas{Send: enum("a", "b"), Accept: enum("a", "b"), Return: enum("x"), Expect: enum("x")}
	new := VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x", "y"), Expect: enum("x", "y")}
	r := CheckEdgeRPC(rpcEdge(), old, new, true, cfg())
	if r.OK {
		t.Fatal("expected break")
	}
	if !reflect.DeepEqual(r.FailedConjuncts, []string{"C1", "C3"}) {
		t.Errorf("FailedConjuncts = %v, want [C1 C3]", r.FailedConjuncts)
	}
	if !hasTag(r.Violations, "[C1]") || !hasTag(r.Violations, "[C3]") {
		t.Errorf("expected both C1 and C3 tags, got: %v", r.Violations)
	}
}

// The target conjunct catches a (new, new) inconsistency that every mixed
// pair tolerates: the caller starts sending a value the new provider rejects,
// while the old provider accepted it and the old caller never sent it.
func TestRPCTargetOnly(t *testing.T) {
	old := VersionedSchemas{Send: enum("a"), Accept: enum("a", "b"), Return: enum("x"), Expect: enum("x")}
	new := VersionedSchemas{Send: enum("a", "b"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")}
	r := CheckEdgeRPC(rpcEdge(), old, new, true, cfg())
	if !reflect.DeepEqual(r.FailedConjuncts, []string{"TGT"}) {
		t.Errorf("FailedConjuncts = %v, want [TGT] (violations %v)", r.FailedConjuncts, r.Violations)
	}
	// Under the Tier-3 fallback the target pair is not evaluated.
	if r := CheckEdgeRPC(rpcEdge(), old, new, false, cfg()); !r.OK {
		t.Errorf("checkTarget=false must not evaluate TGT, got %v", r.FailedConjuncts)
	}
}

// WARN-only findings are recorded but do not fail the edge.
func TestRPCWarningsDoNotBreak(t *testing.T) {
	i32 := types.Prim("integer", "int32")
	i64 := types.Prim("integer", "int64")
	old := VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: i32, Expect: i32}
	new := VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: i64, Expect: i64}
	r := CheckEdgeRPC(rpcEdge(), old, new, true, cfg())
	if !r.OK || len(r.FailedConjuncts) != 0 {
		t.Errorf("format widening is WARN-only, edge must stay OK: %v", r.FailedConjuncts)
	}
	if len(r.Violations) == 0 || r.Violations[0].Severity != types.SevWARN {
		t.Errorf("expected a recorded WARN, got %v", r.Violations)
	}
}

func TestConsistent(t *testing.T) {
	e := rpcEdge()
	ok := Consistent(e, VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")}, cfg())
	if !ok.OK {
		t.Errorf("internally consistent state should pass, got %v", ok.Violations)
	}
	reqBad := Consistent(e, VersionedSchemas{Send: enum("a", "b"), Accept: enum("a"), Return: enum("x"), Expect: enum("x")}, cfg())
	if reqBad.OK || !hasTag(reqBad.Violations, "[CONSIST-REQ]") {
		t.Errorf("request-side inconsistency expected, got OK=%v vs=%v", reqBad.OK, reqBad.Violations)
	}
	resBad := Consistent(e, VersionedSchemas{Send: enum("a"), Accept: enum("a"), Return: enum("x", "y"), Expect: enum("x")}, cfg())
	if resBad.OK || !hasTag(resBad.Violations, "[CONSIST-RES]") {
		t.Errorf("response-side inconsistency expected, got OK=%v vs=%v", resBad.OK, resBad.Violations)
	}
}
