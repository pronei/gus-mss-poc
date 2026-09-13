# G1 decisions — choices the rules left open

Every row the handoff decided is implemented as written; this file is only the
residue. `needs owner` marks a choice that **changes results**. The three the
handoff reserved are at the bottom, undecided, with both variants behind a
flag.

---

## 1. Component naming and the side-dependent projection — *needs owner*

**The problem.** D4 and D8 make a projection side-dependent: a Java primitive
is `required` on the return side and not on the accept side; a
`NON_NULL`-serialised field is optional-and-non-nullable on the return side
only; an enum is closed on the side whose mapper is closed. But the loader
resolves each entry of `components/schemas` exactly once and reuses that node
at every occurrence (`loader.go:96-116`), so **one component name can carry
only one shape**. A document holds both sides.

**What I did.** Inline every type, per side, and emit a component only at a
cycle back-edge — where the loader needs a `Ref` and where
`ref-name-mismatch` compares the *local* name across the two documents
(`compat.go:276-296`). This is the shape the checker's coinduction is written
for: the one-step unfolding around the back-edge is compared structurally and
per side, and only the name has to agree. The recursive type itself is
side-neutral (built from whichever side reached it first) and is reported as a
loss; there are 4 such occurrences over six documents, all Orca's
`PipelineExecution`.

**Cost, and why the owner should look.** Documents get bigger: front50 at
2.41.0 is 7 700 lines, and a service with deep model nesting could be much
worse (clouddriver has 64 model types and is untried). The alternative —
side-suffixed component names — is smaller but makes every recursive type
`ref-name-mismatch` against itself, so it is only viable if the checker learns
to compare components across a name map. If document size becomes the binding
constraint, that is the checker change to cost.

## 2. Path spelling: variable names kept, regexes stripped — *needs owner (G3)*

D3 normalizes by erasing variable names (`{id:.+}` → `{}`), but D6 needs the
name to key `params`, and the handoff's own acceptance names the endpoint
`PATCH /v2/applications/{applicationName}`. So the emitted path keeps the name
and drops the regex, and every operation also carries
`x-match-key: "<METHOD> <fully erased path>"`.

This leaves one thing for G3: `graph.yaml` names **one** path per edge and the
checker looks it up verbatim in both documents (`main.go:1090-1098`), so a
caller that spells a variable `{app}` against a provider that spells it
`{application}` will not resolve. `x-match-key` is what pairs them; G3 has to
pick one spelling for the edge and, where the two differ, decide which. I did
not see a mismatch on the six documents, but I did not look across all nine
services.

## 3. Framework routes excluded by jar provenance

D3 puts actuator and framework-registered routes outside the graph but names
only `/health`, `/installedPlugins` and Keel's `/graphql`. A runtime classpath
carries more (CLAIM-G1-007): springdoc, Spring Boot's error controllers,
kork's `GenericErrorController`, Spectator's `MetricsController` — 48
controllers and 261 routes over six documents.

**Decision.** An endpoint is kept only when its declaring class comes from a
jar named `<service>-*`, which is exactly S2's source-census scope. Not a name
pattern on the path, which would need a list nobody can close. Every excluded
route is listed in the diagnostics with class and jar, so the rule is
auditable rather than silent. Reversible with a flag if G3 ever wants them.

## 4. `ANY` expanded over seven verbs

See CLAIM-G1-006. The document cannot say `ANY` and the loader would drop it
silently. Each such endpoint is emitted once per verb, marked
`x-method-any: true`. The alternative — emit `GET` and let G3 expand — keeps
the endpoint count equal to S2's but leaves a caller using `POST` unresolved
against a provider that does accept it.

## 5. A Retrofit `@Query` is optional; a `@Path` is required

Retrofit omits a `@Query` whose argument is null and cannot omit a `@Path`.
So `@Path` goes into `required` and `@Query` does not. This is what produces
the two surviving `REQ.2` findings on the kork `pinVersions` client
(`params.location`, `params.serviceName` are `@Query` on the caller and
required `@RequestParam` on the provider) — which I believe is a true
statement about the declarations, not an artefact. A stricter reading, "a
`@Query` on a primitive parameter is always sent", would remove some of these;
it is not in the rules and I did not adopt it.

