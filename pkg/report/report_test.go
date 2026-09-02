package report

import (
	"strings"
	"testing"

	"github.com/faults-lab/gus/pkg/chain"
	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/solver"
	"github.com/faults-lab/gus/pkg/types"
)

func brokenEdge() edge.EdgeResult {
	return edge.EdgeResult{
		Edge:            edge.Edge{Name: "a->b", Channel: "http"},
		OK:              false,
		FailedConjuncts: []string{"C3"},
		Violations: []types.Violation{{
			Path: "[C3]$.x", Severity: types.SevBREAK, Rule: "RES.1",
			Message: "required field removed", OldType: "string", NewType: "<absent>",
		}},
	}
}

// Regression: ConsistentResult.Text() once shadowed `status` inside the !r.OK
// branch and always printed YES.
func TestConsistentResultStatus(t *testing.T) {
	bad := &ConsistentResult{OK: false, Edges: []edge.EdgeResult{brokenEdge()}}
	if txt := bad.Text(); !strings.Contains(txt, "Result: NO") {
		t.Errorf("inconsistent state must report NO, got:\n%s", txt)
	}
	good := &ConsistentResult{OK: true}
	if txt := good.Text(); !strings.Contains(txt, "Result: YES") {
		t.Errorf("consistent state must report YES, got:\n%s", txt)
	}
}

func TestGUSResultText(t *testing.T) {
	r := &GUSResult{Scenario: "[T] S", OK: false, Edges: []edge.EdgeResult{brokenEdge()}}
	txt := r.Text()
	for _, want := range []string{"[T] S", "Decision: NO", "a->b", "C3", "RES.1", "required field removed"} {
		if !strings.Contains(txt, want) {
			t.Errorf("GUSResult.Text missing %q:\n%s", want, txt)
		}
	}
}

// Broken chains print the path, the message, and the batch attribution.
func TestGUSResultChainText(t *testing.T) {
	r := &GUSResult{Scenario: "S", OK: false, Chains: []chain.ChainResult{{
		Key: "order-identity", Rule: "chain-weakened", Message: "optional at source",
		Provider: chain.Annotation{Service: "checkout"}, Requirer: chain.Annotation{Service: "email"},
		ChainPath: []string{"checkout", "email"}, Culprits: []string{"checkout"},
	}}}
	txt := r.Text()
	for _, want := range []string{"Chain order-identity", "chain-weakened", "checkout -> email", "attributed within the batch to: checkout"} {
		if !strings.Contains(txt, want) {
			t.Errorf("chain text missing %q:\n%s", want, txt)
		}
	}
}

func TestMSSReportText(t *testing.T) {
	gus := &GUSResult{Scenario: "S", OK: false, Edges: []edge.EdgeResult{brokenEdge()}}
	m := &MSSReport{
		Scenario: "S",
		GUS:      gus,
		MSS: &solver.MSSResult{
			Safe:    []solver.Upgrade{{Service: "c", FromVer: "v1", ToVer: "v2"}},
			Removed: []solver.Upgrade{{Service: "b", FromVer: "v1", ToVer: "v2"}},
			Reasons: map[string]string{"b": "breaks edge a->b"},
			Order:   [][]string{{"c"}},
		},
	}
	txt := m.Text()
	for _, want := range []string{"Safe subset", "c v1→v2", "Excluded", "b v1→v2", "breaks edge a->b"} {
		if !strings.Contains(txt, want) {
			t.Errorf("MSSReport.Text missing %q:\n%s", want, txt)
		}
	}
}

func TestMSSReportEmptySafe(t *testing.T) {
	gus := &GUSResult{Scenario: "S", OK: false, Edges: []edge.EdgeResult{brokenEdge()}}
	m := &MSSReport{Scenario: "S", GUS: gus, MSS: &solver.MSSResult{
		Removed: []solver.Upgrade{{Service: "b", FromVer: "v1", ToVer: "v2"}},
		Reasons: map[string]string{"b": "broken"},
	}}
	if !strings.Contains(m.Text(), "empty") {
		t.Errorf("empty safe subset should be called out:\n%s", m.Text())
	}
}

// A WARN-only edge does not fail the decision but its findings are printed.
func TestGUSResultWarnOnlyEdge(t *testing.T) {
	warnEdge := edge.EdgeResult{
		Edge: edge.Edge{Name: "a->b", Channel: "http"}, OK: true, CallerSpecUsed: true,
		Violations: []types.Violation{{
			Path: "[C3]$.n", Severity: types.SevWARN, Rule: "format-change",
			Message: "producer format int64 may exceed consumer format int32", OldType: "integer(int32)", NewType: "integer(int64)",
		}},
	}
	txt := (&GUSResult{Scenario: "S", OK: true, Edges: []edge.EdgeResult{warnEdge}}).Text()
	for _, want := range []string{"Decision: YES", "a->b", "WARN (no conjunct fails", "format-change"} {
		if !strings.Contains(txt, want) {
			t.Errorf("warn-only edge text missing %q:\n%s", want, txt)
		}
	}
	if strings.Contains(txt, "BREAK") {
		t.Errorf("warn-only edge must not be labelled BREAK:\n%s", txt)
	}
}
