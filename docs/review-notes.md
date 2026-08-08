# GUS/MSS — deck review notes (errata, prior art, significance)

A slide-by-slide review of `gus-mss-deck.pdf` against the implementation,
the literature, and the tool ecosystem (July 2026). Items marked **fixed**
were corrected in the reference implementation as part of this review;
items marked **deck** need changes to the deck/paper text itself.

---

## Slide 1 — "Pact: pairwise contract testing"

Fair as far as it goes. Two caveats for the paper text:

- Pact is *example-based behavioral* verification of real provider code.
  That is a weakness (coverage = examples) **and** a strength GUS lacks:
  Pact verdicts are about deployments, GUS verdicts are about documents.
  Empirically specs drift — APIContext measured ~75% of production APIs
  deviating from their published OpenAPI specs — so "tests cover
  examples, not types" cuts both ways and the paper should say so.
- Pact Broker's `can-i-deploy` + verification matrix already answers the
  cross-version question dynamically: it checks a candidate version
  against **all versions currently deployed in an environment** and
  accepts multiple pacticipants per query (a batch). What it lacks is
  type-exhaustiveness, chains, subset/ordering output.

## Slide 2 — "What Pact misses — and the lattice fix"

- **`int ≤ str`, `bool ≤ str` as default is wrong** (deck, **fixed** in
  code). "A JSON parser tolerates it" is true of Jackson (which coerces
  scalars to String by default and — see jackson-databind #3240 — can't
  even be configured not to) and of untyped JS consumers. Go
  `encoding/json`, serde_json, pydantic v2 (lax *and* strict) and JSON
  Schema validation all reject a number token where a string is
  declared. The implementation now defaults to a strict order
  (`integer ≤ number` only) with `coercion: lenient` as an explicit
  per-scenario profile. The paper should present coercion as a
  *per-consumer-stack profile*, not an axiom.
- `integer ≤ number` silently loses precision above 2^53 when the
  consumer models number as IEEE-754 double (deck: add the caveat).
- "Lattice" is a misnomer: `int < num < str`, `bool < str` is a poset
  (int and bool have no meet). Cosmetic, but the deck leans on the word.
- "Closed objects" was advertised but the response side never consulted
  openness (**fixed**: RES.5 flags fields added into a closed consumer;
  note no shipped spec uses `additionalProperties: false`, so add one to
  a scenario if the claim stays).
- Prior art for the asymmetric primitive story: Avro's writer→reader
  promotion rules (int→long→float→double, string↔bytes) have shipped
  since ~2010 and are what registries execute; Confluent's JSON Schema
  mode promotes writer `integer` to reader `number`. No surveyed tool
  treats `int ≤ string` as safe — GUS's lenient edge is nonstandard and
  must be justified per stack.

## Slide 3 — "A handful of subtyping rules"

- The rules are (co/contra-variant) record + enum-set subtyping — i.e.
  **Gay & Hole binary session subtyping** (Acta Informatica 2005) plus
  standard width/depth rules. That is the right citation (see slide 5).
- **`x-tolerance` is vaporware** (deck): mentioned as the escape hatch
  for response-enum widening, parsed nowhere, present in no spec. Either
  implement or cut.
- The rule notation switches silently between value-set inclusion
  (enums) and field-set inclusion (objects), and quantifies over
  `sent(caller)` — which, in the shipped artifact, didn't exist (see
  slide 4). **Fixed**: caller schemas are now real when declared.
- "(Ref,Ref) ↦ ⊤, decidable on finite ASTs": what the code did was
  *name equality* with a write-only seen-set — no unfolding, no
  structural comparison; renaming a component with identical structure
  was a guaranteed false BREAK. The loader in fact inlines refs and only
  emits `Ref` at cycle back-edges, so one-unfolding comparison + assume
  at same-named back-edges is sound — but resolution order was Go map
  order, making verdicts **nondeterministic under mutual recursion**
  (probe: 8/60 vs 52/60 runs). **Fixed**: sorted deterministic
  resolution; deck should describe the actual (loader-level) coinduction.
- Enum-vs-prim fell to a blanket kind-mismatch, contradicting this
  slide's own value-set semantics (`Enum(S) ≤ Prim(base)` is safe on the
  request leg, etc.). **Fixed** with value-set rules; same for
  literal/prim and literal/enum directions (both false-negative and
  false-positive branches existed).

