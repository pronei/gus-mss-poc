# S6 memo — cross-service identities (chain candidates)

Method: shallow clones at the latest release tag per repo; source reading
only (controllers, Retrofit/Spring annotations, model classes, propagation
filters). Nothing built, nothing run. Findings and the ranked recommendation
are in `chains.md`; this memo is the evidence.

**Headline.** Spinnaker mints most identities in *responses* and replays them
as *path parameters*, which the current checker cannot see. Three families
are genuinely request-carried and worth annotating: caller-minted idempotency
keys (`clientRequestId`, `correlationId`), the `application` scope relayed
through Orca, and artifact credentials at `PUT /artifacts/fetch`. The plan's
hypothesised bake-id and canary-id chains are refuted as response carriage,
and the `X-SPINNAKER-*` headers are undeclared at 8 of 10 services.

## Corpus

- CLAIM-S6-001: the ten repositories were cloned with `git clone --depth 1 --branch <tag>` at gate v6.69.0 (1af7f70af0bec53e17f362beac5fd3d754fc6280), orca v8.64.0 (2fdb327a9f67345c4919e1503ff5119fa3c31caf), clouddriver v5.95.0 (5e0ce2abb37cce236e4fb65b5f1ffa4ee781346e), front50 v2.41.0 (ceda49e0cb67925d85f0dc7f928c8909f53f1813), echo v2.47.2 (38c2df6d67593962b8d981526cbdd69805bf817a), igor v4.22.0 (627ec479540511c3b46708f56b3fd4967bf40e25), fiat v1.57.0 (1c7fb38cd9bb3c3ea6c81d364612ca7abaadfe6a), rosco v1.26.0 (0ae53eb04d872050841dd813d993d7e5c38ea50f), kayenta v2.46.0 (a69573be9d8fededacf80817e4151a2c8df41276), keel v1.4.1 (1aa966989fc39cf9fb7abf35d3fdc856503ae0d8); each tag is the highest `vN.N.N` tag on `git ls-remote --tags`. source: scratchpad/spinnaker/S6/<repo> `git rev-parse HEAD`

## `clientRequestId` — Orca ⇒ Clouddriver

- CLAIM-S6-002: Orca mints the value as `sha256(stageId + "-" + stageStartTime + "-" + payloadBytes)` from the ambient `ExecutionContext`. source: spinnaker/orca@v8.64.0 orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/KatoService.java:121-128
- CLAIM-S6-003: it is sent as `@Query("clientRequestId") String` on `POST /{cloudProvider}/ops`. source: spinnaker/orca@v8.64.0 orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/KatoRestService.java:32
- CLAIM-S6-004: Clouddriver declares it `@RequestParam(value = "clientRequestId", required = false) String`. source: spinnaker/clouddriver@v5.95.0 clouddriver-web/src/main/groovy/com/netflix/spinnaker/clouddriver/controllers/OperationsController.groovy:93
- CLAIM-S6-005: when absent Clouddriver substitutes a fresh random UUID: `Optional.ofNullable(id).orElse(UUID.randomUUID().toString())`. source: spinnaker/clouddriver@v5.95.0 clouddriver-web/src/main/groovy/com/netflix/spinnaker/clouddriver/controllers/OperationsController.groovy:238
- CLAIM-S6-006: Clouddriver looks the task up by it before executing and skips execution when a non-retryable task already exists. source: spinnaker/clouddriver@v5.95.0 clouddriver-core/src/main/groovy/com/netflix/spinnaker/clouddriver/orchestration/DefaultOrchestrationProcessor.groovy:242
- CLAIM-S6-007: `RedisTaskRepository.create` registers the task with `SETNX` on a key derived from it and marks the loser `"Duplicate of " + clientRequestId`. source: spinnaker/clouddriver@v5.95.0 clouddriver-core/src/main/java/com/netflix/spinnaker/clouddriver/data/task/jedis/RedisTaskRepository.java:103-113
- CLAIM-S6-008: Orca retries `requestOperations` three times with a one-second delay, so the dedup key is what keeps the retries idempotent. source: spinnaker/orca@v8.64.0 orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/KatoService.java:45-49

