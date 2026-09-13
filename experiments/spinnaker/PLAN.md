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

## 4. Decisions (revised by the review pass, 2026-09-11; see §6)

**D1. Source parsing vs reflection over artifacts.** Kept: reflection.
Confirmed on released bytecode for all ten services (S3-022/024; the review's
own constant-pool scan of the ten `-web` jars and three unpacked images):
`RuntimeVisibleAnnotations`, `Signature` and Kotlin `Metadata` survive in every
era (class majors 52/55/61). Three constraints the extractor honours:
(a) `MethodParameters` is absent everywhere (no `-parameters`), so a parameter
name comes from the annotation value, else from `LocalVariableTable`, else the
parameter is unnamed and the endpoint is flagged; (b) the service's own jars are
unversioned in the gcr.io era and versioned in the GAR era, so the classpath is
the `CLASSPATH=` line of `/opt/<svc>/bin/<svc>`, never a file-name pattern;
(c) the Jackson-visible shape is read through each service's configured
`ObjectMapper` (D7), not by raw reflection over model classes. The extractor
runs on a JDK 17; this machine has none, so a portable JDK is unpacked under the
experiment directory. Risk unchanged: old artifacts (S3 decided the range, D2).

**D2. Release range and mesh.** Revised: **nine services**, not ten. No BOM of
the 346 pins Keel (S3-006; review R1(c)), so Keel is out of the first run — no
invented pin — and its 54 caller rows and 44 provider rows are dropped and
listed as out of scope. Kayenta is pinned from 1.7.0 (S3-007), irrelevant to the
range below. First run: **BOM range 1.30.0…1.38.0** — 50 releases, 49
consecutive pairs in version order, every pinned service a live container image
on one registry (`us-docker.pkg.dev`), Java 11→17, uniform jar naming; S3's
recommendation, reproduced by the review. The deep-history run 1.0.0…1.23.7
(202 releases, 201 pairs, gcr.io, Java 8/11, unversioned jars) is a later
extension; 1.24.0…1.26.7 has no artifact anywhere; 1.27.0…1.29.7 is Maven-only
and is not mixed into an image-based run. CalVer releases (2025.0.0 onward) pin
all nine services at one version and one monorepo commit, so "services moved
independently" no longer holds there; CalVer pairs are excluded from the first
run. Pairs are consecutive in version order (patch trains overlap in time).
The latest tags S1/S2/S6 read are exactly the 1.38.0 pins for the nine services,
so the scouting surfaces are the last state of the range.

