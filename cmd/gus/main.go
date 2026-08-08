// GUS (Global Upgrade Safety) checker — validates type compatibility across
// microservice boundaries and computes the Maximal Safe Subset (MSS) for
// simultaneous service upgrades.
//
// Usage:
//
//	gus check      --graph graph.yaml --scenario scenario.yaml
//	gus mss        --graph graph.yaml --scenario scenario.yaml
//	gus consistent --graph graph.yaml --scenario scenario.yaml [--state target]
//	gus validate   --graph graph.yaml --scenario-dir dir/
//	gus viz        --graph graph.yaml --scenario scenario.yaml [--html out.html]
//
// Exit codes: 0 = decision YES / all expectations met; 1 = decision NO (or,
// for mss, not every proposed upgrade is in the safe subset); 2 = the inputs
// could not be evaluated (missing spec, unknown service/version, unsupported
// construct). Evaluation errors are never downgraded to a passing result.
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/faults-lab/gus/pkg/chain"
	"github.com/faults-lab/gus/pkg/compat"
	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/graph"
	"github.com/faults-lab/gus/pkg/lattice"
	"github.com/faults-lab/gus/pkg/report"
	"github.com/faults-lab/gus/pkg/schema"
	"github.com/faults-lab/gus/pkg/solver"
	"github.com/faults-lab/gus/pkg/types"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
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
	case "evolve":
		runEvolve(os.Args[2:])
	case "viz":
		runViz(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, `GUS — Global Upgrade Safety Checker

Commands:
  check       Report statically visible wire hazards for a proposed upgrade batch
  mss         Compute the safe subset + rollout order when GUS=NO
  consistent  Verify a single deployment state is internally compatible
  validate    Run all scenarios in a directory and check expected results
  evolve      Replay ordered rollout steps, maintaining a provenance ledger
  viz         Emit JSON artifact for the browser-based scenario visualizer

Flags:
  --graph        Path to graph.yaml (service mesh topology)
  --scenario     Path to scenario.yaml (upgrade definition)
  --scenario-dir Path to directory of scenario YAML files (for validate)
  --format       Output format: text (default) or json
  --state        For consistent: baseline (default) or target`)
}

func fatalf(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, "gus: "+format+"\n", args...)
	os.Exit(2)
}

