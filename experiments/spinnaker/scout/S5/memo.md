# S5 memo — checker fit

Sample: `gate@v6.69.0`, `orca@v8.64.0`, `front50@v2.41.0`,
`clouddriver@v5.95.0` (latest release tags on 2026-09-11), shallow-cloned.
Counts are grep occurrences under `*/src/main/*` in `.java`/`.groovy`/`.kt`
and are **sample only** — the review replaces them with the S2 census.
Checker facts are `gus@main` at `99e3c8c`.

## Verdict in three lines

Three constructs need a checker change; each has a projection alternative and
a cost (gaps.md). Everything else is convention. The two decisions that need
revising on evidence are **D8** (orca's enums are not closed) and **D5** (typed
maps are being miscounted as untyped, which pushes the untyped share toward
the 50% NO-GO threshold for no reason). **D7** hides the largest unbudgeted
extractor cost: Jackson polymorphism and open-ness live in runtime-registered
mixins, not on the model classes.

## What the loader does today

CLAIM-S5-001: `operationObj` declares no `parameters` field, so an OpenAPI
`parameters:` block is dropped silently rather than rejected.
source: gus@main pkg/schema/loader.go:182-186

CLAIM-S5-002: A request schema is read only from
`requestBody.content["application/json"]`; any other media type yields a nil
request. source: gus@main pkg/schema/loader.go:138

CLAIM-S5-003: The response schema is the first 2xx code, in sorted order, that
has `application/json` content; all others are dropped.
source: gus@main pkg/schema/loader.go:605-632

CLAIM-S5-004: `allOf` is a hard load error, not a degradation.
source: gus@main pkg/schema/loader.go:342

CLAIM-S5-005: An object that mixes named `properties` with an
`additionalProperties` **schema** is a hard load error.
source: gus@main pkg/schema/loader.go:531

CLAIM-S5-006: An edge whose path is absent from the provider's document fails
the run with `endpoint %s %s not found in provider`, so an unmatched caller
declaration is an input error rather than a finding.
source: gus@main cmd/gus/main.go:1097

CLAIM-S5-007: A schema with no `type` and no `properties` becomes `types.Any`,
and `Any` on either side returns no violations at all.
source: gus@main pkg/schema/loader.go:462 and pkg/compat/compat.go:71-73

CLAIM-S5-008: `x-provides`, `x-requires` and `x-alias` are read only on an
object's properties, never on a top-level schema.
source: gus@main pkg/schema/loader.go:498-507

CLAIM-S5-030: Endpoints are keyed on the exact `{Path, Method}` pair, so all
path normalization must happen in the projection.
source: gus@main pkg/schema/loader.go:56-59,120-149

CLAIM-S5-031: A property's `default` sets only `HasDefault`; the value is not
retained, and `HasDefault` suppresses REQ.1 and REQ.2.
source: gus@main pkg/schema/loader.go:494-496 and pkg/compat/compat.go:535,551

CLAIM-S5-032: `additionalProperties` as a schema on a property-less object
becomes `types.Map`, whose key kind and value type are then compared.
source: gus@main pkg/schema/loader.go:526-538 and pkg/compat/compat.go:483-497

CLAIM-S5-033: `type: array` recurses into `items`.
source: gus@main pkg/schema/loader.go:445-450

CLAIM-S5-034: `additionalProperties: true` beside named properties is accepted
and produces an open object. source: gus@main pkg/schema/loader.go:521-524

CLAIM-S5-035: A schema with `type: object` and no properties is an open object
with no fields, which yields no violation in either direction.
source: gus@main pkg/schema/loader.go:474-542 and pkg/compat/compat.go:526-614

CLAIM-S5-036: `oneOf` becomes an exclusive union, and a variant admitted by
more than one alternative is reported as `oneof-ambiguity`.
source: gus@main pkg/schema/loader.go:352-367 and pkg/compat/compat.go:246-252

CLAIM-S5-037: The loader has no representation for "omitted when null"; a
field is either in `required` or not, and `nullable` is separate.
source: gus@main pkg/schema/loader.go:474-512

