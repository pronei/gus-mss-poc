# G1 memo — the contract extractor

What it is: a Java 17 tool that reads one Spinnaker service's **runtime
classpath** — the jars a released container actually ships — and writes one
OpenAPI 3.0 document that `gus` loads. No source parsing (D1). It runs inside
the service's own class loader, so the schemas come from the service's own
configured `ObjectMapper` rather than from plain reflection (D1(c), D7).

    extractor/mvnw package
    java -jar target/gus-contract-extractor.jar \
         --classpath corpus/1.38.0/front50 --service front50 --version 2.41.0 \
         --mesh ../scout/S1/tools/mesh.tsv \
         --out out/front50-2.41.0.yaml --diag out/front50-2.41.0.diag.json

`tools/accept.sh` runs the whole acceptance suite of the handoff in one go.

## What was built

| file | what it carries |
|---|---|
| `Main` | the only class outside the service's loader: reads the `CLASSPATH=` line, builds a `URLClassLoader` over those jars with this tool's jar appended and the **platform** loader as parent, hands over to `Extract` |
| `Classpath` | the `CLASSPATH=` line of `bin/<svc>` (D1(b)) |
| `ClassIndex` | which jar owns which class, plus a constant-pool byte prefilter so that only candidates are ever loaded |
| `ClassFile` | a minimal class-file reader, for `LocalVariableTable` parameter names (D1(a)) |
| `Anns` | annotations read by **name**, so nothing compiles against Spring or Retrofit |
| `ProviderScan` | Spring MVC controllers → provider endpoints |
| `CallerScan` | Retrofit interfaces (both generations) → `x-role: client` endpoints |
| `Mesh` | S1's `mesh.tsv`, the interface → provider binding |
| `Mapper` | the service's configured `ObjectMapper` |
| `Shape` | Java type → schema, walked through that mapper |
| `Doc`, `Schema`, `Yaml` | the document, and a deterministic writer |
| `Diag` | counts, losses, flagged endpoints |
| `tools/` | the acceptance suite, and `pull_layer.py` (a stopgap for G2) |

**CLAIM-G1-001**: the toolchain is pinned and nothing was installed on the
host. Temurin **JDK 17.0.20.1+1** (`OpenJDK17U-jdk_aarch64_mac_hotspot`,
sha256 `196d13ba…f0e8`, verified before unpacking) sits under
`experiments/spinnaker/.jdk/`; `extractor/mvnw` fetches **Maven 3.9.16**
(sha512 `831a8591…b6f6`, verified) into `.mvn-dist/` and uses a project-local
repository. All three paths are gitignored. source: `extractor/mvnw`;
`.gitignore`.

**CLAIM-G1-002**: the tool has **no runtime dependency of its own**.
`jackson-databind` and `jackson-annotations` are `provided` scope — at run
time `Shape` links against the Jackson the service ships (2.13.5 in front50
at 2.41.0, `jackson-databind-2.13.5.jar`) — and the YAML writer is
hand-written rather than snakeyaml, precisely so that nothing of ours has to
be reconciled with Spring Boot's dependency set inside the service's loader.
Spring and Retrofit are never compiled against at all: every annotation is
read by name, which is also what lets one code path serve both Retrofit
generations (CLAIM-S1-018). source: `pom.xml`; `Anns`; `Yaml`.

**CLAIM-G1-003**: the classpath is the `CLASSPATH=` line, as D1(b) requires,
and it is large: front50 at 2.41.0 has 408 jars and 92 455 classes, gate at
6.69.0 381 jars, orca at 8.64.0 406 jars. Loading every class to look for an
annotation is neither fast nor safe, so `ClassIndex` prefilters on the
annotation descriptor as a byte sequence in the constant pool and only
candidates are passed to `Class.forName(name, false, loader)` — resolved, not
initialised. A whole extraction takes about five seconds. source:
`out/*.diag.json` (`classpath-jars`, `classes-on-classpath`).

## Constructs the rules did not cover

**CLAIM-G1-004**: **Spring MVC handler methods need not be public, and in
Front50 mostly are not.** `PluginInfoController.list`, `.get`, `.upsert`,
`.delete` and the rest are package-private; so are the handlers of
`PipelineTemplateController` (14), `V2PipelineTemplateController` (16),
`DeliveryController`, `PluginBinaryController`, `PluginVersionController`,
`ReorderPipelinesController` and `AdminController`. Spring registers them
anyway — `AbstractHandlerMethodMapping` selects over
`ReflectionUtils.USER_DECLARED_METHODS`, which ignores access — and S2's
source census includes them. A `Modifier.isPublic` filter, which is the
obvious way to write this scan, silently dropped **eight of Front50's
seventeen controllers and 33 of its 90 endpoints**. The rule now is: any
declared, non-synthetic, non-bridge, non-static method carrying a mapping
annotation, walked up the class hierarchy and deduplicated on name and
descriptor. source: `com.netflix.spinnaker.front50.controllers.PluginInfoController`
in `front50-web-2.41.0.jar` (`javap -p`: `java.util.Collection<PluginInfo>
list(java.lang.String);` — no `public`); `ProviderScan.handlerMethods`.

