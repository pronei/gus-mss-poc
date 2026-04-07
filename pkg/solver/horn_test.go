package solver

import (
	"testing"
)

func TestAllSafe_NoClauses(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	result := ComputeMSS(proposed, nil)

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
	result := ComputeMSS(proposed, clauses)

	if len(result.Safe) != 1 {
		t.Fatalf("expected 1 safe, got %d", len(result.Safe))
	}
	if result.Safe[0].Service != "B" {
		t.Errorf("expected B to be safe, got %s", result.Safe[0].Service)
	}
	if len(result.Removed) != 1 {
		t.Fatalf("expected 1 removed, got %d", len(result.Removed))
	}
	if result.Removed[0].Service != "A" {
		t.Errorf("expected A to be removed, got %s", result.Removed[0].Service)
	}
	if result.Reasons["A"] != "A breaks self-consistency" {
		t.Errorf("unexpected reason for A: %s", result.Reasons["A"])
	}
}

func TestChain_DepNotInU_RemovesCause(t *testing.T) {
	// Clause: not(A) OR B, but B is not in the proposed set.
	// Since B is false (not proposed), A must also be false.
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "A", Dep: "B", Reason: "A->B edge breaks, B not upgrading"},
	}
	result := ComputeMSS(proposed, clauses)

	safeSet := make(map[string]bool)
	for _, u := range result.Safe {
		safeSet[u.Service] = true
	}

	if safeSet["A"] {
		t.Error("A should have been removed (B not in U)")
	}
	if !safeSet["C"] {
		t.Error("C should be safe")
	}
	if len(result.Removed) != 1 || result.Removed[0].Service != "A" {
		t.Errorf("expected [A] removed, got %v", result.Removed)
	}
}

func TestMultipleIndependentExclusions(t *testing.T) {
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
		{Service: "D", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		// Unit clause: exclude A
		{Cause: "A", Dep: "", Reason: "A self-incompatible"},
		// Chain: C depends on E (not in U), so C is removed
		{Cause: "C", Dep: "E", Reason: "C->E edge, E not upgrading"},
	}
	result := ComputeMSS(proposed, clauses)

	safeSet := make(map[string]bool)
	for _, u := range result.Safe {
		safeSet[u.Service] = true
	}

	if safeSet["A"] {
		t.Error("A should be removed (unit clause)")
	}
	if !safeSet["B"] {
		t.Error("B should be safe")
	}
	if safeSet["C"] {
		t.Error("C should be removed (dep E not in U)")
	}
	if !safeSet["D"] {
		t.Error("D should be safe")
	}
	if len(result.Safe) != 2 {
		t.Errorf("expected 2 safe, got %d", len(result.Safe))
	}
	if len(result.Removed) != 2 {
		t.Errorf("expected 2 removed, got %d", len(result.Removed))
	}
}

func TestEmptyProposed(t *testing.T) {
	clauses := []Clause{
		{Cause: "A", Dep: "B", Reason: "irrelevant"},
	}
	result := ComputeMSS(nil, clauses)

	if len(result.Safe) != 0 {
		t.Errorf("expected 0 safe, got %d", len(result.Safe))
	}
	if len(result.Removed) != 0 {
		t.Errorf("expected 0 removed, got %d", len(result.Removed))
	}
}

func TestTransitivePropagation(t *testing.T) {
	// Chain: A depends on B, B depends on C. C is not in U.
	// Expected: both A and B are removed.
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "D", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "A", Dep: "B", Reason: "A needs B"},
		{Cause: "B", Dep: "C", Reason: "B needs C (not upgrading)"},
	}
	result := ComputeMSS(proposed, clauses)

	safeSet := make(map[string]bool)
	for _, u := range result.Safe {
		safeSet[u.Service] = true
	}

	if safeSet["A"] {
		t.Error("A should be removed (transitive: A->B->C, C not in U)")
	}
	if safeSet["B"] {
		t.Error("B should be removed (B->C, C not in U)")
	}
	if !safeSet["D"] {
		t.Error("D should be safe (independent)")
	}
}

func TestUnitClauseCascade(t *testing.T) {
	// Unit clause removes A. A is a dep for B. So B should also be removed.
	proposed := []Upgrade{
		{Service: "A", FromVer: "v1", ToVer: "v2"},
		{Service: "B", FromVer: "v1", ToVer: "v2"},
		{Service: "C", FromVer: "v1", ToVer: "v2"},
	}
	clauses := []Clause{
		{Cause: "A", Dep: "", Reason: "A is broken"},
		{Cause: "B", Dep: "A", Reason: "B needs A"},
	}
	result := ComputeMSS(proposed, clauses)

	safeSet := make(map[string]bool)
	for _, u := range result.Safe {
		safeSet[u.Service] = true
	}

	if safeSet["A"] {
		t.Error("A should be removed (unit clause)")
	}
	if safeSet["B"] {
		t.Error("B should be removed (depends on A which is excluded)")
	}
	if !safeSet["C"] {
		t.Error("C should be safe")
	}
}