## `correlationId` — Keel ⇒ Orca

- CLAIM-S6-009: Keel puts the value into `OrchestrationTrigger(correlationId = correlationId, ...)` in the body it sends to Orca. source: spinnaker/keel@v1.4.1 keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/orca/OrcaTaskLauncher.kt:115
- CLAIM-S6-010: the declared type is `val correlationId: String?` — Kotlin nullable. source: spinnaker/keel@v1.4.1 keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/model/OrchestrationRequest.kt:29
- CLAIM-S6-011: the transport is `@POST("/ops")` with `@Body request: OrchestrationRequest` — a typed body, not a `Map`. source: spinnaker/keel@v1.4.1 keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/orca/OrcaService.kt:31
- CLAIM-S6-012: for cluster resources the minted value is `"${resource.id}:$region"` plus a `"${resource.id}:managed-rollout"` variant. source: spinnaker/keel@v1.4.1 keel-core/src/main/kotlin/com/netflix/spinnaker/keel/api/plugins/BaseClusterHandler.kt:83
- CLAIM-S6-013: for bakes it is `"bake:$name:$version"`. source: spinnaker/keel@v1.4.1 keel-bakery-plugin/src/main/kotlin/com/netflix/spinnaker/keel/bakery/artifact/ImageHandler.kt:259
- CLAIM-S6-014: Orca reads `correlationId` out of the trigger JSON in `TriggerDeserializer`. source: spinnaker/orca@v8.64.0 orca-core/src/main/java/com/netflix/spinnaker/orca/pipeline/model/support/TriggerDeserializer.kt:53
- CLAIM-S6-015: `ExecutionLauncher.checkForCorrelatedExecution` returns the pre-existing execution instead of launching a second one, and returns `null` immediately when the correlationId is null. source: spinnaker/orca@v8.64.0 orca-core/src/main/java/com/netflix/spinnaker/orca/pipeline/ExecutionLauncher.java:138-154
- CLAIM-S6-016: Orca serves `GET /executions/correlated/{correlationId}` via `executionRepository.retrieveByCorrelationId`. source: spinnaker/orca@v8.64.0 orca-web/src/main/java/com/netflix/spinnaker/orca/controllers/CorrelatedTasksController.java:43
- CLAIM-S6-017: Keel declares that endpoint as `@GET("/executions/correlated/{correlationId}")` on its Orca client. source: spinnaker/keel@v1.4.1 keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/orca/OrcaService.kt:70
- CLAIM-S6-018: Keel gates all actuation on it — `actuationInProgress` is true iff `getCorrelatedExecutions` is non-empty. source: spinnaker/keel@v1.4.1 keel-titus-plugin/src/main/kotlin/com/netflix/spinnaker/keel/titus/TitusClusterHandler.kt:140-145

## `application` — Gate ⇒ Orca ⇒ Front50

