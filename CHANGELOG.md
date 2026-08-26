# Changelog

All notable changes to this repository are tracked here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
anchored to the GUS/MSS paper submission rather than semver — until the
formalism stabilises, API changes are expected.

## 0.3.1 — eval-enabling assertions (2026-08-25)

### Added
- `expect.breaks_exact`: when set, the distinct (edge, rule) pairs of every
  reported finding (any severity) must equal the expected list exactly —
  false positives become measurable. Adopted on scenarios B/D/H and
  evolution steps 01/10 (D now asserts ZERO edge findings: only the chain
  detects it).
- Baseline consistency gate: `check`/`mss`/`validate` (and each staged
  post-hoc replay) now verify Consistent(θ) first; an inconsistent
  baseline is an evaluation error (exit 2), never a silent pass — the
  skip of untouched edges is sound only under this precondition.

## 0.3.0 — evolution suite, provenance ledger, visualizer rebuild, paper (2026-07-06)

### Added
- `gus evolve`: replays ordered rollout steps and maintains a persistent
  per-identity provenance ledger (`pkg/evolve`). Detects guarantees that
  erode while nothing requires them and traces later violations to the
  origin step. Ledger records all carrying paths (`chain.AllPaths`).
- Evolution suite: `scenarios/online-boutique/evolution/` — 11 steps of
  plausible feature development covering every rule, staged rollout
  orders, the TGT deadlock, x-alias rename bridging, and the silent-
  erosion-then-exposure story (step 07 → step 11).
- Rollout-order expectations (`expect.order`) in scenario YAML; staged
  post-hoc verification replays MSS stages instead of a naive
  simultaneous re-check.
- Edge-directed chain hop lookup: intermediates are validated against
  what they SEND toward the next hop, making x-alias renames checkable.
- New spec versions: frontend v4–v7, checkout v4–v8, shipping v4–v5,
  currency v3–v4, payment v2, cart v2, recommendation v2–v3, email v3–v4.
- Workshop paper draft (`docs/paper/gus-workshop.tex`, single-file,
  compiles on Overleaf; rendered PDF included). Scoped strictly to the
  implemented artifact: pair-quantified edge compatibility, plan safety
  with staged-replay certificates, the easy-fragment/NP-hard boundary,
  and the guarantee ledger — no coercion-dependent claims (the paper
  assumes strict JSON decoding throughout).
- First-principles primer (`docs/primer.md`): the formal background —
  variance, coinduction, Horn logic and the union-closure lemma, Max-Ones
  hardness, rollout order theory, ledger semantics — with a theory→code
  map and the objections to raise before an audience does.
- Review errata (`docs/review-notes.md`): the adversarial-review findings
  that motivated 0.2.0's design decisions.
- `pkg/lattice` test suite (strict/lenient JSON profiles, proto
  wire-compatibility including the deliberate absence of float⊑double).

### Changed
- Visualizer rebuilt from scratch: self-contained (no p5.js CDN, no
  webfonts), SVG mesh, legible violation cards (window sentence, human
  rule names, type pills), deployment-plan stages, chain cards with
  culprit highlighting. Artifact gains failed_conjuncts, caller_spec_used,
  mss.order, scenario.coercion; drops embedded raw specs.
- WARN-only findings no longer break an edge (they render as warnings and
  generate no clauses) — expand-phase changes like response format
  widening ship with a range-risk warning instead of a false block.
- Chains that come into existence at θ' (a new x-requires) now count
  against the batch even if the guarantee eroded earlier; culprit
  analysis treats a revert that dissolves the chain as a repair.
- `chain.CheckChains` now validates EVERY simple call path between a
  provider and requirer (bounded, deterministic shortest-first), not just
  the BFS-shortest — a mesh can route an identity along any of them.
  `bfsPath` removed.

### Removed
- Dead code: `edge.CheckEdgeSubscribe` (unreachable — no topic→schema
  resolution exists; kafka edges are rejected upstream),
  `EdgeResult.Conjunct()` (unused; `FailedConjuncts` carries the data),
  and the write-only `schema.Spec.Schemas` component map (the sorted
  pre-resolution loop that guarantees deterministic AST shapes remains).

## 0.2.0 — soundness overhaul (2026-07-02)

### Soundness review

