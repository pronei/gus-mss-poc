// GUS (Global Upgrade Safety) checker — validates type compatibility across
// microservice boundaries and computes the Maximal Safe Subset (MSS) for
// simultaneous service upgrades.
//
// Usage:
//
//	gus check      --graph graph.yaml --scenario scenario.yaml
//	gus mss        --graph graph.yaml --scenario scenario.yaml
//	gus consistent --graph graph.yaml --scenario scenario.yaml
//	gus validate   --graph graph.yaml --scenario-dir dir/
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/faults-lab/gus/pkg/compat"
	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/graph"
	"github.com/faults-lab/gus/pkg/report"
	"github.com/faults-lab/gus/pkg/schema"
	"github.com/faults-lab/gus/pkg/solver"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}
	switch os.Args[1] {
	case "check":
		runCheck(os.Args[2:])
	case "mss":
		runMSS(os.Args[2:])
	case "consistent":
		runConsistent(os.Args[2:])
	case "validate":
		runValidate(os.Args[2:])
	case "viz":
		runViz(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", os.Args[1])
		usage()
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, `GUS — Global Upgrade Safety Checker

Commands:
  check       Run GUS compatibility check (equivalent to Pact's can-i-deploy, but multi-service aware)
  mss         Compute Maximal Safe Subset when GUS=NO
  consistent  Verify a single deployment state is internally compatible
  validate    Run all scenarios in a directory and check expected results
  viz         Emit JSON artifact for the browser-based scenario visualizer

Flags:
  --graph       Path to graph.yaml (service mesh topology)
  --scenario    Path to scenario.yaml (upgrade definition)
  --scenario-dir Path to directory of scenario YAML files (for validate)
  --format      Output format: text (default) or json`)
}

