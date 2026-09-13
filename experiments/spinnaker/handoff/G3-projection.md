# Handoff — G3, the projection and the harness

For one Opus session at maximum effort. Self-contained: read this file, then
the files it names, in order. Repository `github.com/pronei/gus-mss-poc`,
branch `experiments`, directory `experiments/spinnaker/`. Everything you write
goes under `experiments/spinnaker/projection/` (code, `graph/`, `scenarios/`,
`results/`, `README.md`, `memo.md`, `decisions.md`). You do not modify the
checker (`pkg/`, `cmd/`), the extractor, the fetcher, any scout report, the
review, or the plan. The decisions listed under "Already decided" are the
owner's; do not reopen them, and record anything the rules leave open in
`decisions.md` marked `needs owner`.

## Read first

1. `PLAN.md` §4 (every decision as revised, including the owner's rulings of
   2026-09-11 and 2026-09-12) and §6 (changelog).
2. `scout/review.md`: R3, R4, "Review pass 2" (the live-leg rule and its
   numbers) and "Review pass 3" (what G1 and G2 delivered and what they
   found), plus `scout/review.json` → `pass2`, `pass3`.
3. `extractor/memo.md`, `extractor/decisions.md` (the seven constructs the
   rules did not cover, and the four `presence-mismatch` findings left for
   you), `extractor/tools/cross_version_check.sh` (a working two-service,
   two-version run through `gus` — your starting point).
4. `fetcher/memo.md` (where the bytes are and how to stage a BOM).
5. `scout/review/r1ab_reconcile.py` (the D3 normalization as the review
   applied it), `scout/review/r1a_unmatched.tsv` (the categorised residue at
   1.38.0), `scout/S1/tools/mesh.tsv`, `scout/S4/ground-truth-candidates.md`.
6. The checker's input contract and vocabulary: `README.md` at the repository
   root; `cmd/gus/main.go` (`loadEdgeSchemas` — the `/_calls/<provider><path>`
   lookup is verbatim on the graph edge's path; a declared endpoint the
   provider lacks is a hard error), `pkg/graph/yaml.go` (graph and scenario
   formats); the two finished experiments for the shape of a run and a README
   that states its lossy steps first: `experiments/otel-semconv/README.md`,
   `experiments/boutique-proto/README.md`.

## Inputs you are handed

- **The corpus.** 50 BOMs, 1.30.0 … 1.38.0, nine services each, on the
  external volume `/Volumes/WDGDM/gus-spinnaker-corpus/<bom>/<svc>/{bin/<svc>,
  lib/*.jar}`, described by `corpus.lock`. Stage one BOM at a time onto the
  local disk (`python3 fetcher/stage.py <bom> --full`, ~2 GiB, ~3 min with
  re-hashing; `--release --keep 1` to free it). Never work on the volume
  directly and never commit anything under `corpus/`.
- **The extractor.** `extractor/mvnw -q -DskipTests package` once (JDK 17 is
  under `experiments/spinnaker/.jdk/`, Maven under `.mvn-dist/`, both
  gitignored); then per service per BOM:

      java -jar extractor/target/gus-contract-extractor.jar \
        --classpath corpus/<bom>/<svc> --service <svc> --version <pinned> \
        --mesh scout/S1/tools/mesh.tsv --presence <declared|none> \
        --kork-rows drop --indirect-fiat drop \
        --out projection/docs/<presence>/<bom>/<svc>.yaml --diag projection/docs/<presence>/<bom>/<svc>.diag.json

  About five seconds per document. The documents are large (front50 at
  2.41.0 is 7 700 lines): keep `projection/docs/` gitignored and commit a
  manifest of their sha256s instead (`projection/docs.lock`), so the run is
  reproducible from `corpus.lock` and the extractor's jar.
