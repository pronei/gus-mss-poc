package solver

import (
	"reflect"
	"sort"
	"testing"
)

func safeSet(r MSSResult) []string {
	var s []string
	for _, u := range r.Safe {
		s = append(s, u.Service)
	}
	sort.Strings(s)
	return s
}

func removedSet(r MSSResult) []string {
	var s []string
	for _, u := range r.Removed {
		s = append(s, u.Service)
	}
	sort.Strings(s)
	return s
}

func ups(names ...string) []Upgrade {
	u := make([]Upgrade, len(names))
	for i, n := range names {
		u[i] = Upgrade{Service: n, FromVer: "v1", ToVer: "v2"}
	}
	return u
}

// The safe subset of a definite system is its unique maximum, so clause
// order must not change it.
func TestOrderIndependence(t *testing.T) {
	proposed := ups("A", "B", "C", "D")
	base := []Clause{
		{Cause: "A", Dep: "B", Reason: "A needs B"},
		{Cause: "B", Dep: "C", Reason: "B needs C"},
		{Cause: "C", Dep: "E", Reason: "C needs E (not in U)"}, // forces C, B, A out
		{Cause: "D", Dep: "", Reason: "D self-incompatible"},   // forces D out
	}
	want := ComputeMSS(proposed, base, nil)
	perms := [][]Clause{
		{base[3], base[2], base[1], base[0]},
		{base[2], base[0], base[3], base[1]},
		{base[1], base[3], base[0], base[2]},
	}
	for i, p := range perms {
		got := ComputeMSS(proposed, p, nil)
		if !reflect.DeepEqual(safeSet(got), safeSet(want)) || !reflect.DeepEqual(removedSet(got), removedSet(want)) {
			t.Errorf("perm %d safe=%v removed=%v, want %v / %v", i, safeSet(got), removedSet(got), safeSet(want), removedSet(want))
		}
	}
	if len(want.Safe) != 0 {
		t.Errorf("expected empty safe set, got %v", safeSet(want))
	}
}

// Mutual clauses {A->B, B->A}: without pressure both survive; one unit
// exclusion cascades to the partner.
func TestMutualClauses(t *testing.T) {
	proposed := ups("A", "B", "C")
	mutual := []Clause{{Cause: "A", Dep: "B", Reason: "edge A<->B"}, {Cause: "B", Dep: "A", Reason: "edge A<->B"}}
	if got := ComputeMSS(proposed, mutual, nil); !reflect.DeepEqual(safeSet(got), []string{"A", "B", "C"}) {
		t.Errorf("mutual clauses with no unit: safe=%v, want [A B C]", safeSet(got))
	}
	withUnit := append([]Clause{{Cause: "A", Dep: "", Reason: "A broken"}}, mutual...)
	got := ComputeMSS(proposed, withUnit, nil)
	if !reflect.DeepEqual(safeSet(got), []string{"C"}) || !reflect.DeepEqual(removedSet(got), []string{"A", "B"}) {
		t.Errorf("unit ¬A must cascade to B: safe=%v removed=%v", safeSet(got), removedSet(got))
	}
}

func TestUnitClauseOnNonProposedIsNoop(t *testing.T) {
	got := ComputeMSS(ups("A", "B"), []Clause{{Cause: "Z", Dep: "", Reason: "Z not proposed"}}, nil)
	if !reflect.DeepEqual(safeSet(got), []string{"A", "B"}) {
		t.Errorf("safe=%v, want [A B]", safeSet(got))
	}
}

func TestLongTransitiveChain(t *testing.T) {
	proposed := ups("A", "B", "C", "D", "Z")
	clauses := []Clause{
		{Cause: "A", Dep: "B", Reason: "A->B"}, {Cause: "B", Dep: "C", Reason: "B->C"},
		{Cause: "C", Dep: "D", Reason: "C->D"}, {Cause: "D", Dep: "E", Reason: "D->E (E not in U)"},
	}
	if got := ComputeMSS(proposed, clauses, nil); !reflect.DeepEqual(safeSet(got), []string{"Z"}) {
		t.Errorf("safe=%v, want [Z] (A,B,C,D all cascade out)", safeSet(got))
	}
}

// Diamond: A requires both B and C; excluding B alone drops A but keeps C.
func TestDiamondExclusion(t *testing.T) {
	clauses := []Clause{
		{Cause: "A", Dep: "B", Reason: "A needs B"}, {Cause: "A", Dep: "C", Reason: "A needs C"},
		{Cause: "B", Dep: "", Reason: "B broken"},
	}
	got := ComputeMSS(ups("A", "B", "C"), clauses, nil)
	if !reflect.DeepEqual(safeSet(got), []string{"C"}) {
		t.Errorf("safe=%v, want [C]", safeSet(got))
	}
	if got.Reasons["A"] == "" || got.Reasons["B"] == "" {
		t.Errorf("every removed service needs a reason: %#v", got.Reasons)
	}
}

func TestAllRemovedHaveReasons(t *testing.T) {
	got := ComputeMSS(ups("A", "B", "C"), []Clause{
		{Cause: "A", Dep: "", Reason: "unit A"}, {Cause: "B", Dep: "X", Reason: "B needs X not in U"},
	}, nil)
	for _, u := range got.Removed {
		if got.Reasons[u.Service] == "" {
			t.Errorf("removed %s has no reason", u.Service)
		}
	}
}

// Output is deterministic: the safe set is reported sorted by service name,
// whatever order the proposal listed.
func TestSafeSortedByName(t *testing.T) {
	got := ComputeMSS(ups("D", "C", "B", "A"), nil, nil)
	var order []string
	for _, u := range got.Safe {
		order = append(order, u.Service)
	}
	if !reflect.DeepEqual(order, []string{"A", "B", "C", "D"}) {
		t.Errorf("safe order = %v, want sorted [A B C D]", order)
	}
}

func TestDuplicateClausesHarmless(t *testing.T) {
	dup := []Clause{{Cause: "A", Dep: "", Reason: "A broken"}, {Cause: "A", Dep: "", Reason: "A broken (dup)"}}
	got := ComputeMSS(ups("A", "B"), dup, nil)
	if !reflect.DeepEqual(safeSet(got), []string{"B"}) || len(got.Removed) != 1 {
		t.Errorf("safe=%v removed=%v, want [B] / [A]", safeSet(got), removedSet(got))
	}
}

// Precedences among surviving upgrades become stages; a precedence whose
// endpoint was excluded imposes nothing.
func TestPrecedenceStages(t *testing.T) {
	got := ComputeMSS(ups("A", "B", "C"), nil, []Precedence{{First: "A", Then: "B", Reason: "A before B"}})
	want := [][]string{{"A", "C"}, {"B"}}
	if !reflect.DeepEqual(got.Order, want) {
		t.Errorf("order = %v, want %v", got.Order, want)
	}
	got = ComputeMSS(ups("A", "B", "C"), []Clause{{Cause: "A", Dep: "", Reason: "A broken"}},
		[]Precedence{{First: "A", Then: "B", Reason: "A before B"}})
	if !reflect.DeepEqual(safeSet(got), []string{"B", "C"}) || len(got.Order) != 1 {
		t.Errorf("excluded endpoint must drop the precedence: safe=%v order=%v", safeSet(got), got.Order)
	}
}