- CLAIM-S6-019: Gate writes the path variable into the outbound body: `body.put("application", app)`. source: spinnaker/gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/TaskService.java:59
- CLAIM-S6-020: the Gate endpoint is `POST /applications/{application}/tasks`. source: spinnaker/gate@v6.69.0 gate-web/src/main/groovy/com/netflix/spinnaker/gate/controllers/ApplicationController.groovy:229
- CLAIM-S6-021: Gate's declared Orca contract is `@POST("/ops") Call<Map> doOperation(@Body Map<String, Object> body)` — the identity is not in the declared type. source: spinnaker/gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/OrcaService.java:21
- CLAIM-S6-022: Orca's `POST /ops` (consumes `application/context+json`) reads `input.application` and `input.job`. source: spinnaker/orca@v8.64.0 orca-web/src/main/groovy/com/netflix/spinnaker/orca/controllers/OperationsController.groovy:377
- CLAIM-S6-023: Orca throws `IllegalArgumentException("Missing one or more required task parameters (application.name)")` when the field is absent. source: spinnaker/orca@v8.64.0 orca-front50/src/main/groovy/com/netflix/spinnaker/orca/front50/tasks/AbstractFront50Task.groovy:66-72
- CLAIM-S6-024: Orca's `Application` model declares `public String name`. source: spinnaker/orca@v8.64.0 orca-front50/src/main/groovy/com/netflix/spinnaker/orca/front50/model/Application.groovy:35
- CLAIM-S6-025: Orca declares `@POST("/v2/applications") Response create(@Body Application)` and `@PATCH("/v2/applications/{applicationName}") Response update(@Path("applicationName") String, @Body Application)`. source: spinnaker/orca@v8.64.0 orca-front50/src/main/groovy/com/netflix/spinnaker/orca/front50/Front50Service.groovy:44
- CLAIM-S6-026: the call site passes the same value as path parameter and body field: `front50Service.update(application.name, application)`. source: spinnaker/orca@v8.64.0 orca-applications/src/main/groovy/com/netflix/spinnaker/orca/applications/tasks/UpsertApplicationTask.groovy:82
- CLAIM-S6-027: Front50 rejects a PATCH whose body `name` differs from the path parameter with `InvalidApplicationRequestException`. source: spinnaker/front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/v2/ApplicationsController.java:151-156
- CLAIM-S6-028: Front50's write authorization is keyed on the body field: `@PreAuthorize("hasPermission(#app.name, 'APPLICATION', 'WRITE')")`. source: spinnaker/front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/v2/ApplicationsController.java:146
- CLAIM-S6-029: Front50's `create` uses `app.getName()` as the uniqueness key. source: spinnaker/front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/v2/ApplicationsController.java:120

## `application` / `parentPipelineExecutionId` — Echo ⇒ Orca ⇒ Kayenta, Front50

- CLAIM-S6-030: Echo's declared Orca contract is `@POST("orchestrate") Call<TriggerResponse> trigger(@Body Pipeline pipeline)` — typed, unlike Gate's. source: spinnaker/echo@v2.47.2 echo-pipelinetriggers/src/main/java/com/netflix/spinnaker/echo/pipelinetriggers/orca/OrcaService.java:37
- CLAIM-S6-031: Echo's `Pipeline` declares `@JsonProperty @NonNull String application` and `@JsonProperty String id`. source: spinnaker/echo@v2.47.2 echo-model/src/main/java/com/netflix/spinnaker/echo/model/Pipeline.java:40
- CLAIM-S6-032: Orca passes `stage.execution.application` and `stage.execution.id` into the Kayenta call. source: spinnaker/orca@v8.64.0 orca-kayenta/src/main/kotlin/com/netflix/spinnaker/orca/kayenta/tasks/RunKayentaCanaryTask.kt:48
- CLAIM-S6-033: they travel as `@Query("application")` and `@Query("parentPipelineExecutionId")` on `POST /canary/{canaryConfigId}` — the execution id is renamed at this hop. source: spinnaker/orca@v8.64.0 orca-kayenta/src/main/kotlin/com/netflix/spinnaker/orca/kayenta/KayentaService.kt:35-36
- CLAIM-S6-034: Kayenta declares both as `@RequestParam(required = false) final String`. source: spinnaker/kayenta@v2.46.0 kayenta-web/src/main/java/com/netflix/kayenta/controllers/CanaryController.java:76
- CLAIM-S6-035: Kayenta copies `parentPipelineExecutionId` into the canary pipeline context only when it is non-null. source: spinnaker/kayenta@v2.46.0 kayenta-core/src/main/java/com/netflix/kayenta/canary/ExecutionMapper.java:409
- CLAIM-S6-036: Kayenta returns it to callers on `CanaryExecutionStatusResponse.parentPipelineExecutionId`. source: spinnaker/kayenta@v2.46.0 kayenta-core/src/main/java/com/netflix/kayenta/canary/CanaryExecutionStatusResponse.java:30
- CLAIM-S6-037: Orca's `StartPipelineTask` fetches an application's pipelines from Front50 and filters by id client-side, so only `application` crosses the wire. source: spinnaker/orca@v8.64.0 orca-front50/src/main/groovy/com/netflix/spinnaker/orca/front50/tasks/StartPipelineTask.groovy:68
- CLAIM-S6-038: Front50 serves it at `GET /pipelines/{application}`, while Orca declares the same path with the variable named `applicationName` — a D3 normalization case. source: spinnaker/front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PipelineController.java:201