func runCheck(args []string) {
	fs := flag.NewFlagSet("check", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	scenarioPath := fs.String("scenario", "", "path to scenario.yaml")
	format := fs.String("format", "text", "output format: text or json")
	fs.Parse(args)

	g, sc := mustLoadInputs(*graphPath, *scenarioPath)
	result, err := executeGUS(newSpecLoader(), g, sc, sc.Upgrades)
	if err != nil {
		fatalf("%v", err)
	}

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
	loader := newSpecLoader()
	gusResult, err := executeGUS(loader, g, sc, sc.Upgrades)
	if err != nil {
		fatalf("%v", err)
	}

	if gusResult.OK {
		fmt.Print(gusResult.Text())
		fmt.Println("\nAll upgrades are safe. No MSS computation needed.")
		return
	}

	mssResult, postHocOK, err := computeMSSWithPostHoc(loader, g, sc, gusResult)
	if err != nil {
		fatalf("%v", err)
	}
	rpt := &report.MSSReport{
		Scenario:   sc.Name,
		GUS:        gusResult,
		MSS:        mssResult,
		PostHocOK:  postHocOK,
		PostHocRan: true,
	}
	fmt.Print(rpt.Text())

	// The batch as proposed is not safe (and if post-hoc failed, neither is
	// the subset) — never signal green for a partial answer.
	os.Exit(1)
}

// computeMSSWithPostHoc derives clauses, solves, and re-verifies the safe
// subset by replaying its rollout STAGE BY STAGE: within a stage the mixed
// pairings must hold against the accumulated state; a completed stage then
// becomes part of the baseline for the next. This is the executable meaning
// of the solver's Order output — an MSS that only works when sequenced (e.g.
// callers before provider) passes here and would rightly fail a naive
// simultaneous re-check.
func computeMSSWithPostHoc(loader *specLoader, g *graph.Graph, sc *graph.ScenarioDef, gusResult *report.GUSResult) (*solver.MSSResult, bool, error) {
	clauses, precedences := buildClauses(gusResult, sc)
	proposed := buildUpgrades(sc)
	mssResult := solver.ComputeMSS(proposed, clauses, precedences)

	postHocOK := true
	safeUpgrades := make(map[string]string, len(mssResult.Safe))
	for _, u := range mssResult.Safe {
		safeUpgrades[u.Service] = u.ToVer
	}
	base := overlay(sc.Baseline, nil)
	for _, stage := range mssResult.Order {
		stageUp := make(map[string]string, len(stage))
		for _, svc := range stage {
			stageUp[svc] = safeUpgrades[svc]
		}
		scStage := *sc
		scStage.Baseline = base
		verify, err := executeGUS(loader, g, &scStage, stageUp)
		if err != nil {
			return nil, false, fmt.Errorf("post-hoc verification: %w", err)
		}
		if !verify.OK {
			postHocOK = false
			break
		}
		base = overlay(base, stageUp)
	}
	return &mssResult, postHocOK, nil
}

func runConsistent(args []string) {
	fs := flag.NewFlagSet("consistent", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	scenarioPath := fs.String("scenario", "", "path to scenario.yaml")
	state := fs.String("state", "baseline", "deployment state to check: baseline or target")
	fs.Parse(args)

	g, sc := mustLoadInputs(*graphPath, *scenarioPath)
	versions := materialize(resolveState(sc, *state == "target"), g)

	cfg := scenarioConfig(sc)
	loader := newSpecLoader()
	result := &report.ConsistentResult{State: *state, OK: true}

	for _, edgeDef := range g.Def.Edges {
		if edgeDef.Channel == "kafka" {
			fatalf("edge %s: kafka edges are not supported (no topic→schema resolution)", edgeDef.Name)
		}
		ver := versions[edgeDef.From]
		provVer := versions[edgeDef.To]
		es, err := loadEdgeSchemas(loader, g, edgeDef, ver, provVer, ver, provVer)
		if err != nil {
			fatalf("edge %s: %v", edgeDef.Name, err)
		}
		er := edge.Consistent(toEdge(edgeDef), es.old, cfg)
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
		os.Exit(2)
	}

	g, err := graph.LoadGraph(*graphPath)
	if err != nil {
		fatalf("loading graph: %v", err)
	}
	scenarios, err := graph.LoadScenarioDir(*scenarioDir)
	if err != nil {
		fatalf("loading scenarios: %v", err)
	}

	loader := newSpecLoader()
	passed, failed := 0, 0
	for _, sc := range scenarios {
		if err := validateScenarioRefs(g, sc); err != nil {
			fmt.Printf("  FAIL  %s\n    %v\n", sc.Name, err)
			failed++
			continue
		}
		gusResult, err := executeGUS(loader, g, sc, sc.Upgrades)
		if err != nil {
			fmt.Printf("  FAIL  %s\n    %v\n", sc.Name, err)
			failed++
			continue
		}
		ok, msgs := validateExpectations(loader, sc, gusResult, g)
		if ok {
			fmt.Printf("  PASS  %s\n", sc.Name)
			passed++
		} else {
			fmt.Printf("  FAIL  %s\n", sc.Name)
			for _, m := range msgs {
				fmt.Printf("    %s\n", m)
			}
			failed++
		}
	}

	fmt.Printf("\n%d passed, %d failed\n", passed, failed)
	if failed > 0 {
		os.Exit(1)
	}
}

// --- Core execution ---

// scenarioConfig builds the compat configuration for a scenario, honoring its
// coercion profile ("" or "strict" → strict; "lenient" → Jackson-style
// scalar-to-string coercion).
func scenarioConfig(sc *graph.ScenarioDef) compat.Config {
	cfg := compat.DefaultConfig()
	if sc.Coercion == "lenient" {
		cfg.Coercion = lattice.CoercionLenient
	}
	return cfg
}

// resolveState materializes a full service→version map for either the
// baseline state (θ) or the target state (θ' = baseline overlaid with the
// given upgrades).
func resolveState(sc *graph.ScenarioDef, target bool) map[string]string {
	versions := make(map[string]string)
	for svc, v := range sc.Baseline {
		versions[svc] = v
	}
	if target {
		for svc, v := range sc.Upgrades {
			versions[svc] = v
		}
	}
	return versions
}

func versionOf(versions map[string]string, svc string) string {
	if v, ok := versions[svc]; ok {
		return v
	}
	return "v1"
}

// executeGUS evaluates the EdgeOK conjunction plus chain integrity for the
// given upgrade set (which may be a subset of the scenario's proposal, e.g.
// for post-hoc verification). Any input that cannot be evaluated is an error,
// never a silent pass.
func executeGUS(loader *specLoader, g *graph.Graph, sc *graph.ScenarioDef, upgrades map[string]string) (*report.GUSResult, error) {
	cfg := scenarioConfig(sc)
	result := &report.GUSResult{Scenario: sc.Name, OK: true}

	for _, edgeDef := range g.Def.Edges {
		if edgeDef.Channel == "kafka" {
			return nil, fmt.Errorf("edge %s: kafka edges are not supported (no topic→schema resolution exists; refusing to skip a safety check silently)", edgeDef.Name)
		}

		_, callerUpgrading := upgrades[edgeDef.From]
		_, providerUpgrading := upgrades[edgeDef.To]
		if !callerUpgrading && !providerUpgrading {
			continue // schemas identical on both sides; conjuncts hold trivially
		}

		baseCallerVer := versionOf(sc.Baseline, edgeDef.From)
		baseProvVer := versionOf(sc.Baseline, edgeDef.To)
		newCallerVer := baseCallerVer
		if v, ok := upgrades[edgeDef.From]; ok {
			newCallerVer = v
		}
		newProvVer := baseProvVer
		if v, ok := upgrades[edgeDef.To]; ok {
			newProvVer = v
		}

		es, err := loadEdgeSchemas(loader, g, edgeDef, baseCallerVer, baseProvVer, newCallerVer, newProvVer)
		if err != nil {
			return nil, fmt.Errorf("edge %s: %w", edgeDef.Name, err)
		}

		er := edge.CheckEdgeRPC(toEdge(edgeDef), es.old, es.new, es.callerReal, cfg)
		result.Edges = append(result.Edges, er)
		if !er.OK {
			result.OK = false
		}
	}

	// Chain integrity: evaluate at the target state; a chain already broken
	// at the baseline is pre-existing hygiene, not an upgrade hazard.
	targetVersions := overlay(sc.Baseline, upgrades)
	targetChains, err := evaluateChains(loader, g, targetVersions)
	if err != nil {
		return nil, err
	}
	baselineChains, err := evaluateChains(loader, g, materialize(sc.Baseline, g))
	if err != nil {
		return nil, err
	}
	baselineOK := make(map[string]bool)
	for _, cr := range baselineChains {
		baselineOK[chainID(cr)] = cr.OK
	}
	for _, cr := range targetChains {
		// Pre-existing = the chain EXISTED at the baseline and was already
		// broken there. A chain that only comes into existence at θ' (a new
		// x-requires) counts against this batch even if the guarantee eroded
		// long ago — the batch is what turns the erosion into a violation.
		if prevOK, existed := baselineOK[chainID(cr)]; !cr.OK && existed && !prevOK {
			fmt.Fprintf(os.Stderr, "warn: chain %s is already broken at the baseline state (pre-existing, not counted against this upgrade; run `gus evolve` to trace where the guarantee eroded)\n", cr.Key)
			continue
		}
		result.Chains = append(result.Chains, cr)
		if !cr.OK {
			result.OK = false
		}
	}

	// Attribute each broken chain to the upgrade(s) that caused it: a service
	// whose lone revert repairs the chain is a culprit; if no single revert
	// repairs it, every on-path upgrading service is held responsible.
	for i := range result.Chains {
		cr := &result.Chains[i]
		if cr.OK {
			continue
		}
		var onPathUp []string
		for _, svc := range cr.ChainPath {
			if _, ok := upgrades[svc]; ok {
				onPathUp = append(onPathUp, svc)
			}
		}
		var culprits []string
		for _, svc := range onPathUp {
			reverted := overlay(sc.Baseline, upgrades)
			reverted[svc] = versionOf(sc.Baseline, svc)
			rcs, err := evaluateChains(loader, g, reverted)
			if err != nil {
				return nil, err
			}
			// The revert repairs the chain if it now passes — or if it no
			// longer exists (the revert withdrew the annotation demanding it).
			repaired := true
			for _, rc := range rcs {
				if chainID(rc) == chainID(*cr) {
					repaired = rc.OK
					break
				}
			}
			if repaired {
				culprits = append(culprits, svc)
			}
		}
		if len(culprits) == 0 {
			culprits = onPathUp
		}
		cr.Culprits = culprits
	}

	return result, nil
}

func chainID(cr chain.ChainResult) string {
	return cr.Key + "|" + cr.Provider.Service + "|" + cr.Provider.Field + "|" + cr.Requirer.Service + "|" + cr.Requirer.Field
}

func overlay(base, upgrades map[string]string) map[string]string {
	out := make(map[string]string, len(base)+len(upgrades))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range upgrades {
		out[k] = v
	}
	return out
}

// materialize fills in the default v1 for graph services absent from the map.
func materialize(versions map[string]string, g *graph.Graph) map[string]string {
	out := make(map[string]string, len(g.Def.Services))
	for svc := range g.Def.Services {
		out[svc] = versionOf(versions, svc)
	}
	return out
}

// --- Chain evaluation ---

// evaluateChains scans annotations and validates every x-provides/x-requires
// chain at the given deployment state.
func evaluateChains(loader *specLoader, g *graph.Graph, versions map[string]string) ([]chain.ChainResult, error) {
	full := materialize(versions, g)

	specs, annotations, err := scanMesh(loader, g, full)
	if err != nil {
		return nil, err
	}

	var edges []chain.EdgeInfo
	for _, e := range g.Def.Edges {
		edges = append(edges, chain.EdgeInfo{Caller: e.From, Provider: e.To})
	}

	lookup := func(service, next, fieldName string) *chain.FieldInfo {
		spec, ok := specs[service]
		if !ok {
			return nil
		}
		// Prefer the schema the service actually SENDS toward the next hop
		// (its declared outbound contract for that edge); fall back to a
		// whole-spec search when no outbound contract is declared.
		if send := callerSendSchema(g, spec, service, next); send != nil {
			return lookupFieldIn([]*types.Node{send}, fieldName)
		}
		return lookupField(spec, fieldName)
	}

	return chain.CheckChains(annotations, edges, lookup), nil
}

// scanMesh loads every service's spec at the given (fully materialized)
// versions and collects all x-provides/x-requires annotations.
func scanMesh(loader *specLoader, g *graph.Graph, full map[string]string) (map[string]*schema.Spec, []chain.Annotation, error) {
	specs := make(map[string]*schema.Spec, len(full))
	svcNames := make([]string, 0, len(full))
	for svc := range full {
		svcNames = append(svcNames, svc)
	}
	sort.Strings(svcNames)

	var annotations []chain.Annotation
	for _, svc := range svcNames {
		spec, err := loader.load(g, svc, full[svc])
		if err != nil {
			return nil, nil, fmt.Errorf("service %s@%s: %w", svc, full[svc], err)
		}
		specs[svc] = spec
		for _, key := range sortedEndpointKeys(spec) {
			ep := spec.Endpoints[key]
			label := key.Method + " " + key.Path
			annotations = append(annotations, chain.ScanAnnotations(ep.Request, svc, full[svc], label)...)
			annotations = append(annotations, chain.ScanAnnotations(ep.Response, svc, full[svc], label)...)
		}
	}
	return specs, annotations, nil
}

// callerSendSchema returns the request schema `service` declares for its
// outbound call to `next`, or nil if no edge or no client declaration exists.
func callerSendSchema(g *graph.Graph, spec *schema.Spec, service, next string) *types.Node {
	for _, e := range g.Def.Edges {
		if e.From != service || e.To != next {
			continue
		}
		method := strings.ToUpper(e.Method)
		if ep, ok := spec.Endpoints[schema.EndpointKey{
			Path:   filepath.ToSlash(filepath.Join("/_calls", e.To, e.Path)),
			Method: method,
		}]; ok {
			return ep.Request
		}
		if ep, ok := spec.Endpoints[schema.EndpointKey{Path: e.Path, Method: method}]; ok && ep.Role == "client" {
			return ep.Request
		}
	}
	return nil
}

// lookupField applies the resolver tiers over every endpoint schema of a
// service: exact name, case-normalized name, then x-alias (a field declaring
// x-alias: <previousName> is the renamed carrier of that identity).
func lookupField(spec *schema.Spec, fieldName string) *chain.FieldInfo {
	var roots []*types.Node
	for _, key := range sortedEndpointKeys(spec) {
		ep := spec.Endpoints[key]
		roots = append(roots, ep.Request, ep.Response)
	}
	return lookupFieldIn(roots, fieldName)
}

// lookupFieldIn applies the resolver tiers over the given schema trees.
func lookupFieldIn(roots []*types.Node, fieldName string) *chain.FieldInfo {
	var exact, caseNorm, aliased *chain.FieldInfo
	lower := strings.ToLower(fieldName)

	for _, root := range roots {
		collectFields(root, func(h fieldHit) {
			fi := &chain.FieldInfo{Name: h.name, Required: h.required, Nullable: h.nullable, Schema: h.schema}
			switch {
			case h.name == fieldName:
				if exact == nil {
					exact = fi
				}
			case strings.ToLower(h.name) == lower:
				if caseNorm == nil {
					caseNorm = fi
				}
			case h.alias == fieldName:
				if aliased == nil {
					aliased = fi
				}
			}
		})
	}

	if exact != nil {
		return exact
	}
	if caseNorm != nil {
		return caseNorm
	}
	return aliased
}

func sortedEndpointKeys(spec *schema.Spec) []schema.EndpointKey {
	keys := make([]schema.EndpointKey, 0, len(spec.Endpoints))
	for k := range spec.Endpoints {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].Path != keys[j].Path {
			return keys[i].Path < keys[j].Path
		}
		return keys[i].Method < keys[j].Method
	})
	return keys
}

