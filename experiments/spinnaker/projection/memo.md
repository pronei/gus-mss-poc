# G3 memo — the projection and the harness

What it is: the step from G1's documents to verdicts. Fifty BOMs (1.30.0 …
1.38.0) are extracted per pin, normalised into loaded copies the checker can
read (D3, D6), gated by `gus consistent` at every BOM (D11), and the 49
consecutive pairs are run through `gus check`, `gus mss` and `gus evolve` in
two presence profiles; `compare.py` reads the output back against the leg
states of the documents and against S4's labels.

    python3 baseline.py extract            # stage, extract, release; docs.lock via `baseline.py lock`
    python3 normalize.py --all             # unmatched.tsv, match-summary.json
    python3 graph.py catalog               # graph/edges.tsv
    python3 gate.py                        # loaded copies, BOM graphs, gus consistent, triage/
    python3 graph.py pairs --presence none; python3 graph.py pairs --presence declared
    python3 scenarios.py                   # scenarios/
    ./run.sh                               # results/<presence>/
    python3 compare.py                     # results/compare.{md,json}, findings.tsv, caller-drift.tsv

## What was built

| file | what it does |
|---|---|
| `common.py` | release order and pins from `corpus.lock`; paths; the `gus` build |
| `baseline.py` | extraction per pin, `docs.lock`, `verify-lock` (the byte-identity acceptance) |
| `normalize.py` | D3 on the documents: `x-match-key` pairing, the dispatch table, unmatched categories |
| `graph.py` | the edge catalog, loaded copies (text-spliced), BOM and pair graphs, the delta channel, `verify` |
| `gate.py` | `gus consistent` per BOM, triage rows, the bytecode tables the documents cannot replace |
| `scenarios.py` | 46 batches per pair, evolve steps, `pairs.tsv` |
| `run.sh` | check + mss per scenario, evolve per pair through one ledger |
| `compare.py`, `report.py` | findings by conjunct, leg, component and state; safe subsets; caller drift; S4 |

## Constructs the rules did not cover

**CLAIM-G3-001**: **the 450 pins are 238 distinct service versions, and a
version is always the same jar set.** Across the 50 BOMs of `corpus.lock`, no
(service, version) appears with two different classpath/jar-sha256 sets, so an
extraction per BOM would re-read identical bytes 212 times. `baseline.py`
extracts each pin once, from the first BOM that pins it, and links every BOM's
document to it. source: `corpus.lock` (`boms.<bom>.services.<svc>.{version,classpath,jars}`);
`baseline.plan`.

**CLAIM-G3-002**: **the only byte of a document that depends on where the jars
sit is the header's `# classpath:` line, which prints the argument as given.**
Extracting through a symlink named `classpath/<svc>-<version>` makes a pin's
document independent of the BOM that supplied its jars (decisions.md 1).
source: `extractor/src/main/java/com/netflix/spinnaker/gusx/Extract.java`
(`header`: `b.append("# classpath: ").append(a.classpathDir)`).

**CLAIM-G3-003**: **the checker cannot find the extractor's caller declaration
for `POST /`.** `loadEdgeSchemas` looks the declaration up under
`filepath.Join("/_calls", edge.To, edge.Path)`, and the join cleans its result:
for the provider path `/` it is `/_calls/echo`, while the extractor writes
`/_calls/echo/` (`"/_calls/" + provider + Paths.normalize(path)`, and
`normalize("/")` keeps the slash). No error follows — the edge silently runs
under Tier 3, the provider self-diff, with no caller drift possible. Every
document in the corpus carries such a key (front50, gate, orca and igor call
echo's `POST /`; igor's is the edge of S4-023). Loaded copies re-key every
caller operation to the joined form. source: `cmd/gus/main.go:1120-1124`;
`CallerScan.iface` (`e.path = "/_calls/" + b.provider + Paths.normalize(rawPath)`);
`docs/pins/none/*/*.yaml`.

