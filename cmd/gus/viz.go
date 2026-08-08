// gus viz — emit a JSON artifact describing a scenario's services, edges,
// violations, and MSS result. When --html is set, the artifact is embedded
// into the viz.html template producing a self-contained page.
//
// The artifact shape and build logic live in pkg/viz so the frontend stays a
// pure static site; this file only wires CLI flags to that package.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/faults-lab/gus/pkg/solver"
	"github.com/faults-lab/gus/pkg/viz"
)

func runViz(args []string) {
	fs := flag.NewFlagSet("viz", flag.ExitOnError)
	graphPath := fs.String("graph", "", "path to graph.yaml")
	scenarioPath := fs.String("scenario", "", "path to scenario.yaml")
	pretty := fs.Bool("pretty", true, "pretty-print JSON output")
	htmlOut := fs.String("html", "", "if set, write a self-contained HTML file (embeds JSON into viz.html)")
	templatePath := fs.String("template", "", "path to viz.html template (defaults to ./viz/viz.html)")
	fs.Parse(args)

	g, sc := mustLoadInputs(*graphPath, *scenarioPath)
	loader := newSpecLoader()
	gusResult, err := executeGUS(loader, g, sc, sc.Upgrades)
	if err != nil {
		fatalf("%v", err)
	}

	// Always compute MSS so the artifact carries it even on GUS=PASS.
	clauses, precedences := buildClauses(gusResult, sc)
	proposed := buildUpgrades(sc)
	mssResult := solver.ComputeMSS(proposed, clauses, precedences)

	art := viz.Build(g, sc, gusResult, &mssResult)

	data, err := viz.Marshal(art, *pretty)
	if err != nil {
		fmt.Fprintf(os.Stderr, "viz: marshal: %v\n", err)
		os.Exit(1)
	}

	if *htmlOut == "" {
		fmt.Println(string(data))
		return
	}

	tpl, err := viz.LoadTemplate(*templatePath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "viz: template: %v\n", err)
		os.Exit(1)
	}
	compact, err := json.Marshal(art)
	if err != nil {
		fmt.Fprintf(os.Stderr, "viz: marshal compact: %v\n", err)
		os.Exit(1)
	}
	out := viz.EmbedInTemplate(tpl, compact)
	if err := os.WriteFile(*htmlOut, []byte(out), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "viz: write html: %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "wrote %s (open in a browser)\n", *htmlOut)
}