CLAIM-S5-038: Object fields are matched by property name only.
source: gus@main pkg/compat/compat.go:531-566

CLAIM-S5-039: `x-alias` is carried on `Field.XAlias` and consumed by the chain
resolver; the pair relation never reads it.
source: gus@main pkg/types/types.go:91-98 and pkg/compat/compat.go:531-566

CLAIM-S5-040: A property absent from the document is simply absent from the
object. source: gus@main pkg/schema/loader.go:480-513

CLAIM-S5-041: Objects are open unless `additionalProperties: false`.
source: gus@main pkg/schema/loader.go:521-524

CLAIM-S5-047: `nullable: true` wraps the node in `types.Nullable`, and null
mismatches are direction-dependent BREAKs.
source: gus@main pkg/schema/loader.go:466-471 and pkg/compat/compat.go:203-219

CLAIM-S5-048: A schema present on one side only is a BREAK
(`presence-mismatch`); nil on both sides is silent.
source: gus@main pkg/compat/compat.go:60-69

CLAIM-S5-044: An `enum` becomes `types.Enum` with the declared type as
`EnumBase`; narrowing on request and widening on response are BREAKs.
source: gus@main pkg/schema/loader.go:414-425 and pkg/compat/compat.go:455-473

CLAIM-S5-059: A `$ref` cycle produces a `Ref` back-edge, and two `Ref`s are
compared by their service-stripped local names.
source: gus@main pkg/schema/loader.go:306-312 and pkg/compat/compat.go:270-296

CLAIM-S5-056: A format mismatch is WARN, not BREAK, and only `int32→int64` and
`float→double` widen. source: gus@main pkg/lattice/lattice.go:88-101 and
pkg/compat/compat.go:405-410

CLAIM-S5-057: An absent format on either side is unconstrained.
source: gus@main pkg/lattice/lattice.go:92-94

CLAIM-S5-055: A caller contract is found under `/_calls/<provider><path>` or
at the provider's plain path marked `x-role: client`.
source: gus@main cmd/gus/main.go:1117-1128

## What the corpus contains

CLAIM-S5-009: front50's `Pipeline` carries `Object config`,
`List<Map<String,Object>> stages` and `Map<String,Object> template`, and gets
its accessors from Lombok `@Getter`/`@Setter` rather than declared methods.
source: front50@v2.41.0 front50-api/src/main/java/com/netflix/spinnaker/front50/api/model/pipeline/Pipeline.java:40,51,56 (Lombok accessors at :36-56)

CLAIM-S5-010: `Pipeline`'s `@JsonAnyGetter`/`@JsonAnySetter` are declared on a
separate mixin class, not on `Pipeline`.
source: front50@v2.41.0 front50-core/src/main/java/com/netflix/spinnaker/front50/jackson/mixins/PipelineMixins.java:32,35

CLAIM-S5-011: That mixin is bound to `Pipeline` at runtime by a Jackson
module. source: front50@v2.41.0 front50-core/src/main/java/com/netflix/spinnaker/front50/jackson/Front50ApiModule.java:34

CLAIM-S5-012: clouddriver's `CredentialsDefinition` discriminator comes from a
mixin, and its subtypes are registered at runtime from Spring beans.
source: clouddriver@v5.95.0 clouddriver-core/src/main/java/com/netflix/spinnaker/clouddriver/jackson/AccountDefinitionModule.java:45,46 and .../jackson/mixins/CredentialsDefinitionMixin.java:32

CLAIM-S5-013: orca's shared ObjectMapper enables
`READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`, so orca accepts unknown enum
values instead of failing.
source: orca@v8.64.0 orca-core/src/main/java/com/netflix/spinnaker/orca/jackson/OrcaObjectMapper.java:57

