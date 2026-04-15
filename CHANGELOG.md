# Changelog

All notable changes to this repository are tracked here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
anchored to the GUS/MSS paper submission rather than semver — until the
formalism stabilises, API changes are expected.

## [Unreleased]

### Added
- **Online Boutique mesh expansion** — `graph.yaml` now covers 9 services
  (frontend, checkout, shipping, productcatalog, currency, cart,
  recommendation, payment, email) and 14 RPC edges, matching the paper's
  mesh illustration.
- **New service specs** — currency (v1/v2), cart (v1), recommendation (v1),
  payment (v1), productcatalog v3 (recursive categories), email v2 (safe
  optional field), checkout v3 (adds `idempotency_key`, changes
  `order_id` from `string` to `integer` to exercise the JSON primitive
  lattice asymmetry), shipping v3 (safe optional estimated_delivery).
- **Scenario E — Hasty Money restructure.** Currency v2 collapses
  `Money{currency_code, units, nanos}` into `Money{currency_code,
  amount}`. Exercises REQ.1 + RES.1 breaks on distinct callers in one
  change.
- **Scenario F — Recursive category tree.** ProductCatalog v3 replaces a
  flat enum with a recursive `Category{name, children}`. Stresses
  coinductive `$ref`-cycle handling via `kind-mismatch`.
- **Scenario G — Composite upgrade with non-trivial MSS.** Three
  services upgrade together; only one (email v2, safe) survives. First
  scenario to demonstrate Horn-clause propagation on independent breaks.
- **Scenario I — Full-mesh upgrade storm.** Six services upgrade,
  `recommendation` stays at v1 and triggers the cascade. Exercises the
  4-pairing lattice asymmetry (order_id `string`↔`integer`: C3 passes,
  C4 fails) and an x-provides/x-requires data-flow chain mismatch that
  neither Pact nor Buf can detect.
- **`gus viz` subcommand** — emits a JSON artifact describing services,
  edges, violations, and MSS result. With `--html` it embeds the artifact
  into the static template to produce a self-contained page.
- **Static p5.js visualizer** (`viz/viz.html`) — hierarchical tiered
  layout, straight arrows color-matched to edge status, violation-scoped
  node tooltips, click-to-pin with scrollable content and close button,
  clickable sidebar of broken edges.
- **`pkg/viz` package** — artifact types, `Build()`, `Marshal()`,
  `EmbedInTemplate()`, `LoadTemplate()`, and `ExplainViolation()`. The
  CLI subcommand is now a thin wrapper so the frontend stays a pure
  static site.
- **README, CHANGELOG, LICENSE.**

### Changed
- **Hit detection on the visualizer** — node hit zone now includes the
  service-name label below the circle, not just the circle itself.
  Fixes the "click to pin does not work on nodes" bug where clicks on
  the label were being interpreted as empty-canvas clicks.
- **Arrow rendering** — replaced bezier curves with straight lines,
  bolder strokes (2.6/2.0/1.4 base weights, +0.8 on hover), solid
  13×7px arrowheads color-matched to edge state.
- **Graph layout** — replaced the force-directed layout with a
  hierarchical tiered placement using longest-path topological depth
  and barycenter sort to minimise edge crossings.
- **Node tooltip** — replaced the full-spec dump with a violation-scoped
  listing (edges where this service is caller or provider) plus a
  compact schema diff summary for safe upgrades only.

### Fixed
- **Race between p5 `mousePressed` and the document `click` handler** —
  the redundant document-level handler was cleared pinned state
  immediately after it was set. Removed; pin/unpin now handled in one
  place (`mousePressed` + × button).

### Architecture
- Viz artifact construction moved from `cmd/gus/viz.go` to `pkg/viz/`.
  The Go binary and the HTML viewer are now decoupled: anything that
  can emit the JSON shape defined in `pkg/viz/artifact.go` works with
  the viewer unchanged.

## [0.1.0] — initial commit

### Added
- **Core solver** — types AST (Prim, Literal, Enum, Array, Object, Map,
  Union, Nullable, Ref, Any), JSON + proto primitive lattices, compat
  rules keyed to REQ.1–REQ.6 / RES.1–RES.6, OpenAPI 3.0 loader with
  `$ref` resolution, RPC edge checker with the full 4-pairing (C1–C4),
  Horn-SAT MSS solver (O(|clauses| + |U|)).
- **CLI** — `gus check`, `gus mss`, `gus consistent`, `gus validate`.
- **Online Boutique baseline** — 3-service slice (frontend, checkout,
  shipping, email, productcatalog) with scenarios B–D and H.
- **Chain checker** — `x-provides` / `x-requires` BFS with monotonicity
  rules.
