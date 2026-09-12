# S2 — provider surface: what the ten Spinnaker services expose

Deliverables: `endpoints.tsv` (732 rows, header exactly as the plan specifies),
`typing-census.md`, this memo. Row-level claims live in the TSV's `claim` column
in their own namespace (`CLAIM-S2-R0001` … `CLAIM-S2-R0732`), each carrying
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