func runCheck(args []string) {
	fs := flag.NewFlagSet("check", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	scenarioPath := fs.String("scenario", "", "path to scenario.yaml")
	format := fs.String("format", "text", "output format: text or json")
	fs.Parse(args)

	g, sc := mustLoadInputs(*graphPath, *scenarioPath)
	result := executeGUS(g, sc)

	switch *format {
	case "json":
		data, _ := result.JSON()
		fmt.Println(string(data))
	default:
		fmt.Print(result.Text())
	}

	if !result.OK {
		os.Exit(1)
	}
}

func runMSS(args []string) {
	fs := flag.NewFlagSet("mss", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	scenarioPath := fs.String("scenario", "", "path to scenario.yaml")
	fs.Parse(args)

	g, sc := mustLoadInputs(*graphPath, *scenarioPath)
	gusResult := executeGUS(g, sc)

	if gusResult.OK {
		fmt.Print(gusResult.Text())
		fmt.Println("\nAll upgrades are safe. No MSS computation needed.")
		return
	}

	// Build Horn clauses from violations
	clauses := buildClauses(gusResult, g, sc)
	proposed := buildUpgrades(sc)

	mssResult := solver.ComputeMSS(proposed, clauses)
	rpt := &report.MSSReport{
		Scenario: sc.Name,
		GUS:      gusResult,
		MSS:      &mssResult,
	}
	fmt.Print(rpt.Text())

	if len(mssResult.Safe) == 0 {
		os.Exit(1)
	}
}

func runConsistent(args []string) {
	fs := flag.NewFlagSet("consistent", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	scenarioPath := fs.String("scenario", "", "path to scenario.yaml")
	fs.Parse(args)

	g, sc := mustLoadInputs(*graphPath, *scenarioPath)
	cfg := compat.DefaultConfig()
	result := &report.ConsistentResult{OK: true}

	for _, edgeDef := range g.Def.Edges {
		ver := resolveVersion(sc.Baseline, edgeDef.From, "v1")
		provVer := resolveVersion(sc.Baseline, edgeDef.To, "v1")

		schemas, err := loadEdgeSchemas(g, edgeDef, ver, provVer)
		if err != nil {
			fmt.Fprintf(os.Stderr, "warn: %s: %v\n", edgeDef.Name, err)
			continue
		}

		e := toEdge(edgeDef)
		er := edge.Consistent(e, schemas, cfg)
		result.Edges = append(result.Edges, er)
		if !er.OK {
			result.OK = false
		}
	}

	fmt.Print(result.Text())
	if !result.OK {
		os.Exit(1)
	}
}

func runValidate(args []string) {
	fs := flag.NewFlagSet("validate", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	scenarioDir := fs.String("scenario-dir", "", "path to scenario directory")
	fs.Parse(args)

	if *graphPath == "" || *scenarioDir == "" {
		fmt.Fprintln(os.Stderr, "Usage: gus validate --graph <path> --scenario-dir <dir>")
		os.Exit(1)
	}

	g, err := graph.LoadGraph(*graphPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error loading graph: %v\n", err)
		os.Exit(1)
	}

	scenarios, err := graph.LoadScenarioDir(*scenarioDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error loading scenarios: %v\n", err)
		os.Exit(1)
	}

	passed, failed := 0, 0
	for _, sc := range scenarios {
		gusResult := executeGUS(g, sc)
		ok := validateExpectations(sc, gusResult, g)
		if ok {
			fmt.Printf("  PASS  %s\n", sc.Name)
			passed++
		} else {
			fmt.Printf("  FAIL  %s\n", sc.Name)
			failed++
		}
	}

	fmt.Printf("\n%d passed, %d failed\n", passed, failed)
	if failed > 0 {
		os.Exit(1)
	}
}

// --- Core execution ---

func executeGUS(g *graph.Graph, sc *graph.ScenarioDef) *report.GUSResult {
	cfg := compat.DefaultConfig()
	result := &report.GUSResult{Scenario: sc.Name, OK: true}

	for _, edgeDef := range g.Def.Edges {
		// Determine if this edge is affected by the upgrade
		_, callerUpgrading := sc.Upgrades[edgeDef.From]
		_, providerUpgrading := sc.Upgrades[edgeDef.To]
		if !callerUpgrading && !providerUpgrading {
			continue // neither endpoint is upgrading
		}

		baseCallerVer := resolveVersion(sc.Baseline, edgeDef.From, "v1")
		baseProvVer := resolveVersion(sc.Baseline, edgeDef.To, "v1")
		newCallerVer := resolveVersion(sc.Upgrades, edgeDef.From, baseCallerVer)
		newProvVer := resolveVersion(sc.Upgrades, edgeDef.To, baseProvVer)

		oldSchemas, err := loadEdgeSchemas(g, edgeDef, baseCallerVer, baseProvVer)
		if err != nil {
			fmt.Fprintf(os.Stderr, "warn: old schemas for %s: %v\n", edgeDef.Name, err)
			continue
		}
		newSchemas, err := loadEdgeSchemas(g, edgeDef, newCallerVer, newProvVer)
		if err != nil {
			fmt.Fprintf(os.Stderr, "warn: new schemas for %s: %v\n", edgeDef.Name, err)
			continue
		}

		e := toEdge(edgeDef)

		var er edge.EdgeResult
		switch edgeDef.Channel {
		case "kafka":
			er = edge.CheckEdgeSubscribe(e,
				oldSchemas.Send, newSchemas.Send,
				oldSchemas.Expect, newSchemas.Expect,
				cfg)
		default:
			er = edge.CheckEdgeRPC(e, oldSchemas, newSchemas, cfg)
		}

		result.Edges = append(result.Edges, er)
		if !er.OK {
			result.OK = false
		}
	}

	return result
}

func buildClauses(gusResult *report.GUSResult, g *graph.Graph, sc *graph.ScenarioDef) []solver.Clause {
	var clauses []solver.Clause
	for _, er := range gusResult.Edges {
		if er.OK {
			continue
		}
		// Find which upgrade(s) caused this edge to break
		_, callerUpgrading := sc.Upgrades[er.Edge.From]
		_, providerUpgrading := sc.Upgrades[er.Edge.To]

		reason := fmt.Sprintf("breaks edge %s", er.Edge.Name)

		if callerUpgrading && providerUpgrading {
			// Both upgrading — can't determine which is the cause without deeper analysis
			// Conservative: exclude both unless the other also upgrades
			clauses = append(clauses, solver.Clause{
				Cause: er.Edge.From, Dep: er.Edge.To, Reason: reason,
			})
			clauses = append(clauses, solver.Clause{
				Cause: er.Edge.To, Dep: er.Edge.From, Reason: reason,
			})
		} else if callerUpgrading {
			// Only caller upgrading: if this edge breaks, maybe provider needs to upgrade too
			if _, inU := sc.Upgrades[er.Edge.To]; inU {
				clauses = append(clauses, solver.Clause{
					Cause: er.Edge.From, Dep: er.Edge.To, Reason: reason,
				})
			} else {
				// Provider not in upgrade set — unconditional exclusion
				clauses = append(clauses, solver.Clause{
					Cause: er.Edge.From, Dep: "", Reason: reason,
				})
			}
		} else if providerUpgrading {
			if _, inU := sc.Upgrades[er.Edge.From]; inU {
				clauses = append(clauses, solver.Clause{
					Cause: er.Edge.To, Dep: er.Edge.From, Reason: reason,
				})
			} else {
				clauses = append(clauses, solver.Clause{
					Cause: er.Edge.To, Dep: "", Reason: reason,
				})
			}
		}
	}
	return clauses
}

func buildUpgrades(sc *graph.ScenarioDef) []solver.Upgrade {
	var upgrades []solver.Upgrade
	for svc, toVer := range sc.Upgrades {
		fromVer, ok := sc.Baseline[svc]
		if !ok {
			fromVer = "v1"
		}
		upgrades = append(upgrades, solver.Upgrade{
			Service: svc, FromVer: fromVer, ToVer: toVer,
		})
	}
	return upgrades
}

func validateExpectations(sc *graph.ScenarioDef, gusResult *report.GUSResult, g *graph.Graph) bool {
	if sc.Expect == nil {
		return true // no expectations to check
	}

	ok := true

	// Check GUS decision
	if sc.Expect.GUS != "" {
		expectPass := strings.EqualFold(sc.Expect.GUS, "PASS")
		if gusResult.OK != expectPass {
			fmt.Printf("    expected GUS=%s, got %v\n", sc.Expect.GUS, gusResult.OK)
			ok = false
		}
	}

	// Check expected breaks
	for _, eb := range sc.Expect.Breaks {
		found := false
		for _, er := range gusResult.Edges {
			if er.Edge.Name == eb.Edge {
				for _, v := range er.Violations {
					if v.Rule == eb.Rule {
						found = true
						break
					}
				}
			}
		}
		if !found {
			fmt.Printf("    expected break on edge %s with rule %s, not found\n", eb.Edge, eb.Rule)
			ok = false
		}
	}

	// Check MSS if expected
	if len(sc.Expect.MSS) > 0 {
		clauses := buildClauses(gusResult, g, sc)
		proposed := buildUpgrades(sc)
		mssResult := solver.ComputeMSS(proposed, clauses)

		gotSafe := make(map[string]bool)
		for _, u := range mssResult.Safe {
			gotSafe[u.Service] = true
		}
		for _, expected := range sc.Expect.MSS {
			if !gotSafe[expected] {
				fmt.Printf("    expected %s in MSS, not found\n", expected)
				ok = false
			}
		}
	}

	return ok
}

// --- Helpers ---

func mustLoadInputs(graphPath, scenarioPath string) (*graph.Graph, *graph.ScenarioDef) {
	if graphPath == "" || scenarioPath == "" {
		fmt.Fprintln(os.Stderr, "Both --graph and --scenario are required")
		os.Exit(1)
	}
	g, err := graph.LoadGraph(graphPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error loading graph: %v\n", err)
		os.Exit(1)
	}
	sc, err := graph.LoadScenario(scenarioPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error loading scenario: %v\n", err)
		os.Exit(1)
	}
	return g, sc
}

func resolveVersion(versions map[string]string, svc, fallback string) string {
	if v, ok := versions[svc]; ok {
		return v
	}
	return fallback
}

func loadEdgeSchemas(g *graph.Graph, edgeDef graph.EdgeDef, callerVer, providerVer string) (edge.VersionedSchemas, error) {
	var schemas edge.VersionedSchemas

	// Load provider spec for Accept + Return
	provPath, err := g.SpecPath(edgeDef.To, providerVer)
	if err != nil {
		return schemas, fmt.Errorf("provider %s@%s: %w", edgeDef.To, providerVer, err)
	}
	provSpec, err := schema.Load(provPath, edgeDef.To)
	if err != nil {
		return schemas, fmt.Errorf("load %s: %w", provPath, err)
	}

	key := schema.EndpointKey{Path: edgeDef.Path, Method: strings.ToLower(edgeDef.Method)}
	ep, ok := provSpec.Endpoints[key]
	if !ok {
		// Try uppercase method
		key.Method = strings.ToUpper(edgeDef.Method)
		ep, ok = provSpec.Endpoints[key]
		if !ok {
			return schemas, fmt.Errorf("endpoint %s %s not found in %s", edgeDef.Method, edgeDef.Path, provPath)
		}
	}

	schemas.Accept = ep.Request
	schemas.Return = ep.Response

	// For Send/Expect: use caller's spec if available, else fall back to provider's schemas
	callerPath, err := g.SpecPath(edgeDef.From, callerVer)
	if err != nil {
		// No caller spec — Send=Accept, Expect=Return (Tier 3 default)
		schemas.Send = schemas.Accept
		schemas.Expect = schemas.Return
		return schemas, nil
	}

	callerSpec, err := schema.Load(callerPath, edgeDef.From)
	if err != nil {
		schemas.Send = schemas.Accept
		schemas.Expect = schemas.Return
		return schemas, nil
	}

	// Try /_calls/<provider><path> convention
	callKey := schema.EndpointKey{
		Path:   filepath.Join("/_calls", edgeDef.To, edgeDef.Path),
		Method: strings.ToLower(edgeDef.Method),
	}
	if callerEP, ok := callerSpec.Endpoints[callKey]; ok {
		schemas.Send = callerEP.Request
		schemas.Expect = callerEP.Response
	} else {
		// Fall back to provider schemas
		schemas.Send = schemas.Accept
		schemas.Expect = schemas.Return
	}

	return schemas, nil
}

func toEdge(ed graph.EdgeDef) edge.Edge {
	name := ed.Name
	if name == "" {
		name = ed.From + "->" + ed.To
	}
	channel := ed.Channel
	if channel == "" {
		channel = "http"
	}
	return edge.Edge{
		Name:    name,
		From:    ed.From,
		To:      ed.To,
		Channel: channel,
		Method:  ed.Method,
		Path:    ed.Path,
		Topic:   ed.Topic,
	}
}