**D3. Endpoint identity.** Revised. A caller's Retrofit path and the provider's
Spring mapping are the same endpoint when method and normalized template match,
with the normalization fixed by R1: strip a baked-in query string (17 rows at
1.38.0; the fixed pairs go into `params` with `default`), add the missing
leading slash of Retrofit-2 relative paths (101 rows; `"."` is the base URL),
erase variable names and regexes (`{id:.+}` → `{}`), collapse doubled and strip
trailing slashes, let a provider `**` match any suffix, let a caller literal
fill a provider variable slot, and let a provider method `ANY` match every
method; no per-service prefix rule was needed at 1.38.0 (the table exists,
empty). Three classes of unmatched rows are not findings: (i) actuator
endpoints (`/health`, `/installedPlugins` — kork's `InstalledPluginsEndpoint`)
and framework-registered routes (Keel's DGS `/graphql`) are outside the graph;
(ii) a caller variable over a provider dispatch literal (`/{provider}/images/find`
against `/aws/images/find`, …: 7 rows at 1.38.0) is expanded by a hand table
into one edge per concrete controller; (iii) rows missing from a scouting census
are census defects. The residue — 17 rows at 1.38.0, all dead client methods —
is the finding "caller declares an endpoint the provider does not expose".
Because `cmd/gus/main.go:1097` makes an unmatched edge a hard input error, G3
drops those edges from `graph.yaml` and reports them on a separate channel; no
checker change.

**D4. Presence (the `required` list).** Two profiles as before, but the
*declared* profile is nearly empty on this corpus and its legs are restated:
`@JsonProperty(required = true)` occurs zero times in the ten repositories and
in kork (S2-012, S5-017) — dropped; a validation annotation counts only when the
enclosing parameter carries `@Valid`/`@Validated` (S5-018), which concentrates
the leg in Kayenta; Kotlin non-null constructor parameters without defaults are
Keel's signal (S2-014) and Keel is out of the first run (D2), leaving Orca's two
Kotlin model types; Java primitives on the return side remain. The declared/none
gap is reported as a property of the corpus, not as signal. New rule: a field a
service never serialises when null — global `NON_NULL` on the MVC mapper in Orca
(`OrcaObjectMapper` is the `objectMapper` bean, WebConfiguration.groovy:66),
Clouddriver (CloudDriverConfig.java:166), Keel (DefaultConfiguration.kt:73) and
Kayenta (KayentaConfiguration.java:136), and per-class `@JsonInclude(NON_NULL)`
elsewhere — is projected on the return side as optional and not nullable, never
`nullable: true`, or `nullable-response-widening` fires for a value that never
reaches the wire (S5-014/037). Nothing inferred from initializers or usage.

**D5. Openness.** Revised. Every accept and expect object stays open
(`additionalProperties: true`; Spring Boot disables `FAIL_ON_UNKNOWN_PROPERTIES`,
and Orca, Echo, Keel, Kayenta disable it explicitly); send and return objects
list their declared fields. *Untyped*, per side: raw `Map`/`List`/`Collection`/
`Set`, `Map<String,Object>`/`Map<String,Any>`/`Map<*,*>`/wildcard values,
`Object`/`Any`/Groovy `def`, `JsonNode`, containers of those, and Map-subclass
models (front50 `PipelineTemplate` and `Notification` extend
`HashMap<String,Object>`, S2-005/006). A typed map `Map<String,X>` with a
concrete `X` is *typed*: it projects to `additionalProperties: <X>`, loads as
`types.Map`, and `checkMap` compares key kind and value type (S5-032;
loader.go:526-538, compat.go:483-497). `Object` projects to
`{type: object, additionalProperties: true}`, never `{}` — an empty schema is
`types.Any` and short-circuits every comparison (loader.go:462, compat.go:71-73).
Opaque returns (`Call<ResponseBody>`, Retrofit-1 `Response`, `Void`, `void`,
`StreamingResponseBody`) are contentless, not untyped, and are projected as a
contentless 200 on both sides (D6).

*Owner's ruling (2026-09-11): untypedness is decided on both sides.* A leg of
an edge (request: caller `Send` against provider `Accept`; response: provider
`Return` against caller `Expect`) is *untyped* only when both declarations of
that leg's payload are untyped; an *edge* is untyped only when both of its
legs are. Untyped edges stay in the graph and are excluded from every claim;
the §5 threshold counts these edges. A leg with exactly one untyped side is
*vacuous*: the checker compares it, but it can only pass, because an open
object with no properties admits any sender and — under the presence
profiles of D4 — demands nothing of any producer. Vacuous legs are therefore
not counted as evidence either way: every figure in the README is reported
over *live* legs (both sides typed), per leg and, under D6's wrapper, per
component (`params`, `headers`, `body`, response), and the share of vacuous
legs is stated beside it. Measured by R1 at 1.38.0 under the either-side
reading: 50.6 % of the 470 reconciled edges have at least one untyped side
(56.9 % on the nine-service mesh); 4.9 % have both legs untyped on at least
one side, which is an upper bound for the edge count under this ruling (the
review's script tests each leg on either side, not both). The per-leg and
per-component numbers under this ruling are to be computed by the next
review pass, after the S1 and S2 redos.

*Owner's rulings (2026-09-12).* (i) The 30 kork-plugins `Front50Service`
rows are **out** of the graph: the client is instantiated only when an
operator sets `spinnaker.extensibility.repositories.front50.enabled`, which
no shipped profile in the ten services does (S1-025), so a stock deployment
never makes the call; the rows stay in `edges.tsv` and the extractor emits
them behind `--kork-rows`, and the README records them as a declared but
dormant client. (ii) The 36 indirect `FiatService` rows (Clouddriver, Echo,
Igor, Keel, where no application code injects the client and the calls are
issued by `FiatPermissionEvaluator` inside `fiat-api`) are **out** for the
same reason of provenance: the declaration is a library's, not the service's;
Gate's, Orca's and Front50's direct `FiatService` calls stay. (iii) The
*declared* presence profile is **kept as a near-empty control** beside
*none* (the extractor's `--presence` flag); the README reports both and
states that on this corpus *declared* reduces to Java primitives on the
return side. (iv) The claims stay as scoped in D12: caller-drift and
type-level findings on live legs, with the vacuous share stated; the build
proceeds on that basis.

**D6. Parameters.** Revised. The checker models request bodies and the lowest
2xx JSON response, so path, query and header parameters are folded into the
request object under a fixed wrapper `{properties: {params, headers, body}}`,
the payload under `body` — a body field and a query parameter of the same name
cannot collide, and a `Map`-typed body never sits beside named properties (the
loader rejects that, loader.go:531). `params.<name>` is required for
`@PathVariable`, and for `@RequestParam` unless `required = false` or a
`defaultValue` (which emits `default:`); `headers.<name>` likewise (at 1.38.0:
`X-RateLimit-App` optional on 45 Gate endpoints, `X-SPINNAKER-USER` required on
17 Keel endpoints). A catch-all `Map<String,String>`/`MultiValueMap` query binder
(22 endpoints) makes `params` an open object and the request side untyped.
Baked-in query pairs from the caller side go into `params` with `default:`. A
`void`/`Void`/`ResponseBody`/`Response`/non-JSON response is a `200` with no
content on both caller and provider (otherwise `nil` against a schema is a
`presence-mismatch` BREAK, compat.go:62-68); response codes other than the
lowest 2xx are dropped and counted (64 endpoints declare one). Identities that
travel as parameters (D9) live inside `params`/`headers`, the only place
`x-provides`/`x-requires` are read (loader.go:498-507). A projection convention,
no checker change.

**D7. Polymorphism and generics.** Revised. `@JsonTypeInfo` hierarchies →
`oneOf` over the registered subtypes with the discriminator a closed one-value
enum in each variant (two open variants admit each other and `oneof-ambiguity`
fires on every payload); unregistered `Object` → open object. The declarations
are mostly not on the model class: Keel's `KeelApiAnnotationIntrospector`
synthesises type resolvers for six unannotated types and its modules bind 36
mixins, Clouddriver's whole polymorphic surface is mixin-declared with subtypes
registered from Spring beans at runtime, Front50's `Pipeline` any-getter/setter
live on a mixin (S2-008/009/010/011, S5-010/011/012) — so the extractor
constructs each service's configured `ObjectMapper` with its modules registered
and reads the resolved configuration; bean-registered subtypes are an accepted
loss (base as open object, untyped). `Id.CLASS` discriminators are
fully-qualified class names. Plain inheritance is flattened at extraction:
`allOf` is a hard loader error (loader.go:342). Generic containers resolve
through the reflected `Signature`; raw types count as untyped. Unbudgeted cost
per S5: 8–16 h for driving the configured mapper.

**D8. Nullability and enums.** Revised. Kotlin `T?` and `@Nullable` →
`nullable: true`; Java boxed types without annotation → not nullable, counted as
unknown. Enums are closed only where the mapper on that side is closed: Orca's
MVC mapper enables `READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`
(OrcaObjectMapper.java:57, the `objectMapper` bean), so Orca's accept side is
open; the fiat-api client mapper used by every `FiatService` caller
(FiatAuthenticationConfig.java:61) and Rosco's Clouddriver client
(ServiceConfig.java:46) enable `READ_UNKNOWN_ENUM_VALUES_AS_NULL`, so those
expect sides are open; every other side is Jackson-default closed (kork-retrofit
sets nothing; Keel is only case-insensitive). Projection: open side →
`type: string`; closed side → closed `enum` of the constants. "The first corpus
with real closed enums" holds only for edges closed on both sides.

**D9. Chains.** Kept out of the first run. R1(e): three of S6's five chains
name a declared field at every hop — `clientRequestId` Orca→Clouddriver (query
parameter on both sides), `artifactAccount`+`type` Orca/Rosco→Clouddriver
`PUT /artifacts/fetch` (kork `Artifact` body on both sides), `source.executionId`
Orca→Echo `POST /notifications` (nested field, typed on both sides).
`correlationId` Keel→Orca survives only reduced (Keel's typed body → Orca's
`GET /executions/correlated/{correlationId}` path parameter; the `POST /ops`
body sink is a `Map`) and is deferred with Keel (D2); `application`
Gate→Orca→Front50 fails at its mint (Gate's body is `Map<String,Object>`) and
survives only as Orca→Front50. Response-minted identities and the undeclared
`X-SPINNAKER-*` headers stay outside. Second run: annotate the three survivors
(plus the reduced Orca→Front50 chain) by hand and report them separately as
synthetic; G1 must carry caller-side query/path/header parameters, which S1's
`edges.tsv` does not.

**D10. Ground truth.** Kept. A release pair is "breaking" only with a quoted
statement and a link (S4). Pairs with no evidence are unlabeled, not safe. S4
delivered 38 rows, all with URL and quote; CLAIM-S4-019, quoted from a
documentation pull request closed without merging, does not count (a
contributor's draft is not a project statement), leaving 37 (breaking 14,
compat-note 20, upgrade-order 1, deprecation-removed 2). 38 > 20, so two
independent labelers are required before any row is treated as ground truth.
Within 1.30.0…1.38.0: 17 rows, 6 `breaking`, of which only S4-021 and S4-023
(Retrofit-2 migration failures of a caller's declared interface) are
contract-visible in the checker's sense. Labels on minor-line transitions
(`1.N.x → 1.M.0`) map to the version-ordered pair (last 1.N patch, 1.M.0).

**D11. The consistency gate as a fidelity test.** Kept. A BOM baseline that
fails `gus consistent` is triaged before anything else: projection defect (fix
G1/G3), normalization defect (fix D3, including its dispatch-slot table),
census defect (back to the scout), or real inconsistency (kept, reported as a
finding about the corpus, pair skipped).

**D12. What is not claimed.** Revised. No prevalence claim; no claim about
presence hazards under the *none* profile; no chain claim in the first run; no
claim about Keel or about CalVer pairs; untyped edges excluded from precision
figures; and, because the untyped share exceeds 50 % (D5), the first run is
scoped to the caller-drift question (C2, C4, TGT) on the typed remainder of the
edges, stated in the README before any number (§5).

## 5. Risks that end the plan early

* Artifacts for old versions unavailable → range shrinks or reflection route
  dies (S3 answers within hours).
* Untyped share (D5) above 50% of the edges → NO-GO for the pair-relation
  claims. Decided threshold: the review pass computes the share over S1's
  resolved edges after S2's census, counting an edge as untyped only when
  both of its legs are untyped on both sides (owner's ruling in D5); at or
  below 50% the plan proceeds with the untyped edges excluded from precision
  figures (D12) and with every figure reported over live legs, above it the
  run is scoped to the caller-drift question on the typed remainder only, and
  that scoping is stated in the README before any number. Under this ruling
  the measured share (at most 4.9 % at 1.38.0; either-side reading 50.6 %)
  is far below the line, so the threshold no longer scopes the run; what protects
  the figures instead is the live-leg reporting rule of D5.
* Retrofit interfaces unresolvable to a target service (dynamic selectors) →
  edges without a provider; report and drop.
* Path normalization needing per-endpoint hand rules → D3 becomes a manual
  table; acceptable up to a few dozen rows.

## 6. Changelog

Decisions revised by the review pass are recorded here with the claims that
motivated them. Filled by the review pass of 2026-09-11 (`scout/review.md`).

| date | decision | from | to | claims |
|---|---|---|---|---|
| 2026-09-11 | D1 | reflection, no extractor constraints | reflection with: parameter names from annotation value → `LocalVariableTable` → flagged (`MethodParameters` absent everywhere); classpath from the `CLASSPATH=` line (jar naming flips at the gcr.io/GAR boundary); shapes read through each service's configured `ObjectMapper`; JDK 17 required (none on this machine) | S3-020/021/022/023/024/028; review jar scan |
| 2026-09-11 | D2 | all ten services; longest contiguous range with artifacts for every pinned service | nine services (Keel pinned by no BOM, no invented pin, 98 edge rows out); first run 1.30.0…1.38.0 (49 pairs, all images, one registry); 1.0.0…1.23.7 (201 pairs) as extension; 1.24.0…1.26.7 lost; 1.27.0…1.29.7 Maven-only, not mixed in; CalVer pairs excluded (one monorepo commit per BOM); version order | S3-006/007/012/015/027; S1-001; R1(c); BOM pins of 1.38.0 and 2025.x |
| 2026-09-11 | D3 | names erased, trailing slash and prefixes normalized; unmatched = finding | R1 normalization spelled out (query strings, leading slash, regexes, `**`, literal-fills-slot, `ANY`); hand table for provider dispatch slots (7 rows); actuator/framework routes outside the graph; census gaps back to the scout; the 17 stale declarations are the finding and are dropped from `graph.yaml` because main.go:1097 is a hard error | S1-019; S2-021/023; S5-006/016; R1(a) |
| 2026-09-11 | D4 | declared = Kotlin non-null, primitives, `@JsonProperty(required)`, validation | `@JsonProperty(required)` leg dropped (zero occurrences); validation only under `@Valid`/`@Validated`; Kotlin leg leaves with Keel; declared ≈ none reported as a corpus property; NON_NULL-serialised fields optional and not nullable on the return side | S2-012/013/014/015; S5-014/017/018/037; WebConfiguration.groovy:66, CloudDriverConfig.java:166, DefaultConfiguration.kt:73, KayentaConfiguration.java:136 |
| 2026-09-11 | D5 | every `Map` and `Object` untyped; `Object` → open object | typed maps `Map<String,X>` are typed (`types.Map`, `checkMap`); `Object` → `{type: object, additionalProperties: true}`, never `{}`; Map-subclass models untyped; opaque returns contentless; measured 50.6 % (ten) / 56.9 % (nine) → §5 scoping; either/both inconsistency flagged | S5-007/032; S2-004/005/006; R1(b) |
| 2026-09-11 | D6 | `params` and `headers` beside the body; lowest 2xx | `{params, headers, body}` wrapper; contentless 200 on both sides for void/opaque/non-JSON; catch-all query maps → open `params`; baked-in query pairs → `params` with `default`; identities in parameters inside `params`/`headers` | S5-001/002/003/005/008/025/048; S2-019/020/021 |
| 2026-09-11 | D7 | `oneOf` over registered subtypes; raw types untyped | extractor drives the configured `ObjectMapper` (mixins, introspectors, modules); bean-registered subtypes an accepted loss; one-value closed enum discriminator; `Id.CLASS` = FQCN; inheritance flattened (`allOf` is a hard load error) | S2-008/009/010/011/016; S5-004/010/011/012/024/036 |
| 2026-09-11 | D8 | Java enums closed everywhere | closedness per service and per direction: Orca accept side open; every `FiatService` caller's expect side and Rosco's Clouddriver client open; closed elsewhere; open side → `type: string` | S5-013/058; S1-008; FiatAuthenticationConfig.java:61, rosco ServiceConfig.java:46, orca WebConfiguration.groovy:66 |
| 2026-09-11 | D9 | out of the first run; annotate 3–5 identities in a second run | kept; the three chains that survive R1(e) named (clientRequestId, artifactAccount+type, source.executionId) plus the reduced Orca→Front50 leg; chain 1 deferred with Keel; G1 must carry caller-side parameters | S6-002…008, 049-052, 068-073; R1(e) |
| 2026-09-11 | D10 | quoted statement and link; two labelers above twenty | kept; CLAIM-S4-019 does not count (closed, unmerged PR); 37 rows, 14 breaking; two labelers required; labels mapped to version-ordered pairs | S4-041/048/050; R1(d) |
| 2026-09-11 | D11 | triage: projection, normalization, real | kept; adds the categories dispatch slot and census defect | R1(a) |
| 2026-09-11 | D12 | no prevalence, no presence-under-none, no chains, untyped excluded | adds: no Keel claim, no CalVer claim, and the §5 scoping to caller-drift on the typed remainder | R1(b) |
| 2026-09-11 | D5 (owner) | untyped when any side of any leg is untyped; §5 gate on that reading | untyped only when both sides of both legs are untyped; one-sided legs are vacuous, excluded from evidence, and every figure is reported over live legs per component; measured at most 4.9 % (both legs untyped on at least one side; 50.6 % either-side) → §5 scoping lifted, R4 to be re-evaluated after the S1/S2 redos | R1(b); owner's ruling |
| 2026-09-12 | R4 | SCOPED-GO (reconciled 88.2 %, untyped 50.6 % either-side) | GO after the S1/S2 redos: reconciled 93.1 %, untyped 0.8 % under the D5 ruling; live legs 24.7 % reported as the quality number; given-ups unchanged | review pass 2; S1-028; S2-030/037 |
| 2026-09-12 | D3 | — | self-edges (caller = provider) dropped from the graph by G3 | S1-030 |
| 2026-09-12 | D5 | — | G1 marks untyped sides (`x-untyped: true`); figures reported over live legs | review pass 2 R1(b) |
| 2026-09-12 | D2/D3 (owner) | kork `Front50Service` rows and indirect `FiatService` rows undecided | both out of the graph, documented as dormant/library-issued clients; extractor flags `--kork-rows drop --indirect-fiat drop` | S1-025/028/030; G1 decisions A, B |
| 2026-09-12 | D4 (owner) | *declared* profile listed among the given-ups | kept as a near-empty control beside *none*; both reported | G1 decisions C |
| 2026-09-12 | D12 (owner) | — | claims as scoped: live legs only, vacuous share stated; the build proceeds | review pass 2 |

