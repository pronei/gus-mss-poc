# S6 — cross-service identities in Spinnaker: chain candidates

Scope per PLAN.md D9: **find candidates, do not annotate.** Every factual
statement carries a claim number resolved in `memo.md`.

Corpus: ten repositories shallow-cloned at their latest release tags
(CLAIM-S6-001). Everything below is read from source at those tags; nothing
was built or run.

## 0. The shape of the answer, before the details

Spinnaker mints almost all of its identities **in responses**, not in
requests: `POST /…/bake` returns a bake id, `POST /ops` returns a task id,
`POST /pipelines` returns a pipeline with a server-generated `id`. The
caller then replays the identity as a **path parameter** on the next call.
That is the dominant pattern, and the checker cannot see it today
(§9, §10, §11).

What *is* request-carried, and therefore usable, falls into three groups:

* **Idempotency / correlation keys minted by the caller** — `clientRequestId`
  (Orca→Clouddriver, §1) and `correlationId` (Keel→Orca, §2). Both are
  minted by the sending service, both are the key a receiver joins on, and
  both fail *silently* when broken. These are the two best chains in the
  corpus.
* **Scope identities relayed through Orca** — `application`, which enters at
  Gate or Echo, is stored on the execution, and leaves again towards Front50,
  Clouddriver and Kayenta (§3, §4). This is the only family with a genuine
  **relay hop**, and it renames at almost every hop.
* **Execution provenance** — the Orca execution id, which travels as a header
  everywhere (§11, unusable) *except* two places where it is a declared
  request field: `parentPipelineExecutionId` to Kayenta (§4) and
  `source.executionId` to Echo (§5).

One structural obstacle recurs and should be stated before any chain is
annotated: **Gate→Orca and Orca→Clouddriver carry untyped `Map` bodies**
(CLAIM-S6-021, CLAIM-S6-048). An identity that travels inside those bodies
has no declared field at that hop, so the projection would have to invent
the schema. Chains that avoid those two edges are worth much more.

Carriage kinds used below: **request-payload** (body field), **request-param**
(path or query parameter — usable only under D6, which folds parameters into
a synthetic `params` object), **header**, **response**.

---

## 1. `clientRequestId` — Orca ⇒ Clouddriver

* **Identity**: per-operation idempotency key.
* **Carriage kind**: request-param (query). Usable under D6.
* **Mint** — service `orca`, endpoint `POST /{cloudProvider}/ops` (outbound),
  field `clientRequestId`, type `String`. Value is
  `sha256(stageId + "-" + stageStartTime + "-" + payloadBytes)`, computed
  from the ambient `ExecutionContext`. CLAIM-S6-002, CLAIM-S6-003.
* **Hops**: none. Two-node chain.
* **Sink** — service `clouddriver`, endpoint `POST /{cloudProvider}/ops`,
  parameter `clientRequestId`, declared `@RequestParam(required = false)`.
  CLAIM-S6-004.
  *What "relies" means*: it is the **primary key of the task table**.
  `DefaultOrchestrationProcessor` looks the task up by it before executing
  and skips execution when a non-retryable task already exists
  (CLAIM-S6-006); `RedisTaskRepository.create` does `SETNX kato:taskmap:<id>`
  and marks the loser `Duplicate of <id>` (CLAIM-S6-007).
* **Verdict**: **recommend (rank 1)**.
* **If renamed or made optional at the one hop**: Clouddriver substitutes a
  fresh random UUID for a missing value (CLAIM-S6-005), so nothing errors —
  and Orca retries every `requestOperations` call up to three times
  (CLAIM-S6-008). The result is that each retry starts a *new* cloud
  operation: duplicate server groups, duplicate scaling actions, duplicate
  deletes. Silent, non-idempotent, and only visible in the cloud provider.

## 2. `correlationId` — Keel ⇒ Orca

* **Identity**: "an actuation for this resource+region is already in flight".
* **Carriage kind**: request-payload on the mint hop (typed Kotlin body),
  request-param (path) on the read-back hop. Both usable.
