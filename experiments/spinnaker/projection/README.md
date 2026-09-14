# Spinnaker's release train through the checker

**Question.** Spinnaker ships nine independently versioned JVM services in
coordinated releases, and every service declares the HTTP APIs it calls as
Retrofit interfaces. That makes it the first corpus in this repository where
the caller side of an edge is a real declaration, so C2, C4 and TGT — caller
drift and target-state conflicts — can be measured on released code. What
does `gus` see across 50 releases, and does any of it match what the project
itself recorded as breaking?

**Corpus.** BOMs 1.30.0 … 1.38.0 in version order: 50 releases, 49
consecutive pairs, 450 (BOM, service) pins that name 238 distinct service
versions. Contracts come from the released container images by reflection
(G1, `extractor/`), fetched anonymously and locked by digest (G2,
`fetcher/`, `corpus.lock`). Keel is pinned by no BOM and is out; CalVer
releases (one monorepo commit per BOM) and 1.24.0–1.29.7 (no image) are out.

**Projection and harness (this directory).** Each pin is extracted once in
two presence profiles (`none`: no `required` lists; `declared`: `required`
only where the Java says so, which on this corpus is primitives on the return
side). Every caller declaration is paired with the provider operation it calls
(D3), the documents the checker reads are rebuilt from the extractor's text
with three edits (the checker's lookup key, positional path variables, D6),
every BOM is gated by `gus consistent` with a triage row per failure (D11),
and each pair runs 46 batches — all nine services, each service alone, every
pair of services — through `gus check` and `gus mss`, plus one `gus evolve`
step. `compare.py` reads the output against the leg states of the documents
and against S4's labels.

## Lossy steps, stated first

1. **Evidence exists on live legs only, and there are few.** A leg is live
   when neither declaration of its payload is untyped (D5, owner's ruling).
   At 1.38.0, over the 394 matched edges and both declarations at that BOM:

   | reading | untyped edges | live legs | vacuous legs |
   |---|---|---|---|
   | request = body, as review pass 2 counted it | 1.0 % | 16.0 % | 24.9 % |
   | request = the whole `{params, headers, body}` wrapper | 2.5 % | 44.2 % | 28.3 % |
   | review pass 2 on the scout tables (body reading) | 0.8 % | 24.7 % | 18.9 % |

   Per component at 1.38.0, live / vacuous: `params` 68.0 % / 6.9 %,
   `headers` 0 % / 0 %, `body` 8.4 % / 6.6 %, response 23.6 % / 43.2 % (at
   1.30.0: 66.5/7.2, 0/0, 8.0/7.5, 22.6/44.4). Most calls are `GET`s with typed
   path and query parameters; most responses have an untyped side. Every figure
   below counts a break as evidence only when its component is live at the
   version pairing of its conjunct.
2. **The consistency gate removes a quarter of the edges from every pair.**
   A pair can only be judged from a consistent baseline (`gus check` refuses
   otherwise), so every edge with a BREAK at the baseline BOM leaves that pair:
   77–98 edges per pair, 99 distinct edges over the range. Why they fail is
   the triage table below: 53 of the 99 carry a declaration the two services
   really disagree on, 26 a projection defect and 30 a checker limit (an edge
   can carry more than one).
3. **Two dormant client families are out** (owner's rulings of 2026-09-12):
   kork-plugins' `Front50Service` (25 caller operations per BOM, created only
   when an operator enables a property no shipped profile sets) and the
   indirect `FiatService` of clouddriver, echo and igor (24 per BOM, issued by
   `fiat-api` rather than the service). Both are listed per BOM in
   `unmatched.tsv`. With them gone there is no self-edge at any BOM.
4. **Stale declarations are dropped and reported.** Nine caller operations at
   every BOM call an endpoint the provider does not expose (for example Gate,
   Orca and Clouddriver `GET /credentials` on Front50, Echo `POST /graphql` on
   Front50). One more, Orca's `PUT /admin/db/truncate/{namespace}` on
   Clouddriver, is lost to a projection defect: its handler ships in
   `cats-sql-*.jar`, which the extractor's provenance rule does not recognise
   as Clouddriver's (memo, CLAIM-G3-007).
5. **Opaque responses are not findings.** On 73–79 edges per BOM the caller
   declares no response body (Retrofit-1 `Response`/`Void`, `Call<ResponseBody>`,
   `Call<Void>`); on 23–24 of them the provider returns one. Those callers
   discard the body; they are loaded expecting anything and never counted
   (decisions.md 5).
6. **The two presence profiles give identical results** — the same gate
   exclusions at all 50 BOMs, the same findings and the same verdicts in all
   4 508 scenarios — because `declared` adds `required` only to Java primitives
   on the return side, and no conjunct here turns on them. Nothing is claimed
   about presence under `none`.
7. **Out of scope:** Keel (42 caller operations toward it per BOM), CalVer
   pairs, 1.24.0–1.29.7, chains (D9), prevalence.
8. **Custom serializers are the unmeasured risk.** A `JsonSerializer` makes
   the wire type differ from the declared Java type, and nothing static sees it
   (G1). Nothing here was compared with traffic.
9. **Edges that exist at only one BOM of a pair are not judged by the
   checker** (a missing endpoint is a hard error, not a finding). 30 such
   edge-pair rows are reported beside the checker in `graph/deltas.tsv`.
10. **The lattice is strict.** Both ends are Java, and Spring and Jackson
    coerce scalars; no rule chose a coercion profile, so none was changed
    (decisions.md 7).
11. **One extractor rule decides both of the run's breaks.** A Retrofit-1
    method returning a raw collection is projected as an untyped *object*; the
    same method under Retrofit 2 (`Call<List>`) becomes an untyped *array*.
    This keeps 20 edges out of every pair up to 1.36.3 and produces the only
    two breaks of the 49 pairs, at 1.36.3 → 1.37.0, where Gate moved to
    Retrofit 2 (memo, CLAIM-G3-020).

## The run

    python3 baseline.py extract && python3 baseline.py lock      # 238 pins x 3 runs; docs.lock
    python3 normalize.py --all                                   # unmatched.tsv, match-summary.json
    python3 graph.py catalog                                     # graph/edges.tsv
    python3 gate.py                                              # loaded copies, BOM graphs, gus consistent, triage/
    python3 graph.py pairs --presence none && python3 graph.py pairs --presence declared
    python3 scenarios.py && ./run.sh && python3 compare.py       # results/

| step | what | wall |
|---|---|---|
| extraction | 238 pins × (2 profiles + a client listing run), staging each pin's BOM from the corpus volume with sha256 re-hashing, 6 JVMs | 69 min 46 s; 714 runs, 0 failed |
| gate | loaded copies, 100 BOM graphs, `gus consistent`, triage | 46 s |
| fidelity | `graph.py verify` on every loaded copy (50 BOMs × 2 profiles) | 6 min 29 s; all faithful |
| harness | 98 pair graphs; 4 508 × `gus check` + `gus mss` where not safe; 98 × `gus evolve` | 5 min 57 s (check+mss 148 s and 159 s, evolve 15 s and 22 s) |
| acceptance | `baseline.py verify-lock 1.37.10`: stage the BOM, re-extract all nine services from its own jars, regenerate `docs.lock` | 6 min 24 s; byte-identical |

`docs/`, the loaded copies, the graph YAML and the raw checker output are not
committed (about 700 MB: documents 167 MB, loaded copies 242 MB, raw checker
output 222 MB, scratch 67 MB; all regenerable from `corpus.lock`, the extractor
jar and these scripts); `docs.lock` records the sha256 of every document.

## Results

### Pairing and gate

At every BOM, 94.1–94.3 % of the caller operations bound to one of the nine
services match a provider operation, **97.2–97.4 % once the 12 actuator calls
are excluded** (1.38.0: 367 matched of 389 resolved, 377 without the actuator
calls; the dispatch table's seven rows expand to 34 edges). No ties, no caller-side collisions, identical edge sets in
both profiles. `gus consistent` fails at every BOM and every failure has a
triage row (both profiles identical):

| category | findings (50 BOMs) | distinct edges | what they are |
|---|---|---|---|
| real inconsistency | 3 582 | 53 | the provider requires a query parameter the caller may omit (REQ.2, 2 336); a caller reads a body a `void` handler never sends (496); a scalar or enum the two models declare differently (600); a kind mismatch or unsent required parameter (150) |
| projection defect | 1 716 | 26 | an `Optional<Boolean>` parameter emitted as a required string (400); `@Nullable` provider fields against unannotated caller fields (D8, 350); query parameter arity and text binding (416); `@RequestBody String` projected as a JSON string (250); the `POST /ops` same-key collision (150); raw `ResponseEntity` emitted contentless (100); a primitive `@Query` marked optional (50) |
| checker limitation | 1 203 | 30 | an untyped side of another JSON kind (953) and object against map (250): declarations both sides agree on the wire, compared by kind first (decisions.md 6) |
| opaque response | 50 | 1 | clouddriver streams `PUT /artifacts/fetch`, igor reads it raw (D6) |
| warning | 100 | 1 | `format-change` WARN only; the gate inside `check` ignores it |

Per BOM this is 77–98 excluded edges: 92–98 up to 1.36.3 (29 of them checker
limitations), 77–82 from 1.37.0 on (10), when Gate's clients move to Retrofit 2
(lossy step 11).

### The harness

| | `none` | `declared` |
|---|---|---|
| scenarios (49 pairs × 46 batches) | 2 254 | 2 254 |
| could not evaluate (exit 2) | 0 | 0 |
| edges silently on Tier 3 | 0 | 0 |
| batches not safe as proposed | 10 (all at P37) | 10 (all at P37) |
| post-hoc certificate FAIL | 0 | 0 |
| breaks in the `all` batches | 2 | 2 |
| of which on live legs | **0** | **0** |
| warnings | 299 | 299 |

**48 of 49 pairs are safe in every batch.** The pair graphs hold 284–317
edges, and between the two BOMs of a pair documents do change — P07
(1.30.6 → 1.31.0) alone changes 32 provider components — but every change on
a graph edge is an added field or an added optional parameter, which no
conjunct breaks when accepting objects are open and no field is required.

**P37 (1.36.3 → 1.37.0)** is the one pair that is not. Its two breaks are C4
and TGT `kind-mismatch` at the response of `gate-clouddriver/9`
(`GET /applications/{application}/clusters/{account}/{clusterName}/{type}/serverGroups/{serverGroupName}`):
Gate 1.37.0 expects an array where Clouddriver's response is an object. Both
declarations are untyped — Gate's `ClouddriverService.getServerGroup` returns a
raw `List` before and after, Clouddriver's `ClusterController.getServerGroup`
returns `Object` — so the leg is untyped, the break is not evidence, and what
changed is the extractor's reading of a raw `List` across the Retrofit
migration (lossy step 11). `gus mss` excludes Gate and Clouddriver as a rollout
deadlock (C4 and TGT pin them in opposite orders), ships the other seven, and
its certificate passes; the ten unsafe batches are exactly the ten that contain
Gate.

**Warnings.** 294 are one standing difference, `orca-kayenta/2` (Orca sends
`int` thresholds, Kayenta reads `double`), reported by every `all` batch. The
other five are at P37 and are the one piece of caller drift on live legs in the
range: Orca and Igor both widen `buildNumber` from `int` to `long` in 1.37.0,
so the new Orca against the old Igor (C2) is a range warning on five edges.

**Caller drift.** Twenty caller declarations on pair-graph edges change
between the two BOMs of their pair (P05, P07, P10, P11, P14, P16 and P20 one
each, P33 two, P37 eleven; by component: parameters 8, response 7, body 4,
headers 1). One carries a C2/C4/TGT break — `gate-clouddriver/9` above; none
does on a live leg. `results/caller-drift.tsv` has all of them.

**Edges added and removed** (`graph/deltas.tsv`, 30 rows). P07 adds Orca's
call to Front50's new `GET /pipelines/triggeredBy/{id}/{status}`, the endpoint
CLAIM-S4-009 announces behind the flag CLAIM-S4-010 describes: a new caller
against an old provider finds no endpoint, so providers must go first — an
ordering the checker cannot express and the delta channel reports. P15–P17 show
six Echo and Orca calls to Igor's job-as-query-parameter build endpoints that
exist at 1.32.4 and 1.33.1 but not at 1.33.0: 1.32.4 was built after 1.33.0
(2024-03-08 against 2024-01-05), so the version-ordered pair 1.32.4 → 1.33.0
loses a backported change. The rest are new calls to endpoints that already
existed.

### S4 against the checker

Sixteen S4 rows target a release inside the range once CLAIM-S4-019 is set
aside (D10); fourteen of them map to one of its pairs, because S4-007 and
S4-008 start at 1.29.x. Every labelled pair is safe in every batch except P37,
labelled by CLAIM-S4-020 (the Retrofit 2 migration, compat-note).
The two contract-visible breaking rows:

* **CLAIM-S4-021** (Echo → Front50, HTTP 400 on `GET /pipelines/{id}/get`,
  1.36.0 → 1.37.6). The edge is `echo-front50/3`; D10 maps the range to the
  seven pairs P34, P35, P37–P41 where Echo or Front50 changes pin. In all seven
  neither declaration changes, the parameters leg is live, the response vacuous,
  and the checker reports nothing. The reported URL carries a pipeline name with
  brackets and spaces in the path: the break is the Retrofit 2 client's path
  encoding, which no declaration carries.
* **CLAIM-S4-023** (Igor → Echo `POST /`, 1.37.10 → 1.38.0). The edge is
  `igor-echo/1`, mapped to P48 and P49. The gate excludes it at both baselines —
  Igor declares a `String` response against Echo's `void`
  `HistoryController.saveHistory`, a real inconsistency in every release — and
  its body leg is vacuous anyway: Igor's `@Body Event` is abstract and projects
  untyped, against Echo's typed `Event`. Nothing changes across the two pairs.
  The reported failure is Igor not starting, which CLAIM-S4-024's fix (the
  abstract `@Body` type replaced by a map) places in Retrofit 2 converter
  construction, not on the wire.

The checker is silent on both, and on this corpus it could not have been
otherwise: neither break is a change in a declared payload.

`gus evolve` records 49 steps per profile and no identity (no chain is
annotated in the first run, D9).

## What the corpus exposed in the checker

Reported, not fixed.

1. **A caller declaration the checker cannot find degrades silently.**
   `loadEdgeSchemas` joins `/_calls`, the provider and the edge path with
   `filepath.Join`, which cleans the result, so a key such as `/_calls/echo/`
   is never found, and the edge falls back to the provider self-diff without a
   word (CLAIM-G3-003). Every edge here is re-keyed, and `CallerSpecUsed` is
   true on all of them.
2. **Kinds are compared before openness, and the only top type is Any.** An
   open object with no properties is D5's untyped `Map`/`Object`, yet it breaks
   against a typed map, an array or a scalar; 1 203 gate findings on 30 edges
   come from this (CLAIM-G3-015).
3. **Absence is checked before Any.** An empty schema admits every value, but
   not an absent body (`presence-mismatch` fires first), so "the caller reads
   nothing" cannot be written as "the caller accepts anything" wherever the
   provider may send no body (decisions.md 5).
4. **Edges are global.** A graph cannot say that an edge exists at some
   versions only, and `gus evolve` needs one graph valid at every step; the
   harness builds one graph per BOM and per pair instead (decisions.md 2).
5. **An endpoint is (path, method).** Spring dispatches on `consumes` and
   `params` too; Orca's two `POST /ops` handlers are one endpoint to the
   checker (CLAIM-G3-017).
6. **A missing endpoint is a hard error, not a finding.** An added call
   against an old provider, or a removed endpoint with old callers still
   rolling, cannot be judged; they are reported beside the checker.
7. **`gus consistent` and the gate inside `gus check` disagree on warnings**
   (CLAIM-G3-018).
8. **Text output is not deterministic**: object summaries list fields in map
   order (CLAIM-G3-019).

## Files

| path | what |
|---|---|
| `common.py`, `baseline.py`, `normalize.py`, `graph.py`, `gate.py`, `scenarios.py`, `run.sh`, `compare.py`, `report.py` | the pipeline, in that order |
| `docs.lock`, `docs.lock.verify.json` | sha256 of every extracted document; the byte-identity acceptance |
| `unmatched.tsv`, `match-summary.json` | every caller operation that yields no edge, per BOM, with its category; matched shares |
| `graph/edges.tsv`, `graph/deltas.tsv`, `graph/<presence>/pairs.json` | the edge catalog, the edges at one BOM of a pair, per-pair graph accounting |
| `triage/<presence>/<bom>.tsv`, `triage/gate-summary.json` | one row per consistency finding, with category and basis |
| `scenarios/` | 2 254 pair scenarios, 49 evolve steps, 50 gate baselines, `pairs.tsv` |
| `results/compare.md`, `results/compare.json`, `results/findings.tsv`, `results/caller-drift.tsv`, `results/<presence>/{ledger.json,run-times.txt}` | what the checker saw |
| `memo.md`, `decisions.md` | claims, counts and what could not be verified; choices the rules left open |
