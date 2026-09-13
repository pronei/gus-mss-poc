# Review pass (Phase 1b) over the six Spinnaker scout reports

Reviewer run: 2026-09-11. Scripts and their outputs are under `scout/review/`
(`r0_completeness.py`, `r1ab_reconcile.py`, `r1b_sensitivity_igor_gap.py`,
`r1_nine_service_mesh.py`, `r1c_boms.py`, `r1d_groundtruth.py`, `r1e_chains.py`,
`r1f_gaps.py`, `r2_jarscan.py`, `r2_fetch.sh`, `r2_s2_coverage.py`,
`r2_s2_014_keel_models.py`, `build_review_json.py`); every number below is in
`scout/review.json`. The scouts' clones under the scratchpad were used read-only;
their tags were checked with `git describe --tags` (all ten at the tags of
CLAIM-S1-001; S2 additionally kork v7.254.0). The checker is `gus@main` at
`99e3c8c`, read-only. Registry and web queries were anonymous.

Two facts the scouts did not state, established here and used throughout:

* The "latest tags" S1, S2, S5 and S6 read are exactly the pins of BOM 1.38.0
  for all nine BOM-pinned services (gate 6.69.0, orca 8.64.0, clouddriver 5.95.0,
  front50 2.41.0, echo 2.47.2, igor 4.22.0, fiat 1.57.0, rosco 1.26.0, kayenta
  2.46.0; `S3/boms/1.38.0.yml`). The reconciliation of R1 is therefore at one
  coherent BOM state — the last one of the range recommended below — not at a
  mixture of tags. Keel v1.4.1 is the repository's own last tag; no BOM pins Keel.
* From 2025.0.0 on, every BOM pins all nine services at one version and one
  monorepo commit (checked 2025.0.0, 2025.1.0, 2025.2.0, 2026.0.0). The property
  the corpus was chosen for — independently versioned services inside a
  coordinated release — holds on the 1.x train only.

## R0 Completeness

| report | files | header exact | memo ends with "## What I could not verify" | claims numbered and sourced | result |
|---|---|---|---|---|---|
| S1 | edges.tsv (534 rows), clients.md, memo.md | yes | yes | 20/20 numbered, all with `source:`; the Counts section is unnumbered (used only as orientation) | **pass** |
| S2 | endpoints.tsv (732 rows), typing-census.md, memo.md | yes; `typing` values all in the vocabulary; every row's `claim` carries `source:` | yes | 25/25 numbered and sourced; row claims CLAIM-S2-R0001…R0732 | **pass** (but see R2: the census is incomplete) |
| S3 | boms.tsv (3460 rows = 346 releases × 10 services), artifacts.md, memo.md | yes | yes | 28/28 numbered; 11 (003, 010, 012, 013, 016, 020, 021, 024, 025, 026, 027) carry their evidence inline (a URL, a command, a file path, or "parse of all 346 BOMs") without the literal `source:` label — logged as a formatting deviation, not a failure | **pass** |
| S4 | ground-truth-candidates.md (38 rows), memo.md, releases.tsv (extra, 121 rows) | yes (table columns exactly `pair services kind quoted_sentence source_url claim`; kinds in vocabulary) | yes | 001–002, 041–053 in the memo; 003–040 are the table rows, each with quote and URL | **pass** |
| S5 | gaps.md (62 rows), memo.md | yes (`construct count loader_today projection_convention checker_change cost claim`); every row has a claim | yes | 59/59 numbered (049–054 share one `source:` line at the end of their paragraph; 045/046 are a pair) | **pass** |
| S6 | chains.md, memo.md | chains.md gives identity, mint, sink, hops with a field at each, and claim references for five ranked chains | yes | 78/78 numbered and sourced | **pass** |

S3's declared deviation — `artifact_kind = not-pinned`, `pinned_version = -`,
`retrievable = n/a` for the 367 (release, service) rows a BOM does not pin (346
Keel + 21 Kayenta) — is **accepted**: `no` would be false and would corrupt the
longest-run computation; the filter `artifact_kind != not-pinned` is applied in
R1(c) and every one of the 367 rows carries `n/a` and `-` consistently.

Two arithmetic slips, not R0 failures: CLAIM-S1-019 says 100 rows lack a leading
slash and 433 have one (sum 533); the file has 101 and 433. The verb count in
S1's memo says POST 117; the file has 118 (total 534).

## R1 Reconciliation

### R1(a) S1 edges against S2 endpoints (`r1ab_reconcile.py`, `r1a_matched.tsv`, `r1a_unmatched.tsv`)