* **Mint** — service `keel`, endpoint `POST /ops` (outbound, declared
  `@Body OrchestrationRequest`), field `trigger.correlationId`, type
  `String?` (Kotlin nullable). CLAIM-S6-009, CLAIM-S6-010, CLAIM-S6-011.
  The value is `"<resource.id>:<region>"` (plus a
  `"<resource.id>:managed-rollout"` variant) for cluster resources
  (CLAIM-S6-012) and `"bake:<artifact>:<version>"` for bakes
  (CLAIM-S6-013).
* **Hops**: none. Two-node chain, but bidirectional: Keel writes it on one
  endpoint and reads it back on another.
* **Sink** — service `orca`. Two sinks:
  1. `POST /ops` — `ExecutionLauncher.checkForCorrelatedExecution` returns
     the pre-existing execution instead of launching a second one; a `null`
     correlationId disables the check entirely (CLAIM-S6-015). Orca parses
     the field out of the trigger JSON in `TriggerDeserializer`
     (CLAIM-S6-014).
  2. `GET /executions/correlated/{correlationId}` — path parameter, resolved
     through `executionRepository.retrieveByCorrelationId` (CLAIM-S6-016).
     Keel declares this endpoint (CLAIM-S6-017) and gates *all* actuation on
     it: `actuationInProgress` is true iff the list is non-empty
     (CLAIM-S6-018).
* **Verdict**: **recommend (rank 2)**.
* **If renamed or made optional at one hop**: this is the sharpest failure
  in the corpus. Drop or rename `trigger.correlationId` on the write side and
  Orca stops indexing the execution; `getCorrelatedExecutions` then always
  returns empty; `actuationInProgress` is permanently false; **Keel
  re-launches the same deploy or bake on every reconciliation cycle**, in a
  loop, with no error anywhere. Rename it on the read side instead (the path
  parameter) and Orca 404s a lookup Keel treats as "nothing running" — same
  loop. Type-flip it (say `String` → `List<String>`) and the join silently
  never matches.

## 3. `application` — Gate ⇒ Orca ⇒ Front50 (the create/update path)

* **Identity**: application name, the primary key of Front50 and the
  authorization subject for Fiat.
* **Carriage kind**: request-payload throughout, but **untyped at the first
  hop**.
* **Mint** — service `gate`, endpoint `POST /applications/{application}/tasks`
  (CLAIM-S6-020). `TaskService.createAppTask` writes the path variable into
  the outbound body: `body.put("application", app)` (CLAIM-S6-019). The
  outbound contract is `POST /ops` with `@Body Map<String, Object>` — the
  field exists at runtime but **is not in the declared type**
  (CLAIM-S6-021).
* **Hop 1** — service `orca`, inbound `POST /ops` (consumes
  `application/context+json`) reads `input.application` and `input.job`
  (CLAIM-S6-022). Outbound to Front50: `POST /v2/applications` with
  `@Body Application`, or `PATCH /v2/applications/{applicationName}` with
  `@Body Application` (CLAIM-S6-025), called as
  `front50Service.update(application.name, application)` — the same value in
  **both** the path parameter and the body field (CLAIM-S6-026).
  **Renamed: yes, twice.** `application` (String, top level) becomes
  `job[].application.name` on the way in and `name` / `applicationName` on
  the way out. Orca's own `Application` model declares `public String name`
  (CLAIM-S6-024).
  Orca is also an *intermediate sink*: `AbstractFront50Task` throws
  `IllegalArgumentException("Missing one or more required task parameters
  (application.name)")` when the field is absent (CLAIM-S6-023).
* **Sink** — service `front50`, `PATCH /v2/applications/{applicationName}`,
  body field `name`. Three distinct reliances:
  the body's `name` must equal the path parameter or the request is rejected
  with `InvalidApplicationRequestException` (CLAIM-S6-027); the Fiat
  authorization decision is keyed on the body field via
  `@PreAuthorize("hasPermission(#app.name, 'APPLICATION', 'WRITE')")`
  (CLAIM-S6-028); and `create` uses it as the uniqueness key
  (CLAIM-S6-029).
* **Verdict**: **recommend (rank 3)** — with the caveat that the Gate→Orca
  hop must be annotated on an invented field, since the declared body is
  `Map`.