## 6. Validation annotations recorded, not applied

CLAIM-S5-018 gates a validation annotation on `@Valid`/`@Validated` at the
enclosing parameter. The gate is detected (6 bodies over six documents) and
recorded as `x-validated: true` on the operation, but the body's own
`@NotNull` fields are **not** yet turned into `required`. Doing so needs a
second walk of the body type under the gate, and on this corpus the leg is
concentrated in Kayenta, which is untried. Left as a gap rather than a
half-applied rule.

## 7. Defaults are emitted in the declared type

Only the *presence* of `default` is read (`loader.go:494-496`), so the value
is free. It is still emitted as a boolean or an integer where the parameter
declares one, so the document is valid OpenAPI rather than `default: "true"`
under `type: boolean`.

## 8. Parameters are typed by their declared Java type, not as strings

Everything in a path segment, a query string or a header is a string on the
wire, but the declared Java type is what both sides agree on, and typing
`params` from it is what makes a caller's `boolean restricted` meet a
provider's `boolean restricted`. An unrecognised type falls back to
`type: string`.

## 9. `pull_layer.py` is a stopgap, not a second fetcher

G1 needed a corpus before G2 delivered. `tools/pull_layer.py` implements the
same steps in the same order as G2's contract and writes G2's layout, so the
two are interchangeable; G2 has since delivered and its corpus is what the
acceptance suite runs against. The script stays only so that this report
reproduces without G2. It should not be maintained.

---

## The three the owner has to settle

These are **not** decided here. Both variants are available behind a flag and
the default is "keep", which is the larger graph; nothing in the extractor
depends on the answer.

### A. Do the 30 kork `Front50Service` rows enter the graph?

`--kork-rows keep|drop` (default `keep`). The interface is real, compiled into
all ten services and bound by a literal config key, but it is created only
when an operator sets `spinnaker.extensibility.repositories.front50.enabled`,
which no shipped profile in the ten does (CLAIM-S1-025). Front50's three rows
are additionally a self-edge, which R3 has already told G3 to drop.

Evidence from this side: the three methods reconcile against Front50's real
endpoints, and the `pinVersions` edge is one of the two places the consistency
gate still fires (§5 above). Keeping them adds a real finding; dropping them
removes it.

### B. Do the 36 indirect `FiatService` rows enter the graph?

`--indirect-fiat keep|drop` (default `keep`). In Clouddriver, Echo, Igor and
Keel no application code injects `FiatService`; the calls are issued by
`FiatPermissionEvaluator` inside `fiat-api` (S1 clients.md). The declaration
is on the caller's classpath and the traffic does leave the caller, so the
rows are emitted; whether they are edges is a projection decision. The flag
drops them for exactly those four services and keeps Gate's, Orca's and
Front50's direct ones.

### C. Is the *declared* presence profile kept as a control?

`--presence declared|none` (default `declared`). Under `declared` the only
thing that ever lands in a `required` list on this corpus is a Java primitive
on the return side — `@JsonProperty(required = true)` is absent (CLAIM-S5-017,
confirmed here), validation is gated and unapplied (§6), and the Kotlin leg
leaves with Keel. Under `none` no `required` list is emitted at all. R4
already lists the declared profile among what the run gives up; the flag
exists so that "declared ≈ none" can be *measured* on the real documents
rather than asserted.

### And one for G3, not for the owner

The four `presence-mismatch` findings that survive the consistency gate are a
Retrofit-1 caller declaring `retrofit.client.Response` or `Void` against a
provider that returns a body (`POST /pipelines`, `POST /serviceAccounts`,
`POST /v2/applications`, `PATCH /v2/applications/{applicationName}`). D6 says
caller and provider must **both** carry a contentless 200 — but only G3 sees
both documents, so only G3 can arrange it. Every such operation is marked
`x-response-opaque: true`, which distinguishes "declared void" from "could not
determine". G3 either zeroes the provider's response for those edges, per D6,
or reports them as the finding "caller discards a body the provider sends".
