# S2 — provider surface: what the ten Spinnaker services expose

Deliverables: `endpoints.tsv` (748 rows after the redo of 2026-09-11 below; 732 as
first delivered; header exactly as the plan specifies), `typing-census.md`, this
memo, and the scripts that produce them (`extract.py`, `emit.py`, `census.py`,
`models.py`, `audit_prune.py`). Row-level claims live in the TSV's `claim` column
in their own namespace (`CLAIM-S2-R0001` … `CLAIM-S2-R0748`), each carrying
`source:spinnaker/<repo>@<tag> <path>:<line>`. The numbered claims below are the
memo's own. In their sources, `…` abbreviates
`src/main/{java,groovy,kotlin}/com/netflix/spinnaker/<service>` (for Kayenta,
`src/main/java/com/netflix/kayenta`), so `front50-web/…/controllers/X.java`
expands to
`front50-web/…/controllers/X.java`.

**Method.** Shallow clone of each repository at its latest release tag, then
source parsing of every file carrying `@RestController` or `@Controller` — a
comment- and string-masked scanner over Java, Groovy and Kotlin, with class-level
`@RequestMapping` prefixes, `consumes`/`produces` and `@Deprecated` inherited by
the methods inside the class body. Nothing was built. This departs from the plan's
D1 default (reflection over artifacts) because the brief scoped me to grep and
reading; "What I could not verify" says what that costs.

---

CLAIM-S2-001: The trees read were gate v6.69.0 `1af7f70a`, orca v8.64.0
`2fdb327a`, clouddriver v5.95.0 `5e0ce2ab`, front50 v2.41.0 `ceda49e0`, echo
v2.47.2 `38c2df6d`, igor v4.22.0 `627ec479`, fiat v1.57.0 `1c7fb38c`, rosco
v1.26.0 `0ae53eb0`, kayenta v2.46.0 `a69573be`, keel v1.4.1 `1aa96698` — each the
highest `vN.N.N` tag on the GitHub remote on 2026-09-11. kork v7.254.0 `a7b6fdea`
was cloned for type resolution only and contributes no rows. source:
`git ls-remote --tags` then `git clone --depth 1 --branch <tag>` for each of
spinnaker/{gate,orca,clouddriver,front50,echo,igor,fiat,rosco,kayenta,keel,kork};
the tag alone pins the tree, and each short SHA above is the tag's commit.

CLAIM-S2-002: Front50's `PipelineController.list` answers `GET /pipelines` with
`Collection<Pipeline>` and five optional query parameters — `restricted`,
`refresh` (both `defaultValue = "true"`), `enabledPipelines`, `enabledTriggers`,
`triggerTypes`. source: spinnaker/front50@v2.41.0
front50-web/…/controllers/PipelineController.java:109

CLAIM-S2-003: The ten services expose 732 endpoints (one row per HTTP-method ×
path-template pair, from 726 mapping-annotation sites) across 221 controller files;
228 files carry `@RestController`/`@Controller`. Gate 278, clouddriver 130,
front50 90, keel 59, orca 48, kayenta 48, igor 35, fiat 16, echo 14, rosco 14.
Coverage is complete: re-scanning for mapping annotations absent from the output
leaves zero unmatched once class-level ones are excluded. source: `endpoints.tsv`,
derived from the trees of CLAIM-S2-001

CLAIM-S2-004: 305 of 732 endpoints (41.7%) are untyped on at least one side under
D5 — below the plan's 50% threshold, but very unevenly: gate 195/278 (70%),
kayenta 19/48 (40%), rosco 5/14 (36%), orca 17/48 (35%), igor 9/35 (26%),
clouddriver 33/130 (25%), front50 19/90 (21%), echo 2/14 (14%), keel 5/59 (8%),
fiat 1/16 (6%). Excluding Gate: 110/454 (24%). source: `typing-census.md` §1.1

CLAIM-S2-005: Front50's `PipelineTemplate` — request body or return type of nine
Front50 endpoints — is a `Map` subclass, not a bean: `public class
PipelineTemplate extends HashMap<String, Object> implements Timestamped`. An
endpoint naming it is untyped exactly as a `Map` is. source:
spinnaker/front50@v2.41.0
front50-core/…/model/pipeline/PipelineTemplate.java:29