* **If renamed or made optional at one hop**: renaming at Gate → Orca's
  `AbstractFront50Task` throws immediately, so every application create and
  update fails loudly (good failure). Renaming at Orca→Front50 is worse:
  `#app.name` evaluates to null, the `hasPermission` check is made against a
  null subject, and the path/body equality check throws — an authorization
  decision taken on an absent identity is the hazard worth catching.

## 4. `application` and `parentPipelineExecutionId` — Echo ⇒ Orca ⇒ Kayenta

* **Identity**: `application` (scope) and the Orca pipeline execution id
  (provenance), on the canary path.
* **Carriage kind**: request-payload at the mint hop (typed), request-param
  (query) at the sink hop.
* **Mint (application)** — service `echo`, endpoint `POST /orchestrate`,
  declared `@Body Pipeline` — a **typed** body (CLAIM-S6-030) whose
  `application` field is Lombok `@NonNull String` (CLAIM-S6-031). This is the
  only cross-service pipeline-trigger contract in the mesh that is not a
  bare `Map`.
* **Mint (execution id)** — service `orca`. The execution id is created
  inside Orca and leaves it as a declared field only here and in §5.
* **Hop** — service `orca`, outbound `POST /canary/{canaryConfigId}` with
  `@Query("application")` and `@Query("parentPipelineExecutionId")`
  (CLAIM-S6-033), fed from `stage.execution.application` and
  `stage.execution.id` (CLAIM-S6-032). **Renamed: yes** — the execution id
  travels as `parentPipelineExecutionId`; `application` keeps its name.
* **Sink** — service `kayenta`, `POST /canary/{canaryConfigId}`, both
  declared `@RequestParam(required = false)` (CLAIM-S6-034).
  *What "relies" means*: `ExecutionMapper` copies
  `parentPipelineExecutionId` into the canary pipeline's context, but only
  when it is non-null (CLAIM-S6-035), and `CanaryExecutionStatusResponse`
  hands it back to callers (CLAIM-S6-036). It is a stored join key, not a
  validated input.
* **A second sink for `application`** — service `front50`,
  `GET /pipelines/{application}`: Orca's `StartPipelineTask` fetches all of
  an application's pipelines and filters client-side (CLAIM-S6-037,
  CLAIM-S6-038). **Renamed:** `application` → path variable
  `applicationName` in the Retrofit declaration, `{application}` in the
  Spring mapping — a normalization case for D3 as well.
* **Verdict**: **recommend (rank 4)** for the `application` leg;
  `parentPipelineExecutionId` is a good rename example but a weak sink.
* **If renamed or made optional at one hop**: `parentPipelineExecutionId`
  going missing costs nothing at run time and everything afterwards — canary
  executions can no longer be joined to the pipeline that started them, so
  the canary history in Deck and every downstream report loses its parent
  link, silently. `application` going missing on the Echo→Orca hop is caught
  by `@NonNull` (Jackson builder throws), so that hop fails loudly.

## 5. `source.executionId` / `source.application` — Orca ⇒ Echo

* **Identity**: Orca execution id and application, on the notification path.
* **Carriage kind**: request-payload, **typed on both sides**.
* **Mint** — service `orca`, endpoint `POST /notifications`, declared
  `@Body Notification` with a nested `Source { executionType, executionId,
  application, user }`, all `String` (CLAIM-S6-049).
* **Hops**: none.
* **Sink** — service `echo`, `POST /notifications`,
  `@RequestBody Notification` whose model declares the identical nested
  `Source` (CLAIM-S6-050, CLAIM-S6-051).
  *What "relies" means*: every notification template dereferences
  `notification.source.application` and `notification.source.executionId` to
  build the execution deep link, and `MicrosoftTeamsNotificationService`
  concatenates the execution id directly into the URL (CLAIM-S6-052).
* **Verdict**: **recommend (rank 5)**. It is the cleanest structural example
  in the corpus — a nested object, both sides typed, both sides declared —
  even though it is a single hop and the blast radius is small.
* **If renamed or made optional at one hop**: FreeMarker dereferences the
  field unguarded, so a null or missing `source.executionId` raises an
  invalid-reference error and the notification is not delivered. Manual
  judgment notifications are the ones that break, which means a human never
  learns a pipeline is waiting on them.