- **What a document contains** (`extractor/out/front50-2.41.0.yaml` is a
  reference): provider operations with `x-match-key: "<VERB> <erased path>"`;
  caller operations under `/_calls/<provider><path>` with `x-role: client`,
  `x-provider`, `x-interface`, `x-resolved-by`, the same `x-match-key`;
  requests as `{params, headers, body}`; `x-untyped: true` on every untyped
  side; `x-non-null` on NON_NULL return fields; `x-response-opaque: true`
  where a caller declares `Response`/`Void`; `x-method-any: true` on each of
  the seven copies of an `ANY` mapping; `x-validated: true` on `@Valid`
  bodies; `x-java-type` for traceability. `diag.json` lists the framework
  routes excluded by provenance, the same-key collisions, the losses
  (bean-registered subtypes, side-neutral recursive types) and the Retrofit
  interfaces with no provider.

## Already decided (apply, do not reopen)

- **Mesh:** nine services (Keel out), 1.30.0 … 1.38.0, consecutive pairs in
  version order (1.37.9 → 1.37.10 → 1.37.11 → 1.38.0). CalVer out.
- **Out of the graph, documented in the README:** the 30 kork-plugins
  `Front50Service` rows (dormant client; `--kork-rows drop`), the 36 indirect
  `FiatService` rows (library-issued; `--indirect-fiat drop`), self-edges
  (caller = provider), actuator and framework routes (already excluded by
  the extractor's provenance rule; confirm none reaches `graph.yaml`), and
  the stale caller declarations (a caller `/_calls` operation whose
  `x-match-key` has no provider operation at the same BOM — the checker
  would hard-error on them, so drop the edge and report it as a finding in
  `unmatched.tsv` with its category).
- **Endpoint identity (D3):** match caller and provider on `x-match-key`
  (verb plus erased path). The graph edge's `path` is the provider's spelling
  (variable names kept, regexes dropped); where the caller's spelling differs
  (`{app}` vs `{application}`), rewrite the caller document's `/_calls` path
  to the provider's spelling before loading — the checker looks the edge up
  verbatim in both documents. Apply the seven-row provider-dispatch table of
  `scout/review/r1a_unmatched.tsv` (a caller `/{}/images/find` matches every
  concrete provider controller for that slot: one edge per controller). An
  `ANY` provider mapping matches every verb: the extractor already emitted
  the seven copies; count endpoints on `x-match-key`, never on operations.
- **Openness and untypedness (D5):** a leg (request: caller Send vs provider
  Accept; response: provider Return vs caller Expect) is *live* when neither
  side carries `x-untyped`, *vacuous* when exactly one does, *untyped* when
  both do; an edge is untyped when both legs are. Untyped edges stay in the
  graph; vacuous legs are compared but never counted as evidence. Every
  figure in the README is reported over live legs, per component (`params`,
  `headers`, `body`, response) where a component-level `x-untyped` allows
  it, with the vacuous share beside it. Do not re-derive Java types; the
  flags are the classification.
- **Opaque responses (D6):** where a caller operation carries
  `x-response-opaque: true`, the provider's response on that edge is replaced
  by a contentless 200 in the loaded copy, and the edge is listed in the
  README as "caller discards the body" (count them; they are not findings).
- **Presence (D4):** two complete runs, `--presence declared` and
  `--presence none`; report both, and state that on this corpus *declared*
  reduces to Java primitives on the return side.
- **Same-key collisions:** when two provider operations share (path, verb)
  (Orca `POST /ops`, Gate `POST /pipelines/{id}/evaluateExpression`), the
  extractor kept one deterministically; note the affected edges in the
  README and do not treat a finding on them as evidence.
- **Consistency gate (D11):** at every BOM baseline run `gus consistent`
  over the full graph before any pair is judged. Triage every failure into
  one of: projection defect (report to G1 with the operation and the rule;
  do not patch the document by hand), normalization defect (a D3 rule or a
  dispatch row — fix in your normalizer, add the row), opaque response
  (apply D6), real inconsistency (kept, reported, the affected edge excluded
  from that pair). Keep a triage file per BOM.
- **Ground truth (D10):** S4's rows, S4-019 excluded; a `1.N.x → 1.M.0` label
  maps to the pair (last 1.N patch, 1.M.0); unlabelled pairs are unlabelled,
  never safe; per-service labels map to the BOM pair whose pins cross those
  versions. Two independent labelers are required by D10 — you are not one
  of them; use the rows as delivered and say so.
- **Claims (D12):** caller-drift (C2, C4, TGT) and type-level breaks on live
  legs; nothing about presence under *none*; no chain claim; no prevalence
  claim; untyped edges out of precision figures; Keel, CalVer and the
  1.24.0–1.29.7 window out.

## Build, in this order

1. **`normalize.py`** — the D3 rules exactly as `r1ab_reconcile.py` applies
   them, on extractor output instead of scout tables; `unmatched.tsv` with
   the categories (actuator, framework, dispatch-slot, stale, self-edge,
   kork, indirect-fiat) for every caller operation that yields no edge.
2. **`graph.py`** — `graph.yaml` for the nine services with every BOM's
   document registered (`services: {svc: {<bom>: docs/<presence>/<bom>/<svc>.yaml}}`
   — paths must not escape the graph file's directory, so write the graph
   beside `docs/`), edges from the matched caller operations, one per
   (caller, provider, verb, provider path), named `<caller>-<provider>/<n>`.
   Edge count and its breakdown per caller and provider go into `memo.md`.
3. **`baseline.py`** — stage a BOM, extract nine documents (both presence
   profiles), run `gus consistent`, triage, release the BOM; loop over the 50
   BOMs; `docs.lock` and `triage/<bom>.tsv` as outputs. Report wall time.
4. **`scenarios.py`** — per consecutive pair: `all` (nine upgrades), one
   per service, and the 36 pairs of services; `steps/` for `gus evolve`
   (the `all` batches in version order); ids `P<NN>-<batch>`.
5. **`run.sh`** — `gus check --format json` and `gus mss` per scenario,
   `gus evolve` over the steps, six parallel jobs; `results/<presence>/`.
6. **`compare.py`** — per pair: findings by conjunct (C1–C4, TGT), by rule,
   by component, on live legs only; the safe subset and post-hoc verdict;
   the S4 label; the caller-drift table (edges where the caller's declaration
   changed between the two BOMs: body, params, expect); the live/vacuous
   accounting; and the "what the checker saw vs what S4 says" table for the
   labelled pairs, stating for each label whether it sits on a live leg.
7. **`README.md`** — lossy steps first (the untyped share and live-leg
   share, the two dormant client families, self-edges, stale declarations,
   opaque responses, the presence profiles, Keel, CalVer, custom serializers
   as the unmeasured risk), then the run, then the results tables, then what
   the corpus exposed in the checker (report; do not fix).

## Acceptance

- `gus consistent` passes at all 50 baselines or every failure has a triage
  row; the count per category is in the README.
- At 1.38.0 the matched share over resolved caller operations is at least
  90 % after the actuator rows are excluded and the dispatch table applied
  (the review's estimate is 96 %); the untyped-edge share under D5 and the
  live-leg share are reported next to review pass 2's 0.8 % and 24.7 %.
- All 49 pairs × 46 batches × 2 profiles run to completion; every post-hoc
  certificate FAIL is listed with its scenario.
- The two contract-visible breaking rows of S4 in range are each traced to
  the edge and leg they touch, with the checker's verdict there.
- `docs.lock` regenerates byte-identically from the corpus and the
  extractor jar on a second run of one BOM.

## Report back

`projection/memo.md`: counts (edges, per caller and provider; live, vacuous,
untyped legs; triage per category; findings per conjunct and rule; safe
subsets and certificate failures), wall times, every construct the rules did
not cover (numbered `CLAIM-G3-NNN` with the document and operation), and a
last section titled "## What I could not verify". `projection/decisions.md`
for every choice the rules left open, `needs owner` where it changes results.
If the checker hard-errors on something the rules did not anticipate, record
the exact error and the document and stop that pair; do not modify the
checker.