## Slide 4 — "From two schemas to four"

The centerpiece claim — and in the shipped artifact it was **silently
inert twice over**:

1. The `/_calls/<provider><path>` caller lookup used a lowercase HTTP
   method against an uppercase-keyed index: it could never match
   (**fixed**, and the loader now also honors the convention the specs
   actually use — the provider path marked `x-role: client`).
2. Zero specs used `/_calls`, so 100% of edges ran the Tier-3 fallback
   `Send := Accept`, `Expect := Return`.

Consequences while broken: C2 was the mirror of C1 and C4 of C3 (a
bidirectional provider self-diff — exactly what a registry's FULL mode
does); scenario C/H caller-side narratives influenced nothing; the
fallback *fabricated* caller drift, producing false BREAKs on canonically
safe provider request-widening (probe: enum `[fast,slow]→[fast,slow,turbo]`
flagged as C2 "narrowing" and excluded from MSS). **Fixed**: the fallback
now anchors the caller to the *old provider contract* in both states
(callers were built against the live contract), which makes C2/C4/TGT
trivially true and C1/C3 an honest backward-compat diff; reports label
Tier-3 edges explicitly.

- Tier 1 (source-derived Send) remains unimplemented — the deck presents
  a three-tier ladder of which the top rung is the load-bearing one for
  the whole premise. Respector (ICSE'24), AutoGuard/AutoOAS (2025) and
  Akita/Postman's traffic inference show this layer is buildable; the
  paper should position Tier 1 as *consuming* that work.

## Slide 5 — "Session types: one pairing, then three more"

- **Terminology** (deck): C1–C4 are 2 mixed pairings × 2 legs, not four
  pairings. The (θ,θ) pairing is the baseline; (θ′,θ′) is the target
  state. The README used to claim "all four pairings" are checked while
  the code checked only the two mixed ones — **fixed** (TGT conjunct now
  checked when caller schemas are real; `consistent --state target`).
- **The "WHY ONLY THREE" box is formally wrong** (deck): `¬x_u ∨ ¬x_v`
  has zero positive literals and therefore *is* a Horn clause; Horn-SAT
  with it stays linear-time satisfiable. What actually breaks is (a)
  satisfying true-sets stop being union-closed, so the *unique maximum*
  collapses, and (b) maximum-cardinality becomes NP-hard (Max-Ones over
  weakly-negative constraints; Khanna–Sudan–Trevisan–Williamson — the
  citation that makes the box rigorous; it embeds independent set).
  Inclusion-maximal subsets would remain poly-time. Also, the promised
  post-hoc `GUS(θ′,θ′)` **did not exist** in the implementation
  (**fixed**: TGT conjunct + post-hoc re-verification of the safe
  subset in `mss` and `validate`).
- **The MPST citation is misplaced** (deck): nothing multiparty is used —
  no global types, no projection, no sequencing; each edge is an
  isolated binary request/response. Cite Gay & Hole. (Ironically, global
  protocol composition is the one MPST idea that would address slide 2's
  "no global composition" complaint.)
- The C1 box's "dual & well-typed channel iff Send ≤ Accept" misstates
  duality — well-typedness of the exchange also needs the response leg.

## Slide 6 — "Per-edge checks become Horn clauses"

- **The worked example's clause was unsound as implemented.** The deck
  emits `¬x_B ∨ x_A` ("if B upgrades, A must upgrade too") for a C1
  failure. Under the deck's own coexistence premise, upgrading A does
  not remove old-A instances *during* the roll — the implication is only
  sound if A **completes before B starts**, i.e. it is an *ordering*
  constraint, which the deck never states and the solver never modeled.
  Worse, the implementation ignored conjuncts entirely and emitted the
  symmetric biconditional for every both-upgrading broken edge, which
  unit propagation can never falsify: a two-service batch whose shared
  edge failed C1 **and** C4 returned *both services as the "safe"
  subset* (reproduced; `Decision: NO` followed by
  `Safe subset: {frontend, checkout}`). The 8-scenario suite couldn't
  see it because the old validator only checked MSS ⊇ expected.
  **Fixed**: conjunct-aware clause generation per the pinning rule,
  explicit precedence constraints (C1/C3 ⇒ caller before provider,
  C2/C4 ⇒ provider before caller), deadlock-cycle detection (C1+C4
  co-failure ⇒ no rolling order exists ⇒ exclude the pair), rollout
  order in the output, exact-match validation, and post-hoc
  re-verification. The deck needs the ordering semantics stated and the
  pinning-rule box amended: a failure pins one θ′ variable *and orients
  a rollout edge*.

## Slide 7 — "HORN_MSS: the linear-time safe-subset solver"

- The algorithm is **Dowling–Gallier (1984)** unit propagation computing
  the complement of the unique minimal model; uniqueness follows from
  Horn model-intersection closure. Correct — and 40 years old; cite it.
- "Unique maximum-cardinality" and O(|clauses|+|U|) hold only for the
  definite+unit fragment — i.e., only because the hard constraints
  (target-state conflicts, deadlock pairs) were dropped. With them, the
  answer is conservative, not maximum (documented in `pkg/solver`).
- The pseudocode's `blocked ← services_in(clauses)` would block every
  service any clause mentions — as written it computes the wrong set
  (deck: fix to "unit-clause targets ∪ deps outside U").
- "Linear time" markets the cheap stage: the dominant cost is the GUS
  sweep (edges × spec size). The implementation now memoizes spec
  parsing, but the paper's complexity claim should be about the whole
  pipeline.

## Slides 8–9 — "Catching multi-hop integrity violations"

- **The entire chain feature was dead code**: `pkg/chain` had zero
  importers; scenario D actually validated an ordinary direct-edge RES.4
  (contradicting "no two-service contract spans the chain"), and
  scenario I's integer-vs-string chain claim produced no output. Even if
  wired, the checker compared only required/nullable — **no types** —
  so the scenario I claim was undetectable *by design*; and the x-alias
  tier was an explicit no-op stub. **Fixed**: chains are wired into
  `check`/`mss`/`validate`/`viz`; typed (identities are strictly typed
  end-to-end, deliberately ignoring the lenient profile); the source
  hop is judged by the annotated field itself; culprits are attributed
  by single-revert analysis and feed unit clauses; scenario D is now a
  true chain-only break (every per-edge conjunct passes) and scenario I
  reports `chain-type-mismatch`.
- **Semantic muddle to state honestly** (deck): fields live in requests
  (flowing caller→provider) or responses (flowing provider→caller), but
  discovery BFSes forward call edges only, so response-carried
  identities (slide 9's `returns: correlationId`!) flow to nodes not on
  any discovered path. The implementation now scopes chains to
  request-carried identities; the deck's A→B→C→D picture needs that
  restriction or a flow-aware graph.
- "Intermediates annotate nothing" vs. tier 3 "x-alias declaration at a
  renaming hop" is a self-contradiction (the alias *is* an annotation on
  the intermediate) — and tier-2 case normalization (lowercasing) does
  not bridge the slide's own `correlationId ≡ correlation_id` example
  (that needs camel/snake normalization).
- Slide 9's YAML (`calls:/sends:/accepts:` + annotation lists) matches
  no format the loader parses. Replace with the real syntax (inline
  `x-provides: "key"` on OpenAPI schema fields).

## Implementation-only findings (no deck change needed)

All fixed in this review:

- `gus consistent` always printed `Result: YES` (variable shadowing,
  with an `_ = status` silencing the compiler).
- Schema-load errors, typo'd services/versions, unknown upgrade targets,
  unparseable specs and kafka edges were **warn-and-skip → silent PASS**;
  a one-character typo flipped Decision NO to YES with exit 0. All are
  now hard errors (exit 2); `mss` no longer exits 0 for a failing batch.
- `validate` was one-sided (MSS subset check, `mss: []` skipped, extra
  breaks unchecked) — a degenerate solver returning *all* upgrades
  passed 8/8. Now exact-match + chains + post-hoc.
- `allOf`/`anyOf` silently became `Any` (checking disabled for the
  subtree); property conversion errors degraded to `Any`; dangling
  `$ref`s loaded as vacuously-compatible names. Now errors.
- `additionalProperties`-as-schema was dropped (checkMap unreachable);
  now modeled as `Map` for property-less objects.
- Format (int32/int64) range checks didn't flip variance on the response
  leg (real overflow hazard silent, safe direction warned). Fixed.
- Violation old/new labels were role-positional, printing chronology
  backwards for C2/C4 (`old: integer → new: string` for a v1
  string→v3 integer change). Messages are now role-phrased and edge.go
  restores chronological labels per conjunct.
- Union matching escalated WARN-only variant pairs to BREAK, reported
  only the first unmatched variant, and had no width subtyping.
- MSS output ordering was nondeterministic (map iteration). Sorted.
- viz: `escapeHtml` didn't escape quotes (attribute-injection XSS from
  mesh-controlled strings); `SpecPath` allowed `../` traversal into the
  shareable artifact (spec contents are embedded verbatim); the "what
  only GUS catches" panel classified by rule name only, so C1/C2
  findings any pairwise differ catches were labeled GUS-unique. Fixed
  (quote escaping, path confinement, conjunct-filtered panel, chain
  rendering). Remaining: viz.html loads p5.js/fonts from CDNs with no
  SRI — not self-contained as claimed.