**CLAIM-G3-004**: **one graph cannot hold fifty releases.** The matched edge
set is 376 edges at 1.30.0 and 394 at 1.38.0, and pairs add and remove edges
(the 1.32.4 → 1.33.0 pair, patch train to minor line, removes six that 1.33.1
adds back). `gus consistent` and the baseline gate of `check` visit every edge
of the graph and hard-error on a provider endpoint missing at the baseline, so
the harness builds a graph per BOM for the gate and a graph per pair for the
run (decisions.md 2). source: `graph/none/pairs.json`; `cmd/gus/main.go:202-217,456-480,1095-1098`.

**CLAIM-G3-005**: **callers and providers disagree on path-variable names, and
D6 keys parameters by name.** At 1.38.0, before alignment, 116 of the 232 gate
findings (on 96 edges) were REQ.1 on `params.<provider variable>` where the
caller fills that position with a variable of another name — gate's
`ClouddriverService` writes `/applications/{name}/clusters`, clouddriver maps
`/applications/{application}/clusters`. Aligning by position removes all of them.
One case is a permutation (gate `/applications/{name}/clusters/{account}/{cluster}`
against clouddriver `/applications/{application}/clusters/{account}/{name}`) and
one a literal fill (orca's `Front50Service` `/notifications/application/{applicationName}`
against front50's `/notifications/{type}/{name}`). source: `gate.py` runs of
2026-09-13 (`triage/none/1.38.0.tsv` before and after `graph.path_param_plan`);
`graph/none/loaded/1.38.0/gate.yaml` (`x-g3-path-params`).

**CLAIM-G3-006**: **D6's provider-side replacement cannot be confined to the
edge it is for.** At 1.30.0 ten and at 1.38.0 nine provider endpoints are called
at the same BOM by one caller that declares the response opaque and by another
that declares a type — among them clouddriver `GET /applications/{name}`,
`PUT /artifacts/fetch` and echo's `POST /`. There are 73 opaque caller edges at
1.30.0 (49 against a contentless provider, 24 against a body) and 79 at 1.38.0
(55 and 24). The replacement is made on the caller's side instead
(decisions.md 5). source: `normalize.match_bom` (`opaque`, `provider_resp`), survey of 2026-09-13.

**CLAIM-G3-007**: **a Clouddriver controller lives in a jar the provenance rule
does not recognise as Clouddriver's.** `CatsSqlAdminController`
(`PUT /admin/db/truncate/{namespace}`) ships in `cats-sql-5.95.0.jar` (and
`cats-sql-5.80.0.jar`), a module of the clouddriver repository whose jar is not
named `clouddriver-*`; the extractor excludes it as a framework route, and orca's
`CloudDriverCacheService` calls it, so the edge is lost at every BOM and the call
appears in unmatched.tsv as `framework`. A projection defect for G1
(CLAIM-G1-007's rule). source: `docs/pins/none/clouddriver/5.95.0.diag.json`
(`framework-route-excluded`); unmatched.tsv.

**CLAIM-G3-008**: **an `Optional<T>` request parameter is emitted as a required
string.** clouddriver's `CredentialsController.listAccountCredentials(@RequestParam
Optional<Boolean> expand)` — optional in Spring, typed by its argument — is
`params.expand: {type: string}` and required in the document, which produces
REQ.1, REQ.2 and prim-mismatch findings on every caller of `GET /credentials`
(gate, orca, fiat, igor). source: `javap -v` on
`com.netflix.spinnaker.clouddriver.controllers.CredentialsController` in
`clouddriver-web-5.95.0.jar`; `gate.PROVIDER_PARAMS`.

**CLAIM-G3-009**: **`@RequestBody String` is projected as a JSON string.**
Spring reads the raw text of any payload into a `String` body; the document
says `type: string`, so every caller sending an object is a `kind-mismatch`.
echo's `WebhooksController.forwardEvent(String, String, @RequestBody String, HttpHeaders)`
(`POST /webhooks/{type}/{source}`) and igor's `GoogleCloudBuildController`
(`createBuild`, `updateBuild`, `extractArtifacts`, `runTrigger`) are the cases.
source: `javap -v` on those classes in `echo-webhooks-2.47.2.jar` and `igor-web-4.22.0.jar`.

**CLAIM-G3-010**: **`okhttp3.RequestBody` is projected as a bean.** echo's
`IgorService.updateBuildStatus` and `extractGoogleCloudBuildArtifacts` take
`@Body okhttp3.RequestBody`; the document has `{duplex: boolean, oneShot: boolean}`
(the class's `isDuplex`/`isOneShot` getters), required under `declared`. A raw
body is bytes, like `ResponseBody` on the return side. source: `javap -v` on
`com.netflix.spinnaker.echo.services.IgorService` in `echo-core-2.47.2.jar`.

**CLAIM-G3-011**: **a raw `ResponseEntity` is emitted as a contentless 200.**
`AmazonClusterController.getScalingActivities` (clouddriver-aws) and
`EcsServerGroupController.getServerGroupEvents` (clouddriver-ecs) return a raw
`ResponseEntity`, whose body is untyped, not absent; gate's `ClouddriverService`
declares `Call<List>` and `Call<List<Map>>` for them, and the gate reports
`presence-mismatch`. source: `javap -v` on both classes in the 5.95.0 jars.

**CLAIM-G3-012**: **callers read bodies that `void` handlers never send.**
Gate 6.69.0's `OrcaService` declares `Call<Map>` for orca's
`TaskController.deleteTask`, `cancelTask`, `cancelTasks`; gate 6.58.0 declares
`Map` for `deletePipeline`, `cancel`, `pause`, `resume` (all `void`, three with
`@ResponseStatus(ACCEPTED)`, in orca 8.31.0 and 8.64.0); front50's Retrofit-1
`EchoService.postEvent` returns `String` against echo's
`HistoryController.saveHistory` (`void`); orca's `KayentaService.cancelPipelineExecution`
returns `Map<?,?>` against kayenta-orca's `PipelineController.cancel` (`void`).
The documents cannot distinguish `void` from a stream or a raw entity (all three
are a contentless 200), so the gate reads these from `gate.PROVIDER_RESPONSE`.
source: `javap -v` on `TaskController` (`orca-web-8.31.0.jar`, `orca-web-8.64.0.jar`),
`OrcaService` (`gate-core-6.58.0.jar`, `gate-core-6.69.0.jar`), `HistoryController`
(`echo-web-2.47.2.jar`), `EchoService` (`front50-core-2.41.0.jar`),
`PipelineController` (`kayenta-orca-2.46.0.jar`), `KayentaService` (`orca-kayenta-8.64.0.jar`).

**CLAIM-G3-013**: **one gate failure is D6's own case seen from the provider.**
clouddriver's `ArtifactController.fetch` returns `StreamingResponseBody` (a
contentless 200 in the document) and igor's `HelmAccountsService.getIndex`
declares `Call<String>` for it: a non-JSON body read raw, which D6 makes
contentless on both sides. source: `javap -v` on `ArtifactController`
(`clouddriver-web-5.95.0.jar`) and `HelmAccountsService` (`igor-web-4.22.0.jar`).

**CLAIM-G3-014**: **a primitive `@Query` cannot be omitted.** Of the 45 REQ.2
findings on a named query parameter at 1.38.0, the Retrofit signatures put 42 on
reference types, 2 on primitives and 1 matched no method; at 1.30.0, 38, 2 and 1
of 41. orca's `Front50Service.setPreferredPluginVersion(@Query("preferred") boolean)`
is always sent and the document marks it optional (decisions.md 8). source:
`javap -v` on the callers' Retrofit interfaces at both BOMs.

**CLAIM-G3-015**: **a leg with one untyped side can fail.** D5 projects an
untyped `Map`/`Object` as an open object and a typed map as a map; the checker
compares kinds before anything else, so an untyped caller `Map` against
clouddriver's `Map<String, List<String>>` (`GET /applications/{application}/clusters`),
a `Map<String,String>` against echo's subscription POJO, or an untyped side of
another JSON kind is a `kind-mismatch` BREAK. The owner's ruling assumed such a
leg "can only pass". Ten edges at 1.38.0 and 29 at 1.30.0 fail the gate this
way. source: `triage/none/1.38.0.tsv`, `triage/none/1.30.0.tsv` (category `checker limitation`);
`pkg/compat/compat.go:103-110`.

**CLAIM-G3-016**: **D8's "unknown" nullability breaks on the response side.**
A provider field annotated `@Nullable` against the same field unannotated in the
caller's model is `nullable-response-widening`: orca's `OortService` manifest
model (`$.status.failed.message`, `$.status.stable.message`) and gate's
`ClouddriverService` credentials responses. Both Java fields accept null.
source: `triage/none/1.38.0.tsv` (rule `nullable-response-widening`).

**CLAIM-G3-017**: **the same-key collision is visible in the bytecode and
decides a verdict.** orca's `OperationsController` maps `POST /ops` twice:
`ops(List<Map>)` and `ops(Map)` with `consumes = "application/context+json"`.
The document keeps the list variant; gate's `OrcaService` posts a `Map`, so the
body is a `kind-mismatch` that the other handler would accept. source: `javap -v`
on `OperationsController` in `orca-web-8.64.0.jar`; CLAIM-G1-009.

**CLAIM-G3-018**: **`gus consistent` and the gate inside `gus check` disagree on
warnings.** `consistent` reports an edge with only WARN findings as
INCONSISTENT (exit 1); `check` on the same baseline says YES, because its gate
counts BREAKs alone. At 1.38.0 this is `orca-kayenta/2` (`format-change`, orca
sends `int` thresholds, kayenta accepts `double`). source: `cmd/gus/main.go:212-216`
against `:469-472`; runs of 2026-09-13.

**CLAIM-G3-019**: **the checker's text output is not deterministic.** Three
consecutive `gus consistent` runs on the same graph and scenario print object
summaries with their fields in different orders (11 lines differ between two of
them at 1.38.0), so no output of the harness is compared as text.
source: three runs of `gus consistent --graph graph/none/bom-1.38.0.yaml
--scenario scenarios/baselines/1.38.0.yaml` on 2026-09-13, diffed; `pkg/types` `Summary`.

**CLAIM-G3-020**: **a Retrofit-1 raw collection is projected as an object, the
same method under Retrofit 2 as an array, and the run's only breaks follow.**
`CallerScan.callerResponse` returns `Schema.untypedObject()` for any raw
generic return, so Gate 6.64.2's Retrofit-1 methods returning a raw `List` expect
an untyped object; Gate 6.66.0's `Call<List>` passes the raw-generic test and
`Shape` makes it an untyped array. On 20 Gate edges whose provider returns an
array this is a `checker limitation` at the gate from 1.30.0 to 1.36.3 that
disappears at 1.37.0 (all 20 caller responses go object → array; none of the
providers changes). On `gate-clouddriver/9` the provider returns `Object`, so the
same transition produces the C4 and TGT `kind-mismatch` at P37 — the only two
breaks of 49 pairs, both on an untyped leg. The Java declarations do not change
kind: `ClouddriverService.getServerGroup` returns `java.util.List` in
gate-core 6.58.0 and `retrofit2.Call<java.util.List>` in 6.69.0, and
`ClusterController.getServerGroup` returns `java.lang.Object` in clouddriver-web
5.95.0. A projection defect for G1. source: `graph/none/loaded/{1.36.3,1.37.0}/gate.yaml`;
`triage/none/{1.36.3,1.37.0}.tsv`; `javap -v` on those classes;
`CallerScan.callerResponse` (`if (Types.isRawGeneric(...)) return Schema.untypedObject();`).

**CLAIM-G3-021**: **across 49 pairs, 4 508 scenarios and both presence
profiles, the checker reports no break on a live leg.** 48 pairs are safe in
every batch; P37 has the two breaks of CLAIM-G3-020. No scenario failed to
evaluate, no edge ran under Tier 3, no post-hoc certificate failed, and the two
profiles agree on every finding, verdict and safe subset. source:
`results/compare.json` (`totals`, `profiles`).

**CLAIM-G3-022**: **the one caller drift on live legs is a warning.** At P37
Orca (8.57.2 → 8.61.0) and Igor (4.18.2 → 4.19.0) both widen `buildNumber` from
`int32` to `int64`; C2 (new Orca, old Igor) is a `format-change` WARN on five
edges. The other 294 warnings are one standing difference repeated in every
pair (`orca-kayenta/2`: Orca `int` thresholds, Kayenta `double`). source:
`results/findings.tsv`; `graph/none/loaded/{1.36.3,1.37.0}/{orca,igor}.yaml`.

**CLAIM-G3-023**: **S4's two contract-visible breaks are not payload changes.**
CLAIM-S4-021's edge `echo-front50/3` has the same declarations on both sides in
all seven pairs D10 maps it to (P34, P35, P37–P41; parameters live, response
vacuous, no finding); the reported URL puts a pipeline name with brackets and
spaces into the path, which is client path encoding. CLAIM-S4-023's edge
`igor-echo/1` is excluded by the gate at P48 and P49 (Igor reads a `String` from
Echo's `void` handler, in every release), its body leg is vacuous (Igor's
abstract `@Body Event` projects untyped), and no declaration changes; the
failure was Igor not starting, which CLAIM-S4-024's fix places in Retrofit 2's
converter for an abstract body. source: `results/compare.json` (`labels[].trace`);
`graph/none/loaded/{1.37.10,1.37.11,1.38.0}/{igor,echo}.yaml`.

**CLAIM-G3-024**: **the delta channel reports an ordering S4 describes and the
checker cannot express.** At P07 Orca starts calling Front50's new
`GET /pipelines/triggeredBy/{id}/{status}` (CLAIM-S4-009, behind the flag of
CLAIM-S4-010): a new caller against the old provider finds no endpoint, so the
provider must go first. The same channel shows version order crossing patch
trains: six Echo and Orca calls to Igor build endpoints exist at 1.32.4 and
1.33.1 but not at 1.33.0, because 1.32.4 (BOM timestamp 2024-03-08) was built
after 1.33.0 (2024-01-05). source: `graph/deltas.tsv`; `corpus.lock` (`timestamp`).

**CLAIM-G3-025**: **`docs.lock` regenerates byte-identically from a BOM other
than the one that supplied most of its jars.** `baseline.py verify-lock 1.37.10`
staged 1.37.10 whole, re-extracted its nine services in three runs each (27
documents; eight of its nine pins had been extracted from 1.37.9's jars) and
regenerated a `docs.lock` equal byte for byte to the committed one. source:
`docs.lock.verify.json`.

## Counts

**Pins and documents.** 238 distinct pins; 714 extractions (two profiles and
the client listing run), 0 failed; 476 distinct profile documents.

**Edges.** At 1.38.0, 394 edges (343 exact, 17 by template, 34 by dispatch from
7 table rows); at 1.30.0, 376. Over the range 394 identities, 376 of them at all
50 BOMs. At 1.38.0 by caller: gate 197, orca 140, echo 19, clouddriver 13,
front50 10, igor 7, fiat 6, rosco 2, kayenta 0; by provider: clouddriver 142,
front50 99, igor 55, orca 34, fiat 25, kayenta 18, echo 12, rosco 9, gate 0.
Pair graphs hold 284–317 edges; 30 edge-pair rows exist at one BOM only.

**Matching.** Matched share of resolved caller operations 94.1–94.3 % per BOM,
97.2–97.4 % without the 12 actuator calls (1.38.0: 367 of 389). Per BOM, in
`unmatched.tsv`: out-of-mesh 42, kork 25, indirect-fiat 24, actuator 12, stale 9,
framework 1, self-edge 0, dispatch-slot 0 (5 650 rows over 50 BOMs).

**Legs** (1.38.0, 394 edges, both declarations at that BOM). Body reading:
requests contentless 301, one side contentless 11, live 33, untyped 23, vacuous
26; responses contentless 55, one side contentless 21, live 93, untyped 55,
vacuous 170 — live 16.0 %, vacuous 24.9 %, untyped edges 1.0 %. Whole-wrapper
reading: live 44.2 %, vacuous 28.3 %, untyped edges 2.5 %. Components live /
vacuous: params 68.0 / 6.9 %, headers 0 / 0 %, body 8.4 / 6.6 %, response 23.6 /
43.2 %.

**Triage** (50 BOMs; identical in both profiles). 6 651 findings: real
inconsistency 3 582 (53 edges), projection defect 1 716 (26), checker limitation
1 203 (30), opaque response 50 (1), warning 100 (1); 77–98 edges excluded per
BOM, 99 distinct. On 73–79 edges per BOM the caller operation is opaque, and
23–24 of those are loaded expecting Any; path variables aligned on 95–98 edges
per BOM.

**Findings** (`all` batches, per profile). BREAK 2 (C4 1, TGT 1; rule
`kind-mismatch`; component response; leg state untyped), 0 on live legs. WARN
299 (`format-change`).

**Safe subsets.** 10 batches not safe, all at P37 (every batch containing Gate).
`all`: safe subset {echo, fiat, front50, igor, kayenta, orca, rosco}, Gate and
Clouddriver excluded as a rollout deadlock; `gate`, `clouddriver+gate`: empty;
`<service>+gate`: {<service>}. Post-hoc certificate FAIL: none.

**Wall times.** Extraction 69 min 46 s (staging included, 6 JVMs); gate 46 s
for 100 BOM graphs; loaded-copy verification 6 min 29 s; pair graphs + `run.sh`
+ `compare.py` 5 min 57 s (check+mss 148 s `none`, 159 s `declared`; evolve 15 s
and 22 s); `verify-lock` 6 min 24 s.

## What I could not verify

* **That any declaration is the wire.** No service was run and no response was
  compared. A custom `JsonSerializer`, a runtime-registered subtype or a
  converter configured in a `@Bean` method makes the declared type differ from
  the bytes, and nothing here detects it (inherited from G1).
* **The bytecode tables at every version they are applied to.**
  `PROVIDER_RESPONSE`, `PROVIDER_PARAMS` and `CALLER_PRIMITIVE_QUERY` were read at
  1.38.0 (Orca's pipeline operations also at 1.30.0) and are applied wherever the
  document shows the same symptom. A handler that changed in between would carry
  the wrong category; its exclusion, which depends only on severity, would not
  change.
* **The primitive-`@Query` reading beyond two BOMs.** Only the REQ.2 rows of
  1.30.0 and 1.38.0 were checked against Retrofit signatures, and one row per BOM
  matched no method.
* **What Clouddriver really returns for `getServerGroup`.** It declares
  `Object`; whether that is a JSON array (and Gate's migration right) or an
  object decides whether P37's untyped break is a real hazard.
* **The labels.** S4's rows are one labeler's; D10 requires two, and I am not
  one of them. The mapping of range labels to the pairs where a named service
  changes pin is mechanical.
* **Converter configuration.** A `String` caller return is read as a JSON
  string because no Spinnaker or kork jar references `ScalarsConverterFactory`;
  a converter registered elsewhere at runtime was not looked for.
* **Leniency.** The strict lattice was never compared with a lenient run; the
  text-binding findings and any scalar-into-string body would change.
* **The review's live-leg share.** 16.0 % here against 24.7 % in review pass 2
  is not reconciled row by row: the populations differ (the scout tables carried
  the kork and Keel rows and no dispatch expansion) and the extractor's `x-untyped`
  marks differ from the review's type-name classifier.
* **Path encoding and client construction.** Positional alignment treats a path
  variable as its value; how a client percent-encodes it, and whether a client
  can be built at all, are outside every declaration (CLAIM-G3-023).
* **Chronology.** Pairs follow version order as D2 decides; where patch trains
  overlap (CLAIM-G3-024) a pair is not an upgrade anyone shipped, and no pair was
  re-read in date order.