// fieldHit is one named object field encountered while walking a schema tree.
type fieldHit struct {
	name     string
	required bool
	nullable bool
	schema   *types.Node
	alias    string
}

func collectFields(n *types.Node, visit func(fieldHit)) {
	if n == nil {
		return
	}
	switch n.Kind {
	case types.KindObject:
		names := make([]string, 0, len(n.Fields))
		for name := range n.Fields {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			f := n.Fields[name]
			s, nullable := f.Schema, false
			if s != nil && s.Kind == types.KindNullable {
				s, nullable = s.Inner, true
			}
			visit(fieldHit{name: name, required: f.Required, nullable: nullable, schema: s, alias: f.XAlias})
			collectFields(f.Schema, visit)
		}
	case types.KindArray:
		collectFields(n.Items, visit)
	case types.KindNullable:
		collectFields(n.Inner, visit)
	case types.KindUnion:
		for _, v := range n.Variants {
			collectFields(v, visit)
		}
	case types.KindMap:
		collectFields(n.MapValue, visit)
	}
}

// --- Clause generation ---

// buildClauses translates every failed conjunct into the deck's pinning-rule
// clause plus a rollout-order constraint (slide 6):
//
//	C1/C3 pin the provider's θ' schema: if the provider ships, the caller's
//	  OLD contract must already be gone — the caller must fully upgrade
//	  first. Clause ¬x_provider ∨ x_caller, precedence caller ≺ provider.
//	  If the caller is not upgrading (or has no real caller schema, so its
//	  contract cannot change), the clause degenerates to the unit ¬x_provider.
//	C2/C4 pin the caller's θ' schema symmetrically: ¬x_caller ∨ x_provider,
//	  precedence provider ≺ caller; unit ¬x_caller if the provider is not
//	  upgrading.
//	TGT pins both θ' schemas: the two upgrades cannot coexist in the final
//	  state. Encoded as a 2-cycle of precedences so the solver's deadlock
//	  exclusion removes both (conservative: shipping exactly one would
//	  require an NP-hard choice; see pkg/solver).
//
// Chain breaks are attributed by reverting each on-path upgrading service in
// isolation: services whose revert repairs the chain get unit exclusions; if
// no single revert repairs it, every on-path upgrading service is excluded.
func buildClauses(gusResult *report.GUSResult, sc *graph.ScenarioDef) ([]solver.Clause, []solver.Precedence) {
	var clauses []solver.Clause
	var precedences []solver.Precedence
	seenClause := make(map[string]bool)
	seenPrec := make(map[string]bool)

	add := func(c solver.Clause) {
		k := c.Cause + "|" + c.Dep
		if !seenClause[k] {
			seenClause[k] = true
			clauses = append(clauses, c)
		}
	}
	addPrec := func(p solver.Precedence) {
		k := p.First + "|" + p.Then
		if !seenPrec[k] {
			seenPrec[k] = true
			precedences = append(precedences, p)
		}
	}

	for _, er := range gusResult.Edges {
		if er.OK {
			continue
		}
		u, v := er.Edge.From, er.Edge.To
		_, uUp := sc.Upgrades[u]
		_, vUp := sc.Upgrades[v]
		reason := fmt.Sprintf("breaks edge %s", er.Edge.Name)

		for _, conj := range er.FailedConjuncts {
			switch conj {
			case "C1", "C3":
				if !vUp {
					continue // conjunct pins θ'_v; can only fail when v upgrades
				}
				if uUp && er.CallerSpecUsed {
					add(solver.Clause{Cause: v, Dep: u, Reason: reason + " [" + conj + "]"})
					addPrec(solver.Precedence{First: u, Then: v, Reason: reason + " [" + conj + "]"})
				} else {
					add(solver.Clause{Cause: v, Dep: "", Reason: reason + " [" + conj + "]: old " + u + " instances persist"})
				}
			case "C2", "C4":
				if !uUp {
					continue
				}
				if vUp {
					add(solver.Clause{Cause: u, Dep: v, Reason: reason + " [" + conj + "]"})
					addPrec(solver.Precedence{First: v, Then: u, Reason: reason + " [" + conj + "]"})
				} else {
					add(solver.Clause{Cause: u, Dep: "", Reason: reason + " [" + conj + "]: old " + v + " instances persist"})
				}
			case "TGT":
				if uUp && vUp {
					r := reason + " [TGT]: target-state incompatibility"
					addPrec(solver.Precedence{First: u, Then: v, Reason: r})
					addPrec(solver.Precedence{First: v, Then: u, Reason: r})
				} else if uUp {
					add(solver.Clause{Cause: u, Dep: "", Reason: reason + " [TGT]"})
				} else if vUp {
					add(solver.Clause{Cause: v, Dep: "", Reason: reason + " [TGT]"})
				}
			}
		}
	}

	for _, cr := range gusResult.Chains {
		if cr.OK {
			continue
		}
		reason := fmt.Sprintf("breaks data-flow chain %q (%s)", cr.Key, cr.Rule)
		for _, svc := range cr.Culprits {
			add(solver.Clause{Cause: svc, Dep: "", Reason: reason})
		}
	}

	return clauses, precedences
}