## Significance assessment (summary)

**The problem is real; the framing needed narrowing.**

- *For*: SOSP'21 (Zhang et al.) — ~⅔ of 123 real upgrade failures in 8
  mature systems were cross-version incompatibilities, 40% via network
  messages, mostly caught after release; protobuf's `required` removal
  and proto3 unknown-field reversal are documented instances of exactly
  the required-field and passthrough chain classes; Kubernetes publishes
  a hand-written version-skew policy GUS-style checking would mechanize.
- *Against*: response-enum widening has library-crash evidence but no
  named public outage; most headline incidents (Knight, Reddit Pi-Day,
  Monzo, Cloudflare '25) violated contracts *not visible in any spec*;
  disciplined teams already forbid every scenario via expand/contract +
  per-repo CI diffing; and continuous per-service deployers have no
  batch for MSS to optimize.
- *The honest target user*: platform teams and vendors shipping
  **versioned multi-service releases** — Helm umbrella charts, ArgoCD
  app-of-apps, on-prem bundles, deploy trains — where "exclude service X
  and roll in this order" is mechanically actionable.
- *The genuinely novel composition*: static cross-version subtyping over
  OpenAPI, mesh-wide, with subset + **rollout order** output. Per-edge,
  it is approximately "oasdiff run per direction with a coercion
  profile"; nobody else does the batch-level composition. The chain
  layer is novel but annotation-priced; *inferring* provenance (from
  traces/code) is the piece that would be a real research contribution.
- *To be credible, the paper needs*: spec-vs-reality validation (or
  Tier-1 inference), evaluation on real version histories rather than
  authored scenarios, the ordering-aware solver this review added, and
  the honest tool comparison above.

## Key references surfaced by the review

- Gay & Hole, *Subtyping for session types in the π-calculus*, Acta
  Informatica 2005 (the correct citation for C1–C4 subtyping).
- Dowling & Gallier, *Linear-time algorithms for testing the
  satisfiability of propositional Horn formulae*, JLP 1984 (HORN_MSS).
- Khanna, Sudan, Trevisan, Williamson, *The approximability of
  constraint satisfaction problems*, SICOMP 2001 (Max-Ones/Horn
  NP-hardness — the real "why only three" argument).
- Zhang et al., *Understanding and detecting software upgrade failures
  in distributed systems*, SOSP 2021 (+ DUPChecker: static cross-version
  format checking, 800+ finds — closest prior tool).
- Ajmani, Liskov, Shrira, *Modular software upgrades for distributed
  systems*, ECOOP 2006; Ma et al., *Version-consistent dynamic
  reconfiguration*, ESEC/FSE 2011 (mixed-version correctness lineage).
- Seco et al., *Robust contract evolution in a type-safe microservices
  architecture*, ⟨Programming⟩ 2020 (type-safe cross-version contract
  evolution with coexisting consumers, at OutSystems).
- Confluent Schema Registry compatibility modes; Avro schema resolution;
  Buf breaking rules (WIRE/WIRE_JSON); Pact `can-i-deploy`/matrix;
  oasdiff breaking-change catalog (direction-aware, incl. response-enum
  warnings); Google Service Weaver (cross-version communication
  eliminated by construction; archived 2025).
- Fowler, *ParallelChange* (expand/contract) and *TolerantReader*; AWS
  Builders' Library, *Ensuring rollback safety during deployments*
  (two-phase serialization changes — the operational doctrine GUS
  mechanizes).
