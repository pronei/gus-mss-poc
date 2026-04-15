# GUS Scenario Visualizer

A standalone static frontend that renders a GUS scenario — services as
nodes, edges annotated with violated rules, tooltips that explain each
break in plain English, and a sidebar summarising the Maximal Safe Subset.

The frontend is intentionally decoupled from the Go tool:

```
graph.yaml         ┐                                   ┌─ viz/viz.html (p5.js, static)
scenario.yaml      ├─► pkg/viz.Build(...) ─► JSON ─────┤
OpenAPI specs/     ┘   (Go library — used by gus viz)  └─ viz/scenario-*.html (embedded)
```

`pkg/viz.Build()` produces the artifact. The command `gus viz` is a thin
wrapper that emits it as JSON or embeds it into `viz.html`. Anything else
that can produce the same JSON shape (see `pkg/viz/artifact.go`) works with
the frontend unchanged — you don't need the Go tool to view a scenario once
the HTML is generated.

## Three ways to open the view

**Self-contained HTML (simplest).** One file, opens with a double-click:

```sh
gus viz --graph graph.yaml --scenario scenarios/scenario-i.yaml \
        --html viz/scenario-i.html --template viz/viz.html
open viz/scenario-i.html
```

**JSON + static hosting.** Useful for iterating on the frontend without
re-embedding:

```sh
gus viz --graph ... --scenario ... > viz/data.json
cd viz && python3 -m http.server 8000
# open http://localhost:8000/viz.html?data=./data.json
```

**Paste JSON at load time.** Open `viz.html` with no data; a paste pane
appears. Useful for sharing artifacts over chat.

## What you see

- **Node** — black circle, version inside (`v1→v2` if upgrading, otherwise
  `v1`), service name below. Halo ring: green = safe upgrade (in MSS),
  red = excluded from MSS, no ring = unchanged in this scenario.
- **Edge** — straight arrow from caller to provider. Gray = unaffected,
  olive = safe within the upgrade, red = violation. Broken edges carry a
  white pill with the rule name at their midpoint.
- **Click a node** to pin its tooltip — lists only the violations on edges
  involving that service, so the view stays scoped to what actually broke.
  For services with only safe changes, a compact diff summary is shown.
- **Click an edge rule pill** (or anywhere along a broken edge) to pin the
  edge tooltip — full violation list with conjunct (C1–C4), JSONPath, type
  transition, and a templated rolling-deployment explanation.
- **Sidebar** — scenario description, MSS (safe vs removed with reasons),
  and a clickable list of broken edges.

## Frontend files

| File                        | Purpose                                        |
|-----------------------------|------------------------------------------------|
| `viz.html`                  | Template + frontend (p5.js, vanilla JS, CSS)   |
| `scenario-*.html`           | Pre-embedded scenarios (examples from §7)      |
| (JSON at runtime)           | `window.__VIZ_DATA__` or `?data=URL` or paste  |

## The JSON contract

The frontend treats `pkg/viz.Artifact` as the contract — `scenario`,
`services[]`, `edges[]`, `mss{}` with shapes documented in
`pkg/viz/artifact.go`. Any producer that emits this JSON shape can drive
the viewer; see the artifact builder for field-by-field semantics.

## Frontend-only flags

| Query param   | Purpose                                         |
|---------------|-------------------------------------------------|
| `?data=URL`   | Fetch artifact JSON from `URL`                  |
| (none)        | Try embedded `/*__VIZ_DATA__*/`, else paste UI  |

## CLI flags for embedding

| Flag           | Description                                                     |
|----------------|-----------------------------------------------------------------|
| `--graph`      | `graph.yaml`                                                    |
| `--scenario`   | scenario YAML                                                   |
| `--html PATH`  | write a self-contained HTML file (JSON embedded)                |
| `--template`   | override the `viz.html` template location                       |
| `--pretty`     | pretty-print stdout JSON (default true)                         |