A full adversarial review of the formalism and implementation
(`docs/review-notes.md` has the slide-by-slide findings). Everything
below ships in this change set.

#### Fixed — soundness
- **MSS returned broken co-upgrades as "safe."** Both-endpoints-upgrading
  broken edges were encoded as symmetric implications that unit
  propagation can never falsify; a two-service batch failing C1+C4
  reported the full set as its safe subset. Clause generation is now
  conjunct-aware per the deck's pinning rule, emits rollout-ordering
  precedences, and the solver excludes precedence deadlock cycles and
  outputs a stage-by-stage rollout order. `mss` re-verifies its answer
  by re-running GUS on the safe subset (post-hoc target-state check,
  previously promised on slide 5 and unimplemented).
- **The four-schema model was inert.** The `/_calls` caller lookup could
  never match (method-case mismatch) and no spec used the convention, so
  every edge ran the `Send:=Accept` fallback — C1–C4 degenerated to a
  provider self-diff and the fallback fabricated caller drift (false
  BREAKs on safe provider request-widening). Caller declarations are now
  honored (`x-role: client` plain paths or `/_calls/...`), and the
  Tier-3 fallback anchors the caller to the *old* provider contract.
- **Silent-pass error handling.** Missing specs/versions/endpoints,
  unknown scenario services, `allOf`/`anyOf`, dangling `$ref`s, and
  kafka edges all degraded to warnings (or `Any`) and a passing exit
  code. All are now hard failures (exit 2); `mss` exits non-zero when
  the batch as proposed is unsafe.
- **Nondeterministic verdicts on mutually recursive schemas** (component
  resolution followed Go map order; identical inputs flipped PASS/FAIL).
  Resolution is now sorted and deterministic; MSS output is sorted.
- **Chain checker was dead code** (imported by nothing; no type checks;
  x-alias tier stubbed). Now wired into `check`/`mss`/`validate`/`viz`,
  typed (identities strictly typed end-to-end), with source-hop
  semantics, working alias resolution, culprit attribution feeding unit
  clauses, and chain expectations in scenario YAML.
- **Strict-by-default JSON lattice.** `int/num/bool ≤ string` moved
  behind an opt-in `coercion: lenient` profile (Jackson-style consumers
  only); strict decoders reject those coercions. Proto lattice: removed
  wire-incompatible `float ⊑ double`.
- **Compat rules:** enum↔prim and literal value-set rules (both false
  positives and false negatives), union WARN-escalation and width
  subtyping, RES.5 (fields added into a closed consumer), REQ.2 default
  awareness, direction-aware format range checks, role-neutral messages
  with chronology-correct old/new labels for C2/C4.
- **`gus consistent` always printed "Result: YES"** (variable
  shadowing); also gained `--state target`.
- **Validator was one-sided** (MSS subset-only, `mss: []` skipped,
  extra breaks unchecked — a solver returning every upgrade as safe
  passed 8/8). Now exact-match MSS (including empty), chain
  expectations, and post-hoc verification.
- **viz:** quote-escaping in `escapeHtml` (attribute-injection XSS from
  mesh-controlled strings), spec-path confinement (`../` traversal into
  the shareable artifact), conjunct-filtered "cross-version findings"
  panel (C1/C2 findings are ordinary pairwise diffs and are no longer
  labeled GUS-unique), chain rendering, robust tag parsing.

#### Changed — scenarios & specs
- Frontend v2 narrows its shipping sends to `[standard]` (the old
  "widen own sends" change was unsafe against every provider and only
  passed because the caller path was dead). New frontend v3 is
  checkout-v3-aligned (sends `idempotency_key`, expects integer
  `order_id`).
- Scenario C now demonstrates conjunct-aware MSS: `mss: [frontend]`
  (was `[]`), matching the README narrative for the first time.
- Scenario D is a true chain-only break (every per-edge conjunct
  passes; `chain-weakened` with culprit attribution) — previously it
  validated an ordinary direct-edge RES.4.
- Scenario I runs under `coercion: lenient`, and its MSS
  (`{shipping, email}`) now falls out of a frontend↔checkout rollout
  deadlock plus unit clauses instead of an accidental cascade; the
  chain type mismatch is actually detected (`chain-type-mismatch`).
- README rewritten with an honest tool-comparison table and framing
  ("reports statically visible hazards", not "decides safety");
  `docs/review-notes.md` added.

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
