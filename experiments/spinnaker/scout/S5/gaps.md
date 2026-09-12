# S5 — checker fit: constructs, loader behaviour, projection conventions, costs

**Sample.** `spinnaker/gate@v6.69.0`, `spinnaker/orca@v8.64.0`,
`spinnaker/front50@v2.41.0`, `spinnaker/clouddriver@v5.95.0`, shallow-cloned
at those tags. `count` is the number of matching lines under `*/src/main/*`
in `.java`, `.groovy` and `.kt` across those four repositories — an
occurrence count, **not** an endpoint count, and **sample only**: the review
replaces every number here with the S2 census. `loader_today` cites
`gus@main`. `cost` is one estimate covering whichever route the row
recommends (projection or checker); rows that name both give both.

Approximate endpoint scale in the sample: 668 method-level Spring mappings,
532 Retrofit method annotations.

| construct | count | loader_today | projection_convention | checker_change | cost | claim |
|---|---|---|---|---|---|---|
| Spring endpoint (method-level mapping) | 668 | `Load` walks `paths` × the seven methods and keys each on `{Path, Method}` — `pkg/schema/loader.go:120-149` | one path item per mapping; class-level `@RequestMapping` value concatenated with the method-level one, leading slash forced | no | 0h (inside G1) | CLAIM-S5-030 |
| `@PathVariable` | 509 | **ignored silently**: `operationObj` (`loader.go:182-186`) declares no `parameters` field, so an OpenAPI `parameters:` block is dropped without error | fold into the request object as `params.<name>`, `required: true` (D6) | no | 2h | CLAIM-S5-001 |
| `@RequestParam` (all) | 370 | as above | `params.<name>`; `required` from the annotation | no | 1h | CLAIM-S5-001 |
| `@RequestParam(required=false)` | 234 | as above | `params.<name>` absent from `required` | no | 0h | CLAIM-S5-001 |
| `@RequestParam(defaultValue=…)` | 111 | `default:` sets `Field.HasDefault` (`loader.go:494-496`), which suppresses REQ.1 and REQ.2 (`pkg/compat/compat.go:535,551`) | emit `default:` — only its presence is read, not its value | no | 0h | CLAIM-S5-031 |
| `@RequestHeader` (gate only) | 48 | ignored, as `@PathVariable` | `headers.<name>` sub-object of the request (D6) | no | 1h | CLAIM-S5-001 |
| `@RequestBody` | 117 | request read **only** from `content["application/json"]` — `loader.go:138` | `requestBody.content.application/json.schema` | no | 0h | CLAIM-S5-002 |
| `Map<String, Object>` body or return | 2016 | `additionalProperties: true` → open Object with no fields (`loader.go:521-524`); such an object yields no violation in either direction (REQ.1/REQ.4/RES.1/RES.5 all vacuous) | `{type: object, additionalProperties: true}`; count the endpoint **untyped** (D5) | no | 0h | CLAIM-S5-009 |
| `Map<String, String>` and other typed maps | 1004 | `additionalProperties` **as a schema** on a property-less object → `types.Map` (`loader.go:526-538`); `checkMap` compares key kind and value type (`compat.go:483-497`) | `additionalProperties: {type: string}`; count **typed** — see D5 note below | no | 1h | CLAIM-S5-032 |
| `List<Map…>` / `Collection<Map…>` | 817 | `array` → `types.Array(items)` (`loader.go:445-450`) | `{type: array, items: <map projection>}` | no | 0h | CLAIM-S5-033 |
| raw `Map` / raw `List` (no type args) | 1510 | same as `Map<String,Object>` | open object / array-of-open-object; **untyped** (D7) | no | 0h | CLAIM-S5-034 |
| Retrofit `Call<Map>` / `Call<List<Map>>` (raw) | 123 | as above, on the caller side | same; these are the caller half of D5's untyped share | no | 0h | CLAIM-S5-015 |
| bare `Object` field or parameter | 329 | a schema with no `type` and no `properties` → `types.Any` (`loader.go:460-462`), and `Any` short-circuits every comparison (`compat.go:71-73`) | **`{type: object, additionalProperties: true}`, never `{}`** — an open object still gives `kind-mismatch` against a scalar; `{}` passes everything | no | 0.5h | CLAIM-S5-007 |
| `JsonNode` / `ObjectNode` / `ArrayNode` | 67 | as bare `Object` | open object; untyped | no | 0h | CLAIM-S5-035 |
| `@JsonTypeInfo` + `@JsonSubTypes` on the class | 9 / 7 | `oneOf` → `types.Union` with `Exclusive` (`loader.go:352-367`); `oneof-ambiguity` at `compat.go:243-254` | `oneOf` over the subtypes, discriminator a **closed one-value enum** in each variant — otherwise two open-object variants admit each other and `oneof-ambiguity` fires on every payload | no | 3h | CLAIM-S5-036 |
| `@JsonTypeInfo` declared in a **mixin**, registered by a Jackson module | 2 modules | loader sees only the document | the extractor must read the annotations through an `ObjectMapper` with the service's `SimpleModule`s registered, not by reflecting the model class — clouddriver's `CredentialsDefinitionMixin` and front50's `PipelineMixins` are invisible to plain reflection | no (extractor) | 8–16h | CLAIM-S5-010, CLAIM-S5-011 |
| subtypes registered at runtime from Spring beans | 1 (`AccountDefinitionModule`) | n/a | not statically enumerable: project the base as an open object and count it untyped | no | 0h (accepted loss) | CLAIM-S5-012 |
| `@JsonTypeInfo(use = Id.CLASS)` | 6 | as `oneOf` above | discriminator values are fully-qualified class names; a package move then reads as `enum-request-narrowing`, which is correct but noisy | no | 0h | CLAIM-S5-024 |
| Jackson inheritance **without** `@JsonTypeInfo` (`class X extends Y`) | 987 | **`allOf` is a hard error** — `loader.go:342` | flatten the superclass's properties into the subclass schema at extraction time (no `allOf` in any emitted document). This is the single mandatory projection convention. | no under the convention; yes if `allOf` must be supported (`pkg/schema/loader.go:340-343` plus a merge pass) | 2h projection / ~12h checker | CLAIM-S5-004 |
| `@JsonInclude(NON_NULL)` (class/field) | 83 | nothing: the loader has no notion of "omitted when null" | on the **return** side a NON_NULL field is optional-and-never-null: leave it out of `required` and do **not** mark it `nullable` | no | 1h | CLAIM-S5-037 |
| global `setSerializationInclusion(NON_NULL)` (orca) | 1 | as above, mesh-wide for orca | apply the rule above to every orca return field; otherwise `nullable-response-widening` (`compat.go:212-218`) fires for a null that never reaches the wire | no | 0h | CLAIM-S5-014 |
| `@JsonAnyGetter` / `@JsonAnySetter` | 60 | named properties **plus** an `additionalProperties` schema is an error (`loader.go:531`); `additionalProperties: true` beside properties is fine (`loader.go:521-524`) | keep the named properties and set `additionalProperties: true`; the any-map's value type is dropped | no | 0h | CLAIM-S5-005 |
| `@JsonProperty(required = true)` | **0** | `required` list → `Field.Required` (`loader.go:476-479`) | nothing to project — this leg of D4's *Declared* profile contributes nothing on this corpus | no | 0h | CLAIM-S5-017 |
| `@JsonProperty("wireName")` rename | 553 | property names are matched by string only (`compat.go:531-566`) | use the annotation value as the property name | no | 0h | CLAIM-S5-038 |
| `@JsonAlias` | 10 | `x-alias` is read on object properties (`loader.go:504-507`) and used by the **chain** resolver only, not by the pair relation | emit `x-alias`; a rename still reads as one field dropped + one added in REQ/RES | yes if a rename should be non-breaking in the pair relation: `pkg/compat/compat.go:531-566` would have to consult `Field.XAlias` | 0h chains / 6h pair relation | CLAIM-S5-039 |
| `@JsonIgnore` / `@JsonIgnoreProperties` | 335 | n/a | drop the property | no | 0h | CLAIM-S5-040 |
| `@JsonIgnoreProperties(ignoreUnknown = true)` | 62 | open is the default (`loader.go:521`) | `additionalProperties: true`; note its **absence** does not mean closed, because Spring Boot disables `FAIL_ON_UNKNOWN_PROPERTIES` | no | 0h | CLAIM-S5-041 |
| custom `@JsonSerialize` / `@JsonDeserialize` | 74 | n/a — the declared Java type is not the wire type | not derivable: project as an open object and count untyped, or hand-maintain a per-serializer table | no | 0h + a table | CLAIM-S5-042 |
| `@JsonValue` (object serialized as a scalar) | 3 | n/a | project as the scalar the `@JsonValue` accessor returns | no | 1h | CLAIM-S5-043 |
| Java `enum` | 175 declarations | `enum` → `types.Enum` with `EnumBase` (`loader.go:414-425`); narrowing/widening rules at `compat.go:455-473` | closed `enum:` of constant names — **but see D8: not closed in orca** | no | 2h | CLAIM-S5-044 |
| Kotlin `T?` | 335 | `nullable: true` → `types.Nullable`; rules at `compat.go:203-219` | direct | no | 0h | CLAIM-S5-045 |
| Kotlin non-null ctor param, no default | 161 | `required` list | `required: [name]` | no | 0h | CLAIM-S5-046 |
| Kotlin ctor param with a default | 252 | `HasDefault` suppresses REQ.1/REQ.2 | emit `default:` (value irrelevant) | no | 0h | CLAIM-S5-031 |
| Java primitive parameter/field (`int`, `long`, `boolean`) | 1035 | `required` list | required on the **return** side (D4); on the accept side a primitive with `@RequestParam(required=false, defaultValue=…)` is **not** required | no | 0h | CLAIM-S5-020 |
| Java boxed type, unannotated | — | n/a | neither `nullable` nor `required`; counted unknown (D8) | no | 0h | CLAIM-S5-047 |
| `@Nullable` / `@Nonnull` (Java) | 646 | `nullable: true` | direct | no | 0h | CLAIM-S5-047 |
| validation annotations (`@NotNull`, `@Size`, …) | 177 | `required` list | `required: true` **only when the enclosing parameter carries `@Valid`/`@Validated`** — otherwise Spring never runs the validator and the annotation is documentation | no | 1h | CLAIM-S5-018 |
| `@Valid` / `@Validated` | 11 | as above | the gate on the row above | no | 0h | CLAIM-S5-018 |
| `ResponseEntity<T>` | 77 | only the lowest 2xx `application/json` response is read (`loader.go:605-632`) | unwrap to `T` under `"200"` | no | 1h | CLAIM-S5-003 |
| `ResponseEntity` with a runtime-chosen status | 5 | codes other than the lowest 2xx are dropped | drop and count (D6) | no | 0h | CLAIM-S5-003 |
| `ResponseEntity<Void>` / void return | 7 Retrofit + many controllers | no `application/json` response → `Response = nil` (`loader.go:626-631`); `nil` against a non-`nil` is a BREAK — `presence-mismatch`, `compat.go:62-68` | emit a `"200"` with **no** `content` on **both** caller and provider, so both sides are `nil`; any asymmetry is a spurious break | no (a "treat nil as Any" change would weaken checking) | 1h projection / 2h checker, not recommended | CLAIM-S5-048 |
| Retrofit `Call<ResponseBody>` (opaque stream) | 73 | as above | `"200"` with no content on both sides | no | 0h | CLAIM-S5-025 |
| multipart / form-urlencoded request | 7 | no `application/json` request content → `Request = nil` (`loader.go:137-145`) | omit the request body; count the endpoint body-untyped | no | 0h | CLAIM-S5-022 |
| non-JSON response (`application/x-yaml`, octet-stream, `text/plain`) | 20 | as above | `"200"` with no content on both sides | no | 0h | CLAIM-S5-049 |
| `Mono` / `Flux` | **0** | n/a | none needed | no | 0h | CLAIM-S5-021 |
| `DeferredResult<T>` / `Callable<T>` | 62 | n/a | unwrap to `T` | no | 0.5h | CLAIM-S5-050 |
| `Optional<T>` accessor | 105 | no `Optional` notion | unwrap to `T`, leave out of `required`, mark `nullable` under D8 | no | 0.5h | CLAIM-S5-051 |
| Map-subclass model (`X extends HashMap<String,Object>`) | 16 | named properties **plus** an `additionalProperties` schema is an error (`loader.go:531`) — and that is exactly this shape | open object with the subclass's declared properties and `additionalProperties: true`; the map's value schema is dropped | no as projected; yes to model object-with-value-schema (`pkg/types/types.go:52-88`, `pkg/compat/compat.go:501-520`) | 1h projection / ~8h checker | CLAIM-S5-023 |
| `implements Map<K,V>` / `ForwardingMap` | 2 | as above | as above | no | 0h | CLAIM-S5-023 |
| recursive model type (`StageExecution.getParent()`) | ≥1 confirmed | cycle back-edge → `types.Ref` (`loader.go:306-312`); `ref-name-mismatch` compares the **local** component name across services (`compat.go:270-296`) | name components after the Java simple class name so both documents agree at the back-edge | no | 1h | CLAIM-S5-019 |
| interface-typed body/return (`PipelineExecution`, `StageExecution`, `Trigger`) | 477 interface declarations | no notion of an interface | project the interface's Jackson-visible getters, or `oneOf` over implementations where they are registered | no | 3h | CLAIM-S5-019 |
| Groovy `def` (untyped) field | 3743 | as bare `Object` | open object; untyped | no | 0h | CLAIM-S5-052 |
| Lombok `@Getter`/`@Setter`/`@Data` | 1464 | n/a | none — but source parsing does not see the generated accessors while reflection over compiled classes does; this is the corpus evidence for D1 | no | 0h | CLAIM-S5-009 |
| versioned path (`/v1`, `/v2`, …) | 147 | the path is an opaque exact-match string (`EndpointKey`, `loader.go:56-59`) | D3 normalization happens entirely in the projection; both sides must be rewritten identically | no | 2h | CLAIM-S5-053 |
| path variable with a regex (`{id:.+}`) | 79 | as above | strip the regex and erase the variable name before matching | no | 1h | CLAIM-S5-020 |
| Retrofit path with an embedded query string | 13 | the `?…` becomes part of the path key and can never match a provider path | split at `?`; move the fixed pairs into `params` with `default:` | no | 1h | CLAIM-S5-016 |
| caller declares an endpoint the provider does not expose | S1 to count | **hard input error**: `endpoint %s %s not found in provider` (`cmd/gus/main.go:1097`), exit 2 — not a finding | drop the edge from `graph.yaml` and report it on a separate channel, as `boutique-proto` does for RPC additions and removals | yes to make it a finding: `cmd/gus/main.go:1090-1098` plus a new rule | 0.5h projection / 4h checker | CLAIM-S5-006 |
| `@Deprecated` endpoint or field | 171 | no representation | record out of band | no | 0h; a `deprecated: true` keyword raising a WARN would be ~4h | CLAIM-S5-054 |
| springdoc `@Operation` / `@Schema` | 262 | n/a | usable for descriptions; not needed for checking | no | 0h | CLAIM-S5-055 |
| numeric format (`int32`/`int64`/`double`) | — | `Prim.Format`; `FormatLeq` widens `int32→int64` and `float→double` only, and a mismatch is **WARN**, not BREAK (`pkg/lattice/lattice.go:88-101`, `compat.go:405-410`) | emit `format:` from the Java type | no | 0.5h | CLAIM-S5-056 |
| date/time (`JavaTimeModule`, `@JsonFormat`) | 2 explicit + module | `format` is unconstrained when it differs and is not a listed widening — WARN only | `type: string, format: date-time`; a switch to epoch millis then reads as `string`→`integer`, a correct `prim-mismatch` BREAK | no | 0.5h | CLAIM-S5-057 |
| identity carried in a path/query/header (chains) | — | `x-provides`/`x-requires`/`x-alias` are read **only on object properties** (`loader.go:498-507`), never on a top-level schema or a parameter | any identity travelling in a path variable, query parameter or header must live inside the synthetic `params`/`headers` object; this constrains D6 as much as D9 does | no | 0h | CLAIM-S5-008 |

