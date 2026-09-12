# Handoff — G1, the contract extractor

For one Opus session at maximum effort. Self-contained: read this file, then
the files it names, in that order. Repository: `github.com/pronei/gus-mss-poc`,
branch `experiments`, directory `experiments/spinnaker/`. Everything you write
goes under `experiments/spinnaker/extractor/` (source, tests, golden files,
`memo.md`, `decisions.md`). You do not modify the checker (`pkg/`, `cmd/`),
any scout report, the review, or the plan.

## Read first

1. `PLAN.md` §4 (decisions D1, D3–D8, D12 as revised) and §6 (changelog).
2. `scout/review.md`: R3, R4, "First task for G1", and "Review pass 2".
3. `scout/S5/gaps.md` (every construct with the projection convention decided
   for it) and `scout/S2/typing-census.md` (what the model classes look like).
4. `scout/S2/endpoints.tsv` (748 rows: the provider surface at BOM 1.38.0,
   parsed from source — your acceptance oracle for the endpoint set) and
   `scout/S1/tools/mesh.tsv` (interface → provider binding, incl. KORK rows).
5. The checker's input contract: `README.md` at the repository root, and
   `pkg/schema/loader.go` (what loads, what is a hard error: `allOf`, an object
   mixing properties with an `additionalProperties` schema, `parameters:`
   blocks are ignored silently).
6. `scout/S3/artifacts.md` §classpath layout (what G2 hands you).

## What you build

A Java 17 tool (`extractor/`), built with a pinned build (Gradle wrapper or
Maven, versions pinned, no snapshot dependencies), that takes

    --classpath <dir>     G2's layout: bin/<svc> (start script), lib/*.jar
    --service <name>      gate | orca | clouddriver | front50 | echo | igor | fiat | rosco | kayenta
    --out <file.yaml>

and writes one OpenAPI 3.0 YAML document for that service at that version:
provider endpoints from Spring MVC annotations, caller endpoints from Retrofit
interfaces, schemas from the service's own Jackson view. No source parsing.

JDK: none is installed on the host. Unpack a portable JDK 17 (Temurin tarball)
under `experiments/spinnaker/.jdk/` and add that path to `.gitignore`; never
install system packages. Dependencies come from Maven Central; pin them.

## Rules that are already decided (do not re-decide)

Class loading. Build the class loader from the jars in the order of the
`CLASSPATH=` line inside `bin/<svc>`, never from file names (jars are
unversioned before 1.28; naming flips at the gcr.io/GAR boundary).

Provider endpoints. A class with `@RestController`/`@Controller`; each mapping
annotation (`@RequestMapping`, `@GetMapping`, …) with class prefix + method
path, leading slash forced, several paths or methods → several endpoints,
`consumes`/`produces` inherited from the class. Emit path, method, and:

- request object `{type: object, properties: {params, headers, body}}` —
  `params.<name>` for every `@PathVariable` (required) and `@RequestParam`
  (required unless `required = false` or `defaultValue`, which emits
  `default:`); a catch-all `Map`/`MultiValueMap` parameter makes `params`
  an open object; `headers.<name>` for `@RequestHeader`; the `@RequestBody`
  type under `body` (JSON only; multipart → no `body`);
- response: the lowest 2xx (`@ResponseStatus` or 200) with the return type
  unwrapped from `ResponseEntity`/`HttpEntity`/`DeferredResult`/`Callable`/
  `Optional`; a contentless `200` for `void`, `Void`, `byte[]`,
  `StreamingResponseBody` and non-JSON `produces`.

Caller endpoints. Every Retrofit interface (retrofit and retrofit2 annotations)
compiled into the service, including `FiatService` from fiat-api and the
kork-plugins `Front50Service`; provider from `scout/S1/tools/mesh.tsv`; emitted
as `x-role: client` endpoints under `/_calls/<provider><path>` with `@Path`/
`@Query`/`@Header` folded into `params`/`headers`, `@Body` under `body`,
`Call<T>` unwrapped, `Call<ResponseBody>`/Retrofit-1 `Response`/`Void`
contentless, baked-in query strings split into `params` with `default`,
relative paths given a leading slash. Parameter names: the annotation value,
else `LocalVariableTable`, else flag the endpoint (`MethodParameters` is absent
in every jar).