CLAIM-S5-058: gate's Gremlin mapper enables
`READ_UNKNOWN_ENUM_VALUES_AS_NULL` and disables
`FAIL_ON_UNKNOWN_PROPERTIES`.
source: gate@v6.69.0 gate-integrations-gremlin/src/main/java/com/netflix/spinnaker/config/GremlinConfig.java:56,57

CLAIM-S5-014: the same orca mapper sets serialization inclusion to `NON_NULL`
and disables `FAIL_ON_UNKNOWN_PROPERTIES`, so a null orca field is absent from
the payload rather than serialized as null.
source: orca@v8.64.0 orca-core/src/main/java/com/netflix/spinnaker/orca/jackson/OrcaObjectMapper.java:56,58

CLAIM-S5-015: gate's Front50 Retrofit client returns raw `Map` and
`List<Map>`. source: gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/Front50Service.java:35,41

CLAIM-S5-016: one of its declarations bakes a query string into the path
template: `@GET("/v2/applications?restricted=false")`.
source: gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/Front50Service.java:37

CLAIM-S5-025: gate's Retrofit clients return `Call<ResponseBody>` for
endpoints with no JSON body (31 in gate, 42 in clouddriver).
source: gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/Front50Service.java:64,67

CLAIM-S5-029: gate declares `Call<ResponseEntity<Void>>`.
source: gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/EchoService.java:25

CLAIM-S5-017: `@JsonProperty(required = true)` occurs zero times in the four
repositories; the four apparent matches are the property name
`"requiredGroupMembership"`.
source: clouddriver@v5.95.0 clouddriver-aws/src/main/java/com/netflix/spinnaker/clouddriver/aws/security/AmazonCredentials.java:102

CLAIM-S5-018: validation annotations appear 177 times but `@Valid`/`@Validated`
only 11 times, so most of them are never enforced.
source: front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PipelineController.java (grep across the four repos, `*/src/main/*`)

CLAIM-S5-019: `StageExecution` is a Java interface with a self-returning
`getParent()` and no `@JsonIgnore`, and `PipelineExecution` holds
`List<StageExecution>` — a genuine reference cycle across two interfaces.
source: orca@v8.64.0 orca-api/src/main/java/com/netflix/spinnaker/orca/api/pipeline/models/StageExecution.java:173 and .../PipelineExecution.java:79

CLAIM-S5-020: front50 mixes regex path variables, primitive query parameters
with defaults, and boxed nullable query parameters in one endpoint.
source: front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PipelineController.java:113,114,164

CLAIM-S5-021: `Mono<` and `Flux<` occur zero times in the four repositories;
the mesh is blocking Spring MVC throughout.
source: grep across gate@v6.69.0, orca@v8.64.0, front50@v2.41.0, clouddriver@v5.95.0 `*/src/main/*`

CLAIM-S5-022: multipart appears in seven places, e.g. a plugin binary upload.
source: front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PluginBinaryController.java:45

CLAIM-S5-027: the same controller returns `ResponseEntity<byte[]>`.
source: front50@v2.41.0 front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PluginBinaryController.java:52

CLAIM-S5-026: gate serves YAML from two endpoints.
source: gate@v6.69.0 gate-web/src/main/groovy/com/netflix/spinnaker/gate/controllers/ManagedController.java:116,183

CLAIM-S5-023: sixteen model classes extend `HashMap`/`LinkedHashMap` and two
implement `Map` directly, so they carry declared properties **and** arbitrary
entries at once.
source: front50@v2.41.0 front50-core/src/main/java/com/netflix/spinnaker/front50/model/pipeline/PipelineTemplate.java:29 and orca@v8.64.0 orca-core/src/main/java/com/netflix/spinnaker/orca/pipeline/model/StageContext.java:29

CLAIM-S5-024: clouddriver uses `@JsonTypeInfo(use = Id.CLASS)`, so the
discriminator value is a fully-qualified Java class name.
source: clouddriver@v5.95.0 clouddriver-google/src/main/groovy/com/netflix/spinnaker/clouddriver/google/model/GoogleServerGroup.groovy:76