func buildUpgrades(sc *graph.ScenarioDef) []solver.Upgrade {
	var upgrades []solver.Upgrade
	for svc, toVer := range sc.Upgrades {
		fromVer, ok := sc.Baseline[svc]
		if !ok {
			fromVer = "v1"
		}
		upgrades = append(upgrades, solver.Upgrade{Service: svc, FromVer: fromVer, ToVer: toVer})
	}
	sort.Slice(upgrades, func(i, j int) bool { return upgrades[i].Service < upgrades[j].Service })
	return upgrades
}

// --- Expectations ---

func validateExpectations(loader *specLoader, sc *graph.ScenarioDef, gusResult *report.GUSResult, g *graph.Graph) (bool, []string) {
	if sc.Expect == nil {
		return true, nil
	}
	var msgs []string

	if sc.Expect.GUS != "" {
		expectPass := strings.EqualFold(sc.Expect.GUS, "PASS")
		if gusResult.OK != expectPass {
			msgs = append(msgs, fmt.Sprintf("expected GUS=%s, got OK=%v", sc.Expect.GUS, gusResult.OK))
		}
	}

	for _, eb := range sc.Expect.Breaks {
		found := false
		for _, er := range gusResult.Edges {
			if er.Edge.Name != eb.Edge {
				continue
			}
			for _, v := range er.Violations {
				if v.Rule == eb.Rule {
					found = true
					break
				}
			}
		}
		if !found {
			msgs = append(msgs, fmt.Sprintf("expected break on edge %s with rule %s, not found", eb.Edge, eb.Rule))
		}
	}

	for _, ec := range sc.Expect.Chains {
		found := false
		for _, cr := range gusResult.Chains {
			if cr.Key == ec.Key && cr.Rule == ec.Rule {
				found = true
				break
			}
		}
		if !found {
			msgs = append(msgs, fmt.Sprintf("expected chain %s with rule %q, not found", ec.Key, ec.Rule))
		}
	}

	// MSS: exact set equality (including the empty set), plus post-hoc
	// verification that the safe subset actually passes GUS.
	if sc.Expect.MSS != nil {
		mssResult, postHocOK, err := computeMSSWithPostHoc(loader, g, sc, gusResult)
		if err != nil {
			msgs = append(msgs, fmt.Sprintf("MSS computation: %v", err))
		} else {
			got := make([]string, 0, len(mssResult.Safe))
			for _, u := range mssResult.Safe {
				got = append(got, u.Service)
			}
			want := append([]string(nil), sc.Expect.MSS...)
			sort.Strings(got)
			sort.Strings(want)
			if strings.Join(got, ",") != strings.Join(want, ",") {
				msgs = append(msgs, fmt.Sprintf("expected MSS exactly {%s}, got {%s}", strings.Join(want, ","), strings.Join(got, ",")))
			}
			if !postHocOK {
				msgs = append(msgs, "post-hoc verification of the safe subset FAILED")
			}
			if sc.Expect.Order != nil {
				fmtStages := func(stages [][]string) string {
					parts := make([]string, len(stages))
					for i, s := range stages {
						sorted := append([]string(nil), s...)
						sort.Strings(sorted)
						parts[i] = strings.Join(sorted, "+")
					}
					return strings.Join(parts, " -> ")
				}
				if fmtStages(mssResult.Order) != fmtStages(sc.Expect.Order) {
					msgs = append(msgs, fmt.Sprintf("expected rollout order %s, got %s",
						fmtStages(sc.Expect.Order), fmtStages(mssResult.Order)))
				}
			}
		}
	}

	return len(msgs) == 0, msgs
}