## Refutations and partial cases

- CLAIM-S6-039: Rosco's bake id is minted in a response — `BakeStatus { String id; State state; Result result; String resourceId }` returned by `POST /api/v1/{region}/bake`. source: spinnaker/orca@v8.64.0 orca-bakery/src/main/groovy/com/netflix/spinnaker/orca/bakery/api/BakeStatus.groovy:35
- CLAIM-S6-040: Orca then replays it as a path parameter, `lookupBake(region, bakeStatus.resourceId)`. source: spinnaker/orca@v8.64.0 orca-bakery/src/main/groovy/com/netflix/spinnaker/orca/bakery/tasks/CompletedBakeTask.groovy:43
- CLAIM-S6-041: Front50 mints the pipeline config id server-side when the submitted pipeline has none: `pipeline.setId(UUID.randomUUID().toString())`. source: spinnaker/front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PipelineController.java:686
- CLAIM-S6-042: Front50's `PUT /pipelines/{id}` rejects a body whose `id` differs from the path id. source: spinnaker/front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PipelineController.java:417
- CLAIM-S6-043: Keel triggers a pipeline by config id as a path parameter, `@POST("/orchestrate/{pipelineConfigId}")`. source: spinnaker/keel@v1.4.1 keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/orca/OrcaService.kt:38
- CLAIM-S6-044: Orca serves it at `POST /orchestrate/{pipelineConfigId}`. source: spinnaker/orca@v8.64.0 orca-web/src/main/groovy/com/netflix/spinnaker/orca/controllers/OperationsController.groovy:109
- CLAIM-S6-045: Clouddriver rejects an operation with no account name: `InvalidRequestException("credentials are required")`. source: spinnaker/clouddriver@v5.95.0 clouddriver-core/src/main/java/com/netflix/spinnaker/clouddriver/security/AbstractAtomicOperationsCredentialsSupport.java:30
- CLAIM-S6-046: and an unknown one with `"credentials not found (name: %s, names: %s)"`. source: spinnaker/clouddriver@v5.95.0 clouddriver-core/src/main/java/com/netflix/spinnaker/clouddriver/security/AbstractAtomicOperationsCredentialsSupport.java:44
- CLAIM-S6-047: Orca uses two names for that identity in one expression — `credentials: stageData.credentials ?: stageData.account`. source: spinnaker/orca@v8.64.0 orca-clouddriver/src/main/groovy/com/netflix/spinnaker/orca/kato/pipeline/support/ResizeStrategySupport.groovy:53
- CLAIM-S6-048: the operation body is declared `@Body Collection<? extends Map<String, Map>> operations` on the Orca side, so the account field is untyped at the contract level. source: spinnaker/orca@v8.64.0 orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/KatoRestService.java:34

## `source.executionId` — Orca ⇒ Echo

- CLAIM-S6-049: Orca declares `@POST("/notifications") Response create(@Body Notification)` with a nested `static class Source { String executionType; String executionId; String application; String user }`. source: spinnaker/orca@v8.64.0 orca-echo/src/main/groovy/com/netflix/spinnaker/orca/echo/EchoService.groovy:52
- CLAIM-S6-050: Echo's own `Notification` declares the structurally identical nested `Source`. source: spinnaker/echo@v2.47.2 echo-notifications/src/main/groovy/com/netflix/spinnaker/echo/api/Notification.groovy:40
- CLAIM-S6-051: Echo's sink is `@RequestMapping("/notifications")` + `POST` `create(@RequestBody Notification notification)`. source: spinnaker/echo@v2.47.2 echo-notifications/src/main/java/com/netflix/spinnaker/echo/controller/NotificationController.java:63
- CLAIM-S6-052: the notification templates dereference `notification.source.application` and `notification.source.executionId` unguarded to build the execution deep link. source: spinnaker/echo@v2.47.2 echo-notifications/src/main/resources/templates/manualJudgment/variables-email.ftl:1

