# Spinnaker as a checker corpus — scouting and groundwork plan

Status: plan only. Nothing here has been run. Every statement about
Spinnaker's internals below is a hypothesis for the scouts to confirm or
refute; the decisions in §4 are defaults to be revised by the review pass.

## 1. Why this corpus, and what it would test

Spinnaker is a mesh of independently versioned JVM services (Gate, Orca,
Clouddriver, Front50, Echo, Igor, Fiat, Rosco, Kayenta, Keel) that call each
other over HTTP. Two properties no previous corpus had:

* **Declared caller contracts.** Each service declares the APIs it consumes
  as Retrofit interfaces (method, path template, parameter and body types,
  return type). That is the checker's Tier-2 caller declaration in the wild,
  so C2, C4 and TGT — caller-side drift and target-state conflicts — become
  measurable on real declarations for the first time.
* **Coordinated releases with independent service versions.** Every
  Spinnaker release ships a bill of materials (BOM) pinning one version per
  service. Consecutive BOMs are real batches; the services inside them moved
  independently.

All ten services are in scope from the first run (D2).

What it cannot test without invention: presence semantics (Jackson fields
are optional unless annotated) and machine-readable ground truth (release
notes are prose). Both are stated as lossy steps before any result is read,
as in the proto and OpenTelemetry experiments.

## 2. Approach in one paragraph

Extract contracts by **reflection over released artifacts**, not by parsing
Java, Groovy and Kotlin source. Provider contracts come from Spring MVC
annotations on compiled controllers plus the Jackson-visible shape of their
parameter and return types; caller contracts come from compiled Retrofit
interfaces plus the configuration that binds each interface to a target
service. Both are projected into the checker's OpenAPI dialect — one
document per service per BOM version, `x-role: client` declarations under
the `/_calls/<provider><path>` convention, query and path parameters folded
into the request object — with one graph for the mesh and scenarios per
consecutive BOM pair. The projection is validated before any pair is judged:
`gus consistent` must hold at every BOM baseline, and every failure is
triaged as a projection defect or a real inconsistency.

## 3. Phases

### Phase 0 — fix the decisions of §4 (you, one sitting)

### Phase 1 — scouting (six agents in parallel, read-only)

All scouts: Opus, maximum effort, general-purpose (they need Bash for git
clones, `javap`, registry queries). Each works in its own worktree under
`experiments/spinnaker/scout/<name>/`, writes the files named below, and
ends with a one-page memo whose last section is titled "What I could not
verify". No scout edits the checker.