// validateScenarioRefs rejects scenarios referencing services or versions the
// graph does not define — a typo'd upgrade must never read as trivially safe.
func validateScenarioRefs(g *graph.Graph, sc *graph.ScenarioDef) error {
	checkRef := func(kind, svc, ver string) error {
		def, ok := g.Def.Services[svc]
		if !ok {
			return fmt.Errorf("%s references unknown service %q", kind, svc)
		}
		if _, ok := def.Versions[ver]; !ok {
			return fmt.Errorf("%s references unknown version %q of service %q", kind, ver, svc)
		}
		return nil
	}
	for svc, ver := range sc.Baseline {
		if err := checkRef("baseline", svc, ver); err != nil {
			return err
		}
	}
	for svc, ver := range sc.Upgrades {
		if err := checkRef("upgrades", svc, ver); err != nil {
			return err
		}
	}
	if sc.Coercion != "" && sc.Coercion != "strict" && sc.Coercion != "lenient" {
		return fmt.Errorf("unknown coercion profile %q (want strict or lenient)", sc.Coercion)
	}
	return nil
}

// --- Spec loading ---

// specLoader memoizes parsed specs by path (a provider spec referenced by k
// edges is parsed once, not 2k times).
type specLoader struct {
	cache map[string]*schema.Spec
}