Schemas. Generated through the service's own configured `ObjectMapper`:
instantiate the service's Jackson modules found on the classpath (Front50:
`Front50ApiModule` with `PipelineMixins`/`TimestampedMixins`; Keel-style
introspectors exist elsewhere) and read mixins, introspectors and registered
subtypes through it; bean-registered subtypes are an accepted loss, counted.
Then, per D5–D8:

- inheritance flattened into the subclass (never `allOf`);
- `Object`, `JsonNode`, raw `Map`/`List`, `Map<String,Object>` →
  `{type: object, additionalProperties: true, x-untyped: true}`, never `{}`;
- `Map<String,X>` with concrete `X` → `additionalProperties: <X>` (typed);
- Map-subclass models (`PipelineTemplate`, `Notification`) → open object with
  their declared properties, `additionalProperties: true`, `x-untyped: true`;
- `@JsonTypeInfo` → `oneOf` over registered subtypes, discriminator a
  one-value closed `enum` per variant; `Id.CLASS` values are FQCNs;
- `@JsonInclude(NON_NULL)` fields, and every field of a service whose MVC
  mapper is globally NON_NULL (Orca, Clouddriver, Kayenta), optional and not
  nullable on the return side;
- Kotlin `T?` and `@Nullable` → `nullable: true`;
- Java enums closed (`enum:` values) except where D8 lists the side open
  (Orca's accept side; every `FiatService` caller's expect side; Rosco's
  Clouddriver client), which projects as `type: string`;
- property names from `@JsonProperty`; `@JsonIgnore` dropped;
  `@JsonAnySetter`/`@JsonAnyGetter` → `additionalProperties: true`;
- Java primitives on the return side are `required` (the only *declared*
  presence signal on the nine-service mesh); nothing else is required unless
  `@JsonProperty(required = true)` (zero occurrences) or a validation
  annotation under `@Valid`/`@Validated` on the accept side;
- every untyped side carries `x-untyped: true` so that G3 can classify legs
  (live / vacuous / untyped) without Java.

Recursive types: emit `$ref` to `components/schemas`; the loader handles cycles.

## First task and acceptance

Front50 at 2.41.0 (G2 lays out `corpus/1.38.0/front50/`; until G2 delivers,
pull the single `/opt/front50` layer of image
`us-docker.pkg.dev/spinnaker-community/docker/front50:2.41.0` yourself into a
gitignored scratch directory — the digest is in `scout/S3/boms.tsv`).

Acceptance, all mechanical, kept as tests:

1. `gus` (build it with `go build ./cmd/gus` at the repository root) loads the
   document without error.
2. The provider endpoint set equals S2's 90 Front50 rows on (method,
   normalized path); differences are listed and each one explained.
3. Golden YAML matches for: `GET /pipelines` (five optional query params, two
   with `default`; array of an open `Pipeline` object); `PATCH
   /v2/applications/{applicationName}` (required path param, `Application`
   body and return); `GET /pipelineTemplates/{id}` (Map subclass → open
   object, `x-untyped`); `POST /pluginBinaries/…` (multipart → no body;
   `ResponseEntity<byte[]>` → contentless); one `@JsonInclude(NON_NULL)` field
   projected optional and non-nullable.
4. Second task, same service: the caller side, including the kork
   `Front50Service` (three methods) and `FiatService` (nine).
5. Third task: Gate at 6.69.0 and Orca at 8.64.0, then the 1.30.0 versions of
   all three, to prove the tool crosses the Java 11 → 17 and Retrofit 1 → 2
   boundaries.

## Report back

`extractor/memo.md`: what was built, every construct you met that the rules
above do not cover (one numbered claim each, `CLAIM-G1-NNN`, with the class
and jar), counts of flagged endpoints, and a last section titled
"## What I could not verify". `extractor/decisions.md`: every choice you had to
make that the rules left open, marked `needs owner` where it changes results.
Do not make these three decisions yourself; emit both variants behind a flag
if you must proceed: whether the kork `Front50Service` rows and the indirect
`FiatService` rows are in the graph (G3's call, pending the owner), and
whether the *declared* presence profile is kept.