## `X-SPINNAKER-*` headers

- CLAIM-S6-053: `X-SPINNAKER-EXECUTION-ID` is minted in Orca, not Gate, by `MDC.put(Header.EXECUTION_ID.getHeader(), event.getExecutionId())`. source: spinnaker/orca@v8.64.0 orca-core/src/main/java/com/netflix/spinnaker/orca/events/ExecutionListenerAdapter.java:40
- CLAIM-S6-054: in gate, orca, clouddriver, front50, echo, igor, rosco, fiat and kayenta no Retrofit interface declares an `X-SPINNAKER-*` parameter and no controller declares one; propagation is done by a kork interceptor reading the MDC, and kork is not one of the ten repositories. source: spinnaker/clouddriver@v5.95.0 clouddriver-core/src/main/java/com/netflix/spinnaker/clouddriver/config/RetrofitConfig.java:45
- CLAIM-S6-055: Keel is the exception: it declares `@Header("X-SPINNAKER-USER")` on 35 client methods across its Clouddriver (20), Orca (7), Front50 (7) and Echo (1) interfaces. source: spinnaker/keel@v1.4.1 keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/orca/OrcaService.kt:34
- CLAIM-S6-056: Keel is also the only repo whose controllers declare `@RequestHeader("X-SPINNAKER-USER")` — 27 of them, all with the default `required = true`, so absence is a 400. source: spinnaker/keel@v1.4.1 keel-web/src/main/kotlin/com/netflix/spinnaker/keel/rest/ResourceController.kt:82
- CLAIM-S6-057: Clouddriver's `DataController` splits `X-SPINNAKER-ACCOUNTS` off the MDC, defaults to an empty set, and throws `AccessDeniedException` when the account is not in it. source: spinnaker/clouddriver@v5.95.0 clouddriver-web/src/main/groovy/com/netflix/spinnaker/clouddriver/controllers/DataController.groovy:88
- CLAIM-S6-058: Rosco reads the execution id off the MDC inside `createBake` and proceeds with `null` when absent. source: spinnaker/rosco@v1.26.0 rosco-web/src/main/groovy/com/netflix/spinnaker/rosco/controllers/BakeryController.groovy:154
- CLAIM-S6-059: Igor falls back to the literal `"NO_EXECUTION_ID"` in its pending-build cache key, so header-less concurrent builds collide on one key. source: spinnaker/igor@v4.22.0 igor-web/src/main/groovy/com/netflix/spinnaker/igor/build/BuildController.groovy:322

## Artifacts

