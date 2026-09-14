# G3 decisions — choices the rules left open

Everything the handoff decided is applied as written; this file is the residue.
`needs owner` marks a choice that **changes results**. Claims cited as
CLAIM-G3-NNN are in `memo.md`.

---

## 1. Extraction runs once per distinct pin

`corpus.lock` names 238 distinct (service, version) pins in the 450 (BOM,
service) pairs of the range, and a pinned version always has the same jar set
(same classpath, same sha256 per jar). `baseline.py extract` stages each pin
from the first BOM that pins it (the two BOMs already on the local disk
first), extracts it, and hard-links `docs/<run>/<bom>/<svc>.yaml` to the pin's
document. The classpath is passed as `classpath/<svc>-<version>` (a symlink
under `.work/`), which is the only path the extractor writes into a document
header, so the bytes do not depend on which BOM supplied the jars.
`baseline.py verify-lock <bom>` stages one BOM whole, re-extracts all nine
services from it, regenerates `docs.lock` and compares it byte for byte with
the committed one. Does not change results.

## 2. One graph per BOM and one per pair, not one graph — *needs owner*

The handoff describes one `graph.yaml` with every BOM's documents and every
matched edge. `gus` treats the edge list as global: `consistent` and the
baseline gate inside `check`/`mss` visit every edge and hard-error when the
provider at the baseline lacks the endpoint (main.go:1097), and a caller
declaration missing at either version silently degrades the edge to the
provider self-diff (Tier 3, main.go:1145). Over 50 releases the edge set
changes (added and removed calls, endpoints that come and go), so a single
graph either fails to load at some BOM or silently mixes tiers.

What is built instead, all under `graph/<presence>/` so that no document path
escapes its graph's directory (graph.go:108-112):

* `bom-<bom>.yaml` — every edge matched at that BOM; the consistency gate.
* `P<NN>.yaml` — the edges matched at both BOMs of the pair (same caller,
  provider, verb and provider path), less the edges the baseline's gate
  excludes (§6). The 50 BOMs' loaded copies are shared by the pair graphs.
* `graph/edges.tsv` — one global catalog: every edge identity (caller,
  provider, verb, provider match key) with its name `<caller>-<provider>/<n>`,
  the BOMs it exists at, its spellings and whether its caller is opaque at
  each BOM. Names are numbered per (caller, provider) in order of the provider's
  erased path and verb over the whole range, so an edge keeps its name in every
  graph.
* `graph/deltas.tsv` — the edges that exist at only one BOM of a pair, with
  what the documents say about why (endpoint added or removed, call added or
  dropped, a declaration that pairs differently). These are the cross-version
  endpoint changes the per-edge model cannot express (a missing endpoint is a
  hard error, not a finding); they are reported beside the checker, not in it.

Why it needs the owner: an edge that exists at only one BOM of a pair is not
judged by the checker at that pair. That is forced by the checker, but it is
a scope statement the README has to carry.

Measured: 394 edge identities over the range, 376 of them at all 50 BOMs; the
pair graphs hold 284–317 edges once the gate has removed 77–98 per pair; 30
edges exist at only one BOM of their pair (`graph/deltas.tsv`); no edge changes
its provider spelling inside a pair, so no pair needed a respelled copy.

## 3. The caller's key is the checker's join, not the extractor's path

`loadEdgeSchemas` looks the caller declaration up under
`filepath.Join("/_calls", provider, edge.path)` (main.go:1121). The join
cleans its result, so the extractor's `/_calls/echo/` (for Retrofit's `POST /`)
is never found and the edge silently runs under Tier 3. Every loaded caller
operation is re-keyed to the joined form of the provider's spelling
(`normalize.calls_key`). Does not change results relative to the rules (D3
already says to rewrite the caller's path); recorded because the handoff calls
the lookup verbatim.

## 4. Path parameters are aligned by position — normalization defect fixed

D3 matches paths with variable names erased, but D6 keys `params` by name, so a
caller that spells a path variable `{name}` against a provider's
`{application}` sends `params.name` while the provider requires
`params.application` — REQ.1 on every such edge (116 findings on 96 edges at
1.38.0 before the fix). A path variable is positional on the wire; its name
never travels. In the loaded caller copy each path variable is renamed to the
provider's name at the same position (simultaneously: `{name}→{application}`
together with `{cluster}→{name}` is a permutation, not a clash), and a caller
literal that fills a provider variable becomes a required `params.<name>` typed
by the literal with the literal as `default` (as the extractor types baked-in
query literals, CallerScan.literal). Segments after a provider `**` are not
aligned. Marked `x-g3-path-params` on the operation. This is D11's
"normalization defect — fix in your normalizer".

## 5. D6 is applied on the caller's side — *needs owner*

The handoff: "where a caller operation carries `x-response-opaque: true`, the
provider's response on that edge is replaced by a contentless 200 in the loaded
copy". The provider's document is one file per BOM shared by every edge to that
endpoint, so the replacement cannot be confined to one edge, and two facts
measured on the corpus make it wrong outside the easy case:

* at 1.30.x ten, at 1.38.0 nine provider endpoints are called by an opaque
  caller and a typed caller at the same BOM; zeroing the provider's response
  breaks the typed caller (`presence-mismatch`, a body it expects is gone);
