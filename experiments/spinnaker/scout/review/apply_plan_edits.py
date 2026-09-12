#!/usr/bin/env python3
"""R3: rewrite the decision texts of PLAN.md §4 in place and append the §6 changelog rows.
Idempotent: refuses to run twice (looks for the 2026-09-11 marker)."""
import re, os, sys
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'PLAN.md')
t = open(p).read()
if '| 2026-09-11 |' in t: sys.exit('changelog already applied')
NEW = {
'D1': """**D1. Source parsing vs reflection over artifacts.** Kept: reflection.
Confirmed on released bytecode for all ten services (S3-022/024; the review's
own constant-pool scan of the ten `-web` jars and three unpacked images):
`RuntimeVisibleAnnotations`, `Signature` and Kotlin `Metadata` survive in every
era (class majors 52/55/61). Three constraints the extractor honours:
(a) `MethodParameters` is absent everywhere (no `-parameters`), so a parameter
name comes from the annotation value, else from `LocalVariableTable`, else the
parameter is unnamed and the endpoint is flagged; (b) the service's own jars are
unversioned in the gcr.io era and versioned in the GAR era, so the classpath is
the `CLASSPATH=` line of `/opt/<svc>/bin/<svc>`, never a file-name pattern;
(c) the Jackson-visible shape is read through each service's configured
`ObjectMapper` (D7), not by raw reflection over model classes. The extractor
runs on a JDK 17; this machine has none, so a portable JDK is unpacked under the
experiment directory. Risk unchanged: old artifacts (S3 decided the range, D2).""",
'D2': """**D2. Release range and mesh.** Revised: **nine services**, not ten. No BOM of
the 346 pins Keel (S3-006; review R1(c)), so Keel is out of the first run — no
invented pin — and its 54 caller rows and 44 provider rows are dropped and
listed as out of scope. Kayenta is pinned from 1.7.0 (S3-007), irrelevant to the
range below. First run: **BOM range 1.30.0…1.38.0** — 50 releases, 49
consecutive pairs in version order, every pinned service a live container image
on one registry (`us-docker.pkg.dev`), Java 11→17, uniform jar naming; S3's
recommendation, reproduced by the review. The deep-history run 1.0.0…1.23.7
(202 releases, 201 pairs, gcr.io, Java 8/11, unversioned jars) is a later
extension; 1.24.0…1.26.7 has no artifact anywhere; 1.27.0…1.29.7 is Maven-only
and is not mixed into an image-based run. CalVer releases (2025.0.0 onward) pin
all nine services at one version and one monorepo commit, so "services moved
independently" no longer holds there; CalVer pairs are excluded from the first
run. Pairs are consecutive in version order (patch trains overlap in time).
The latest tags S1/S2/S6 read are exactly the 1.38.0 pins for the nine services,
so the scouting surfaces are the last state of the range.""",
'D3': """**D3. Endpoint identity.** Revised. A caller's Retrofit path and the provider's
Spring mapping are the same endpoint when method and normalized template match,
with the normalization fixed by R1: strip a baked-in query string (17 rows at
1.38.0; the fixed pairs go into `params` with `default`), add the missing
leading slash of Retrofit-2 relative paths (101 rows; `"."` is the base URL),
erase variable names and regexes (`{id:.+}` → `{}`), collapse doubled and strip
trailing slashes, let a provider `**` match any suffix, let a caller literal
fill a provider variable slot, and let a provider method `ANY` match every
method; no per-service prefix rule was needed at 1.38.0 (the table exists,
empty). Three classes of unmatched rows are not findings: (i) actuator
endpoints (`/health`, `/installedPlugins` — kork's `InstalledPluginsEndpoint`)
and framework-registered routes (Keel's DGS `/graphql`) are outside the graph;
(ii) a caller variable over a provider dispatch literal (`/{provider}/images/find`
against `/aws/images/find`, …: 7 rows at 1.38.0) is expanded by a hand table
into one edge per concrete controller; (iii) rows missing from a scouting census
are census defects. The residue — 17 rows at 1.38.0, all dead client methods —
is the finding "caller declares an endpoint the provider does not expose".
Because `cmd/gus/main.go:1097` makes an unmatched edge a hard input error, G3
drops those edges from `graph.yaml` and reports them on a separate channel; no
checker change.""",
'D4': """**D4. Presence (the `required` list).** Two profiles as before, but the
*declared* profile is nearly empty on this corpus and its legs are restated:
`@JsonProperty(required = true)` occurs zero times in the ten repositories and
in kork (S2-012, S5-017) — dropped; a validation annotation counts only when the
enclosing parameter carries `@Valid`/`@Validated` (S5-018), which concentrates
the leg in Kayenta; Kotlin non-null constructor parameters without defaults are
Keel's signal (S2-014) and Keel is out of the first run (D2), leaving Orca's two
Kotlin model types; Java primitives on the return side remain. The declared/none
gap is reported as a property of the corpus, not as signal. New rule: a field a
service never serialises when null — global `NON_NULL` on the MVC mapper in Orca
(`OrcaObjectMapper` is the `objectMapper` bean, WebConfiguration.groovy:66),
Clouddriver (CloudDriverConfig.java:166), Keel (DefaultConfiguration.kt:73) and
Kayenta (KayentaConfiguration.java:136), and per-class `@JsonInclude(NON_NULL)`
elsewhere — is projected on the return side as optional and not nullable, never
`nullable: true`, or `nullable-response-widening` fires for a value that never
reaches the wire (S5-014/037). Nothing inferred from initializers or usage.""",
'D5': """**D5. Openness.** Revised. Every accept and expect object stays open
(`additionalProperties: true`; Spring Boot disables `FAIL_ON_UNKNOWN_PROPERTIES`,
and Orca, Echo, Keel, Kayenta disable it explicitly); send and return objects
list their declared fields. *Untyped*, per side: raw `Map`/`List`/`Collection`/
`Set`, `Map<String,Object>`/`Map<String,Any>`/`Map<*,*>`/wildcard values,
`Object`/`Any`/Groovy `def`, `JsonNode`, containers of those, and Map-subclass
models (front50 `PipelineTemplate` and `Notification` extend
`HashMap<String,Object>`, S2-005/006). A typed map `Map<String,X>` with a
concrete `X` is *typed*: it projects to `additionalProperties: <X>`, loads as
`types.Map`, and `checkMap` compares key kind and value type (S5-032;
loader.go:526-538, compat.go:483-497). `Object` projects to
`{type: object, additionalProperties: true}`, never `{}` — an empty schema is
`types.Any` and short-circuits every comparison (loader.go:462, compat.go:71-73).
Opaque returns (`Call<ResponseBody>`, Retrofit-1 `Response`, `Void`, `void`,
`StreamingResponseBody`) are contentless, not untyped, and are projected as a
contentless 200 on both sides (D6). Endpoints untyped on both sides are kept in
the graph and excluded from every claim. Measured by R1 at 1.38.0: 50.6 % of the
470 reconciled edges are untyped on at least one side under this definition
(51.1 % as originally written); 56.9 % on the nine-service mesh; both-sides
untyped 4.9 %. Above the 50 % line under every reading, so §5's scoping applies
(D12). Note for the owner: this decision excludes both-sides-untyped edges from
claims while §5 gates on either-side-untyped edges; the review has not changed
which one the gate means.""",
'D6': """**D6. Parameters.** Revised. The checker models request bodies and the lowest
2xx JSON response, so path, query and header parameters are folded into the
request object under a fixed wrapper `{properties: {params, headers, body}}`,
the payload under `body` — a body field and a query parameter of the same name
cannot collide, and a `Map`-typed body never sits beside named properties (the
loader rejects that, loader.go:531). `params.<name>` is required for
`@PathVariable`, and for `@RequestParam` unless `required = false` or a
`defaultValue` (which emits `default:`); `headers.<name>` likewise (at 1.38.0:
`X-RateLimit-App` optional on 45 Gate endpoints, `X-SPINNAKER-USER` required on
17 Keel endpoints). A catch-all `Map<String,String>`/`MultiValueMap` query binder
(22 endpoints) makes `params` an open object and the request side untyped.
Baked-in query pairs from the caller side go into `params` with `default:`. A
`void`/`Void`/`ResponseBody`/`Response`/non-JSON response is a `200` with no
content on both caller and provider (otherwise `nil` against a schema is a
`presence-mismatch` BREAK, compat.go:62-68); response codes other than the
lowest 2xx are dropped and counted (64 endpoints declare one). Identities that
travel as parameters (D9) live inside `params`/`headers`, the only place
`x-provides`/`x-requires` are read (loader.go:498-507). A projection convention,
no checker change.""",
'D7': """**D7. Polymorphism and generics.** Revised. `@JsonTypeInfo` hierarchies →
`oneOf` over the registered subtypes with the discriminator a closed one-value
enum in each variant (two open variants admit each other and `oneof-ambiguity`
fires on every payload); unregistered `Object` → open object. The declarations
are mostly not on the model class: Keel's `KeelApiAnnotationIntrospector`
synthesises type resolvers for six unannotated types and its modules bind 36
mixins, Clouddriver's whole polymorphic surface is mixin-declared with subtypes
registered from Spring beans at runtime, Front50's `Pipeline` any-getter/setter
live on a mixin (S2-008/009/010/011, S5-010/011/012) — so the extractor
constructs each service's configured `ObjectMapper` with its modules registered
and reads the resolved configuration; bean-registered subtypes are an accepted
loss (base as open object, untyped). `Id.CLASS` discriminators are
fully-qualified class names. Plain inheritance is flattened at extraction:
`allOf` is a hard loader error (loader.go:342). Generic containers resolve
through the reflected `Signature`; raw types count as untyped. Unbudgeted cost
per S5: 8–16 h for driving the configured mapper.""",
'D8': """**D8. Nullability and enums.** Revised. Kotlin `T?` and `@Nullable` →
`nullable: true`; Java boxed types without annotation → not nullable, counted as
unknown. Enums are closed only where the mapper on that side is closed: Orca's
MVC mapper enables `READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`
(OrcaObjectMapper.java:57, the `objectMapper` bean), so Orca's accept side is
open; the fiat-api client mapper used by every `FiatService` caller
(FiatAuthenticationConfig.java:61) and Rosco's Clouddriver client
(ServiceConfig.java:46) enable `READ_UNKNOWN_ENUM_VALUES_AS_NULL`, so those
expect sides are open; every other side is Jackson-default closed (kork-retrofit
sets nothing; Keel is only case-insensitive). Projection: open side →
`type: string`; closed side → closed `enum` of the constants. "The first corpus
with real closed enums" holds only for edges closed on both sides.""",
'D9': """**D9. Chains.** Kept out of the first run. R1(e): three of S6's five chains
name a declared field at every hop — `clientRequestId` Orca→Clouddriver (query
parameter on both sides), `artifactAccount`+`type` Orca/Rosco→Clouddriver
`PUT /artifacts/fetch` (kork `Artifact` body on both sides), `source.executionId`
Orca→Echo `POST /notifications` (nested field, typed on both sides).
`correlationId` Keel→Orca survives only reduced (Keel's typed body → Orca's
`GET /executions/correlated/{correlationId}` path parameter; the `POST /ops`
body sink is a `Map`) and is deferred with Keel (D2); `application`
Gate→Orca→Front50 fails at its mint (Gate's body is `Map<String,Object>`) and
survives only as Orca→Front50. Response-minted identities and the undeclared
`X-SPINNAKER-*` headers stay outside. Second run: annotate the three survivors
(plus the reduced Orca→Front50 chain) by hand and report them separately as
synthetic; G1 must carry caller-side query/path/header parameters, which S1's
`edges.tsv` does not.""",
'D10': """**D10. Ground truth.** Kept. A release pair is "breaking" only with a quoted
statement and a link (S4). Pairs with no evidence are unlabeled, not safe. S4
delivered 38 rows, all with URL and quote; CLAIM-S4-019, quoted from a
documentation pull request closed without merging, does not count (a
contributor's draft is not a project statement), leaving 37 (breaking 14,
compat-note 20, upgrade-order 1, deprecation-removed 2). 38 > 20, so two
independent labelers are required before any row is treated as ground truth.
Within 1.30.0…1.38.0: 17 rows, 6 `breaking`, of which only S4-021 and S4-023
(Retrofit-2 migration failures of a caller's declared interface) are
contract-visible in the checker's sense. Labels on minor-line transitions
(`1.N.x → 1.M.0`) map to the version-ordered pair (last 1.N patch, 1.M.0).""",
'D11': """**D11. The consistency gate as a fidelity test.** Kept. A BOM baseline that
fails `gus consistent` is triaged before anything else: projection defect (fix
G1/G3), normalization defect (fix D3, including its dispatch-slot table),
census defect (back to the scout), or real inconsistency (kept, reported as a
finding about the corpus, pair skipped).""",
'D12': """**D12. What is not claimed.** Revised. No prevalence claim; no claim about
presence hazards under the *none* profile; no chain claim in the first run; no
claim about Keel or about CalVer pairs; untyped edges excluded from precision
figures; and, because the untyped share exceeds 50 % (D5), the first run is
scoped to the caller-drift question (C2, C4, TGT) on the typed remainder of the
edges, stated in the README before any number (§5).""",
}
for d, new in NEW.items():
    m = re.search(r'\*\*' + d + r'\. .*?(?=\n\n\*\*D\d+\. |\n\n## 5\. )', t, re.S)
    if not m: sys.exit('could not find ' + d)
    t = t[:m.start()] + new + t[m.end():]
