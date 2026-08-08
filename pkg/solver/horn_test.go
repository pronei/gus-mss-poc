package solver

import (
	"strings"
	"testing"
)

func names(us []Upgrade) []string {
	out := make([]string, len(us))
	for i, u := range us {
		out[i] = u.Service
	}
	return out
}

func setOf(us []Upgrade) map[string]bool {
	m := make(map[string]bool)
	for _, u := range us {
		m[u.Service] = true
	}
	return m
}

func TestAllSafe_NoClauses(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	result := ComputeMSS(proposed, nil, nil)

	if len(result.Safe) != 3 {
		t.Errorf("expected 3 safe, got %d", len(result.Safe))
	}
	if len(result.Removed) != 0 {
		t.Errorf("expected 0 removed, got %d", len(result.Removed))
	}
}

func TestUnitClause_RemovesA(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "A", Dep: "", Reason: "A breaks self-consistency"},
	}
	result := ComputeMSS(proposed, clauses, nil)

	if len(result.Safe) != 1 || result.Safe[0].Service != "B" {
		t.Fatalf("expected safe={B}, got %v", names(result.Safe))
	}
	if len(result.Removed) != 1 || result.Removed[0].Service != "A" {
		t.Fatalf("expected removed={A}, got %v", names(result.Removed))
	}
	if result.Reasons["A"] != "A breaks self-consistency" {
		t.Errorf("unexpected reason for A: %s", result.Reasons["A"])
	}
}

func TestChain_DepNotInU_RemovesCause(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "A", Dep: "B", Reason: "A->B edge breaks, B not upgrading"},
	}
	result := ComputeMSS(proposed, clauses, nil)

	safe := setOf(result.Safe)
	if safe["A"] || !safe["C"] {
		t.Errorf("expected safe={C}, got %v", names(result.Safe))
	}
}

func TestTransitivePropagation(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "D", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "A", Dep: "B", Reason: "A needs B"},
		{Cause: "B", Dep: "C", Reason: "B needs C (not upgrading)"},
	}
	result := ComputeMSS(proposed, clauses, nil)

	safe := setOf(result.Safe)
	if safe["A"] || safe["B"] || !safe["D"] {
		t.Errorf("expected safe={D}, got %v", names(result.Safe))
	}
}

func TestUnitClauseCascade(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "A", Dep: "", Reason: "A is broken"},
		{Cause: "B", Dep: "A", Reason: "B needs A"},
	}
	result := ComputeMSS(proposed, clauses, nil)

	safe := setOf(result.Safe)
	if safe["A"] || safe["B"] || !safe["C"] {
		t.Errorf("expected safe={C}, got %v", names(result.Safe))
	}
}

// The regression at the heart of the review: two co-upgrading services whose
// shared edge breaks in both rolling directions (C1 pins B after A, C4 pins A
// after B) must NOT come back as "safe" — the mutual implications alone are
// satisfied by keeping both, so the ordering layer has to detect the deadlock.
func TestDeadlockCycle_ExcludesBoth(t *testing.T) {
	proposed := []Upgrade{
		{Service: "frontend", FromVer: "v1", ToVer: "v2"},
		{Service: "checkout", FromVer: "v1", ToVer: "v3"},
		{Service: "email", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "checkout", Dep: "frontend", Reason: "C1"},
		{Cause: "frontend", Dep: "checkout", Reason: "C4"},
	}
	precedences := []Precedence{
		{First: "frontend", Then: "checkout", Reason: "C1"},
		{First: "checkout", Then: "frontend", Reason: "C4"},
	}
	result := ComputeMSS(proposed, clauses, precedences)

	safe := setOf(result.Safe)
	if safe["frontend"] || safe["checkout"] {
		t.Fatalf("deadlocked pair must be excluded, got safe=%v", names(result.Safe))
	}
	if !safe["email"] {
		t.Errorf("email is unconstrained and must stay safe, got %v", names(result.Safe))
	}
	for _, svc := range []string{"frontend", "checkout"} {
		if !strings.Contains(result.Reasons[svc], "deadlock") {
			t.Errorf("expected deadlock reason for %s, got %q", svc, result.Reasons[svc])
		}
	}
}

// A one-directional constraint is NOT a deadlock: it yields an order.
func TestPrecedence_YieldsRolloutOrder(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "B", Dep: "A", Reason: "C1 on A->B"},
	}
	precedences := []Precedence{
		{First: "A", Then: "B", Reason: "C1 on A->B"},
	}
	result := ComputeMSS(proposed, clauses, precedences)

	if len(result.Safe) != 3 {
		t.Fatalf("all three should ship (with ordering), got %v", names(result.Safe))
	}
	if len(result.Order) < 2 {
		t.Fatalf("expected at least 2 rollout stages, got %v", result.Order)
	}
	stageOf := map[string]int{}
	for i, stage := range result.Order {
		for _, svc := range stage {
			stageOf[svc] = i
		}
	}
	if stageOf["A"] >= stageOf["B"] {
		t.Errorf("A must roll before B, got order %v", result.Order)
	}
}

// Deadlock exclusion must re-trigger definite-clause propagation.
func TestDeadlockExclusion_Propagates(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "C", Dep: "A", Reason: "C needs A"},
	}
	precedences := []Precedence{
		{First: "A", Then: "B", Reason: "tgt"},
		{First: "B", Then: "A", Reason: "tgt"},
	}
	result := ComputeMSS(proposed, clauses, precedences)

	safe := setOf(result.Safe)
	if safe["A"] || safe["B"] {
		t.Fatalf("A,B deadlock must be excluded, got %v", names(result.Safe))
	}
	if safe["C"] {
		t.Errorf("C depends on excluded A and must be excluded too, got %v", names(result.Safe))
	}
}

func TestEmptyProposed(t *testing.T) {
	clauses := []Clause{{Cause: "A", Dep: "B", Reason: "irrelevant"}}
	result := ComputeMSS(nil, clauses, nil)
	if len(result.Safe) != 0 || len(result.Removed) != 0 {
		t.Errorf("expected empty result, got %v / %v", result.Safe, result.Removed)
	}
}

func TestDeterministicOutputOrder(t *testing.T) {
	proposed := []Upgrade{
		{Service: "zeta", FromVer: "v1", ToVer: "v2"},
		{Service: "alpha", FromVer: "v1", ToVer: "v2"},
		{Service: "mid", FromVer: "v1", ToVer: "v2"},
	}
	for i := 0; i < 20; i++ {
		result := ComputeMSS(proposed, nil, nil)
		got := strings.Join(names(result.Safe), ",")
		if got != "alpha,mid,zeta" {
			t.Fatalf("expected sorted safe set, got %s", got)
		}
	}
}
