# S2 typing census — Spinnaker provider surface

Ten services at their latest release tag (see `memo.md` CLAIM-S2-001 for tags and
commits). 732 endpoint rows in `endpoints.tsv`, extracted by parsing Java, Groovy
and Kotlin source in the 228 files that carry `@RestController` or `@Controller`.

An *endpoint row* is one (HTTP method, resolved path template) pair. A mapping
annotation that declares several paths or several methods contributes one row per
combination, which is how Spring registers them; 732 rows come from 726
method-level mapping annotation sites.

## 1. Counts behind the `typing` column

Classification rule (per D5/D7, with the precedence stated because the vocabulary
is closed and one endpoint gets one value):

1. each side (request body / response body) is classified `none` (absent, `void`,
   `Unit`), `untyped`, `raw`, or `typed`;
2. `untyped` = `Map` and every parameterisation of it, `Object`, `Any`, `JsonNode`,
   Groovy `def`, `List`/`Collection`/`Set` whose element is one of those, and any
   named class that transitively extends `java.util.Map`;
3. `raw` = a generic container used without type arguments — `List`,
   `ResponseEntity`, `HttpEntity`;
4. precedence: `untyped-both` > `untyped-body` > `untyped-return` >
   `polymorphic` > `raw-generic` > `typed`. So `polymorphic` counts only
   endpoints that are *not* already untyped on either side; the last column of
   §1.1 gives the wider count of endpoints whose body or return graph reaches a
   `@JsonTypeInfo`.

`ResponseEntity`, `Mono`, `Flux`, `DeferredResult`, `Callable`,
`CompletableFuture` and `HttpEntity` are unwrapped before classification; the
`return_type` column in `endpoints.tsv` holds the unwrapped type.

### 1.1 Per service

| service | endpoints | typed | untyped-body | untyped-return | untyped-both | raw-generic | polymorphic | untyped share | reaches @JsonTypeInfo |
|---|---|---|---|---|---|---|---|---|---|
| gate | 278 | 83 | 8 | 132 | 25 | 30 | 0 | 70% | 0 |
| orca | 48 | 29 | 5 | 4 | 8 | 0 | 2 | 35% | 2 |
| clouddriver | 130 | 92 | 6 | 26 | 1 | 0 | 5 | 25% | 5 |
| front50 | 90 | 71 | 7 | 8 | 4 | 0 | 0 | 21% | 0 |
| echo | 14 | 11 | 1 | 1 | 0 | 0 | 1 | 14% | 1 |
| igor | 35 | 26 | 1 | 5 | 0 | 3 | 0 | 26% | 0 |
| fiat | 16 | 15 | 1 | 0 | 0 | 0 | 0 | 6% | 0 |
| rosco | 14 | 9 | 1 | 4 | 0 | 0 | 0 | 36% | 0 |
| kayenta | 48 | 18 | 2 | 16 | 1 | 0 | 11 | 40% | 12 |
| keel | 59 | 40 | 0 | 5 | 0 | 0 | 14 | 8% | 15 |
| **all ten** | **732** | **394** | **32** | **201** | **39** | **33** | **33** | **41.7%** | **35** |

*Untyped share* = (`untyped-body` + `untyped-return` + `untyped-both` +
`raw-generic`) / endpoints = 305/732 = **41.7%**, i.e. below the plan's 50%
threshold — but note the plan's §5 threshold is computed over S1's *resolved
edges*, not over endpoints, and Gate alone contributes 195 of the 305.

### 1.2 What makes a side untyped

Return side (157 untyped returns in Gate, 240 across the mesh; top entries):

| service | dominant untyped return types |
|---|---|
| gate | `Map` ×86, `List<Map>` ×34, `Collection<Map>` ×7, `List<Map<String,Object>>` ×5, `Any` ×5, `Map<String,Object>` ×4, `Map<String,Any>` ×3, `def` ×3 |
| clouddriver | `Map` ×5, raw `ResponseEntity` ×4, `Map<String,Object>` ×3, `Map<String,Set<SecurityGroupSummary>>` ×3, `Collection<Map>` ×2, `List<Map>` ×2 |
| front50 | `PipelineTemplate` ×4, `List<PipelineTemplate>` ×2, `Notification` ×2, `Map<String,List<PipelineTemplate>>` ×1, `Collection<Notification>` ×1, `Map<String,PluginInfo.Release>` ×1, `Map<String,Object>` ×1 |
| kayenta | `Map` ×10, `List<Map<String,Object>>` ×4, raw `ResponseEntity` ×1, `Map<String,String>` ×1, `List<Map>` ×1 |
| orca | `Map<String,Object>` ×5, `Map` ×3, `Map<String,String>` ×2, `List<Map<String,Object>>` ×2 |
| igor | `Map<String,Object>` ×2, `List<Map<String,Object>>` ×2, `Map` ×1 |
| keel | `Map<String,Any>` ×2, `Map<String,Map<String,String>>` ×2, `Map<String,Any?>` ×1 |
| rosco | `Map` ×2, `Map<String,Object>` ×2 |
| echo | `Map<String,Object>` ×1 |
| fiat | (none) |