CLAIM-S2-006: Front50's `Notification` is the second such case — `extends
HashMap<String, Object> implements Timestamped` — and it is the class
`NotificationController` imports, not the same-named `front50.echo.Notification`
bean. source: spinnaker/front50@v2.41.0
front50-core/…/model/notification/Notification.java:7
and front50-web/…/controllers/NotificationController.java:8

CLAIM-S2-007: Gate is the untyped outlier because it forwards: 157 of its 278
endpoints return an untyped shape (86 a bare `Map`, 34 a `List<Map>`) and 30 more
a raw Groovy `List`. No Gate endpoint reaches a `@JsonTypeInfo`. source:
`typing-census.md` §1.2

CLAIM-S2-008: Keel declares polymorphism for six model types with **no annotation
anywhere on the type** — `Constraint`, `ConstraintStateAttributes`,
`DeliveryArtifact`, `SortingStrategy`, `Verification`, `PostDeployAction` — via
`KeelApiAnnotationIntrospector.findTypeResolver`, which synthesises a
`StdTypeResolverBuilder(Id.NAME, As.EXISTING_PROPERTY, property = "type")` for
exactly those classes. Ten of Keel's fourteen polymorphic endpoints are
polymorphic only through this path. source: spinnaker/keel@v1.4.1
keel-core/…/jackson/KeelApiModule.kt:104

CLAIM-S2-009: Keel's second mechanism, equally invisible on the model class, is
Jackson mixins: `KeelApiModule.setupModule` binds 15 (e.g.
`setMixInAnnotations<ResourceSpec, ResourceSpecMixin>()`, line 77;
`<DeliveryConfig, DeliveryConfigMixin>()`, line 70) and `KeelEc2ApiModule` binds
21. Three of those mixin classes carry the `@JsonTypeInfo`
(`ClusterDeployStrategyMixin`, `ActionMixin`, `InstanceProviderMixin`); neither
`ResourceSpec` nor `DeliveryConfig` carries one itself. source:
spinnaker/keel@v1.4.1
keel-core/…/jackson/KeelApiModule.kt:67-81
and keel-core/…/jackson/mixins/ClusterDeployStrategyMixin.kt:15

CLAIM-S2-010: Clouddriver's whole polymorphic surface is mixin-declared too, in
the Java form `context.setMixInAnnotations(SecurityGroup.class,
SecurityGroupMixin.class)`. `SecurityGroupMixin`, `RuleMixin` and
`CredentialsDefinitionMixin` carry the `@JsonTypeInfo` and make exactly five
endpoints polymorphic: `GET /credentials/type/{accountType}`, `POST /credentials`,
`PUT /credentials`, `PUT /credentials/{accountName}`, and `GET
/securityGroups/{account}/{cloudProvider}/{region}/{securityGroupNameOrId:.+}`.
source: spinnaker/clouddriver@v5.95.0
clouddriver-core/…/jackson/ClouddriverApiModule.java:36
and clouddriver-core/…/jackson/AccountDefinitionModule.java:45

CLAIM-S2-011: The same indirection hides Front50's openness: `Pipeline`'s
`@JsonAnySetter`/`@JsonAnyGetter` overflow bucket is declared on the mixin
`PipelineMixins` (lines 32, 35), bound by `.addMixIn(Pipeline.class,
PipelineMixins.class)`; `Pipeline.setAny`/`getAny` carry no annotation. Mixin
registrations per service: keel 36, front50 14, clouddriver 10, echo 1, others
zero. source: spinnaker/front50@v2.41.0
front50-core/…/jackson/mixins/PipelineMixins.java:32
and front50-s3/…/model/S3StorageService.java:68

CLAIM-S2-012: `@JsonProperty(required = true)` occurs **zero** times in all ten
repositories at these tags, tests included, and zero times in kork. No Jackson
annotation in the mesh sets `required = true`, so D4's *declared* presence profile
gets nothing from Jackson. source:
`rg -U '@JsonProperty\s*\([^)]*required\s*=\s*true'` over the trees of
CLAIM-S2-001 — no matches

CLAIM-S2-013: Bean validation is `javax.validation` only — 162 import occurrences
(kayenta 90, igor 22, orca 16, echo 16, clouddriver 10, fiat 4, front50 3, gate 1;
rosco and keel zero) — and `jakarta.validation` occurs zero times in any of the
ten. An extractor keyed on `jakarta` finds nothing at these tags. source:
`rg 'import javax\.validation'` / `rg 'import jakarta\.validation'` over the trees
of CLAIM-S2-001

CLAIM-S2-014: Kotlin nullability is the only broad presence signal, and Keel's
alone: of the 25 model types Keel's signatures name, 15 are `data class`es and
their 125 declared properties are 30 nullable (`T?`), 95 non-null. Orca adds 2
Kotlin model types (6 properties, 2 nullable); no other service names a Kotlin
type in a controller signature. source: `typing-census.md` §4

CLAIM-S2-015: Validation annotations concentrate in Kayenta — 14 of the 18 model
classes its endpoints name carry `@NotNull`/`@NotEmpty`/`@Size`/`@Valid`, against
one class each in Front50 and Echo and none anywhere else. source:
`typing-census.md` §4

CLAIM-S2-016: Kayenta's polymorphism is annotation-declared and two hops from the
signature: `@JsonTypeInfo(use = Id.NAME, include = As.PROPERTY, property =
"type")` sits on the `CanaryMetricSetQueryConfig` interface, reached as
`CanaryConfig → CanaryMetricConfig → CanaryMetricSetQueryConfig` from twelve
Kayenta endpoints — every polymorphic endpoint Kayenta has. source:
spinnaker/kayenta@v2.46.0
kayenta-core/…/canary/CanaryMetricSetQueryConfig.java:23

CLAIM-S2-017: Three endpoints bind an `@PathVariable` their own template does not
contain — a provider-side defect a checker could catch. Gate's
`ManagedController.retryVerification` maps
`/{application}/environment/{environment}/verifications/retry` and binds
`@PathVariable("verificationId")`; Keel's
`AdminController.forceConstraintReevaluation` maps
`/application/{application}/environment/{environment}/reevaluate` and binds
`@PathVariable("reference")` and `@PathVariable("version")`; Gate's
`ClusterController.getClusterLoadBalancers` binds `@PathVariable String
applicationName` under the class prefix `/applications/{application}/clusters`.
source: spinnaker/gate@v6.69.0
gate-web/…/controllers/ManagedController.java:370;
spinnaker/keel@v1.4.1
keel-web/…/rest/AdminController.kt:59;
spinnaker/gate@v6.69.0
gate-web/…/controllers/ClusterController.groovy:63

CLAIM-S2-018: The converse also occurs: Gate's
`PipelineController.evaluateVariables` maps
`POST /pipelines/{id}/evaluateVariables` but binds no `@PathVariable` for `{id}`,
taking a required `@RequestParam("executionId")` instead. source:
spinnaker/gate@v6.69.0
gate-web/…/controllers/PipelineController.groovy:390

CLAIM-S2-019: Response status is declared on 64 of 732 endpoints (9%) — `202`×28,
`200`×18, `204`×13, `400`×6, `201`×4, `404`×3, `410`×2, `500`×1, `401`×1 — and
content types on 104 of 732 (14%); the rest take Spring's implicit 200 and the
global Jackson converter. source: `endpoints.tsv`, columns `response_codes`,
`content_types`

CLAIM-S2-020: Header parameters are two conventions plus noise: `X-RateLimit-App`
(optional) on 45 Gate endpoints, `X-SPINNAKER-USER` (required) on 17 Keel
endpoints, a whole-`HttpHeaders` bind on Echo's three webhooks, and three one-offs
in Gate (`Accept`, `X-Hub-Signature`, `X-Event-Key`). source: `endpoints.tsv`,
column `header_params`

CLAIM-S2-021: 261 endpoints take query parameters; 22 of them bind a catch-all
`Map<String,String>`/`MultiValueMap` instead of named parameters (Gate's
`ProxyController`, `ApiExtensionController`, both `CloudMetricController`s, Gate's
two managed reports, Gate's `/v1/data/static/{id}`) and so cannot be projected as
named parameters under D6. source: `endpoints.tsv`, column `query_params`

CLAIM-S2-022: 15 endpoints are `@Deprecated`, all in Gate (12, including the whole
classes `SecurityGroupController` and `StorageAccountController`) and Clouddriver
(3: `OperationsController.operations`, `OperationsController.operation`,
`VpcController.list`). No other service deprecates an endpoint at these tags.
source: `endpoints.tsv` (`[deprecated]` suffix); spinnaker/clouddriver@v5.95.0
clouddriver-web/…/controllers/OperationsController.groovy:68

CLAIM-S2-023: 76 endpoints carry a `/vN` path segment (gate `/v2`×28, `/v3`×5,
`/v1`×2; front50 `/v2`×28; rosco `/api/v1`×8, `/api/v2`×1; clouddriver `/v1`×2;
orca `/v2`×2) and 15 use an Ant `**` wildcard (gate 10, clouddriver 3, front50 2),
including Gate's four `ProxyController` methods on `/proxies/{proxy}/**` — which
D3 path unification has no template to match. Echo, igor, fiat, kayenta and keel
version nothing in the path. source: `endpoints.tsv`, column `path_template`

CLAIM-S2-024: The mesh is pure Spring MVC (servlet): no `RouterFunction` in any of
the ten repositories, and no controller returns `Mono`, `Flux` or
`DeferredResult`. 28 endpoints wrap in `ResponseEntity` (gate 15, clouddriver 5,
echo 2, kayenta 2, front50 1, igor 1) and 2 in `HttpEntity` (gate); eight of the
30 are raw and count untyped on the return side. source:
`rg 'RouterFunction|Mono<|Flux<|DeferredResult'` over the trees of CLAIM-S2-001;
`endpoints.tsv`, column `return_type`

CLAIM-S2-025: Controller language splits 116 Java / 81 Groovy / 24 Kotlin files —
Front50, Fiat and Kayenta pure Java, Keel pure Kotlin, Gate (26/41/6) and
Clouddriver (28/28/2) mixed — so any extractor for this corpus handles all three.
source: `typing-census.md` §2

---

## Redo (2026-09-11)

The review pass refuted CLAIM-S2-003 (`scout/review.md`, R2): the extractor pruned
every directory named `build`, which dropped Igor's source package
`com.netflix.spinnaker.igor.build`. This section is the bounded redo it asked for.
The 25 claims above are left exactly as delivered; every correction is a new
numbered claim here, and the scripts that produce the table are now in this
directory (`extract.py`, `emit.py`, `census.py`, `models.py`, `audit_prune.py`).

Re-run as:

    SPINNAKER_CLONES=<the ten clones> S2_OUT=<work dir> python3 extract.py
    SPINNAKER_CLONES=... S2_OUT=... python3 emit.py --stable-from endpoints.tsv <work dir>/endpoints.tsv
    SPINNAKER_CLONES=... S2_OUT=... python3 census.py && python3 models.py

CLAIM-S2-026: The pre-fix pipeline, re-run over the same ten clones, reproduces
the delivered table byte for byte — 732 rows, md5
`eb593cf8ec7d2f6571dd3d11dc3439fd` — so the only difference in the new table is
the fix below, and the before/after diff is exact. source: the delivered
`endpoints.tsv` of 2026-09-11 against a re-run of `extract.py`+`emit.py` as
delivered, over the clones of CLAIM-S2-001 (tags re-checked with
`git describe --tags`)

CLAIM-S2-027: The defect was name-based pruning in all three of the extractor's
walks — `dirnames[:] = [d for d in dirnames if d not in ('.git', 'build',
'node_modules')]` in the main walk and the mixin-map walk, with `'test'` added in
the type-index walk. It is replaced by a content test: a directory is Gradle
output only when it is named `build` **and** holds `classes/`, `libs/`, `tmp/` or
`generated/` (`is_gradle_output`, `prune`), and a file is test source only when it
sits in a Gradle test source set (`src/test`, `src/integration`, `src/integTest`,
`src/integrationTest`, `src/functionalTest`, `src/testFixtures`,
`src/compatibility` — `in_test_source_set`). No directory is skipped for its name
alone. source: scout/S2/extract.py:19-45 (the pruning block), :466-467, :536-537,
:983-984 (the three walks); the delivered version pruned at its lines 433, 502 and
949 (the line the review quotes)

CLAIM-S2-028: The audit of every other name, over the ten clones of
CLAIM-S2-001, finds one more instance of the same class of mistake and no more
lost rows. (a) `out`, `target`, `generated`, `bin` and `node_modules`: **zero**
directories of those names exist anywhere in the ten clones — only `node_modules`
was ever in the prune list, and none of them could have dropped anything. (b)
`build`: six directories, **all six source packages** — `echo-core/src/main/java/
com/netflix/spinnaker/echo/build`, `igor-core/src/{main/java,test/groovy}/…/igor/
build`, `igor-web/src/{main/groovy,main/java,test/groovy}/…/igor/build`; none
holds a Gradle output marker and none has a Gradle build script beside it, so in
these clones *no* directory named `build` is output and the prune only ever
removed source: 26 files, 19 of them under `src/main`, two of them controllers.
(c) `test`: 191 directories, 15 under a `src/main` tree (the `-tck`, `-test` and
`test-support` modules); the by-name prune and the `'/test/' in dirpath` skip
removed 32 `src/main` files, **none** of which carries
`@RestController`/`@Controller` with a method-level mapping — the same mistake,
but it costs no endpoint row at these tags, which the re-run confirms (the fixed
run differs from the delivered one in Igor's 16 rows and nothing else). source:
`scout/S2/audit_prune.py` over the clones of CLAIM-S2-001; the row-level diff of
CLAIM-S2-029

CLAIM-S2-029: The 16 recovered rows are Igor's `BuildController.groovy` (12
method-level mappings at lines 101, 111, 121, 137, 150, 157, 166, 177, 216, 234,
335, 353 — `/builds/status|artifacts|queue|all|properties/…`, `PUT /masters/{name}/
jobs/{jobName}/stop/{queuedBuild}/{buildNumber}`, `PUT /masters/{master}/jobs/stop/
{queuedBuild}/{buildNumber}`, `PATCH /masters/{name}/jobs/**/update/{buildNumber}`,
`PUT /masters/{name}/jobs/**`) and `InfoController.groovy` (4 at lines 56, 69, 80,
116 — `GET /masters`, `GET /buildServices`, `GET /jobs/{master:.+}`,
`/jobs/{master:.+}/**`). No row was removed and no other row changed in any
column. source: spinnaker/igor@v4.22.0 igor-web/src/main/groovy/com/netflix/
spinnaker/igor/build/BuildController.groovy:59 and InfoController.groovy:43 (the
`@RestController` sites); rows CLAIM-S2-R0733…R0748 of `endpoints.tsv`

CLAIM-S2-030: (corrects CLAIM-S2-003) The ten services expose **748** endpoints
(one row per HTTP-method × path-template pair, from 742 mapping-annotation sites)
across **223** controller files; **230** files carry
`@RestController`/`@Controller`. Gate 278, clouddriver 130, front50 90, keel 59,
**igor 51**, orca 48, kayenta 48, fiat 16, echo 14, rosco 14. The "coverage is
complete" sentence of CLAIM-S2-003 was false for Igor and is now true under the
review's own check (CLAIM-S2-037). source: `endpoints.tsv` (748 rows), derived
from the trees of CLAIM-S2-001

CLAIM-S2-031: (corrects the Igor line of CLAIM-S2-004) **310 of 748 endpoints
(41.4%)** are untyped on at least one side under D5 — igor **14/51 (27%)**, not
9/35 (26%). The other nine services are unchanged: gate 195/278 (70%), kayenta
19/48 (40%), rosco 5/14 (36%), orca 17/48 (35%), clouddriver 33/130 (25%), front50
19/90 (21%), echo 2/14 (14%), keel 5/59 (8%), fiat 1/16 (6%). Excluding Gate:
115/470 (24%). Igor's five new untyped rows are `Object` ×2
(`/builds/queue/{master}/{item}`, `/jobs/{master:.+}/**`), `Map<String,Object>` ×2
(the two `/builds/properties/…`) and `List<Object>` ×1 (`/builds/all/{master:.+}/
**`); the other eleven are typed — `GenericBuild` ×2, `List<Artifact>` ×2,
`List<String>` ×2, `String` ×3, `List<BuildService>` ×1 and the `void` return of
`PATCH …/update/{buildNumber}` whose body is `UpdatedBuild`. source:
`typing-census.md` §1.1 and §1.2, recomputed by `census.py` over the 748 rows

CLAIM-S2-032: (corrects CLAIM-S2-023) **22** endpoints use an Ant `**` wildcard,
not 15 — gate 10, **igor 7**, clouddriver 3, front50 2. Igor's seven are
`/builds/status/{buildNumber}/{master:.+}/**`,
`/builds/artifacts/{buildNumber}/{master:.+}/**`, `/builds/all/{master:.+}/**`,
`/builds/properties/{buildNumber}/{fileName}/{master:.+}/**`, `/jobs/{master:.+}/
**`, `PUT /masters/{name}/jobs/**` and `PATCH /masters/{name}/jobs/**/update/
{buildNumber}`. The review's R2 row estimates 21; the seventh is the `PATCH`,
whose wildcard is **medial**, not a suffix — D3's wording ("a provider `**`
matches any suffix") does not describe it, though `r1ab_reconcile.py` matches it
correctly because it compiles `**` to `.*` inside a path regex. The `/vN` half of
CLAIM-S2-023 is unchanged at 76 (Igor versions nothing in the path). source:
`endpoints.tsv`, column `path_template`

CLAIM-S2-033: The other published counts that move, all recomputed from
`endpoints.tsv`: query parameters on **267** of 748 endpoints (was 261 of 732) and
**23** catch-all `Map<String,String>`/`MultiValueMap` binders (was 22; the new one
is Igor's `PUT /masters/{name}/jobs/**`) — CLAIM-S2-021; response codes declared on
**65** of 748, `202` ×29 (was 64, `202` ×28; the new one is `BuildController.build`)
and content types unchanged at 104 — CLAIM-S2-019; controller files **223** with
**116** Java / **83** Groovy / **24** Kotlin (was 221 / 116 / 81 / 24) —
CLAIM-S2-025; `void` returns 131 (was 130) and endpoints with no request body 579
(was 565). Unchanged: the 15 deprecated endpoints (CLAIM-S2-022), the header
conventions (CLAIM-S2-020), the 33 `polymorphic` rows and 35 endpoints reaching a
`@JsonTypeInfo` (CLAIM-S2-008…011, S2-016), and Gate's untyped profile
(CLAIM-S2-007). source: `endpoints.tsv`; `typing-census.md` §2

CLAIM-S2-034: In the model census (`typing-census.md` §3 and §4) only Igor's row
moves: directly-named model types 5 → **7** (`BuildService` and `UpdatedBuild`
join) and resolved 3 → **6**, because `GenericBuild` now resolves — it too lives
in a `build` package. Igor's Lombok classes 3 → **5** and `@JsonProperty` 1 → **2**;
mesh-wide, resolved model classes 182 → **185** and Lombok 79 → **81**. The
nullability and validation findings are untouched (Igor has no `javax.validation`
import in a named model, no `@Nullable`, no `@NonNull`). source:
spinnaker/igor@v4.22.0 igor-core/src/main/java/com/netflix/spinnaker/igor/build/
model/GenericBuild.java and UpdatedBuild.java, igor-core/src/main/java/com/netflix/
spinnaker/igor/service/BuildService.java; `models.py` over the 748 rows

CLAIM-S2-035: (incidental, found while recounting) CLAIM-S2-024's "28 endpoints
wrap in `ResponseEntity`" does not reproduce even on the delivered table — it has
**26** such rows plus 2 `HttpEntity`, and the claim's own per-service list (gate
15, clouddriver 5, echo 2, kayenta 2, front50 1, igor 1) sums to 26. At 748 rows
it is **27** `ResponseEntity` (igor 2) and 2 `HttpEntity`. The rest of
CLAIM-S2-024 stands: no `RouterFunction`, `Mono`, `Flux` or `DeferredResult`
anywhere, and eight of the wrapped rows are raw (6 raw `ResponseEntity`, 2 raw
`HttpEntity`) and count untyped on the return side. source: `endpoints.tsv`,
column `return_type`, counted over both tables

CLAIM-S2-036: A row claim id is a citation, so it keeps naming the endpoint it
was delivered under: all 732 rows of the first delivery keep ids
CLAIM-S2-R0001…R0732 (every one of them byte-identical in all 14 columns), and the
16 new rows take **R0733…R0748** — so the range in the review's R0 row becomes
R0001…R0748 with no id changing meaning. The ids are therefore no longer in row
order inside Igor's block. source: `scout/S2/emit.py:31-60` (`--stable-from`,
which reads the previous table); the column-by-column diff of the two tables

CLAIM-S2-037: `scout/review/r2_s2_coverage.py`, run unmodified (md5
`28148dcf887fde4095124b98986022db`) against the new table, reports
`_total_missing_method_mappings 0` and `missing: 0` for every service, with Igor
at 17 source controller files and 17 in `endpoints.tsv`. (Clouddriver still shows
59 source files against 58 in the table: the extra file carries `@Controller` with
no method-level mapping, which the checker itself excludes from "missing".) It was
run from a byte-identical copy in a scratch directory, with symlinks to `S1`/`S2`,
so that its output file under `scout/review/` was not overwritten; the 26 files of
`scout/review/` have identical checksums before and after. source: the run of
2026-09-11; scout/review/r2_s2_coverage.py

CLAIM-S2-038: `scout/review/r1ab_reconcile.py`, run the same way (md5
`063f07090b0388db0830c0eea56b9ce3`) against S1's redone `edges.tsv` (564 rows, 563
resolved) and the new table: **524 of 563 resolved edges match, 93.1%** (95.5%
excluding the 14 actuator rows), against 470/533 = 88.2% at the review. Igor as a
provider goes from 33/63 (52.4%) to **57/63 (90.5%)**; its six remaining unmatched
rows are the two actuator rows, the one provider-dispatch-slot row (`orca → igor
/{repoType}/{projectKey}/{repositorySlug}/compareCommits`) and the three stale
`keel → igor /scm/…` declarations — all three classes the review already ruled not
findings, so no census gap remains. Untyped share over the reconciled edges:
262/524 = 50.0% as written, 250/524 = **47.7%** under S5's refinement (below the
50% line for the first time), both sides untyped 21 = 4.0%; the reviewer's
independent classifier reproduces my `typing` column on all 748 rows (0
mismatches). On the nine-service mesh of D2 (`r1_nine_service_mesh.py`): 434/462 =
**93.9%** matched, 96.4% excluding actuator rows, untyped 55.5% as written / 53.0%
refined. The improvement is from both redos — S1 added 30 resolved front50 edges,
S2 the 16 Igor endpoints. source: the runs of 2026-09-11 against
`scout/S1/edges.tsv` (564 rows) and `scout/S2/endpoints.tsv` (748 rows)

### Diff summary

| service | rows before | rows after | added | removed | changed |
|---|---|---|---|---|---|
| gate | 278 | 278 | 0 | 0 | 0 |
| orca | 48 | 48 | 0 | 0 | 0 |
| clouddriver | 130 | 130 | 0 | 0 | 0 |
| front50 | 90 | 90 | 0 | 0 | 0 |
| echo | 14 | 14 | 0 | 0 | 0 |
| igor | 35 | 51 | **16** | 0 | 0 |
| fiat | 16 | 16 | 0 | 0 | 0 |
| rosco | 14 | 14 | 0 | 0 | 0 |
| kayenta | 48 | 48 | 0 | 0 | 0 |
| keel | 59 | 59 | 0 | 0 | 0 |
| **all ten** | **732** | **748** | **16** | **0** | **0** |

All 16 additions are Igor's `build` package; "changed" counts rows present in both
tables whose 14 columns are not identical.

## What I could not verify

* **Runtime paths.** I read mapping annotations, not the dispatcher. Servlet
  context paths, `spring.mvc.servlet.path`, reverse-proxy prefixes and Gate's own
  forwarding rewrites are unconfirmed, so a template here may differ from the URL
  a caller sends; reconcile S1's Retrofit paths with that in mind (D3).
* **Conditional registration.** Many controllers carry `@ConditionalOnProperty` /
  `@ConditionalOnExpression` / `@ConditionalOnBean`; I counted all of them as
  present. Which subset a deployment exposes depends on configuration I did not
  evaluate. Likewise, Kayenta's and Clouddriver's provider-specific controllers
  are counted as they appear in the repository, not as they ship in an artifact.
* **Reflection fidelity (D1).** Parsing source, not bytecode, leaves Kotlin
  `@Metadata` nullability, Groovy's erased static types and Jackson's actual
  serialized property set (Lombok accessors, `@JsonIgnore`, naming strategies,
  `@JsonView`, `@JsonInclude`) unconfirmed. The field counts in
  `typing-census.md` §4 are declaration counts, not Jackson property counts, and
  `Optional<T>` is treated as a container and unwrapped to `T`.
* **Four inferred Kotlin return types** were hand-resolved from the delegate's
  declared type rather than read off a signature (keel@v1.4.1):
  `AdminController.getPausedApplications` → `List<String>`,
  `AdminController.getManagedApplications` (line 45) →
  `Collection<ApplicationSummary>`, the same name at line 157 →
  `ExecutionSummary`, `EnvironmentController.list` → `List<EnvironmentView>`. If a
  delegate's own type is itself inferred, that resolution is one hop shallow.
* **Polymorphism reach is a bounded search.** Detection walks supertypes,
  registered mixins and declared field types to depth 5 with a 400-node budget,
  resolving simple names within the service and then kork. A discriminator further
  away, or on a type from a dependency other than kork, is missed, and a same-named
  class inside the same service could in principle be matched instead of the right
  one. The 33 `polymorphic` rows are a lower bound: the count moved from 28 to 33
  when I found Clouddriver's Java-form mixin registration (CLAIM-S2-010), so a
  registration form I have not thought of would move it again.
* **`@ControllerAdvice` response codes.** Four services declare one (gate, fiat,
  kayenta, keel); the statuses they map are not in `response_codes`, which carries
  only per-endpoint declarations.
* **The untyped share the review needs.** R1 recomputes it over S1's *resolved
  edges*; my 41.7% is over endpoints and is not a substitute. Gate's 70% will move
  the edge-level figure a lot depending on how many resolved edges point at Gate.
* **Row identity.** A mapping annotation with several paths or methods yields
  several rows (732 rows from 726 sites). If R1 wants one row per annotation, six
  rows must be collapsed.
* **Memo length.** This memo runs to roughly three pages rather than the two the
  brief allows; I kept all 25 claims and their sources rather than drop evidence.
  The redo section adds thirteen more.
* **Unannotated query parameters (found in the redo).** `query_params` records
  only `@RequestParam`-annotated parameters. Spring MVC also binds an unannotated
  simple-type parameter as a request parameter, and Igor's two
  `BuildController.getBuildResults` rows are a live case: `propertyFile` carries
  `@Query` — *Retrofit's* annotation (`import retrofit2.http.Query`,
  BuildController.groovy:50), which Spring does not read — so it is bound by name
  and is missing from those rows. How many rows mesh-wide have such a parameter is
  not measured here.
* **Same-name model resolution, one confirmed instance.** The redo's new Igor type
  `BuildService` resolves to `igor-web/…/concourse/client/BuildService.java`, but
  `InfoController` imports `com.netflix.spinnaker.igor.service.BuildService`
  (InfoController.groovy:23). Both are Java, so §3's language counts are
  unaffected, but §4's annotation row for Igor may count the wrong class. This is
  the hazard listed under "polymorphism reach" above, now with a named case.