**Rows requiring a checker change: three, all with a cost and all with a
projection alternative.** `allOf` (2h projection / 12h checker), the
unmatched-endpoint finding (0.5h / 4h), and object-with-value-schema for
Map-subclass models (1h / 8h). Everything else is absorbed by convention.

---

## The plan's decisions D4–D8 against the sample

### D4 — Presence (the `required` list): keep both profiles, add two rules

Supported in shape, but the *Declared* profile is nearly empty on this
corpus and two of its four legs need repair.

* `@JsonProperty(required = true)`: **zero occurrences** in all four
  repositories (CLAIM-S5-017). That leg contributes nothing.
* Validation annotations: 177 occurrences, but only 11 `@Valid`/`@Validated`
  (CLAIM-S5-018). Without `@Valid` on the `@RequestBody` parameter Spring
  never runs the validator, so `@NotNull` on a body field does not make the
  field required at the wire. **Change:** count a validation annotation as
  `required` only when the enclosing parameter carries `@Valid`.
* Kotlin non-null constructor parameters without defaults: 161, concentrated
  in orca (114) and largely in queue and persistence types rather than
  controller models. S2 must say how many sit on the wire.
* Java primitives on the return side: 1035 — the one leg that carries weight.
* **Change, new rule:** `@JsonInclude(NON_NULL)` (83 sites) and orca's global
  `setSerializationInclusion(NON_NULL)` (CLAIM-S5-014) mean a null field is
  *absent*, not null. On the return side such a field must be projected
  **optional and non-nullable**; projecting it `nullable` produces
  `nullable-response-widening` findings for a value that never appears.