**CLAIM-G1-005**: D1(a) holds exactly, and its last leg never fired.
`MethodParameters` is absent from the service jars: across the six documents
424 parameter names came from `LocalVariableTable` and 6 from
`MethodParameters` (all in library classes, none in a Spinnaker controller or
client). **No endpoint was flagged for a nameless parameter**, in any of the
six. The slot arithmetic is the part that matters — a `long` or `double`
parameter occupies two local-variable slots, so a naive index-to-slot map
renames every parameter after the first wide one — and it is unit-tested
against a fixture compiled by this build the same way the corpus was.
source: `out/*.diag.json`; `ClassFileTest`.

**CLAIM-G1-006**: **the census's `ANY` pseudo-method cannot be written down.**
A `@RequestMapping` that declares no `method` is registered by Spring for
every verb, and S2 records it as `ANY` (23 rows mesh-wide: gate 4, orca 2,
clouddriver 6, rosco 2, igor 9; front50 has none). The checker's loader reads
exactly the seven real verbs (`loader.go:118-128`) and would drop an `any:`
key **silently**, so each such endpoint is emitted once per verb and every
copy carries `x-method-any: true`. That is what D3's "a provider method `ANY`
matches every method" costs once it has to be a document: gate's 273 census
rows become 302 operations, orca's 45 become 60. source:
`com.netflix.spinnaker.gate.controllers.ApiExtensionController` in
`gate-web-6.69.0.jar`; `tools/census_diff.py` reports the expansion as its own
category.

**CLAIM-G1-007**: **a runtime classpath carries controllers no source census
can see.** Beyond kork's actuator endpoints (D3 names those), the images ship
springdoc (`OpenApiWebMvcResource`, `SwaggerWelcomeWebMvc`,
`SwaggerConfigResource`, `SwaggerUiHome`, `MultipleOpenApiWebMvcResource`),
Spring Boot's `BasicErrorController` and `ManagementErrorEndpoint`, kork's
`GenericErrorController` and Spectator's `MetricsController`. 48 such
controllers over the six documents, 261 routes. They are outside the graph
under D3, so they are excluded — but by **provenance**, not by a name
pattern: an endpoint is kept only when its declaring class comes from a jar
named `<service>-*`, which is exactly the scope S2's census covered. Every
excluded route is listed in the diagnostics with its class and jar. source:
`out/*.diag.json` (`framework-route-excluded`); `ProviderScan.ownJar`.

**CLAIM-G1-008**: some of those framework paths contain **unresolved Spring
property placeholders** — `${server.error.path:${error.path:/error}}`,
`${springdoc.api-docs.path}` — which are resolved from the environment at
startup and are not knowable statically. All of them fall inside the excluded
set of CLAIM-G1-007, so none reaches a document; if a service jar ever
declared one it would be emitted verbatim and would never match a caller.
source: `out/front50-2.41.0.diag.json`.

**CLAIM-G1-009**: **two provider endpoints can share a (path, method).** Orca
declares `POST /ops` twice (`OperationsController.ops`, the pair R1(a) already
found tied) and Gate declares `POST /pipelines/{id}/evaluateExpression`
twice; Spring separates them on `consumes`/`params`, which the checker's
endpoint key (`{Path, Method}`, loader.go:56-59) does not model. One wins in
deterministic order and the collision is reported — 4 over the six documents.
source: `out/orca-8.64.0.diag.json` (`duplicate-endpoint`).

**CLAIM-G1-010**: **Front50's `Trigger` is a Map subclass by an indirection
CLAIM-S5-023 anticipated but the type check has to reach for.** It extends
`ForwardingMap<String, Object>`, not `HashMap`, so the test is Jackson's
`isMapLikeType`, not a superclass name. With `PipelineTemplate` and
`Notification` that is 16 Map-subclass models over the six documents, each
projected as an open object carrying its declared properties,
`additionalProperties: true` and `x-untyped: true`. The inherited `java.util`
accessors (`isEmpty` and friends) are dropped: Jackson serialises such a class
as a map, so those never reach the wire and must not appear as fields.
source: `com.netflix.spinnaker.front50.api.model.pipeline.Trigger` in
`front50-api-2.41.0.jar`; `Shape.mapSubclass`.