- CLAIM-S6-060: `com.netflix.spinnaker.kork.artifacts.model.Artifact` is not vendored in any of the ten repositories; all resolve it from the binary dependency pinned at `korkVersion=7.254.0`. source: spinnaker/clouddriver@v5.95.0 gradle.properties:1
- CLAIM-S6-061: its fields, read from use sites, are `type`, `name`, `version`, `location`, `reference`, `provenance`, `artifactAccount`, `uuid` (all `String`), `customKind` (`boolean`) and `metadata` (`Map<String, Object>`). source: spinnaker/igor@v4.22.0 igor-web/src/main/groovy/com/netflix/spinnaker/igor/docker/DockerMonitor.groovy:216-224
- CLAIM-S6-062: Igor's docker poller sends a singular field `artifact` typed `GenericArtifact` — Igor's own class, not kork's. source: spinnaker/igor@v4.22.0 igor-core/src/main/java/com/netflix/spinnaker/igor/history/model/DockerEvent.java:30
- CLAIM-S6-063: Igor's Artifactory poller sends a singular `content.artifact` typed kork `Artifact`. source: spinnaker/igor@v4.22.0 igor-core/src/main/java/com/netflix/spinnaker/igor/history/model/ArtifactoryEvent.java:42
- CLAIM-S6-064: Igor also bypasses Echo for Keel with `@POST("artifacts/events") Call<Void> sendArtifactEvent(@Body Map event)`, field `payload.artifacts`. source: spinnaker/igor@v4.22.0 igor-core/src/main/java/com/netflix/spinnaker/igor/keel/KeelService.java:28
- CLAIM-S6-065: Echo renames the identity to `receivedArtifacts` when building the outbound `Pipeline`: `.withReceivedArtifacts(ta.artifacts)`. source: spinnaker/echo@v2.47.2 echo-pipelinetriggers/src/main/java/com/netflix/spinnaker/echo/pipelinetriggers/eventhandlers/BaseTriggerEventHandler.java:103
- CLAIM-S6-066: the same body carries a third copy under `trigger.artifacts`, declared `List<Map<String, Object>>` rather than `List<Artifact>`. source: spinnaker/echo@v2.47.2 echo-model/src/main/java/com/netflix/spinnaker/echo/model/Trigger.java:198
- CLAIM-S6-067: Orca writes the resolved set back onto the trigger under three keys — `artifacts`, `expectedArtifacts` and `resolvedExpectedArtifacts`, the last two carrying the identical payload from adjacent statements. source: spinnaker/orca@v8.64.0 orca-core/src/main/java/com/netflix/spinnaker/orca/pipeline/util/ArtifactUtils.java:245-256
- CLAIM-S6-068: the terminal sink is `PUT /artifacts/fetch` with `@RequestBody Artifact artifact` — the artifact is the body, with no field name. source: spinnaker/clouddriver@v5.95.0 clouddriver-web/src/main/java/com/netflix/spinnaker/clouddriver/controllers/ArtifactController.java:77
- CLAIM-S6-069: it relies on two fields as a composite credential key: an empty `artifactAccount` throws `IllegalArgumentException`, and `(name, type)` must match a registered credential or it throws `MissingCredentialsException`. source: spinnaker/clouddriver@v5.95.0 clouddriver-artifacts/src/main/java/com/netflix/spinnaker/clouddriver/artifacts/ArtifactCredentialsRepository.java:38-51
- CLAIM-S6-070: on success the bytes are streamed straight back to the caller. source: spinnaker/clouddriver@v5.95.0 clouddriver-web/src/main/java/com/netflix/spinnaker/clouddriver/controllers/ArtifactController.java:85
- CLAIM-S6-071: Orca declares the same endpoint as `@PUT("/artifacts/fetch/") Response fetchArtifact(@Body Artifact artifact)`. source: spinnaker/orca@v8.64.0 orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/OortService.java:145
- CLAIM-S6-072: Orca refuses to call it with a null `artifactAccount`. source: spinnaker/orca@v8.64.0 orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/tasks/manifest/ManifestEvaluator.java:181-183
- CLAIM-S6-073: Rosco declares and calls the identical endpoint, so one sink has two independent providers. source: spinnaker/rosco@v1.26.0 rosco-core/src/main/groovy/com/netflix/spinnaker/rosco/services/ClouddriverService.java:30
- CLAIM-S6-074: Clouddriver's `deployManifest` operation keys artifacts on `String.format("[%s]-[%s]-[%s]", type, name, location)`, excluding `reference`, `version` and `artifactAccount`. source: spinnaker/clouddriver@v5.95.0 clouddriver-kubernetes/src/main/java/com/netflix/spinnaker/clouddriver/kubernetes/op/manifest/KubernetesDeployManifestOperation.java:318-323
- CLAIM-S6-075: a different five-field `ArtifactKey` is used to assert that every required artifact was bound, failing the operation otherwise. source: spinnaker/clouddriver@v5.95.0 clouddriver-kubernetes/src/main/java/com/netflix/spinnaker/clouddriver/kubernetes/op/manifest/KubernetesDeployManifestOperation.java:291
- CLAIM-S6-076: on the Rosco bake hop the field is `@JsonProperty("inputArtifacts") List<Artifact>` for Helm but `@JsonProperty("inputArtifact") Artifact` for Kustomize — a rename and a cardinality change on one logical hop. source: spinnaker/orca@v8.64.0 orca-bakery/src/main/java/com/netflix/spinnaker/orca/bakery/api/manifests/kustomize/KustomizeBakeManifestRequest.java:29 (Helm counterpart: orca-bakery/src/main/java/com/netflix/spinnaker/orca/bakery/api/manifests/helm/HelmBakeManifestRequest.java:45)
- CLAIM-S6-077: Rosco receives that request as `@RequestBody Map<String, Object> request`, so nothing on the provider side validates the field name. source: spinnaker/rosco@v1.26.0 rosco-web/src/main/groovy/com/netflix/spinnaker/rosco/controllers/V2BakeryController.java:30
- CLAIM-S6-078: at every service-to-service artifact hop except `PUT /artifacts/fetch` the artifact is erased to a raw `Map` at the Retrofit or Spring boundary, so no compiler or deserializer catches field-name drift. source: spinnaker/orca@v8.64.0 orca-web/src/main/groovy/com/netflix/spinnaker/orca/controllers/OperationsController.groovy:105