Expect *Declared* and *None* to differ far less here than in the
OpenTelemetry run. Report that gap rather than letting it look like signal.

### D5 — Openness: supported, with one reclassification and one fix

Openness everywhere is right: Spring Boot disables
`FAIL_ON_UNKNOWN_PROPERTIES` by default, orca disables it explicitly
(`OrcaObjectMapper.java:56`), and 62 classes say `ignoreUnknown = true`.

* **Change:** D5 counts `Map<String, Object>` **and** typed maps alike as
  untyped. `Map<String, String>` alone is 1004 occurrences, projects to
  `types.Map`, and is genuinely compared by `checkMap` (`compat.go:483-497`).
  Counting it untyped discards a checkable construct and inflates the untyped
  share against the 50% NO-GO threshold. Define *untyped* as `Object`,
  `JsonNode`, raw `Map`, raw `List`, `Map<String,Object>` and
  `List<Map<String,Object>>`; a `Map<String,X>` with concrete `X` is typed.
* **Change:** state that `Object` projects to
  `{type: object, additionalProperties: true}` and never to `{}`. An empty
  schema becomes `types.Any` (`loader.go:460-462`), and `Any` short-circuits
  every comparison (`compat.go:71-73`) — an `Object` → `String` change would
  pass silently.

### D6 — Parameters: supported and necessary; three refinements