**CLAIM-G1-011**: **a polymorphic base whose subtypes come from Spring beans
is the accepted loss CLAIM-S5-012 named, and it is Orca's queue `Message`.**
`com.netflix.spinnaker.q.Message` carries `@JsonTypeInfo` but
`collectAndResolveSubtypesByClass` returns nothing statically, so the base is
projected as an open untyped object and counted — 4 over the six documents,
all this class. Keel's third mechanism, a custom `AnnotationIntrospector` that
synthesises a resolver for an unannotated type, is probed for reflectively
(the method moved between Jackson versions) and would be counted the same way;
Keel is out of the first run under D2, and it did not fire here. source:
`com.netflix.spinnaker.q.Message` in `keiko-core-*.jar` on orca's classpath;
`Shape.polymorphic`.

**CLAIM-G1-012**: **recursion is real but rare, and it is Orca's
`PipelineExecution`.** It is the only type in the six documents that had to
become a component: 4 occurrences (both orca versions, both sides), every
other type inlined. That matches S5's "≥1 confirmed" and makes the component
section empty for front50 and gate. source: `out/orca-*.diag.json`
(`recursive-type-side-neutral`).

**CLAIM-G1-013**: **Gate ships no Jackson module of its own.** Searching every
jar on gate's runtime classpath for a `com.netflix.spinnaker.*` subclass of
`SimpleModule` finds none, so "0 modules registered" for gate is the fact, not
a gap in the search; front50 registers `Front50ApiModule`, which is what makes
`PipelineMixins` and `TimestampedMixins` visible. source: `unzip -l` over
`corpus/1.38.0/gate/lib/*.jar`; `out/gate-6.69.0.yaml` header.

**CLAIM-G1-014**: 123 Retrofit interfaces on the six classpaths are **out of
mesh or unresolved** and contribute no edge — Azure's `AzureClient$AsyncService`,
Jenkins, Slack, the metric stores. Each is named in the diagnostics rather
than guessed at. source: `out/*.diag.json` (`retrofit-no-provider`).

## Three defects this work found in its own projection

Found by running D11's consistency gate over a real version pair — orca and
front50 at 1.30.0 against the same two at 1.38.0, 26 edges, orca's own
`/_calls` declarations supplying the caller side. The gate went from 17
findings to 6.

**CLAIM-G1-015**: **an absent request wrapper is not the same as an empty
one.** A caller whose Retrofit method takes no parameters produced no request
schema at all, while the provider's endpoint had one optional query parameter
and so produced an object — and `nil` against a schema is a
`presence-mismatch` BREAK (`compat.go:62-68`), which is exactly the asymmetry
CLAIM-S5-048 warns about on the response side. The wrapper is now always
emitted, empty if need be; two open objects compare vacuously. Fixed 2 of the
17. source: `gus consistent` on `GET /_calls/front50/pluginInfo` before the
fix; `Doc.request`.

**CLAIM-G1-016**: **`@JsonInclude(NON_NULL)` is a statement about what a
service writes, so it governs the return side only.** Applying it to the
accept side too suppressed `@Nullable` on a caller's *expect* while the
provider's *return* kept it — for the same kork class reached from the same
`kork-api-7.169.0.jar` on both sides — and invented a
`nullable-response-widening` BREAK on
`PluginInfo.Release.remoteExtensions[*].config`. D4 says "on the return side";
the code now says so too. Nullability and inclusion are also read from **every**
member of a property (getter, setter, field, creator parameter) and unioned,
because which member a side happens to pick is not a fact about the wire.
Fixed 3 of the 17. source: `com.netflix.spinnaker.kork.plugins.api.internal.RemoteExtensionConfig`;
`Shape.bean`.

**CLAIM-G1-017**: **Jackson's `BeanPropertyDefinition#isRequired` is wider
than D4's *declared* profile.** It also reports a creator parameter Jackson
must have in order to construct a bean, which says nothing about what has to
be on the wire; it was marking `PluginInfo.Release.remoteExtensions` required
on one side and not the other. The code now reads
`@JsonProperty(required = true)` directly — zero occurrences in this corpus,
as CLAIM-S5-017 says, so this leg contributes nothing and is kept only so that
it would be honoured if it ever appeared. Fixed 6 of the 17. source:
`Shape.requiredHere`.