Body side: `Map` ×36, `Map<String,Object>` ×11, `List<Map>` ×4,
`PipelineTemplate` ×4, `Map<String,String>` ×3, `List<Map<String,Map>>` ×3,
`List<Map<String,String>>` ×2, `Map<String,Boolean>` ×2, `Notification` ×2,
`Map<String,? extends Object>` ×1, `List<Notification>` ×1,
`List<Map<String,Object>>` ×1, `Object` ×1. All 71 untyped bodies come from those
forms; no service declares an untyped body any other way.

`raw-generic` is entirely Groovy raw `List` returns: 30 in Gate, 3 in Igor.

Front50's four `PipelineTemplate` and two `Notification` entries are the **Map
subclasses**: those two model classes extend `HashMap<String,Object>`, so an
endpoint declaring them is untyped in exactly the way a `Map` is, even though the
signature names a class.

## 2. Controller language and endpoint shape

| service | controller files | Java | Groovy | Kotlin | deprecated endpoints | `/vN` paths | `void` return | no request body | declares response codes | declares content types |
|---|---|---|---|---|---|---|---|---|---|---|
| gate | 73 | 26 | 41 | 6 | 12 | 35 | 38 | 222 | 19 | 23 |
| orca | 11 | 5 | 5 | 1 | 0 | 2 | 16 | 32 | 10 | 3 |
| clouddriver | 58 | 28 | 28 | 2 | 3 | 2 | 3 | 119 | 5 | 5 |
| front50 | 17 | 17 | 0 | 0 | 0 | 28 | 27 | 54 | 8 | 13 |
| echo | 7 | 6 | 1 | 0 | 0 | 0 | 2 | 8 | 4 | 1 |
| igor | 15 | 11 | 4 | 0 | 0 | 0 | 3 | 29 | 2 | 6 |
| fiat | 2 | 2 | 0 | 0 | 0 | 0 | 5 | 12 | 0 | 0 |
| rosco | 3 | 1 | 2 | 0 | 0 | 9 | 1 | 10 | 0 | 2 |
| kayenta | 20 | 20 | 0 | 0 | 0 | 0 | 7 | 34 | 7 | 11 |
| keel | 15 | 0 | 0 | 15 | 0 | 0 | 28 | 45 | 9 | 40 |
| **all** | **221** | **116** | **81** | **24** | **15** | **76** | **130** | **565** | **64** | **104** |

(221 controller *files* carry at least one method-level mapping; 228 files carry
`@RestController`/`@Controller`, the difference being controllers with no mapping
annotation of their own.)

Language is per controller file. Gate and Clouddriver are mixed Java/Groovy with a
Kotlin fringe; Front50, Fiat and Kayenta are pure Java; Keel is pure Kotlin;
Rosco and Igor are Java with a Groovy remainder.

Versioned paths: Gate `/v1` ×2, `/v2` ×28, `/v3` ×5; Front50 `/v2` ×28;
Rosco `/api/v1` ×8, `/api/v2` ×1; Clouddriver `/v1` ×2; Orca `/v2` ×2. Gate's
`/v2/pipelineTemplates` and Front50's `/v2/pipelineTemplates` are the largest
versioned pair; Gate's `/v3/builds/*` sits beside a `/v2/builds/*` set in the same
controller.

Response codes are declared on 64 of 732 endpoints (9%): `202` ×28, `200` ×18,
`204` ×13, `400` ×6, `201` ×4, `404` ×3, `410` ×2, `500` ×1, `401` ×1. The rest
return Spring's default 200 with no annotation. Content types are declared on 104
of 732 (14%); everything else relies on the global Jackson converter.