The fold is not optional. `operationObj` has no `parameters` field
(`loader.go:182-186`), so a `parameters:` block is dropped **silently** — the
one place where the loader's usual "fail loudly" discipline does not apply.
509 path variables, 370 query parameters and 48 headers depend on the fold.

1. **Wrap the payload.** Do not put `params` and `headers` beside the body's
   own properties: a body field named `limit` and a query parameter named
   `limit` collide, and for a `Map`-typed body the loader errors outright on
   named properties beside an `additionalProperties` schema
   (`loader.go:531`). Emit `{properties: {params, headers, body}}` uniformly,
   with the payload under `body`. Cost 2h; it also fixes the Map-subclass row.
2. **Split Retrofit paths that carry a literal query string** (13 in the
   sample, e.g. `@GET("/v2/applications?restricted=false")`,
   CLAIM-S5-016). Left unsplit, the `?` is part of the endpoint key and the
   edge can never match the provider.
3. **Be symmetric about empty responses.** Dropping non-lowest-2xx responses
   is safe, but an endpoint with no JSON response yields `Response = nil`,
   and `nil` against a schema is a `presence-mismatch` BREAK
   (`compat.go:62-68`). 73 `Call<ResponseBody>` plus every void endpoint make
   this a live hazard: caller and provider must both emit a contentless 200.

