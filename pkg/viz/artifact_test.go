package viz

import (
	"bytes"
	"strings"
	"testing"

	"github.com/faults-lab/gus/pkg/compat"
	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/graph"
	"github.com/faults-lab/gus/pkg/report"
	"github.com/faults-lab/gus/pkg/solver"
	"github.com/faults-lab/gus/pkg/types"
)

func testGraph() *graph.Graph {
	return &graph.Graph{Def: graph.GraphDef{
		Services: map[string]graph.ServiceDef{"a": {}, "b": {}, "c": {}},
		Edges: []graph.EdgeDef{
			{Name: "a->b", From: "a", To: "b", Method: "POST", Path: "/x"},
			{Name: "a->c", From: "a", To: "c", Method: "GET", Path: "/y"},
		},
	}}
}

func testScenario() *graph.ScenarioDef {
	return &graph.ScenarioDef{
		ID: "T", Name: "test",
		Baseline: map[string]string{"a": "v1", "b": "v1", "c": "v1"},
		Upgrades: map[string]string{"b": "v2", "c": "v2"},
	}
}

func findEdge(art Artifact, name string) *Edge {
	for i := range art.Edges {
		if art.Edges[i].Name == name {
			return &art.Edges[i]
		}
	}
	return nil
}

func findService(art Artifact, id string) *Service {
	for i := range art.Services {
		if art.Services[i].ID == id {
			return &art.Services[i]
		}
	}
	return nil
}

// Drive the real edge checker and solver, then assert the artifact mirrors
// their output: OK flags, conjunct tags lifted into a field, exclusions,
// the MSS snapshot, and the case ID in the title.
func TestBuildMirrorsPipeline(t *testing.T) {
	g, sc := testGraph(), testScenario()
	cfg := compat.DefaultConfig()

	abOld := edge.VersionedSchemas{
		Send: types.Enum([]string{"a"}), Accept: types.Enum([]string{"a"}),
		Return: types.Enum([]string{"x"}), Expect: types.Enum([]string{"x"}),
	}
	abNew := edge.VersionedSchemas{
		Send: types.Enum([]string{"a"}), Accept: types.Enum([]string{"a"}),
		Return: types.Enum([]string{"x", "y"}), Expect: types.Enum([]string{"x", "y"}),
	}
	abEdge := edge.Edge{Name: "a->b", From: "a", To: "b", Channel: "http", Method: "POST", Path: "/x"}
	abRes := edge.CheckEdgeRPC(abEdge, abOld, abNew, true, cfg)
	if abRes.OK {
		t.Fatal("setup: expected a->b to break on C3")
	}
	acEdge := edge.Edge{Name: "a->c", From: "a", To: "c", Channel: "http", Method: "GET", Path: "/y"}
	acRes := edge.CheckEdgeRPC(acEdge, abOld, abOld, true, cfg)

	gus := &report.GUSResult{Scenario: sc.Display(), OK: false, Edges: []edge.EdgeResult{abRes, acRes}}
	mss := solver.ComputeMSS(
		[]solver.Upgrade{{Service: "b", FromVer: "v1", ToVer: "v2"}, {Service: "c", FromVer: "v1", ToVer: "v2"}},
		[]solver.Clause{{Cause: "b", Dep: "", Reason: "breaks edge a->b"}}, nil)

	art := Build(g, sc, gus, &mss)

	if art.Scenario.ID != "T" || art.Scenario.Name != "[T] test" {
		t.Errorf("scenario header = %q / %q, want ID T and display [T] test", art.Scenario.ID, art.Scenario.Name)
	}
	ab := findEdge(art, "a->b")
	if ab == nil || ab.OK || len(ab.Violations) != 1 {
		t.Fatalf("a->b edge missing, wrongly OK, or wrong violation count: %+v", ab)
	}
	v := ab.Violations[0]
	// The frontend's historical shape: C-tags are stored as bare numbers.
	if v.Conjunct != "3" || strings.HasPrefix(v.Path, "[C") || v.Rule != "enum-response-widening" {
		t.Errorf("violation = %+v, want conjunct 3, untagged path, enum-response-widening", v)
	}
	if v.Explanation == "" {
		t.Error("explanation must be filled")
	}
	if ac := findEdge(art, "a->c"); ac == nil || !ac.OK || len(ac.Violations) != 0 || !ac.AffectedByUpgrade {
		t.Errorf("a->c should be safe, affected, no violations: %+v", ac)
	}
	for i := 1; i < len(art.Services); i++ {
		if art.Services[i-1].ID > art.Services[i].ID {
			t.Errorf("services not sorted by ID: %v", art.Services)
		}
	}
	if b := findService(art, "b"); b == nil || !b.IsExcluded || b.StatusReason != "breaks edge a->b" {
		t.Errorf("service b should be excluded with reason: %+v", b)
	}
	if c := findService(art, "c"); c == nil || c.IsExcluded || !c.IsUpgrading {
		t.Errorf("service c should be upgrading and not excluded: %+v", c)
	}
	if !art.MSS.Computed || len(art.MSS.Safe) != 1 || art.MSS.Safe[0].Service != "c" {
		t.Errorf("MSS.Safe = %+v, want [c]", art.MSS.Safe)
	}
	if len(art.MSS.Removed) != 1 || art.MSS.Removed[0].Service != "b" || art.MSS.Removed[0].Reason != "breaks edge a->b" {
		t.Errorf("MSS.Removed = %+v, want [b w/ reason]", art.MSS.Removed)
	}
}

// The HTML viewer treats the JSON as a stable contract: marshalling must be
// deterministic.
func TestMarshalDeterministic(t *testing.T) {
	g, sc := testGraph(), testScenario()
	gus := &report.GUSResult{Scenario: sc.Display(), OK: true}
	mss := solver.ComputeMSS(nil, nil, nil)
	art := Build(g, sc, gus, &mss)
	a, err := Marshal(art, false)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	b, _ := Marshal(art, false)
	if !bytes.Equal(a, b) {
		t.Error("Marshal is not deterministic across calls")
	}
}

func TestStripConjunctTag(t *testing.T) {
	cases := []struct{ in, conj, path string }{
		{"[C3]$.categories", "3", "$.categories"},
		{"[TGT]$.x", "TGT", "$.x"},
		{"[CONSIST-REQ]$.x", "CONSIST-REQ", "$.x"},
		{"$.no.tag", "", "$.no.tag"},
	}
	for _, c := range cases {
		conj, path := stripConjunctTag(c.in)
		if conj != c.conj || path != c.path {
			t.Errorf("stripConjunctTag(%q) = (%q,%q), want (%q,%q)", c.in, conj, path, c.conj, c.path)
		}
	}
}

func TestFieldNameFromPath(t *testing.T) {
	for in, want := range map[string]string{"$.a.b": "b", "$": "$", "$.items[*].sku": "sku", "": ""} {
		if got := fieldNameFromPath(in); got != want {
			t.Errorf("fieldNameFromPath(%q) = %q, want %q", in, got, want)
		}
	}
}