* the four response conjuncts use the caller at θ and θ′ against the provider
  at θ′ and θ; when a caller's opacity differs between the two BOMs (the
  Retrofit 1→2 migration), no per-BOM provider document satisfies both.

What is done: the opaque caller operation expects `{}` — the loader's Any,
which every response passes (compat.go:71-73) — whenever its provider returns a
body at that BOM (`x-g3-expect-any`). Where the provider is contentless too,
nothing changes (nil against nil passes). This agrees with the rule on every
pair where the rule is well defined, and in the one-sided cases it keeps the
typed version's comparisons. The residue: an opaque caller whose provider starts
or stops returning a body between the two BOMs gets a `presence-mismatch` on
the response leg (Any against nil, or nil against a body); `graph/<presence>/pairs.json`
counts those edges per pair (`d6_provider_body_changes`). Measured over the 49
pairs: no such edge, and one pair-graph edge whose caller's opacity changes
(P16, `orca-clouddriver/4`, opaque at 1.32.4 and typed at 1.33.0), on which
the checker reports nothing. On 73–79 edges per BOM the caller operation is
opaque; on 23–24 of them the provider returns a body, and the caller is loaded
expecting Any. Such findings sit on
a leg whose caller side is contentless and never count as evidence (compare.py
reads evidence on live legs only).

## 6. Triage: what a gate failure does to the pair

Every BREAK finding at a BOM's gate excludes its edge from the pair whose
baseline that BOM is — the checker refuses an inconsistent baseline
(main.go:476), so there is no alternative. An edge that is consistent at the
baseline and inconsistent at the target stays in the pair: the transition is
what the pair tests, and the break shows as TGT (and in the mixed conjuncts).
WARN-only findings do not exclude (`gus consistent` prints them; the gate inside
`check`/`mss` counts BREAKs alone, main.go:469).

Categories are assigned by `gate.py classify` from the documents plus two tables
read off the bytecode (`PROVIDER_RESPONSE`: whether a contentless provider
response is `void`, a stream, or a raw `ResponseEntity`; `PROVIDER_PARAMS`: an
`Optional<T>` request parameter the document marks required). The four D11
categories are used as the handoff defines them, with one addition — *needs owner*:

**checker limitation.** Both declarations are what the rules make of the Java,
the wire shapes agree, and the checker still reports a break: an open untyped
object (D5's projection of `Map`/`Object`) against a typed map or a POJO
(`kind-mismatch` object/map), or an untyped side against a value of another
JSON kind. D5's ruling assumed a leg with one untyped side "can only pass"; on
this checker it can fail, because the only top type is Any and D5 forbids
projecting to it. These edges are excluded like the others (the checker forces
it) and reported under their own name rather than as projection defects (the
documents follow D5) or real inconsistencies (the wire agrees).

## 7. The strict lattice is kept — *needs owner*

`gus` compares primitives under the strict JSON lattice unless a scenario asks
for `coercion: lenient`. Both ends of every edge here are Java: Spring binds a
query or path parameter from its text through the conversion service (a
`boolean` argument arrives as `"true"`, which a `String` parameter accepts), and
Jackson's default mapper coerces scalars (`MapperFeature.ALLOW_COERCION_OF_SCALARS`,
`DeserializationFeature.ACCEPT_FLOAT_AS_INT`). No rule of the plan names a
coercion profile, so every scenario runs strict. At the gate the parameter
cases are triaged as projection defects with that reason (`parameter text
binding`), and a scalar difference in a body (orca reads a kayenta `double` as
`int`) as a real inconsistency — Jackson would truncate, which is a change of
value. A lenient run is one line per scenario and would remove the text-binding
findings (and admit scalar→string in bodies); it is not done here.

## 8. A primitive `@Query` is sent — projection defect, by table

G1 decision 5 reads every Retrofit `@Query` as optional ("omitted when null").
A Java primitive is never null. Of the 45 REQ.2 findings on a named query
parameter at 1.38.0, the Retrofit signatures (javap) put 42 on reference types,
2 on primitives and leave 1 unmatched; at 1.30.0, 38/2/1 of 41. The primitive
that is not already explained by the provider's `Optional` parameter
(`orca Front50Service.setPreferredPluginVersion(@Query("preferred") boolean)`)
is triaged as a projection defect through `gate.CALLER_PRIMITIVE_QUERY`; the
reference-typed ones stay real inconsistencies as the rule reads them. The
check was made on the pins of 1.30.0 and 1.38.0 only.

## 9. Checker output is compared on structure, never on its text

`gus` prints type summaries of objects with their fields in map iteration
order, which changes between runs on identical inputs (CLAIM-G3-019). The
harness reads `check --format json` and matches findings on edge, conjunct,
path and rule; the `old`/`new` summaries are carried for the reader only.

## 10. Other open points, not result-changing

* **`gus mss` only where `gus check` says no.** Where a batch is safe, `mss`
  prints the check and one fixed sentence (main.go:126-130); run.sh writes that
  text instead of a second run.
* **`gus evolve` per pair.** It needs one graph whose edges exist at every step,
  which §2 rules out; each pair's step runs against its pair graph, in version
  order, through one ledger (the ledger skips recorded steps). No identity is
  annotated in the first run (D9), so the ledger records no identity.
* **The listing run.** unmatched.tsv's categories `kork` and `indirect-fiat`
  are operations the profile documents do not contain; they come from a
  client-only extraction with both families kept (`common.KEEP`).