func newSpecLoader() *specLoader {
	return &specLoader{cache: make(map[string]*schema.Spec)}
}

func (l *specLoader) load(g *graph.Graph, svc, ver string) (*schema.Spec, error) {
	path, err := g.SpecPath(svc, ver)
	if err != nil {
		return nil, err
	}
	if s, ok := l.cache[path]; ok {
		return s, nil
	}
	s, err := schema.Load(path, svc)
	if err != nil {
		return nil, err
	}
	l.cache[path] = s
	return s, nil
}

type edgeSchemas struct {
	old, new   edge.VersionedSchemas
	callerReal bool
}

// loadEdgeSchemas assembles the four role schemas for both deployment states
// of one edge.
//
// Provider side (Accept/Return): the provider spec's endpoint — required.
//
// Caller side (Send/Expect), resolver tiers:
//
//	Tier 2 — the caller's spec declares the outbound call, either under the
//	  /_calls/<provider><path> convention or as the provider's plain path
//	  marked x-role: client. Used only when BOTH versions declare it.
//	Tier 3 — otherwise, the caller is assumed pinned to the OLD provider
//	  contract for both states (callers were built against the contract that
//	  was live): Send := Accept(θ), Expect := Return(θ). Under this fallback
//	  C2/C4 hold trivially and C1/C3 degenerate to a provider self-diff —
//	  honest backward-compat checking, with no fabricated caller drift.
//
// (Tier 1 — deriving Send from caller source code — is not implemented.)
func loadEdgeSchemas(loader *specLoader, g *graph.Graph, edgeDef graph.EdgeDef, baseCallerVer, baseProvVer, newCallerVer, newProvVer string) (edgeSchemas, error) {
	var es edgeSchemas
	method := strings.ToUpper(edgeDef.Method)

	provEndpoint := func(ver string) (*schema.EndpointSchemas, error) {
		spec, err := loader.load(g, edgeDef.To, ver)
		if err != nil {
			return nil, fmt.Errorf("provider %s@%s: %w", edgeDef.To, ver, err)
		}
		ep, ok := spec.Endpoints[schema.EndpointKey{Path: edgeDef.Path, Method: method}]
		if !ok {
			return nil, fmt.Errorf("endpoint %s %s not found in provider %s@%s", method, edgeDef.Path, edgeDef.To, ver)
		}
		return ep, nil
	}

	oldProv, err := provEndpoint(baseProvVer)
	if err != nil {
		return es, err
	}
	newProv := oldProv
	if newProvVer != baseProvVer {
		if newProv, err = provEndpoint(newProvVer); err != nil {
			return es, err
		}
	}
	es.old.Accept, es.old.Return = oldProv.Request, oldProv.Response
	es.new.Accept, es.new.Return = newProv.Request, newProv.Response

	callerEndpoint := func(ver string) *schema.EndpointSchemas {
		spec, err := loader.load(g, edgeDef.From, ver)
		if err != nil {
			return nil
		}
		if ep, ok := spec.Endpoints[schema.EndpointKey{
			Path:   filepath.ToSlash(filepath.Join("/_calls", edgeDef.To, edgeDef.Path)),
			Method: method,
		}]; ok {
			return ep
		}
		if ep, ok := spec.Endpoints[schema.EndpointKey{Path: edgeDef.Path, Method: method}]; ok && ep.Role == "client" {
			return ep
		}
		return nil
	}

	oldCaller := callerEndpoint(baseCallerVer)
	newCaller := oldCaller
	if newCallerVer != baseCallerVer {
		newCaller = callerEndpoint(newCallerVer)
	}

	if oldCaller != nil && newCaller != nil {
		es.callerReal = true
		es.old.Send, es.old.Expect = oldCaller.Request, oldCaller.Response
		es.new.Send, es.new.Expect = newCaller.Request, newCaller.Response
		return es, nil
	}

	// Tier 3: anchor both states to the old provider contract.
	es.old.Send, es.old.Expect = es.old.Accept, es.old.Return
	es.new.Send, es.new.Expect = es.old.Accept, es.old.Return
	return es, nil
}

// --- Helpers ---

func mustLoadInputs(graphPath, scenarioPath string) (*graph.Graph, *graph.ScenarioDef) {
	if graphPath == "" || scenarioPath == "" {
		fmt.Fprintln(os.Stderr, "Both --graph and --scenario are required")
		os.Exit(2)
	}
	g, err := graph.LoadGraph(graphPath)
	if err != nil {
		fatalf("loading graph: %v", err)
	}
	sc, err := graph.LoadScenario(scenarioPath)
	if err != nil {
		fatalf("loading scenario: %v", err)
	}
	if err := validateScenarioRefs(g, sc); err != nil {
		fatalf("scenario %s: %v", sc.Name, err)
	}
	return g, sc
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