Two smaller ones from the same run: a baked-in query literal was emitted as a
string regardless of what the provider binds (`?restricted=false` against a
`boolean` is a `prim-mismatch` on every payload), so the literal now types
itself; and the mesh join keyed on the interface's **simple** name, which S1
explicitly warns against — "`Front50Service` is declared six times in the ten
plus once in kork … join on `claim`, not on `interface`" — so Gate's own
`Front50Service` and the kork-plugins one each matched both bindings and each
interface was walked twice. Keying on the declaring class dropped the
duplicate-endpoint count from 215 to 38.

## What the acceptance suite reports

`tools/accept.sh`, all green:

| check | result |
|---|---|
| 1. `gus` loads every document | 6/6, and `gus consistent` returns YES on each |
| 2. provider endpoints = S2's census | front50 **90/90**, gate **273/273** (+4 `ANY` rows expanded), orca **45/45** (+2) — 0 missing, 0 extra |
| 3. golden fragments | 5/5 |
| 4. caller endpoints = S1's `edges.tsv` | front50 **13/13**, gate **241/241**, orca **133/133** — 0 missing, 0 extra |
| 5. both ends of the range | front50 2.28.0, gate 6.58.0, orca 8.31.0 all extract and load |
| unit tests | 24, covering the class-file reader, D3 normalization, the YAML writer and return unwrapping |

The four differences between an endpoint *row* and an endpoint *count* are all
explained above: `ANY` expansion (CLAIM-G1-006), framework routes excluded by
provenance (CLAIM-G1-007), same-key collisions (CLAIM-G1-009), and Retrofit
overloads that collapse onto one endpoint — 34 of them, which S1 itself
records as distinct rows on one path (`FiatService.sync` twice, Orca's three
`getPipelines`).

Counts over the six documents: 900 provider endpoints, 796 caller endpoints,
**0 flagged**, 2 components, 811 `NON_NULL` return fields, 68 closed enums and
34 open ones (D8 read from each mapper, not assumed), 16 Map-subclass models,
72 catch-all query binders, 383 raw-generic returns, 260 opaque provider
responses and 184 opaque caller ones.

## What I could not verify

* **That the emitted shape is the shape on the wire.** Everything is read
  through the service's configured `ObjectMapper`, which is the right
  authority, but I ran no service and compared no response body. A custom
  `JsonSerializer` (CLAIM-S5-042, 74 sites in S5's sample) makes the declared
  Java type *not* the wire type, and nothing here detects that: such a type is
  projected from its declared properties and is silently wrong rather than
  flagged. This is the largest unmeasured risk in the projection.
* **That the mapper I build is the mapper the service installs.** For orca it
  is the real bean (`OrcaObjectMapper.newInstance()`); for the others it is
  Spring Boot's `Jackson2ObjectMapperBuilder.json()` plus every service-owned
  `Module` on the classpath with a no-argument constructor. A module
  configured *in its `@Bean` method* rather than in its constructor, a
  `Module` registered from a bean, or a subtype registered at runtime
  (CLAIM-S5-012) is not reproduced. I checked the recipe against front50 and
  orca only; the other seven services are unverified.
* **Kotlin nullability.** `@Nullable` is honoured; `kotlin.Metadata` is not
  parsed, so a Kotlin `T?` is currently seen only where the Kotlin module is
  registered and Jackson surfaces it. D2 puts Keel — the corpus's only broad
  Kotlin-nullability signal — out of the first run, and D4 leaves Orca's two
  Kotlin model types; I did not confirm how those two project.
* **Six of the nine services.** Clouddriver, echo, igor, fiat, rosco and
  kayenta were never run. Clouddriver is the one I would expect to bite: its
  whole polymorphic surface is mixin-declared with subtypes registered from
  Spring beans (CLAIM-S5-012), and it is the largest model set in the mesh.
* **Every BOM between the two ends.** 1.30.0 and 1.38.0 both work; the 48
  releases between them are untried, and the deep-history range (1.0.0…1.23.7,
  gcr.io, Java 8/11, unversioned jars) has not been touched at all. The
  unversioned-jar era is exactly what D1(b) exists for, and it is untested.
* **That the `ANY` expansion is harmless.** Emitting seven operations where
  Spring registers seven is faithful, but it inflates the provider surface by
  29 operations on gate and 15 on orca, and I have not checked whether G3's
  graph generation or any figure in the README counts endpoints in a way that
  those inflate.
* **The four `presence-mismatch` findings that remain.** They are real
  declarations — a Retrofit-1 caller declaring `Response`/`Void` against a
  provider that returns a body — but whether they are *findings* or a
  projection rule is D6's "contentless 200 on both sides", which only G3 can
  apply because only G3 sees both documents. I marked them
  (`x-response-opaque: true`) and left the decision; see `decisions.md`.
