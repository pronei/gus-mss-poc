// gus evolve — replay an ordered sequence of rollout steps and maintain a
// persistent provenance ledger for every data-flow identity.
//
// The per-step commands (check/mss) can only judge one transition; the
// ledger judges a LIFETIME. Its purpose is the erosion that per-step checks
// structurally cannot see: a guarantee weakened while no requirer existed
// ships silently, and by the time a requirer appears the erosion is
// baseline. The ledger records guarantees at every shipped state, so the
// eventual violation is traced to the step that weakened the guarantee, not
// the step that finally demanded it.
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/faults-lab/gus/pkg/chain"
	"github.com/faults-lab/gus/pkg/evolve"
	"github.com/faults-lab/gus/pkg/graph"
	"github.com/faults-lab/gus/pkg/report"
)

func runEvolve(args []string) {
	fs := flag.NewFlagSet("evolve", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	stepsDir := fs.String("steps-dir", "", "directory of ordered rollout step scenarios")
	ledgerPath := fs.String("ledger", "", "ledger file persisted between invocations (default <steps-dir>/ledger.json)")
	fs.Parse(args)

	if *graphPath == "" || *stepsDir == "" {
		fmt.Fprintln(os.Stderr, "Usage: gus evolve --graph <path> --steps-dir <dir> [--ledger <file>]")
		os.Exit(2)
	}
	if *ledgerPath == "" {
		*ledgerPath = filepath.Join(*stepsDir, "ledger.json")
	}

	g, err := graph.LoadGraph(*graphPath)
	if err != nil {
		fatalf("loading graph: %v", err)
	}
	steps, err := graph.LoadScenarioDir(*stepsDir)
	if err != nil {
		fatalf("loading steps: %v", err)
	}
	ledger, err := evolve.LoadLedger(*ledgerPath)
	if err != nil {
		fatalf("%v", err)
	}

	loader := newSpecLoader()
	var shipped map[string]string // accumulated reality across steps

	for _, sc := range steps {
		if err := validateScenarioRefs(g, sc); err != nil {
			fatalf("step %s: %v", sc.Name, err)
		}
		if shipped != nil {
			for svc, ver := range sc.Baseline {
				if shipped[svc] != "" && shipped[svc] != ver {
					fmt.Fprintf(os.Stderr, "warn: step %q declares baseline %s@%s but the previous steps shipped %s — the ledger follows the declared baseline\n",
						sc.Name, svc, ver, shipped[svc])
				}
			}
		}

		gusResult, err := executeGUS(loader, g, sc, sc.Upgrades)
		if err != nil {
			fatalf("step %s: %v", sc.Name, err)
		}
		mssResult, _, err := computeMSSWithPostHoc(loader, g, sc, gusResult)
		if err != nil {
			fatalf("step %s: %v", sc.Name, err)
		}
		safeUpgrades := make(map[string]string, len(mssResult.Safe))
		for _, u := range mssResult.Safe {
			safeUpgrades[u.Service] = u.ToVer
		}
		shipped = materialize(overlay(sc.Baseline, safeUpgrades), g)

		if ledger.Recorded(sc.Name) {
			fmt.Fprintf(os.Stderr, "skip (already in ledger): %s\n", sc.Name)
			continue
		}

		obs, err := observeStep(loader, g, sc, shipped, safeUpgrades, gusResult)
		if err != nil {
			fatalf("step %s: %v", sc.Name, err)
		}
		ledger.RecordStep(sc.Name, obs)
	}

	if err := ledger.Save(*ledgerPath); err != nil {
		fatalf("saving ledger: %v", err)
	}
	fmt.Print(ledger.Text())
	fmt.Printf("\nledger written to %s\n", *ledgerPath)
}

// observeStep captures, for every identity key: the guarantee at the SHIPPED
// state (what reality now looks like) and the demands/violations at the
// PROPOSED state (what this step tried to do) — a rejected demand still
// belongs in the history.
func observeStep(loader *specLoader, g *graph.Graph, sc *graph.ScenarioDef,
	shipped, safeUpgrades map[string]string, gusResult *report.GUSResult) ([]evolve.StepObservation, error) {

	_, shippedAnns, err := scanMesh(loader, g, shipped)
	if err != nil {
		return nil, err
	}
	proposed := materialize(overlay(sc.Baseline, sc.Upgrades), g)
	_, proposedAnns, err := scanMesh(loader, g, proposed)
	if err != nil {
		return nil, err
	}

	var edges []chain.EdgeInfo
	for _, e := range g.Def.Edges {
		edges = append(edges, chain.EdgeInfo{Caller: e.From, Provider: e.To})
	}

	providers := map[string]chain.Annotation{}
	provided := map[string]bool{}
	for _, a := range shippedAnns {
		if a.Kind == "provides" {
			if _, dup := providers[a.Key]; !dup {
				providers[a.Key] = a
				provided[a.Key] = true
			}
		}
	}
	shippedRequirers := map[string][]string{}
	for _, a := range shippedAnns {
		if a.Kind == "requires" {
			shippedRequirers[a.Key] = append(shippedRequirers[a.Key], a.Service)
		}
	}
	proposedRequirers := map[string][]string{}
	requirerSvc := map[string]map[string]bool{}
	for _, a := range proposedAnns {
		if a.Kind == "requires" {
			proposedRequirers[a.Key] = append(proposedRequirers[a.Key], a.Service)
			if requirerSvc[a.Key] == nil {
				requirerSvc[a.Key] = map[string]bool{}
			}
			requirerSvc[a.Key][a.Service] = true
		}
	}

	violations := map[string]string{}
	for _, cr := range gusResult.Chains {
		if !cr.OK && (violations[cr.Key] == "" || violations[cr.Key] == "chain-no-path") {
			violations[cr.Key] = cr.Rule
		}
	}

	keys := map[string]bool{}
	for k := range providers {
		keys[k] = true
	}
	for k := range proposedRequirers {
		keys[k] = true
	}
	sortedKeys := make([]string, 0, len(keys))
	for k := range keys {
		sortedKeys = append(sortedKeys, k)
	}
	sort.Strings(sortedKeys)

	var out []evolve.StepObservation
	for _, key := range sortedKeys {
		o := evolve.StepObservation{Key: key}
		if provided[key] {
			a := providers[key]
			parts := strings.Split(a.Field, ".")
			g8 := &evolve.Guarantee{
				Provider: a.Service,
				Field:    parts[len(parts)-1],
				Required: a.Required,
				Nullable: a.Nullable,
			}
			if a.Schema != nil {
				g8.Type = a.Schema.Summary()
			}
			// Carrying paths toward every requirer at the shipped state — the
			// multi-path record (diamond meshes carry along any route).
			for _, req := range dedupe(shippedRequirers[key]) {
				for _, p := range chain.AllPaths(a.Service, req, edges, 6) {
					g8.Paths = append(g8.Paths, strings.Join(p, ">"))
				}
			}
			sort.Strings(g8.Paths)
			o.Guarantee = g8
		}
		o.Requirers = dedupe(proposedRequirers[key])
		o.Violated = violations[key]
		if o.Violated != "" {
			// The demand did not ship if any demanding service's upgrade was excluded.
			for svc := range requirerSvc[key] {
				if _, wanted := sc.Upgrades[svc]; wanted {
					if _, ok := safeUpgrades[svc]; !ok {
						o.Rejected = true
					}
				}
			}
		}
		out = append(out, o)
	}
	return out, nil
}

func dedupe(in []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range in {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	sort.Strings(out)
	return out
}