### D7 — Polymorphism and generics: supported for the class-annotated case; two gaps

`@JsonTypeInfo` is rare (9 in the sample), so `oneOf` is cheap.

* **Change:** require the discriminator to be a **closed one-value enum** in
  each variant. Two open-object variants admit each other's values, and
  `oneof-ambiguity` (`compat.go:243-254`) then fires on every payload.
* **Change, the expensive one:** D7 assumes the annotations sit on the class.
  In clouddriver they sit on a **mixin** registered by a Jackson module, and
  the subtypes are registered from Spring beans at runtime
  (CLAIM-S5-012); front50's `Pipeline` gets its open-ness the same way
  (CLAIM-S5-010, CLAIM-S5-011). Reflecting the model class sees neither. The
  extractor must drive an `ObjectMapper` with the service's modules
  registered and read the resulting configuration. 8–16h, and the plan does
  not budget it. Where subtypes come from beans, accept the loss and count
  the base untyped.
* **Change:** say something about plain inheritance. 987 `class X extends Y`
  in the sample, and the default jsonschema-generator output for that is
  `allOf`, which the loader rejects outright (`loader.go:342`). Flattening is
  mandatory, not optional.
* Generics: "raw types count as untyped" is right and load-bearing — 1510
  raw `Map`/`List` sites plus 123 raw Retrofit returns.

### D8 — Nullability and enums: nullability supported; the enum claim is falsified for orca

Nullability is fine: 335 Kotlin `T?`, 646 Java `@Nullable`/`@Nonnull`, and
the checker has the matching rules (`compat.go:203-219`). Keep "boxed and
unannotated counts as unknown".

The enum half does not hold. `OrcaObjectMapper.java:57` enables
`READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`, so orca's read side accepts
an unknown enum value and substitutes the type's default rather than failing
(CLAIM-S5-013); gate's Gremlin mapper enables
`READ_UNKNOWN_ENUM_VALUES_AS_NULL` (CLAIM-S5-058). "The first corpus with
real closed enums" is not true wherever those mappers are in force.

**Change.** Make closedness a per-service projection flag read from the
service's `ObjectMapper` configuration — closed by default, open where the
feature is enabled — and check the remaining six services before claiming
closed enums anywhere. Where a service is open, split by direction, which
costs no checker change and is the honest reading:

| side | projection for an enum-typed field |
|---|---|
| Accept (what the service reads) | `type: string` — open, so `enum-request-narrowing` cannot fire into it |
| Return (what the service writes) | closed `enum:` of the constants — `enum-response-widening` out of it is still real |