| Agent | Question | Output contract |
|---|---|---|
| S1 topology | Which of the ten services call which, on which paths? Resolve every Retrofit interface to its target service through the wiring (base-URL config keys, selector beans, Gate's proxying), including the client libraries shared through kork and Fiat's client used by every service. | `edges.tsv` (caller, provider, method, path template, interface, method name, body type, return type); `clients.md` with unresolved interfaces listed |
| S2 provider surface | For each of the ten services at one recent version: every controller endpoint (method, path template, path/query/header params with required flags, body type, return type, response codes, content types), and a typing census: share of endpoints whose body or return is `Map`, `Object`, `List<Map>`, a generic, a `@JsonTypeInfo` hierarchy, a Kotlin type with nullability, a Groovy class with `def` fields | `endpoints.tsv`, `typing-census.md` |
| S3 artifacts | Which BOMs exist (range, cadence), which service versions each pins, whether a container image or published jar is still retrievable for every pinned version, what the classpath inside looks like, which JDK it needs | `boms.tsv`, `artifacts.md`, a go/no-go on the reflection route with the first and last retrievable release |
| S4 history | For every consecutive BOM pair in range: release-note "breaking"/"compatibility"/"upgrade order" statements, issues and PRs about cross-service incompatibility, deprecations removed. Label each pair with evidence links; do not label without a link | `ground-truth-candidates.md` (one row per pair per claim, with source URL and quoted sentence) |
| S5 checker fit | For every construct S2 finds, what the loader does today (`pkg/schema`), what a projection convention absorbs without touching the checker, and what needs a checker change, with an effort estimate each | `gaps.md` (table: construct, count, loader today, projection convention, checker change, cost) |
| S6 chains | Cross-service identities (execution id, application name, pipeline config id, account/credential name, correlation headers): where minted, where required, which hops carry them, in which field or header. Recommend three to five chains worth annotating, with the field at every hop | `chains.md` |

Every factual statement in a scout's memo is a numbered claim with a
source, so the review can sample it:

    CLAIM-S2-014: Front50's PipelineController returns Map for GET /pipelines/{id}.
    source: spinnaker/front50@v2.35.0 front50-web/src/main/java/.../PipelineController.java:118

A memo statement without a claim number and a source is not evidence.

Output schemas (tab-separated, header row exactly as given; one row per item):

* `edges.tsv`: `caller  provider  method  path_template  interface  method_name  body_type  return_type  resolved_by  claim`
  (`resolved_by` = the config key or bean that binds the interface to the provider; `unresolved` allowed)
* `endpoints.tsv`: `service  version  controller  method  path_template  path_params  query_params  header_params  body_type  return_type  response_codes  content_types  typing  claim`
  (`typing` ∈ `typed`, `untyped-body`, `untyped-return`, `untyped-both`, `polymorphic`, `raw-generic`)
* `boms.tsv`: `release  release_date  service  pinned_version  artifact_kind  artifact_ref  retrievable  jdk  claim`
* `ground-truth-candidates.md`: one row per claim: `pair  services  kind  quoted_sentence  source_url  claim`
  (`kind` ∈ `breaking`, `compat-note`, `upgrade-order`, `deprecation-removed`)
* `gaps.md`: table `construct  count  loader_today  projection_convention  checker_change  cost  claim`
* `chains.md`: per chain: identity, mint (service, endpoint, field), sink (service, endpoint, field), hops with the field at each, `claim`
* `typing-census.md`: per service the counts behind `typing`, and the untyped share of endpoints

### Phase 1b — review pass (one Fable-level agent, after all six scouts)

The review is the gate between scouting and building. It is one pass by a
model at least as capable as the scouts, with authority to revise the
defaults of §4 and to send a report back. It writes `scout/review.md`,
`scout/review.json` (the numbers below, for the eventual README) and keeps
its scripts under `scout/review/`.

R0 *Completeness.* Every output file present and parseable with the exact
header; every memo present with a "What I could not verify" section; every
statement numbered and sourced. A report that fails R0 goes back to its
scout with the missing items listed; the review does not proceed on it.

R1 *Reconciliation (scripted, kept).*
  - Every `edges.tsv` row with a resolved provider matches an
    `endpoints.tsv` row of that provider on method and normalized path (D3);
    the unmatched list is written out with the normalization applied.
  - The untyped share per D5 is recomputed from the reconciled edges — not
    taken from S2's census — and compared with the 50% threshold.
  - `boms.tsv` covers all ten services for every release in the proposed
    range; the range is the longest run of consecutive releases with
    `retrievable = yes` for every pinned service.
  - Every ground-truth row has a URL and a quoted sentence; rows without
    both are dropped, and the count of survivors per `kind` is reported.
  - Every chain names a field at every hop that exists in `endpoints.tsv`.
  - `gaps.md` has no row with `checker_change = yes` and an empty
    `projection_convention` unless it also has a cost.

R2 *Re-derivation.* From each scout's memo the reviewer takes the claims
numbered 2, 5 and 8 (the fixed sample; if a memo has fewer than eight
claims, all of them) and re-derives each from the cited source: a git
checkout at the cited tag, `javap -v` on the cited class inside the cited
artifact, a registry query for the cited image. Each re-derivation is
logged as `claim, source, result ∈ {confirmed, refuted, not reproducible}`.
One refutation extends the sample to claims 11, 14, 17 and 20; two
refutations in one report reject it back to the scout. "Not reproducible"
counts as a refutation when the source is a repository or an artifact.

R3 *Decisions.* For each of D1–D12: keep, or revise with the evidence line
that forces the revision. Revisions are written into §4 of this file and
recorded in §6 (Changelog) with the claim numbers that motivated them.

R4 *Verdict.* GO requires all of: the reflection route confirmed on at
least one artifact per service (S3 memo and one R2 re-derivation each);
a proposed range of at least eight consecutive BOM pairs; reconciled edges
at or above 90% of resolved edges; untyped share at or below 50%; at least
one ground-truth row of kind `breaking` surviving R1; and no `gaps.md` row
requiring a checker change without a cost. SCOPED-GO names the claims the
run gives up (D12 plus whatever R1 forced). NO-GO names the failing
condition and what would have to change. The verdict section ends with the
first task for each of G1–G3, written so that a builder can start from it
without reading the scout reports.

R5 *What the review may not do.* Write extractor or projection code; label
ground truth itself; change the 50% threshold or the eight-pair minimum
(those are yours).

### Phase 2 — groundwork (after GO; three builders, sequential dependencies)

| Builder | Deliverable | Tests |
|---|---|---|
| G1 extractor | One Java 17 tool: classpath directory + service name → OpenAPI document. Jackson-derived schemas (jsonschema-generator with the Jackson and Kotlin modules), Spring annotations → endpoints, Retrofit annotations → `x-role: client` endpoints under `/_calls/<provider><path>`, parameters folded per D6 | Golden files for one endpoint of each construct in S2's census; the checker loads every output |
| G2 fetcher | BOM → artifacts → extracted classpaths, cached, with digests in `corpus.lock` | Re-run is byte-identical |
| G3 projection + harness | Path unification (D3), graph, scenarios per pair (all, per service, per pair of services), steps for `gus evolve`, `run.sh`, `compare.py` against S4's labels | `gus consistent` at every baseline; triage file per failure |

Everything lands under `experiments/spinnaker/` on the `experiments` branch,
with a README that states the lossy steps first, as the other two do.

## 4. Decisions (defaults; the review pass revises)

**D1. Source parsing vs reflection over artifacts.** Default: reflection.
Compiled classes carry Java generic signatures, Kotlin nullability metadata,
Jackson and Spring annotations, and Groovy's static types where declared;
source parsing across three languages and dozens of tags is the largest cost
in the whole plan and lower fidelity. Risk: old artifacts unavailable (S3
decides the range).

**D2. Release range and mesh.** Decided: all ten services — Gate, Orca,
Clouddriver, Front50, Echo, Igor, Fiat, Rosco, Kayenta, Keel — from the
start. The range is the longest contiguous BOM range for which S3 finds
artifacts for every service that the BOM pins; a service absent from a BOM
(Keel, Kayenta in early releases) is simply absent from that state, as a
signal group absent from a release was in the OpenTelemetry run, and its
edges appear only for pairs where both sides have it. Consecutive pairs only.

**D3. Endpoint identity.** A caller's Retrofit path and the provider's Spring
mapping are the same endpoint when method and normalized path template
match (path-variable names erased, trailing slash and `/api/v1`-style
prefixes normalized per service). Unmatched edges are reported as "caller
declares an endpoint the provider does not expose" — that is a finding, not
a projection error, once R1 has confirmed the normalization.

**D4. Presence (the `required` list).** Two profiles, as in the OpenTelemetry
experiment. *Declared*: required only where the code says so — Kotlin
non-null constructor parameters without defaults, Java primitives on the
return side, `@JsonProperty(required = true)`, validation annotations on
the accept side. *None*: every field optional. Results are reported for both;
nothing inferred from initializers or usage.

**D5. Openness.** Spring Boot's Jackson defaults tolerate unknown properties,
so every accept and expect object is open (`additionalProperties: true`);
send and return objects list their declared fields. `Map<String, Object>`
and `Object` project to an open object with no properties and are counted
as *untyped*; endpoints that are untyped on both sides are kept in the graph
but excluded from every claim.

**D6. Parameters.** The checker models request bodies and the lowest 2xx
JSON response. Default: fold path and query parameters into the request
object as a synthetic `params` property (each parameter a field, required
when the annotation says so; headers likewise under `headers`) — a projection
convention, no checker change. Response codes other than the lowest 2xx are
dropped and counted.

**D7. Polymorphism and generics.** `@JsonTypeInfo` hierarchies → `oneOf` over
the registered subtypes with the discriminator as a closed enum property;
unregistered `Object` → open object. Generic containers resolve through the
reflected signatures; raw types count as untyped.

**D8. Nullability and enums.** Kotlin `T?` and `@Nullable` → `nullable: true`;
Java boxed types without annotation → not nullable, counted as unknown.
Java enums → closed enums (Jackson rejects unknown values by default), the
first corpus with real closed enums.

**D9. Chains.** Out of the first run. If S6 finds three to five identities
with clear mint and sink fields, annotate them by hand in a second run and
report them separately as synthetic.

**D10. Ground truth.** A release pair is "breaking" only with a quoted
statement and a link (S4). Pairs with no evidence are unlabeled, not safe.
Two independent labelers if S4's list exceeds twenty claims.

**D11. The consistency gate as a fidelity test.** A BOM baseline that fails
`gus consistent` is triaged before anything else: projection defect (fix
G1/G3), normalization defect (fix D3), or real inconsistency (kept, reported
as a finding about the corpus, pair skipped).

**D12. What is not claimed.** No prevalence claim; no claim about presence
hazards under the *none* profile; no chain claim in the first run; untyped
edges excluded from precision figures.

## 5. Risks that end the plan early

* Artifacts for old versions unavailable → range shrinks or reflection route
  dies (S3 answers within hours).
* Untyped share (D5) above 50% of the edges → NO-GO for the pair-relation
  claims. Decided threshold: the review pass computes the share over S1's
  resolved edges after S2's census, counting an edge as untyped when its
  request body or its response is `Map`, `Object`, `List<Map>` or a raw
  type on either side; at or below 50% the plan proceeds with the untyped
  edges excluded from precision figures (D12), above it the run is scoped to
  the caller-drift question on the typed remainder only, and that scoping is
  stated in the README before any number.
* Retrofit interfaces unresolvable to a target service (dynamic selectors) →
  edges without a provider; report and drop.
* Path normalization needing per-endpoint hand rules → D3 becomes a manual
  table; acceptable up to a few dozen rows.

## 6. Changelog

Decisions revised by the review pass are recorded here with the claims that
motivated them. Empty until the review runs.

| date | decision | from | to | claims |
|---|---|---|---|---|