ROWS = """| 2026-09-11 | D1 | reflection, no extractor constraints | reflection with: parameter names from annotation value → `LocalVariableTable` → flagged (`MethodParameters` absent everywhere); classpath from the `CLASSPATH=` line (jar naming flips at the gcr.io/GAR boundary); shapes read through each service's configured `ObjectMapper`; JDK 17 required (none on this machine) | S3-020/021/022/023/024/028; review jar scan |
| 2026-09-11 | D2 | all ten services; longest contiguous range with artifacts for every pinned service | nine services (Keel pinned by no BOM, no invented pin, 98 edge rows out); first run 1.30.0…1.38.0 (49 pairs, all images, one registry); 1.0.0…1.23.7 (201 pairs) as extension; 1.24.0…1.26.7 lost; 1.27.0…1.29.7 Maven-only, not mixed in; CalVer pairs excluded (one monorepo commit per BOM); version order | S3-006/007/012/015/027; S1-001; R1(c); BOM pins of 1.38.0 and 2025.x |
| 2026-09-11 | D3 | names erased, trailing slash and prefixes normalized; unmatched = finding | R1 normalization spelled out (query strings, leading slash, regexes, `**`, literal-fills-slot, `ANY`); hand table for provider dispatch slots (7 rows); actuator/framework routes outside the graph; census gaps back to the scout; the 17 stale declarations are the finding and are dropped from `graph.yaml` because main.go:1097 is a hard error | S1-019; S2-021/023; S5-006/016; R1(a) |
| 2026-09-11 | D4 | declared = Kotlin non-null, primitives, `@JsonProperty(required)`, validation | `@JsonProperty(required)` leg dropped (zero occurrences); validation only under `@Valid`/`@Validated`; Kotlin leg leaves with Keel; declared ≈ none reported as a corpus property; NON_NULL-serialised fields optional and not nullable on the return side | S2-012/013/014/015; S5-014/017/018/037; WebConfiguration.groovy:66, CloudDriverConfig.java:166, DefaultConfiguration.kt:73, KayentaConfiguration.java:136 |
| 2026-09-11 | D5 | every `Map` and `Object` untyped; `Object` → open object | typed maps `Map<String,X>` are typed (`types.Map`, `checkMap`); `Object` → `{type: object, additionalProperties: true}`, never `{}`; Map-subclass models untyped; opaque returns contentless; measured 50.6 % (ten) / 56.9 % (nine) → §5 scoping; either/both inconsistency flagged | S5-007/032; S2-004/005/006; R1(b) |
| 2026-09-11 | D6 | `params` and `headers` beside the body; lowest 2xx | `{params, headers, body}` wrapper; contentless 200 on both sides for void/opaque/non-JSON; catch-all query maps → open `params`; baked-in query pairs → `params` with `default`; identities in parameters inside `params`/`headers` | S5-001/002/003/005/008/025/048; S2-019/020/021 |
| 2026-09-11 | D7 | `oneOf` over registered subtypes; raw types untyped | extractor drives the configured `ObjectMapper` (mixins, introspectors, modules); bean-registered subtypes an accepted loss; one-value closed enum discriminator; `Id.CLASS` = FQCN; inheritance flattened (`allOf` is a hard load error) | S2-008/009/010/011/016; S5-004/010/011/012/024/036 |
| 2026-09-11 | D8 | Java enums closed everywhere | closedness per service and per direction: Orca accept side open; every `FiatService` caller's expect side and Rosco's Clouddriver client open; closed elsewhere; open side → `type: string` | S5-013/058; S1-008; FiatAuthenticationConfig.java:61, rosco ServiceConfig.java:46, orca WebConfiguration.groovy:66 |
| 2026-09-11 | D9 | out of the first run; annotate 3–5 identities in a second run | kept; the three chains that survive R1(e) named (clientRequestId, artifactAccount+type, source.executionId) plus the reduced Orca→Front50 leg; chain 1 deferred with Keel; G1 must carry caller-side parameters | S6-002…008, 049-052, 068-073; R1(e) |
| 2026-09-11 | D10 | quoted statement and link; two labelers above twenty | kept; CLAIM-S4-019 does not count (closed, unmerged PR); 37 rows, 14 breaking; two labelers required; labels mapped to version-ordered pairs | S4-041/048/050; R1(d) |
| 2026-09-11 | D11 | triage: projection, normalization, real | kept; adds the categories dispatch slot and census defect | R1(a) |
| 2026-09-11 | D12 | no prevalence, no presence-under-none, no chains, untyped excluded | adds: no Keel claim, no CalVer claim, and the §5 scoping to caller-drift on the typed remainder | R1(b) |
"""
hdr = '| date | decision | from | to | claims |\n|---|---|---|---|---|\n'
if hdr not in t: sys.exit('changelog header not found')
t = t.replace(hdr, hdr + ROWS)
t = t.replace('motivated them. Empty until the review runs.', 'motivated them. Filled by the review pass of 2026-09-11 (`scout/review.md`).')
t = t.replace('## 4. Decisions (defaults; the review pass revises)', '## 4. Decisions (revised by the review pass, 2026-09-11; see §6)')
open(p, 'w').write(t); print('PLAN.md updated:', len(t), 'chars')