Normalization applied to both sides: strip a baked-in query string (17 S1 rows);
`"."` and `""` become `/`; add the missing leading slash (101 S1 rows); erase
variable names and regexes (`{id:.+}` → `{}`); collapse `//`; strip a trailing
slash; a provider `**` matches any suffix; a provider `{}` slot is filled by a
caller literal or a caller `{}`; a provider method `ANY` matches every method.
No per-service prefix rule was needed at 1.38.0 (callers already declare the
provider's `/v2` and `/api/v1` prefixes); the rule table exists and is empty.
Where several provider templates match, the most specific (most literal
segments, fewest `**`) wins; 4 matches were tied (identical templates in two
controllers, e.g. Orca's two `POST /ops`).

Both sides are at the 1.38.0 pins (see the header), so the comparison is
internally coherent; it is one state, not a range.

| | resolved | matched | share | unmatched |
|---|---|---|---|---|
| all ten services | 533 | 470 | **88.2 %** | 63 |
| excluding the 14 actuator rows | 519 | 470 | 90.6 % | 49 |
| nine-service mesh (Keel dropped, D2) | 435 | 383 | 88.0 % | 52 |
| nine-service mesh excluding 12 actuator rows | 423 | 383 | 90.5 % | 40 |

Per provider (matched / resolved): clouddriver 142/152 (93.4 %), front50
112/120 (93.3 %), fiat 64/65 (98.5 %), igor 33/63 (**52.4 %**), keel 36/44
(81.8 %), orca 42/44 (95.5 %), kayenta 18/18, echo 14/17 (82.4 %), rosco 9/10.

The 63 unmatched rows fall into five classes, each row listed with its
normalized path in `r1a_unmatched.tsv`:

| class | rows | what they are |
|---|---|---|
| actuator | 14 | `GET /health` ×6 (Spring Boot actuator) and `GET /installedPlugins` ×8 (kork's `InstalledPluginsEndpoint`, `@Endpoint(id = "installedPlugins")`) — real endpoints, not MVC controllers, outside S2's method and outside the graph |
| S2 census gap | 24 | Igor's `BuildController.groovy` (12 mappings) and `InfoController.groovy` (4) are missing from `endpoints.tsv` (R2, CLAIM-S2-003); 24 of Igor's 30 unmatched rows match them (`r1b_sensitivity_igor_gap.py`) |
| provider dispatch slot | 7 | a caller variable over a provider literal: Gate/Orca `/{provider}/images/find`, `/tags`, `/{account}/{region}/{imageId}` against Clouddriver's per-cloud `/aws/images/…`, `/gce/images/…` (5), Gate `…/{provider}/serverGroups/{sg}/scalingActivities` (1), Orca `/{repoType}/{projectKey}/{repositorySlug}/compareCommits` against Igor's `/github/…`, `/stash/…` (1) — a D3 hand-table case |
| framework route | 1 | Gate → Keel `POST /graphql`, registered by the DGS framework, not a controller |
| stale caller declaration | 17 | dead client methods: Gate/Orca/Clouddriver `GET /credentials` on Front50 (3), Gate `POST /pipelines/move`, `/strategies/move` (2), Echo `POST graphql` on Front50 (1), Gate on Clouddriver `POST /applications/{name}/jobs/{account}/{region}/{jobName}` and `…/clusters/{account}/{cluster}/{type}/loadBalancers` (2), Gate on Keel `POST /resources`, `DELETE /resources/{name}`, `GET /delivery-configs/{name}/artifacts`, `/reports/onboarding`, `/reports/adoption` (5), Orca on Echo `GET /events/recent/{type}/{since}/` (1), Keel on Igor `/scm/repos/…` ×2 and `/scm/build-results/…` (3) — none exists in the provider's source at 1.38.0 |

With the 24 census-gap rows matched against the two missed controllers (their
signatures hand-read, an estimate S2 must replace), the matched share becomes
494/533 = 92.7 % (95.2 % excluding actuator rows); on the nine-service mesh
407/435 = 93.6 % (96.2 %). The 17 stale rows are the finding "caller declares an
endpoint the provider does not expose"; because `cmd/gus/main.go:1097` makes an
unmatched edge a hard input error (`endpoint %s %s not found in provider`,
confirmed), G3 must drop them from `graph.yaml` and report them separately.

### R1(b) Untyped share over the reconciled edges

Definition as written (plan §5 with the JsonNode addition of the brief): an edge
is untyped when its caller body, caller return (unwrapped from `Call<>`),
provider body or provider return is a `Map` in any parameterisation, `Object`
(`Any`, Groovy `def`), `List<Map…>`, `JsonNode`, a raw generic, or a Map-subclass
model (front50 `PipelineTemplate`, `Notification`). S5's refinement: `Map<String,X>`
with a concrete `X` is typed; only raw `Map`, `Map<String,Object>` and wildcard
values, `Object`, `List<Map…>`, `JsonNode` and raw types are untyped. Opaque
returns (`Call<ResponseBody>`, Retrofit-1 `Response`, `Call<Void>`, `void`,
`StreamingResponseBody`) are contentless, not untyped, in both readings. My
strict classifier reproduces S2's `typing` column on all 732 rows (0 mismatches).

| population | edges | untyped, as written | untyped, S5 refinement | untyped on both sides |
|---|---|---|---|---|
| reconciled, ten services | 470 | 240 = **51.1 %** | 238 = **50.6 %** | 23 = 4.9 % |
| reconciled, nine-service mesh (D2) | 383 | 220 = **57.4 %** | 218 = **56.9 %** | 21 = 5.5 % |
| + Igor census-gap estimate, ten services | 494 | 252 = 51.0 % | 250 = 50.6 % | — |
| + Igor census-gap estimate, nine services | 407 | 232 = 57.0 % | 230 = 56.5 % | — |
| sensitivity: as written, opaque caller returns counted untyped (S1's reading) | 470 | 328 = 69.8 % | — | — |

Per provider, as written (matched edges): kayenta 83 %, orca 71 %, clouddriver
63 %, front50 60 %, echo 57 %, rosco 44 %, keel 33 %, igor 24 %, fiat 11 %.

The share is above the 50 % line under every reading, and the refinement moves
it by two edges. The threshold is applied to the definition in force after R3
(D5 revised to the refinement): 50.6 % on the ten-service reconciliation and
56.9 % on the nine-service mesh the run will actually use. Note for the plan's
owner: D5 excludes from claims the edges untyped on *both* sides (4.9 %), while
§5 gates on edges untyped on *either* side (50.6 %); the two clauses measure
different things, and this review has not changed which one the gate means.

### R1(c) BOM runs (`r1c_boms.py`)

Recomputed from `boms.tsv` with `artifact_kind != not-pinned`, releases in
version order:

* images only: **1.0.0…1.23.7 = 202 releases / 201 pairs**; 1.30.0…2026.3.0 =
  94 / 93; the 50 releases 1.24.0…1.29.7 fail. Confirms CLAIM-S3-012/027.
* images + Maven jars: 1.0.0…1.23.7 unchanged; 1.27.0…2026.3.0 = 120 / 119; the
  24 releases 1.24.0…1.26.7 have no artifact anywhere. Confirms CLAIM-S3-015/027.
* minor-line heads, images only: 1.0.0…1.23.0 = 24 / 23 (confirms CLAIM-S3-027).
* S3's recommended range 1.30.0…1.38.0: 50 releases / 49 consecutive pairs, all
  container images, Kayenta pinned throughout, nine minor heads.
* Ordering by `release_date` instead of version splits the first run at 1.23.5
  (patch trains overlap in time; 1.28.10 is dated after 1.35.0): pairs must be
  taken in version order.
* Services ever pinned: nine (gate, orca, clouddriver, front50, echo, igor,
  fiat, rosco in all 346; kayenta in 325, from 1.7.0). **Keel is pinned by no BOM**
  (confirms CLAIM-S3-006/007). Keel images exist on GAR (199 tags) and GHCR (370)
  only from `2025.0-0`.

### R1(d) Ground-truth rows (`r1d_groundtruth.py`)

All 38 rows have an `https://` URL and a quoted sentence; none is dropped.
Survivors per kind: **breaking 14, compat-note 21, upgrade-order 1,
deprecation-removed 2** (29 from spinnaker.io changelogs, 9 from GitHub).
CLAIM-S4-019 is quoted from spinnaker/spinnaker.io PR 504, closed without
merging (CLAIM-S4-048): it passes the mechanical check but **does not count** as
ground truth — a contributor's unmerged draft is not a project statement about
the release, and its subject (Orca→Front50 timeout properties) is configuration,
not an interface. Excluding it: compat-note 20, total 37. Rows whose target lies
in 1.30.0…1.38.0: 17, of which 6 `breaking` (S4-008, 011, 014, 016, 021, 023);
only S4-021 (Echo→Front50 400 on `GET /pipelines/{app}/get` after the Retrofit-2
migration) and S4-023 (Igor→Echo `POST /` failing at 1.38.0) describe a caller's
declared interface failing; S4-014 is the swagger-ui path, S4-008/011 are
behavioural, S4-016 a provider bug. 38 > 20 → D10's two-labeler requirement is
triggered (CLAIM-S4-050).

### R1(e) Chains (`r1e_chains.py`)

Field existence checked in `endpoints.tsv` (`body_type`, `path_params`,
`query_params`, `header_params`) or `edges.tsv`; body fields verified in the
declared type's source because the TSVs carry only the type name; caller-side
query fields verified in the Retrofit source because `edges.tsv` has no
parameter columns (an S1 schema limit the brief allowed, which G1 must not
inherit).

| chain (S6 rank) | result | why |
|---|---|---|
| 1 `correlationId` Keel → Orca | fails at sink-1 | mint OK (`OrchestrationTrigger.correlationId: String?` in Keel's typed body); Orca `POST /ops` body is `Map`/`List<Map>` on both of its rows, so no declared field; sink-2 `GET /executions/correlated/{correlationId}` path param OK; reader OK. Survives reduced (mint → path-param sink); deferred with Keel under D2 |
| 2 `application` Gate → Orca → Front50 | fails at mint and hop-in | Gate's `POST /ops` body is `Map<String,Object>` (S1) and Orca's is `Map` (S2); the Orca → Front50 leg (`Application.name` body field + `applicationName` path param, both sides) passes. Survives only as a two-node Orca → Front50 chain |
| 3 `clientRequestId` Orca → Clouddriver | passes | `@Query("clientRequestId")` in KatoRestService.java (source; not in edges.tsv); `clientRequestId:optional` in Clouddriver's `POST /{cloudProvider}/ops` query_params |
| 4 `artifactAccount`+`type` Orca/Rosco → Clouddriver | passes | kork `Artifact` (`private final String type; … artifactAccount`) is the declared body on all three rows (`PUT /artifacts/fetch/` callers, `PUT /artifacts/fetch` provider — a D3 trailing-slash case) |
| 5 `source.executionId` Orca → Echo | passes | nested `Source { executionType, executionId, application, user }` declared identically in Orca's `EchoService.Notification` and Echo's `Notification`; Echo's row is `polymorphic` |
| alternate Echo → Orca → Kayenta | fails at hop-in | Orca `POST /orchestrate` body is `Map`; mint (`Pipeline.application`, `@NonNull`) and sink (Kayenta query params) pass |

### R1(f) gaps.md (`r1f_gaps.py`)

62 rows parsed. Four rows carry a `yes` in `checker_change` (inheritance
without `@JsonTypeInfo` — `allOf`; `@JsonAlias` in the pair relation;
Map-subclass models; the unmatched-endpoint finding); every one has a non-empty
projection convention and a cost. **No violation.** Every row has a cost and a
claim.

## R2 Re-derivation

Fixed sample: claims 2, 5, 8 of each memo. Repository claims were opened at the
cited line in the scouts' clones (tags verified); artifact claims re-queried
anonymously (`r2_fetch.sh`; class files read with `r2_jarscan.py`, no JDK);
web claims fetched and the quoted sentence located. Two incidental refutations
(S1-017, S2-003) were found while reconciling; each extended its memo's sample
to 11, 14, 17, 20 as the plan prescribes.

| claim | source | result | evidence |
|---|---|---|---|
| CLAIM-S1-002 | gate@v6.69.0 GateConfig.groovy:254; ServiceConfiguration.java:76 | confirmed | `createClient(serviceName, type, dynamicName = null, forceEnabled = false)` at :254 calls `serviceConfiguration.getServiceEndpoint(serviceName, dynamicName)` (:268); `getServiceEndpoint` returns `Endpoints.newFixedEndpoint(service.getBaseUrl())` (:76-78) |
| CLAIM-S1-005 | gate@v6.69.0 DownstreamServicesHealthIndicator.groovy:59; ServiceConfiguration.java:52 | confirmed | one `HealthCheckableService` per enabled name in `healthCheckableServices` (:59-67); default `List.of("orca","clouddriver","echo","igor","flex","front50","mahe","mine","keel")` (:52-53); the interface has one method, `@GET("/health") Call<Map> health()` |
| CLAIM-S1-008 | fiat@v1.57.0 FiatAuthenticationConfig.java:65; FiatClientConfigurationProperties.java:26 | confirmed | bean built with `.baseUrl(RetrofitUtils.getBaseUrl(fiatConfigurationProperties.getBaseUrl()))` (:65); `@ConfigurationProperties("services.fiat")` (:26) |
| CLAIM-S1-011 (ext.) | kayenta@v2.46.0 RetrofitClientFactory.java:99 | confirmed | `String baseUrl = remoteService.getBaseUrl();` at :99; 12 Retrofit interface files; no main source or config names a Spinnaker service base-URL key |
| CLAIM-S1-014 (ext.) | orca.yml:16-21; CloudDriverConfigurationProperties.java:95-99; rosco ServiceConfig.java:32; keel ClouddriverConfiguration.kt:43 | confirmed | `oort`/`mort`/`kato` `baseUrl: ${services.clouddriver.baseUrl:…}`; `getCloudDriverBaseUrl()` falls back clouddriver → kato → oort; `@Value("${services.clouddriver.base-url:…}")`; `@Value("\${clouddriver.base-url}")` |
| CLAIM-S1-017 (ext.) | `rg 'serviceClientProvider.getService'` over the ten repositories | **refuted** | kork@v7.254.0 `kork-plugins/src/main/kotlin/com/netflix/spinnaker/kork/plugins/update/internal/Front50Service.kt` is a retrofit2 interface (`GET /pluginInfo/{id}`, `GET /pluginInfo`, `PUT /pluginVersions/{serverGroupName}`), bound by `Front50PluginsConfiguration` (`@ConditionalOnProperty("spinnaker.extensibility.repositories.front50.enabled")`) to `spinnaker.extensibility.repositories.front50.url` → `front50.base-url` → `services.front50.base-url`; all ten repositories depend on kork-plugins. S1 flagged kork as unread; the statement is still false |
| CLAIM-S1-020 (ext.) | gate ClouddriverService.java:394 and per-interface counts | confirmed | 63 `FiatService` rows over 7 callers; 6 `HealthCheckableService` rows; Gate `ClouddriverService` 75 rows = 74 quoted-form annotations + `@GET(value = "/functions")` at :394; the other 45 interfaces have rows == annotations |
| CLAIM-S2-002 | front50@v2.41.0 PipelineController.java:109 | confirmed | class `@RequestMapping("pipelines")` (:75); `@RequestMapping(value = "", method = GET)` (:109); `Collection<Pipeline> list(restricted defaultValue "true", refresh defaultValue "true", enabledPipelines, enabledTriggers, triggerTypes)` (:110-116) |
| CLAIM-S2-005 | front50@v2.41.0 PipelineTemplate.java:29 | confirmed | `public class PipelineTemplate extends HashMap<String, Object> implements Timestamped` |
| CLAIM-S2-008 | keel@v1.4.1 KeelApiModule.kt:104 | confirmed | `KeelApiAnnotationIntrospector.types` = {Constraint, ConstraintStateAttributes, DeliveryArtifact, SortingStrategy, Verification, PostDeployAction} (:104-111); `findTypeResolver` → `StdTypeResolverBuilder().init(Id.NAME).inclusion(As.EXISTING_PROPERTY).typeProperty("type")` (:114-121) |
| CLAIM-S2-003 (incidental) | endpoints.tsv vs the trees | **refuted** | `extract.py:949` prunes every directory named `build` (meant for Gradle output), which drops the package `com.netflix.spinnaker.igor.build`: `igor-web/…/igor/build/BuildController.groovy` (12 method mappings: `/builds/status|artifacts|queue|all|properties/…`, `PUT /masters/{name}/jobs/**`, two `stop` variants, `PATCH …/update/{buildNumber}`) and `InfoController.groovy` (4: `/masters`, `/buildServices`, `/jobs/{master:.+}`, `/jobs/{master:.+}/**`) are absent, with no entry in diag.json; the other 226 controller files are present (`r2_s2_coverage.py`). Igor has 51 endpoints, not 35; the mesh 748, not 732; the `**` count is 21, not 15 |
| CLAIM-S2-011 (ext.) | front50 PipelineMixins.java:32,35; S3StorageService.java:68 | confirmed | `@JsonAnySetter` (:32) / `@JsonAnyGetter` (:35) on the mixin; `.addMixIn(Pipeline.class, PipelineMixins.class)` (:68); `Pipeline.setAny`/`getAny` unannotated (:71, :75); KeelApiModule 15 + KeelEc2ApiModule 21 = 36, clouddriver 10, echo 1 as claimed (front50: 16 `addMixIn` calls over 8 files vs the claim's 14 — a scope difference) |
| CLAIM-S2-014 (ext.) | typing-census.md §4 | confirmed in substance; counts method-dependent | independent recount from endpoints.tsv (`r2_s2_014_keel_models.py`): 26 Keel types resolved, 20 data classes, 88 primary-constructor properties, 25 nullable (28 %); S2's models.json counts every `val`/`var`: 25 / 15 / 125 / 30 (24 %). Keel-only, roughly a quarter nullable, holds; the source is a derived table, so this is not counted as a refutation |
| CLAIM-S2-017 (ext.) | gate ManagedController.java:370; keel AdminController.kt:59; gate ClusterController.groovy:63 | confirmed | `@PostMapping(".../verifications/retry")` binds `@PathVariable("verificationId")` (:369-374); `forceConstraintReevaluation` binds `reference`, `version` on `/application/{application}/environment/{environment}/reevaluate` (:59-66); `getClusterLoadBalancers` binds `@PathVariable String applicationName` under class `@RequestMapping("/applications/{application}/clusters")` (:28, :63) |
| CLAIM-S2-020 (ext.) | endpoints.tsv `header_params` | confirmed | `X-RateLimit-App:optional` 45 (gate), `X-SPINNAKER-USER:required` 17 (keel), `headers:required` 3 (echo), `Accept`, `X-Hub-Signature`, `X-Event-Key` 1 each (gate) |
| CLAIM-S3-002 | GCS listing, 346 GETs | confirmed | listing 200, 834 keys, `IsTruncated=false`, 346 match `bom/x.y.z.yml`, 1.0.0…2026.3.0, 302 on 1.x, 44 CalVer (the remainder is 387 `master-<ts>`, 80 `release-1.NN.x-<ts>`, 17 `latest-(un)validated`, `io-codelab`, `mptv-prealpha` — the memo's description of it is incomplete, the count is right) |
| CLAIM-S3-005 | manifest GETs, no Authorization header | confirmed | gcr.io gate:1.19.0-20201012200017 → 200, `sha256:31fdb568e0b6…6635`; us-docker.pkg.dev clouddriver:5.95.0 → 200, `sha256:4db25c293d92…2e99` |
| CLAIM-S3-008 | `tags/list` on three registries | confirmed | gcr 4608, GAR 626, GHCR 514 (anonymous bearer from `ghcr.io/token`); gate:0.4.0-411 → 200 `sha256:4477cb5b8508…7f69` |
| CLAIM-S3-024 (R4 condition) | the ten Maven `-web` jars (S3/jars/) and the three unpacked images | confirmed | all ten jars major 61; `RuntimeVisibleAnnotations` on 9/10 … 333/333 classes, Spring-web annotation descriptors on 3–74 classes each, `Signature` on 4–148, `kotlin.Metadata` on 333/333 Keel classes; `MethodParameters` absent from every class of every jar, including gate-core/gate-web at 1.23.7 (major 55), orca-core/orca-web at 1.30.0 (major 55) and clouddriver-core/-web at 1.38.0 (major 61); `LocalVariableTable` present on ≥ 92 % |
| CLAIM-S4-002 | spinnaker.io 2025.0.0 changelog | confirmed | page: "Version 2025.0.0 is the first version of Spinnaker released from the monorepo. It's equivalent to version 1.38.0"; releases.tsv has 121 rows |
| CLAIM-S4-005 | spinnaker.io 1.29.0 changelog #orca | confirmed | sentence found verbatim |
| CLAIM-S4-008 | spinnaker.io 1.30.0 changelog | confirmed | sentence found (typographic apostrophe normalised, as CLAIM-S4-052 warns); the anchor exists |
| CLAIM-S5-002 | gus@main pkg/schema/loader.go:138 | confirmed | `if jsonContent, ok := op.RequestBody.Content["application/json"]; ok && jsonContent.Schema != nil` |
| CLAIM-S5-005 | loader.go:531 | confirmed | `object mixing named properties with an additionalProperties schema is not supported` |
| CLAIM-S5-008 | loader.go:498-507 | confirmed | `XProvides`/`XRequires`/`XAlias` are read only inside the properties loop (:499-507); declared at :220-222 and read nowhere else in the loader |
| CLAIM-S6-002 | orca@v8.64.0 KatoService.java:121-128 | confirmed | `requestId()` = sha256 of `"%s-%s-%s"` (stageId, stageStartTime, `Arrays.toString(payloadBytes)`) from `ExecutionContext.get()` (:121-129) |
| CLAIM-S6-005 | clouddriver@v5.95.0 OperationsController.groovy:238 | confirmed | `Optional.ofNullable(id).orElse(UUID.randomUUID().toString())` |
| CLAIM-S6-008 | orca@v8.64.0 KatoService.java:45-49 | confirmed | `retrySupport.retry(…, 3, Duration.ofSeconds(1), false)` (:45-49 and :54-58) |

Tally: S1 6 confirmed / 1 refuted; S2 6 confirmed (+1 in substance) / 1
refuted; S3 3/0 (+1); S4 3/0; S5 3/0; S6 3/0. **No report reaches two
refutations; none is rejected.** Two go back for a bounded redo:

* **S1** must add the kork-plugins `Front50Service` (three methods, conditional
  on `spinnaker.extensibility.repositories.front50.enabled`, up to ten callers)
  to `clients.md` and `edges.tsv` or list it as out of scope with the condition,
  correct CLAIM-S1-017, and fix the two counts (101 / 118).
* **S2** must re-deliver `endpoints.tsv` with the 16 rows of Igor's `build`
  package (stop pruning source directories named `build`), correct CLAIM-S2-003
  and the Igor line of CLAIM-S2-004, and re-derive the counts in
  `typing-census.md` that change (Igor's share, the `**` count, the total).

## R3 Decisions

Written into PLAN.md §4 in place; the changelog rows are in §6.

| decision | ruling | evidence that forces it |
|---|---|---|
| D1 reflection | **keep**, three extractor constraints added: `MethodParameters` is absent everywhere, so parameter names come from the annotation value, else `LocalVariableTable`, else the parameter is unnamed and flagged; the classpath is the `CLASSPATH=` line of `/opt/<svc>/bin/<svc>` (jar naming flips at the gcr.io/GAR boundary); shapes are read through each service's configured `ObjectMapper` (D7). A JDK 17 is needed; this machine has none | S3-020/021/022/023/024/028; R2 jar scan |
| D2 range and mesh | **revise**: nine services — Keel is pinned by no BOM and gets no invented pin (98 edge rows out of the first run); first run 1.30.0…1.38.0 (49 pairs, all images, one registry, Java 11→17); 1.0.0…1.23.7 (201 pairs) as the deep-history extension; 1.24.0…1.26.7 lost, 1.27.0…1.29.7 Maven-only and not mixed in; CalVer pairs excluded because every service moves in one monorepo commit; pairs in version order; Kayenta's absence before 1.7.0 is moot | S3-006/007/012/015/027; R1(c); BOM pins of 1.38.0 and 2025.x |
| D3 endpoint identity | **revise**: the R1 normalization becomes the rule (query strings, leading slash, variable/regex erasure, trailing slash, `**`, literal-fills-slot); an explicit hand table for provider dispatch slots (7 rows at 1.38.0); actuator and framework routes are outside the graph, not findings; census gaps are census defects; the residue (17 stale declarations) is the finding, and G3 drops those edges before loading because main.go:1097 makes them a hard error | S1-019; S2-021/023; S5-006/016; R1(a) |
| D4 presence | **revise**: `@JsonProperty(required=true)` leg dropped (zero occurrences); validation counts only under `@Valid`/`@Validated`; Kotlin non-null is Keel's signal and Keel is out, leaving Orca's two Kotlin types and Java primitives on the return side — report declared ≈ none as a corpus property; new rule: NON_NULL-serialised fields (global on the MVC mapper in Orca, Clouddriver, Keel, Kayenta; per-class elsewhere) are optional and not nullable on the return side | S2-012/013/014/015; S5-014/017/018/037; WebConfiguration.groovy:66, CloudDriverConfig.java:166, DefaultConfiguration.kt:73, KayentaConfiguration.java:136 |
| D5 openness | **revise**: typed maps are typed (they project to `types.Map` and are compared); `Object` → `{type: object, additionalProperties: true}`, never `{}`; Map-subclass models untyped; opaque returns contentless. Measured share 50.6 % (ten services) / 56.9 % (nine) under the revised definition — above 50 %, so §5's scoping applies; both-sides-untyped 4.9 %; the D5/§5 either-vs-both inconsistency is flagged for the owner | S5-007/032; S2-004/005/006; R1(b) |
| D6 parameters | **revise**: `{params, headers, body}` wrapper with the payload under `body`; contentless 200 on both sides for void/opaque/non-JSON responses; `Call<ResponseBody>` contentless; baked-in query pairs → `params` with `default`; catch-all query maps → open `params`, request side untyped; identities in parameters live inside `params`/`headers` | S5-001/002/003/005/008/025/048; S2-019/020/021 |
| D7 polymorphism | **revise**: the extractor drives each service's configured `ObjectMapper` (mixins, introspectors, modules); bean-registered subtypes are an accepted loss; discriminator a closed one-value enum per variant; `Id.CLASS` values are FQCNs; inheritance flattened because `allOf` is a hard load error | S2-008/009/010/011/016; S5-004/010/011/012/024/036 |
| D8 enums | **revise**: closedness per service and per direction — Orca's accept side open (its MVC mapper enables `READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`), every `FiatService` caller's expect side open and Rosco's Clouddriver client open (`READ_UNKNOWN_ENUM_VALUES_AS_NULL` in the client mappers), closed elsewhere; open side → `type: string`, closed side → closed `enum` | S5-013/058; S1-008; FiatAuthenticationConfig.java:61, rosco ServiceConfig.java:46, orca WebConfiguration.groovy:66 |
| D9 chains | **keep** out of the first run; the second run annotates the three chains that survive R1(e) (3, 4, 5) and the reduced Orca → Front50 leg of chain 2; chain 1 is deferred with Keel; response-minted identities and undeclared headers stay outside; G1 must carry caller-side parameters | S6-002…008, 049-052, 068-073; R1(e) |
| D10 ground truth | **keep** the rule; S4-019 does not count; 37 rows, 14 breaking; two independent labelers required (38 > 20); labels map to version-ordered pairs | S4-041/048/050; R1(d) |
| D11 consistency gate | **keep**; triage gains the categories "dispatch slot" and "census defect" | R1(a) |
| D12 not claimed | **revise**: add no Keel claim, no CalVer claim, and the §5 scoping — caller-drift (C2, C4, TGT) on the typed remainder only, because the untyped share exceeds 50 % | R1(b) |

The 50 % threshold and the eight-pair minimum are unchanged.

## R4 Verdict

| GO condition | status |
|---|---|
| reflection route confirmed on ≥ 1 artifact per service (S3 memo + own re-derivation) | **met** — CLAIM-S3-024 on all ten `-web` jars, re-derived by `r2_jarscan.py` on the same ten jars and three unpacked images; registry claims S3-005/008 re-derived |
| a proposed range of ≥ 8 consecutive BOM pairs | **met** — 1.30.0…1.38.0, 49 pairs (201 more in 1.0.0…1.23.7) |
| reconciled edges ≥ 90 % of resolved | **not met on the delivered census** — 88.2 % (88.0 % nine-service); 90.6 % once the 14 actuator rows are excluded; 92.7 % / 93.6 % after S2's mandated Igor repair (estimate). The shortfall is a census defect with a known fix, not a corpus property; G3 reconciles G1's own provider extraction, not S2's TSV |
| untyped share ≤ 50 % under D5 after R3 | **not met** — 50.6 % (ten services), 56.9 % (nine); §5 prescribes the scoping for this case |
| ≥ 1 ground-truth row of kind `breaking` surviving R1 | **met** — 14 (6 in range; 2 contract-visible) |
| no gaps.md row requiring a checker change without a cost | **met** |

**Verdict: SCOPED-GO.** The run gives up:

1. the pair-relation claims on untyped edges — the first run is scoped, per §5,
   to the caller-drift question (C2, C4, TGT) on the typed remainder (43 % of
   the nine-service reconciled edges; both-sides-untyped edges, 5.5 %, are kept
   in the graph and excluded from every claim), stated in the README before any
   number;
2. Keel — no BOM pins it; its 54 caller and 44 provider rows are out, and with
   them the corpus's only broad Kotlin-nullability signal and chain 1;
3. CalVer pairs (2025.0.0 onward) — one monorepo commit per BOM;
4. chains (D9, as planned) — three survivors for a second run;
5. the 17 stale caller declarations — reported as findings, not checked;
6. the *declared* presence profile as a distinct result — on the nine-service
   mesh it collapses onto *none* except for Java primitives on the return side,
   Kayenta's `@Valid`-gated validation and Orca's two Kotlin types;
7. the 1.24.0…1.29.7 window — unrecoverable (24 releases) or Maven-only (26).

Precondition before G3's reconciliation step is read as a number: S2's
re-delivered `endpoints.tsv` (Igor's `build` package) and S1's kork-plugins
addendum. G1 and G2 do not depend on either and start now.

### First task for G1 (extractor)

Inputs: a directory holding one service's runtime classpath as G2 lays it out —
`bin/<svc>` (the start script) and `lib/*.jar` — plus the service name; a JDK 17
(portable, unpacked under `experiments/spinnaker/`; none is installed here).
Output: one OpenAPI 3 YAML document per service per BOM version.

First task — provider side of one service, Front50 at 2.41.0 (image
`us-docker.pkg.dev/spinnaker-community/docker/front50:2.41.0`, digest in
`scout/S3/boms.tsv`): build the class loader from the jars in the order of the
`CLASSPATH=` line in `bin/front50` (never from file names — they are unversioned
before 1.28); find classes carrying `@RestController`/`@Controller`; for each
Spring mapping (class prefix + method path, leading slash forced, several paths
or methods → several endpoints, `consumes`/`produces` inherited) emit path,
method, and the request object `{properties: {params, headers, body}}`:
`params.<name>` for every `@PathVariable` (required) and `@RequestParam`
(required unless `required=false` or `defaultValue`, which emits `default:`;
a catch-all `Map`/`MultiValueMap` makes `params` an open object), `headers.<name>`
for `@RequestHeader`, the `@RequestBody` type under `body` (JSON only; multipart
→ no body); the response as the lowest 2xx (`@ResponseStatus` or 200) with the
return type unwrapped from `ResponseEntity`/`HttpEntity`/`DeferredResult`/
`Callable`/`Optional`, and a contentless `200` for `void`, `Void`, `byte[]`,
`StreamingResponseBody` and non-JSON `produces`. Schemas come from
jsonschema-generator with the Jackson and Kotlin modules configured from the
service's own `ObjectMapper`: instantiate the service's Jackson modules found on
the classpath (for Front50: `Front50ApiModule` with `PipelineMixins`/
`TimestampedMixins`) and read mixins, introspectors and subtypes through it.
Conventions from R3: inheritance flattened (no `allOf`); `Object`/`JsonNode`/
raw types → `{type: object, additionalProperties: true}`, never `{}`;
`Map<String,X>` → `additionalProperties: <X>`; Map-subclass models
(`PipelineTemplate`, `Notification`) → open object with their declared
properties and `additionalProperties: true`; `@JsonTypeInfo` → `oneOf` with a
one-value closed `enum` discriminator per variant; NON_NULL-inclusion fields
optional and not nullable on the return side; Kotlin `T?`/`@Nullable` →
`nullable: true`; enums closed unless the service's mapper on that side is
listed open in D8; property names from `@JsonProperty`; `@JsonIgnore` dropped;
`@JsonAnySetter` → `additionalProperties: true`; parameter names from the
annotation value, else `LocalVariableTable`, else flag the endpoint.
Acceptance: `gus` loads the document without error; the endpoint set equals
S2's 90 Front50 rows on (method, normalized path); golden YAML matches for
`GET /pipelines` (five optional query params, two with `default`; return
`array` of an open `Pipeline` object), `PATCH /v2/applications/{applicationName}`
(required path param, `Application` body and return), `GET /pipelineTemplates/{id}`
(Map subclass → open object), `POST /pluginBinaries/…` (multipart → no body;
`ResponseEntity<byte[]>` → contentless), and one `@JsonInclude(NON_NULL)` field
projected optional and non-nullable. Second task, same service: Retrofit
interfaces → `x-role: client` endpoints under `/_calls/<provider><path>` with
`@Path`/`@Query`/`@Header` folded into `params`/`headers`, the provider taken
from `scout/S1/tools/mesh.tsv`, `Call<T>` unwrapped, `Call<ResponseBody>`/
`Response`/`Void` contentless, baked-in query strings split into `params` with
`default`, relative paths given a leading slash.

### First task for G2 (fetcher)

Inputs: a BOM version. Outputs: `corpus/<bom>/<svc>/{bin/<svc>, lib/*.jar}` and
`corpus.lock`. First task — BOM 1.38.0: GET
`https://storage.googleapis.com/halconfig/bom/1.38.0.yml`, parse the nine
`services.<svc>.version` entries (keys may be quoted; ignore `deck`,
`monitoring-*`, `defaultArtifact`, `spinnaker`), resolve each to a manifest on
`us-docker.pkg.dev/spinnaker-community/docker/<svc>:<version>` (fall back to
`gcr.io/spinnaker-marketplace` for < 1.28 and `ghcr.io/spinnaker` for
2026.1.0+, whose anonymous bearer token comes from `ghcr.io/token`; `HEAD` is
405 on the Google registries — use `GET`); accept the three manifest shapes
(v2 manifest, v2 manifest list, OCI index with `unknown/unknown` attestation
children) and select `linux/amd64`; pull only the layer whose tar contains
`opt/<svc>/bin/<svc>` (one `COPY` layer per image, 42–70 % of the compressed
bytes), verify `sha256(blob) == digest`, extract `opt/<svc>/bin/<svc>` and
`opt/<svc>/lib/*.jar`; write the `CLASSPATH=` line's ordered jar list and the
sha256 of every extracted jar, the manifest and layer digests, and the BOM's
`timestamp` into `corpus.lock`. Acceptance: two runs yield a byte-identical
`corpus.lock`; the manifest digests equal those recorded in `scout/S3/boms.tsv`
(clouddriver:5.95.0 `sha256:4db25c29…`); Gate's classpath lists
`gate-web-6.69.0.jar` first after `config`; then the same on 1.30.0 (orca:8.31.0
is a manifest list; amd64 child `sha256:8e6f2a13…`), and the run over
1.30.0…1.38.0 (50 BOMs, ≈ 30 GB compressed if pulled whole, far less with the
single-layer pull) completes without a credential.

### First task for G3 (projection and harness)

Inputs: G1's documents for the nine services at each BOM of 1.30.0…1.38.0,
`scout/S1/tools/mesh.tsv` (interface → provider), `scout/review/r1a_unmatched.tsv`
(the categorised residue at 1.38.0), S4's labelled rows. Outputs: `graph.yaml`,
one scenario per consecutive pair in version order (all edges, per service, per
pair of services), `run.sh`, `compare.py`, and a triage file per `gus consistent`
failure. First task — `normalize.py` and the 1.38.0 baseline: reproduce the D3
rules of `scout/review/r1ab_reconcile.py` on G1's output (query-string strip,
leading slash, variable/regex erasure, trailing slash, `**`, literal-fills-slot,
`ANY`), apply the hand table for the seven dispatch rows (expand each to one edge
per concrete provider controller), drop the actuator/framework rows
(`/health`, `/installedPlugins`, `/graphql`) and the stale declarations from the
graph and write both lists with their categories to `unmatched.tsv`; build
`graph.yaml` for the nine services; run `gus consistent` on the 1.38.0 baseline
and triage every failure as projection defect (back to G1), normalization defect
(D3 table), or real inconsistency (kept, reported, pair skipped). Acceptance: the
matched share over resolved edges at 1.38.0 is ≥ 90 % after the actuator rows
are excluded and the dispatch table applied (the review's estimate is 96 %); the
untyped share is recomputed on G1's output with the D5 definition stated and
reported next to the review's 50.6 % / 56.9 %; `gus consistent` passes or every
failure has a triage entry; `compare.py` maps each S4 row to the version-ordered
pair (`1.N.x → 1.M.0` is the pair (last 1.N patch, 1.M.0)), treats unlabelled
pairs as unlabelled, and keeps S4-019 out. The README states the lossy steps
first: the §5 scoping, Keel, CalVer, presence, and the stale declarations.


## Review pass 2 (2026-09-12) — after the S1 and S2 redos

Scope: the two bounded redos of 2026-09-11. The other four reports are
unchanged and were not re-sampled. Scripts re-run in place; new script
`r1b_legs.py` computes the D5 ruling of 2026-09-11 (untyped only when both
sides of both legs are untyped) and its consequences.

**R0.** Both redos pass. S1 appends CLAIM-S1-021…033 under "## Redo" and keeps
"What I could not verify" last (with a subsection on what the redo left open);
`edges.tsv` grows from 534 to 564 rows — the kork-plugins `Front50Service` (3
methods × 10 callers, `resolved_by` carrying the enabling condition), a pure
addition. S2 appends CLAIM-S2-026…037; `endpoints.tsv` grows from 732 to 748
rows — Igor's 16 — with the extraction scripts now beside the report and a
pruning audit (CLAIM-S2-028: no other name-based prune cost a row at these tags).

**R1.** (a) 564 edges, 563 resolved, **524 matched = 93.1 %** (95.5 % excluding
the 14 actuator rows). The 39 unmatched are the 14 actuator routes, 7 provider
dispatch slots, 1 framework route and the 17 stale caller declarations; the
census-gap class is gone. `r2_s2_coverage.py`: 0 missing controllers, 0 missing
mappings. Per provider: clouddriver 142/152, echo 14/17, fiat 64/65, front50
142/150, igor 57/63, kayenta 18/18, keel 36/44, orca 42/44, rosco 9/10.
(b) Under the owner's ruling, with typed maps typed: **4 of 524 edges (0.8 %)**
are untyped (6, 1.1 %, under the original classifier). Legs: **259 of 1048
live (24.7 %)**, 198 vacuous (18.9 %), the rest contentless on at least one
side; 299 edges (57 %) have no live leg, 225 have at least one, and the
edge-level either-side reference is now 50.0 % as written / 47.7 % refined.
(c), (d), (f) unchanged. (e) chains 3, 4, 5 pass; 1, 2 and the alternate fail
where they did.

**R2.** Seven re-derivations of redo claims, all confirmed (table in
`review.json` → `pass2.R2`): the kork interface and its three methods at
v7.254.0; no shipped profile sets `spinnaker.extensibility`; the 30-row
addition; the three self-edge rows; Igor's controller lines; the 748/51 counts;
the coverage result. No refutation, nothing sent back.

**R3.** D3 gains one rule: self-edges (caller = provider; the three
`front50 → front50` plugin rows) are dropped from `graph.yaml` by G3 — both
sides move in one commit, so they cannot carry cross-version drift. D5's
numbers under the ruling are recorded above; G1 must mark every untyped side
(`x-untyped: true`) so that G3 can classify legs without re-deriving Java
types. D12: the §5 scoping is lifted; every figure is reported over live legs
with the vacuous share beside it. Three decisions are the owner's, not the
review's: whether the 30 operator-enabled kork rows and the 36 indirect Fiat
rows enter the graph, and whether the near-empty *declared* presence profile
is kept as a control or dropped.

**R4. Verdict: GO.** All six conditions are met: reflection route confirmed;
49 pairs; 93.1 % reconciled; 0.8 % untyped under the ruling in force; 14
breaking rows; every checker-change row costed. Still given up, unchanged from
pass 1: Keel, CalVer pairs, chains in the first run (second run: 3, 4, 5), the
17 stale declarations (findings, not checks), the declared presence profile as
a distinct result, and releases 1.24.0–1.29.7. The quality statement the
README must lead with: pair-relation evidence exists on a quarter of the legs
at 1.38.0, and 57 % of edges have no live leg at all. The first tasks for
G1–G3 above stand; the handoff documents under `handoff/` carry them with
these updates.


## Review pass 3 (2026-09-12) — G1 and G2

**G1, the extractor: accepted.** `tools/accept.sh` reproduces in 53 s: 24
unit tests; six documents (three services at both ends of the range) extract
in about five seconds each with no flagged endpoint; provider endpoints equal
S2's census on `x-match-key` (front50 90/90, gate 273/273 plus four `ANY`
expansions, orca 45/45 plus two); caller endpoints equal S1's edges (13/13,
241/241, 133/133); the five golden fragments match; `gus` loads all six and
`gus consistent` returns YES on each. The D11 triage over a real pair (orca
and front50, 1.30.0 to 1.38.0, 26 edges) leaves six baseline findings: four
`presence-mismatch` from Retrofit-1 callers declaring `Response`/`Void`
against providers that return a body (marked `x-response-opaque`; D6's
"contentless on both sides" is G3's to apply), and two `REQ.2` on the kork
`pinVersions` client, which leave with the owner's ruling. Seven things G1
found that the rules did not cover are recorded in `review.json` → `pass3`
and carried into the G3 handoff: path spelling versus `x-match-key`, the
`ANY` expansion, same-key collisions, opaque responses, the single recursive
component, provenance-based exclusion of framework routes, and unapplied
validation. What G1 could not verify stands as the projection's largest
open risk: custom `JsonSerializer`s make the declared type differ from the
wire type and nothing static detects it; six of nine services and 48 of 50
BOMs were never extracted.

**G2, the fetcher: accepted.** 38 tests pass; `verify.py` finds 450 of 450
manifest digests equal to S3's, no classpath/jar-set disagreement, and the
two staged BOMs intact; the corpus of record on the external volume (50 BOMs,
198 492 jars, 100.4 GiB) was written by an independent full re-fetch whose
regenerated lock is byte-identical. Three corrections to the plan's guidance
are recorded (HEAD semantics, the jar-naming boundary, the variable app-layer
index). `corpus.lock` is 47 MiB in one file as asked; a per-BOM split is a
few lines if the repository size matters.

**Owner's rulings applied** (PLAN.md §4, changelog): kork rows out, indirect
Fiat rows out, the *declared* profile kept as a near-empty control, claims as
scoped, build proceeds. No further decision is required before G3.