## 6. Pipeline config id — partially usable

* **Carriage kind**: response at the mint, request-param afterwards.
* Front50 mints it server-side: `pipeline.setId(UUID.randomUUID().toString())`
  when the submitted pipeline has none (CLAIM-S6-041); it reaches callers in
  the response body.
* Front50 *does* enforce it on the write path: `PUT /pipelines/{id}` rejects
  a body whose `id` differs from the path id (CLAIM-S6-042). That is a real
  request-side sink, but the value was minted in an earlier response.
* Echo relays it to Orca as `Pipeline.id` (CLAIM-S6-031); Keel triggers by it
  as `POST /orchestrate/{pipelineConfigId}` (CLAIM-S6-043), which Orca serves
  (CLAIM-S6-044).
* **Verdict**: **partially usable**. A chain anchored at *Echo* (x-provides
  on `Pipeline.id`) rather than at Front50 would be honest and checkable, but
  it misstates where the value comes from. Not in my top five.

## 7. Account / credential name — real, load-bearing, invisible

* **Carriage kind**: request-payload, inside untyped `Map` bodies.
* Clouddriver is an unambiguous sink: a missing account name is
  `InvalidRequestException("credentials are required")` (CLAIM-S6-045) and an
  unknown one is `"credentials not found (name: %s, names: %s)"`
  (CLAIM-S6-046). Both are hard 400s on every mutating cloud operation.
* But the field travels inside `Collection<? extends Map<String, Map>>` on
  the Orca side and `List<Map<String, Map>>` on the Clouddriver side
  (CLAIM-S6-048) — **untyped on both legs**, so under D5 the edge is untyped
  and excluded from every claim anyway.
* Worse for annotation: Orca uses two names for the same identity in the same
  codebase — `credentials` and `account`, coalesced as
  `stageData.credentials ?: stageData.account` (CLAIM-S6-047). An authentic
  `x-alias` case that the projection cannot reach.
* **Verdict**: **not usable today.** Note it as the strongest argument for a
  future "identity inside an untyped map" convention.

## 8. Artifacts / image references — see §12

Deferred to the artifact sub-investigation; findings folded in below.

## 9. Bake id (Rosco ⇒ Orca) — refuted

The plan hypothesised a Rosco→Orca bake-id chain. It is **response
carriage**: `POST /api/v1/{region}/bake` returns `BakeStatus { id, state,
result, resourceId }` (CLAIM-S6-039) and Orca then replays those values as
**path parameters** — `lookupStatus(region, previousStatus.id)` and
`lookupBake(region, bakeStatus.resourceId)` (CLAIM-S6-040). The identity
never appears in a request field minted by Rosco. **Refuted** for the
current checker; it is the canonical example of the return-then-path pattern
the README puts out of scope.

## 10. Canary config id / canary execution id — refuted as minted chains

Same shape: `canaryConfigId` is a path parameter Orca reads out of its own
stage context (which came from a Kayenta or Front50 response), and the canary
execution id is minted in Kayenta's response to `POST /canary/{id}`. Only the
*parent* execution id travels as a request field, and that is §4.
**Refuted** as mint→sink chains; the useful half is already in §4.

## 11. `X-SPINNAKER-*` correlation headers — not usable today

* **Carriage kind**: header, and — decisively — **undeclared** header.
* Minting: `X-SPINNAKER-EXECUTION-ID` is minted by **Orca**, not Gate, by
  putting the execution id into the MDC around every execution event
  (CLAIM-S6-053). `X-SPINNAKER-USER` and `X-SPINNAKER-ACCOUNTS` are minted in
  Gate by kork's `AuthenticatedRequestFilter`; `X-SPINNAKER-REQUEST-ID` by
  Gate's `RequestLoggingFilter`.
* Carriage: in eight of the ten repos the propagation is done by a kork
  interceptor reading the MDC — **no Retrofit interface declares the header
  and no controller declares it as a parameter** (CLAIM-S6-054). The header
  constants themselves live in `kork`, which is not one of the ten
  repositories, so they are not even in the corpus.