Header parameters: `X-RateLimit-App` (optional) on 45 Gate endpoints,
`X-SPINNAKER-USER` (required) on 17 Keel endpoints, a whole-`HttpHeaders` bind on
3 Echo webhook endpoints, and three one-offs in Gate (`Accept`, `X-Hub-Signature`,
`X-Event-Key`).

Query parameters appear on 261 of 732 endpoints. 22 of those bind a *catch-all*
`Map<String,String>`/`MultiValueMap` rather than named parameters (Gate's proxy
and extension controllers, both `cloudMetrics` controllers, Gate's managed
reports, Gate's `/v1/data/static/{id}`) — those cannot be projected as named
parameters.

## 3. How the model types are written

Counting only the *named* types that appear directly as a request body or return
type in `endpoints.tsv` (containers unwrapped, `Map`/`Object`/`JsonNode`
excluded), and resolving each name to its declaring file inside its own service
(falling back to kork):

| service | model types named | resolved | Java | Groovy | Kotlin | Kotlin data classes | Map subclasses |
|---|---|---|---|---|---|---|---|
| gate | 28 | 25 | 18 | 3 | 4 | 0 | 0 |
| orca | 8 | 8 | 5 | 1 | 2 | 1 | 0 |
| clouddriver | 64 | 63 | 50 | 11 | 2 | 0 | 0 |
| front50 | 14 | 14 | 14 | 0 | 0 | 0 | 2 |
| echo | 12 | 11 | 9 | 2 | 0 | 0 | 0 |
| igor | 5 | 3 | 3 | 0 | 0 | 0 | 0 |
| fiat | 8 | 8 | 8 | 0 | 0 | 0 | 0 |
| rosco | 7 | 7 | 2 | 5 | 0 | 0 | 0 |
| kayenta | 19 | 18 | 18 | 0 | 0 | 0 | 0 |
| keel | 25 | 25 | 0 | 0 | 25 | 15 | 0 |

Styles observed, in order of frequency:

* **Java bean, Lombok-generated accessors** — the default everywhere except Keel.
  Lombok (`@Data`, `@Value`, `@Builder`, `@Getter`, `@Setter`,
  `@AllArgsConstructor`, `@NoArgsConstructor`) appears on 79 of the 182 resolved
  model classes. Field presence is therefore invisible in the accessor set and has
  to be read off the field declarations.
* **Kotlin data class** — Keel only: 15 of its 25 model types, the remaining 10
  being interfaces or ordinary classes.
* **Groovy class with `def`/untyped fields** — 22 of the resolved models are
  Groovy (Clouddriver 11, Rosco 5, Gate 3, Echo 2, Orca 1). Groovy `def` fields
  are common in the wider tree (2 881 occurrences in Clouddriver, 722 in Orca,
  145 in Rosco, 99 in Gate) but rare in the classes that appear directly in a
  controller signature.
* **Map subclass** — Front50's `PipelineTemplate` and `Notification`
  (`extends HashMap<String,Object>`); Clouddriver's `KubernetesManifest` and
  Orca's `NamedHashMap`/`WaitForManifestStableContext` are the same pattern but do
  not surface directly in a controller signature at these tags.
* **Jackson any-setter bean** — Front50's `Pipeline` and `Application` and
  Clouddriver/Orca equivalents keep a `Map<String,Object>` overflow bucket wired
  through `@JsonAnySetter`/`@JsonAnyGetter` (Orca 24, Clouddriver 24, Front50 16
  occurrences, tree-wide). For `Pipeline` the annotations live on a **mixin**
  (`PipelineMixins`), not on the class. Such a bean is a declared shape *plus* an
  open remainder.

## 4. Presence and nullability annotations on model types

Counted over the same set of directly-named model classes (class annotations plus
the class body; a class is counted once per annotation kind):

| service | javax.validation | `@JsonProperty` | `@JsonProperty(required=true)` | `@Nullable` | `@NonNull`/`@Nonnull` | Lombok | Kotlin nullable fields |
|---|---|---|---|---|---|---|---|
| gate | 0 | 2 | 0 | 5 | 3 | 12 | 0/3 |
| orca | 0 | 0 | 0 | 1 | 1 | 3 | 2/6 |
| clouddriver | 0 | 2 | 0 | 5 | 1 | 23 | 0/5 |
| front50 | 1 | 0 | 0 | 0 | 3 | 6 | — |
| echo | 1 | 0 | 0 | 0 | 1 | 7 | — |
| igor | 0 | 1 | 0 | 0 | 0 | 3 | — |
| fiat | 0 | 0 | 0 | 0 | 1 | 6 | — |
| rosco | 0 | 1 | 0 | 1 | 1 | 2 | — |
| kayenta | 14 | 1 | 0 | 1 | 2 | 17 | — |
| keel | 0 | 0 | 0 | 0 | 0 | 0 | 30/125 |

Three findings matter for D4 (the *declared* presence profile):

1. **`@JsonProperty(required = true)` does not occur.** Zero occurrences in all
   ten repositories at these tags, tests included, and zero in kork. The
   `required` flag on `@JsonProperty` is never used anywhere in the mesh, so it
   contributes nothing to a *declared* profile.
2. **Validation is `javax.*`, never `jakarta.*`, and it is concentrated in
   Kayenta.** 162 `import javax.validation` occurrences tree-wide (Kayenta 90,
   Igor 22, Orca 16, Echo 16, Clouddriver 10, Fiat 4, Front50 3, Gate 1; Rosco and
   Keel zero) and zero `jakarta.validation` anywhere. On the directly-named model
   classes, only Kayenta (14 of 18) and one class each in Front50 and Echo carry
   a `@NotNull`/`@NotEmpty`/`@Size`/`@Valid`.
3. **Kotlin nullability is the only broad presence signal, and only Keel has it.**
   Across Keel's 25 directly-named model types, 125 declared properties, of which
   30 (24%) are nullable (`T?`); the other 95 are non-null Kotlin types, i.e.
   required at construction unless they carry a default. Orca's two Kotlin model
   types add 6 more properties, 2 nullable. Java `@Nullable` appears on 13 of the
   182 model classes and `@NonNull`/`@Nonnull` on 13; Lombok's `@NonNull` accounts
   for most of the latter and is a constructor check, not a serialization
   constraint.

So under D4's *declared* profile, presence information exists for exactly one
service's models (Keel, via Kotlin) plus Kayenta's validation annotations. For
everything else the declared profile collapses onto the *none* profile.

## 5. Polymorphism, and how it is declared

33 endpoints classify as `polymorphic`; 35 endpoints reach a `@JsonTypeInfo`
somewhere in their body or return graph (two of them are already `untyped-*` and
so keep that label). `@JsonTypeInfo` occurs in 13 Keel files, 5 Clouddriver, 2
Orca, 1 Echo, 1 Kayenta, 2 kork, and 0 in Gate, Front50, Igor, Fiat and Rosco.

Three distinct declaration mechanisms are in use:

* **Annotation on the type** — Kayenta's `CanaryMetricSetQueryConfig`, Echo's
  `Notification`, Orca's `Message`, Keel's `ApplicationEvent`, `ResourceEvent`,
  `PersistentEvent`, `SubmittedResource`, `Stages`.
* **Jackson mixin registered in a module** — Keel's `KeelApiModule` (15) and
  `KeelEc2ApiModule` (21) bind 36 mixins, three of which carry `@JsonTypeInfo`
  (`ClusterDeployStrategyMixin`, `ActionMixin`, `InstanceProviderMixin`).
  Clouddriver's `ClouddriverApiModule`/`AccountDefinitionModule` bind 10, of which
  `SecurityGroupMixin`, `RuleMixin` and `CredentialsDefinitionMixin` carry
  `@JsonTypeInfo` — that is the whole of Clouddriver's polymorphic surface (5
  endpoints on `/credentials*` and `/securityGroups/...`). Front50 binds 14
  (`PipelineMixins`/`TimestampedMixins`, no type info), Echo 1.
* **A custom `AnnotationIntrospector`** — Keel's `KeelApiAnnotationIntrospector`
  synthesises a `StdTypeResolverBuilder` for six types (`Constraint`,
  `ConstraintStateAttributes`, `DeliveryArtifact`, `SortingStrategy`,
  `Verification`, `PostDeployAction`) that carry no annotation at all. Ten of
  Keel's fourteen polymorphic endpoints are polymorphic only because of this.

Only the first mechanism is visible to a scanner that looks at the model class.
Both of the others are module wiring, which is why a reflection-based extractor
(D1) must construct the service's own `ObjectMapper` — with its modules
registered — rather than introspect the classes.

The typical distance from the endpoint signature to the discriminator is two to
four hops, e.g. Kayenta
`CanaryConfig → CanaryMetricConfig → CanaryMetricSetQueryConfig` and Keel
`ExportResult → SubmittedEnvironment → Constraint`.