CLAIM-S5-028: gate marks endpoints `@Deprecated` in place, keeping the mapping.
source: gate@v6.69.0 gate-web/src/main/groovy/com/netflix/spinnaker/gate/controllers/ApplicationController.groovy:130-132

CLAIM-S5-042: `@JsonSerialize`/`@JsonDeserialize` appear 74 times, so 74 sites
have a wire shape that the declared Java type does not describe.
source: grep across gate@v6.69.0, orca@v8.64.0, front50@v2.41.0, clouddriver@v5.95.0 `*/src/main/*`

CLAIM-S5-043: `@JsonValue` appears three times, all in clouddriver.
source: grep across clouddriver@v5.95.0 `*/src/main/*`

CLAIM-S5-045/046: Kotlin nullable types occur 335 times and non-null
constructor parameters without defaults 161 times, 114 of them in orca.
source: grep across gate@v6.69.0, orca@v8.64.0, front50@v2.41.0, clouddriver@v5.95.0 `*/src/main/*`

CLAIM-S5-049: non-JSON response media types (`text/plain`, octet-stream,
YAML) appear 20 times. CLAIM-S5-050: `DeferredResult`/`Callable` 62 times.
CLAIM-S5-051: `Optional<T>` accessors 105 times. CLAIM-S5-052: Groovy `def`
3743 times. CLAIM-S5-053: version-prefixed paths 147 times. CLAIM-S5-054:
`@Deprecated` 171 times.
source: grep across gate@v6.69.0, orca@v8.64.0, front50@v2.41.0, clouddriver@v5.95.0 `*/src/main/*`

## What I could not verify

* **Every count is a grep occurrence count, not an endpoint count.** I did not
  parse Java, Groovy or Kotlin; a line can match twice, a class-level and a
  method-level `@RequestMapping` count alike, and test sources are excluded
  only by the `src/main` path filter. Nothing here should survive contact with
  the S2 census.
* **Six of the ten services were not sampled** — Echo, Igor, Fiat, Rosco,
  Kayenta and Keel. Keel is Kotlin-first and is the one most likely to change
  the Kotlin nullability and enum picture; Fiat's shared client library is in
  every service's classpath and I did not look at it.
* **kork was not read.** The shared Retrofit clients, the `SpinnakerRetrofit`
  configuration and any mesh-wide ObjectMapper customization live there, so
  the enum-openness and NON_NULL findings may be broader or narrower than the
  four repositories show.
* **The enum-openness finding is per-mapper, not per-service.** I confirmed
  which features `OrcaObjectMapper` and `GremlinConfig` set, but not which
  `ObjectMapper` bean Spring MVC actually uses for HTTP message conversion in
  each service. If the web converter uses a different mapper, D8 may hold for
  the wire even where these findings say it does not. This is the single
  weakest claim in the memo and should be settled by running one request
  through each service, not by reading configuration.
* **`@JsonInclude` propagation is unverified.** I did not check whether
  `NON_NULL` on a class also governs nested types, nor whether
  `spring.jackson.default-property-inclusion` is set in any deployed
  configuration (halyard-generated config was out of scope).
* **I did not run the checker on a Spinnaker-derived document.** Every
  statement about what the loader would do with a projected construct is read
  off the source, not observed. The one thing I did execute was a standalone
  probe confirming that `gopkg.in/yaml.v3` decodes unquoted integer and
  boolean YAML scalars into the loader's `[]string` enum field without error,
  so integer enums need no special quoting.
* **Costs are unvalidated estimates.** They assume the G1 extractor is
  jsonschema-generator plus the Jackson and Kotlin modules, as D1 proposes;
  the 8–16h mixin figure in particular is a guess at the work of driving the
  extractor through a configured `ObjectMapper` rather than raw reflection,
  and nobody has tried it.
* **I did not count how many caller declarations fail to match a provider
  path** (the `cmd/gus/main.go:1097` hazard). That number is S1's, and it
  decides whether the unmatched-endpoint row is a 0.5h projection note or a
  reason to build the finding into the checker.