## What I could not verify

- **kork.** Six of the identities I traced pass through classes that live in
  `kork` — `Artifact`, `ExpectedArtifact`, `Header`, `AuthenticatedRequest`,
  `SpinnakerRequestInterceptor`. Kork is not one of the ten repositories in
  the brief and I did not clone it, so CLAIM-S6-061 (Artifact's field names
  and types) is reconstructed from use sites, not read from the declaration,
  and the exact nullability and Jackson annotations on those fields are
  unverified. If the run keeps the artifact chain, kork must be added to the
  corpus or the extractor must read it from the pinned jar.
- **Runtime shape of `Map` bodies.** Everywhere the declared body is
  `Map<String, Object>` (Gate→Orca, Orca→Clouddriver ops, Rosco's bake
  endpoint) I inferred the field names from the code that writes and reads
  them. I did not observe a single real request, so I cannot rule out that a
  deployment, a plugin, or an `ExecutionPreprocessor` adds or renames keys at
  run time. Every claim about a field inside a `Map` body is a claim about
  source, not about the wire.
- **Whether each sink is reachable in practice.** I traced call paths
  statically. I did not check which of them are enabled by default, gated
  behind a feature flag (`artifacts.enabled`, `front50.enabled`,
  `services.fiat.enabled`, `bakery.roscoApisEnabled`), or dead in a stock
  installation. A chain whose sink is off by default is worth less than the
  citation suggests.
- **Completeness of the identity inventory.** I searched the paths the plan
  named plus what the code led me to. I did not do an exhaustive sweep of all
  ten repositories for every cross-service identity, so absence of a chain
  from this report is not evidence that none exists — in particular I did not
  examine Fiat's own outbound calls, Echo's pubsub and webhook inbound paths,
  Igor's SCM/GCB/CodeBuild surfaces beyond their signatures, or Kayenta's
  standalone canary-analysis controller in depth.
- **Header counts.** The counts in CLAIM-S6-055 (35 declared `@Header`) and
  CLAIM-S6-056 (27 `@RequestHeader`) come from a delegated exhaustive sweep;
  I re-derived five of that sweep's citations by hand and all five held, but
  I did not re-count all 62 sites myself.
- **Version history.** Everything here is one release tag per service. I did
  not check whether any of these fields were renamed, added or removed
  between consecutive BOMs, so I cannot say which of the recommended chains
  would actually have fired on a real release pair. That is S4's question and
  it should be crossed with this list before the second run commits to an
  annotation.