* The two exceptions are worth recording: `keel` declares
  `@Header("X-SPINNAKER-USER")` on 35 client methods across its Clouddriver,
  Orca, Front50 and Echo interfaces (CLAIM-S6-055), and `keel` is the only
  repo whose controllers declare `@RequestHeader("X-SPINNAKER-USER")` — 27 of
  them, all with the default `required = true`, so absence is a 400
  (CLAIM-S6-056).
* Sinks exist and are real: Clouddriver's `DataController` denies access when
  `X-SPINNAKER-ACCOUNTS` is absent (CLAIM-S6-057); Rosco reads the execution
  id off the MDC inside `createBake` and proceeds with `null` when absent
  (CLAIM-S6-058); Igor falls back to the literal `"NO_EXECUTION_ID"` in its
  pending-build cache key, so header-less concurrent builds collide on one
  key (CLAIM-S6-059).
* **Verdict**: **not usable today.** D6 does fold headers into a synthetic
  `headers` object, so the *checker* could represent them — but the
  *extractor* cannot find them, because at 8 of 10 services they appear in
  neither the client interface nor the controller signature. The one
  exception, Keel, is a genuinely annotatable header chain
  (Gate mints → Keel declares and forwards → Keel's own controllers require)
  and is listed as the alternate below.

## 12. Artifacts / image references — Igor ⇒ Echo ⇒ Orca ⇒ Clouddriver / Rosco

This is the richest identity in the mesh and the one that renames most, but
it renames in ways the checker's field model only partly reaches.

* **Carriage kind**: request-payload at every hop, but the *shape* changes:
  singular object, list, nested-in-`Map`, and bare-body.
* **kork caveat**: `com.netflix.spinnaker.kork.artifacts.model.Artifact` lives
  in `kork`, which is **not** one of the ten repositories and is not vendored
  anywhere in them; all ten resolve it from the binary dependency pinned at
  `korkVersion=7.254.0` (CLAIM-S6-060). Its field names and types were read
  off use sites: `type`, `name`, `version`, `location`, `reference`,
  `provenance`, `artifactAccount`, `uuid` (all `String`), `customKind`
  (`boolean`), `metadata` (`Map<String, Object>`) (CLAIM-S6-061).
* **Mint** — service `igor`. Igor's only channel to Echo is
  `POST .` with `@Body Event`, so the field name depends on the event
  subclass: the docker poller sends `artifact` (singular) typed
  `GenericArtifact` — igor's *own* class, not kork's (CLAIM-S6-062);
  the Artifactory and Nexus pollers send `content.artifact` (singular),
  typed kork `Artifact` (CLAIM-S6-063). Igor also bypasses Echo entirely for
  Keel: `POST artifacts/events` with `@Body Map`, field `payload.artifacts`
  (CLAIM-S6-064).
* **Hop 1** — service `echo`. Renames `artifacts` →
  **`receivedArtifacts`** when it builds the outbound `Pipeline`
  (CLAIM-S6-065) and sends it on `POST /orchestrate` alongside
  `expectedArtifacts` and a *third* copy under `trigger.artifacts`, which is
  declared `List<Map<String, Object>>` rather than `List<Artifact>` — a type
  downgrade on the same body (CLAIM-S6-066).
* **Hop 2** — service `orca`. `ArtifactUtils.resolveArtifacts` unions
  `receivedArtifacts` with `trigger.artifacts` and writes the result back
  under three keys — `artifacts`, `expectedArtifacts` and
  `resolvedExpectedArtifacts` — the last two carrying the identical payload
  from adjacent statements (CLAIM-S6-067).
* **Sink A (the good one)** — service `clouddriver`,
  `PUT /artifacts/fetch` with `@RequestBody Artifact` — the artifact **is**
  the body, no field name (CLAIM-S6-068). *What "relies" means*: two fields
  are the **credential lookup key**. `artifactAccount` must be non-empty or
  the request fails with `IllegalArgumentException`, and
  `(artifactAccount, type)` must match a registered credential or it fails
  with `MissingCredentialsException` (CLAIM-S6-069); on success the bytes are
  streamed straight to the caller (CLAIM-S6-070). Orca declares the same
  endpoint (CLAIM-S6-071) and refuses to call it with a null `artifactAccount`
  (CLAIM-S6-072) — an unusually explicit caller-side precondition. **Rosco
  calls the identical endpoint** (CLAIM-S6-073), so one sink has two
  independent providers.
* **Sink B** — service `clouddriver`, the `deployManifest` kato operation:
  `requiredArtifacts` and `optionalArtifacts` are folded into a
  `Map<String, Artifact>` keyed by `"[type]-[name]-[location]"`, deliberately
  excluding `reference`, `version` and `artifactAccount` (CLAIM-S6-074), while
  a *different* key over `(type, name, version, location, reference)` is used
  to assert that every required artifact was bound, failing the operation
  otherwise (CLAIM-S6-075).
* **Sink C** — service `rosco`, `POST /api/v2/manifest/bake/{type}`. Orca
  declares a typed `BakeManifestRequest` whose Helm subclass carries
  `inputArtifacts` (`List<Artifact>`) and whose Kustomize subclass **renames
  it to singular `inputArtifact` (`Artifact`)** on the same logical hop
  (CLAIM-S6-076). Rosco receives it as `@RequestBody Map<String, Object>`,
  so nothing on the provider side validates the name (CLAIM-S6-077).
* **Verdict**: **recommend the `PUT /artifacts/fetch` leg only (rank 4).**
  The full Igor→Echo→Orca→Clouddriver path is a superb rename story but it
  is not annotatable as one chain: the identity changes *shape* (singular →
  list → list-inside-`Map` → bare body), and the checker's `x-alias` renames
  a field, not a cardinality or a nesting level. Annotating the
  Orca/Rosco → Clouddriver leg on `artifactAccount` and `type` captures the
  real sink cheaply and honestly.
* **If renamed or made optional at one hop**: `artifactAccount` dropped or
  renamed → every manifest deploy and every Helm bake fails at Clouddriver
  with a credentials error (loud, immediate). `receivedArtifacts` renamed at
  the Echo hop → the artifact silently disappears from the execution and the
  deploy runs with the *previous* image; nothing errors. `inputArtifacts` →
  `inputArtifact` drift at the Rosco hop → Rosco's untyped `Map` body
  silently drops the field and the bake runs with an empty chart list.
  Note that no compiler or deserializer catches any of these: at every
  service-to-service hop except `PUT /artifacts/fetch` the artifact is erased
  to a raw `Map` at the Retrofit/Spring boundary (CLAIM-S6-078).

---

# Ranked recommendation — five chains for the second run

Ranked by (annotatable today) × (severity of the real-world break) ×
(how much of the chain machinery it exercises). Fields are given at every
hop; `→` is one HTTP hop.

### 1. `correlationId` — Keel → Orca *(two nodes, nullable, two endpoints)*

| | service | endpoint | field | kind |
|---|---|---|---|---|
| mint | keel | `POST /ops` | `trigger.correlationId` (`String?`) | body |
| sink 1 | orca | `POST /ops` | `trigger.correlationId` | body |
| sink 2 | orca | `GET /executions/correlated/{correlationId}` | `correlationId` | path |
| reader | keel | declares sink 2 | `correlationId` | path |

**Breaks in practice**: Keel's `actuationInProgress` is false forever, so
Keel re-launches the same deploy or bake every reconciliation cycle, with no
error emitted anywhere. Exercises: nullable source field (Kotlin `String?`),
a chain whose sink is a path parameter, and the "demand nothing provides"
rule if the write side is renamed while the read side is not.

### 2. `application` — Gate → Orca → Front50 *(three nodes, two renames)*

| | service | endpoint | field | kind |
|---|---|---|---|---|
| mint | gate | `POST /ops` (from `POST /applications/{application}/tasks`) | `application` (`String`, inside `Map` body) | body |
| hop | orca | `PATCH /v2/applications/{applicationName}` | `name` in `@Body Application`, **alias of** `application`; also the path parameter | body + path |
| sink | front50 | `PATCH /v2/applications/{applicationName}` | `name` | body |

**Breaks in practice**: Front50 rejects the request when body `name` and the
path disagree, and — worse — the Fiat write-permission check is evaluated on
`#app.name`, so an absent identity means an authorization decision taken
against nothing. Exercises: the only genuine relay hop in the corpus, plus
`x-alias`, plus the same identity in a body field and a path parameter of
one request. Caveat: the Gate→Orca hop must be annotated on a field that the
declared `Map` body does not name.

### 3. `clientRequestId` — Orca → Clouddriver *(two nodes, silent break)*

| | service | endpoint | field | kind |
|---|---|---|---|---|
| mint | orca | `POST /{cloudProvider}/ops` | `clientRequestId` (`String`, query) | param |
| sink | clouddriver | `POST /{cloudProvider}/ops` | `clientRequestId` (`@RequestParam(required=false)`) | param |

**Breaks in practice**: Clouddriver substitutes a random UUID, Orca retries
three times, and each retry executes the cloud operation again — duplicate
server groups, duplicate deletes. No error anywhere, visible only in the
cloud provider's bill. Exercises: a *declared-optional* sink whose optionality
is exactly the hazard, which is the strongest argument in the corpus for the
`declared` vs `none` presence profiles of D4.

### 4. `artifactAccount` (+ `type`) — Orca → Clouddriver and Rosco → Clouddriver *(one sink, two providers)*

| | service | endpoint | field | kind |
|---|---|---|---|---|
| mint A | orca | `PUT /artifacts/fetch/` | `artifactAccount` in `@Body Artifact` | body |
| mint B | rosco | `PUT /artifacts/fetch/` | `artifactAccount` in `@Body Artifact` | body |
| sink | clouddriver | `PUT /artifacts/fetch` | `artifactAccount`, `type` in `@RequestBody Artifact` | body |

**Breaks in practice**: every manifest deploy and every Helm or Kustomize
bake fails with a credentials error; loud and immediate, which makes it the
best control case against the three silent chains above. Exercises: two
independent simple paths into one sink, a two-field composite key, and a
caller-side precondition (Orca refuses to send a null `artifactAccount`).

### 5. `source.executionId` — Orca → Echo *(typed on both sides, nested)*

| | service | endpoint | field | kind |
|---|---|---|---|---|
| mint | orca | `POST /notifications` | `source.executionId` in `@Body Notification` | body |
| sink | echo | `POST /notifications` | `source.executionId` in `@RequestBody Notification` | body |

**Breaks in practice**: FreeMarker dereferences the field unguarded when
rendering the execution deep link, so a missing value fails the render and
the notification is never delivered — including manual-judgment
notifications, which means a human never learns a pipeline is blocked on
them. Exercises: a nested object field, structurally identical model classes
on both sides of one edge, and the cheapest possible annotation.

### Alternates, if five is too many or one of the above is dropped

* **`application` + `parentPipelineExecutionId` — Echo → Orca → Kayenta**
  (§4). A second relay chain, with a clean rename
  (`execution.id` → `parentPipelineExecutionId`) and a typed, `@NonNull`
  source field on the Echo hop. Weak sink: Kayenta stores the value and hands
  it back, so the break is a lost join in the canary history rather than a
  failure.
* **`X-SPINNAKER-USER` — Gate → Keel → {Orca, Clouddriver, Front50, Echo}**
  (§11). The only header chain that is *declared* at both ends — Keel
  declares it on 35 client methods and requires it on 27 controller methods —
  so it is annotatable if D6's `headers` folding is used. Excluded from the
  top five only because Gate, the minter, does not declare it, so the chain
  has no visible source.

## Notes for the reviewer on R1

R1 requires that "every chain names a field at every hop that exists in
`endpoints.tsv`". Two caveats on applying it to the list above.

Three of the five recommended chains name a **parameter**, not a body field,
at one or more hops (`clientRequestId` at both hops, `correlationId` at the
read-back hop, `applicationName` at the Front50 hop). These exist in
`endpoints.tsv` under `query_params` / `path_params`, not `body_type`, so
R1's field-existence check has to look in those columns too, and D6's
`params` folding has to be applied before the chain is judged.

One recommended chain (`application`, rank 2) names a field at the Gate→Orca
hop that does **not** appear in any declared type, because the declared body
is `Map<String, Object>`. If R1 is applied literally, rank 2 fails the check
and should be dropped to the alternates in favour of the Echo→Orca→Kayenta
chain, whose every hop is declared. This is a decision for the review pass,
not for me.
