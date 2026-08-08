# A first-principles primer for the GUS/MSS research line

This is the study guide for the ideas behind the checker and the paper —
what you need to hold in your head to defend every claim, roughly in the
order the ideas depend on each other. Each section ends with the *one
sentence you should be able to say under questioning*, and readings.

---

## 1. The object of study: mixed-version states

A "deployment" is not an atomic state change. Rolling upgrades replace
instances gradually, so for minutes-to-hours the mesh is a **mixture**: any
request may hit an old or new instance on either end. The system therefore
transits a *set of states*, and safety is a property of the whole set —
this is reachability, the most basic move in formal verification: don't
check the destination, check everything you pass through.

Model: a deployment state is a map θ : Services → Versions. A batch U
yields target θ′ = θ ⊕ U. Under the two-versions assumption, each
upgrading service is old, mixed, or new at any instant; an *unordered*
rollout makes every combination reachable. That's why per-edge safety
needs exactly five checks: the two mixed pairings × two message legs
(C1–C4), plus the target pairing (TGT). The baseline pairing is an
assumption you check separately (`Consistent(θ)`) — and it is an honest
*assumption*: GUS certifies transitions, given a sane starting point.

> **Say it:** rolling safety = every reachable mixed-version state is
> consistent; with ≤2 live versions per service that reduces to five
> subtype checks per edge.

Reading: Zhang et al., *Understanding and Detecting Software Upgrade
Failures in Distributed Systems* (SOSP 2021) — the empirical license for
the whole problem (≈⅔ of real upgrade failures are cross-version
interaction, 40% of those via network messages).

---

## 2. Types as sets, subtyping as inclusion, variance as direction

Read a schema as the **set of values** it admits. `T₁ ≤ T₂` means every
value of T₁ is admitted by T₂ — set inclusion. Everything in the compat
checker falls out of asking "who produces, who consumes":

- **Request leg** (`≤_req`): the caller produces, the provider consumes.
  Safe iff Send ⊆ Accept. The *provider's accept set may grow* (widening
  is safe), never shrink. From the provider's viewpoint this is
  **contravariance**: it's safe to demand *less*.
- **Response leg** (`≤_res`): the provider produces, the caller consumes.
  Safe iff Return ⊆ Expect. The *provider's return set may shrink*, never
  grow. **Covariance**: it's safe to promise *more specifically*.

Every concrete rule is this one principle specialized to a constructor:
enums are literal value sets (widening a *response* enum breaks strict
consumers — the "unknown variant crashes the switch" bug); objects use
width/optionality (a required accept field = demand, a required return
field = promise); unions match existentially (T ≤ Union{T,…} on the
request side); `nullable` is just Union{T, null} with the same variance.

**The four-schema model** exists because `Send ≠ Accept` in reality:
caller code drifts from provider contracts. Each side *owns* two schemas
(caller: Send/Expect; provider: Accept/Return). When the caller declares
no outbound contract, the honest fallback is to anchor the caller to the
*old provider contract* — "callers were built against what was live" —
which degrades gracefully to classical backward-compat checking instead
of inventing caller drift (this exact mistake — fabricating Send :=
Accept(θ′) — was the worst bug in the original POC: it manufactured
false breaks on *safe widenings*).

> **Say it:** one relation, two orientations; every rule is "producer's
> set ⊆ consumer's set" for some constructor.

Reading: any treatment of variance (Pierce, *Types and Programming
Languages*, ch. 15–16); Liskov substitution as the semantic anchor.

---

## 3. Orders, lattices, and why "int ≤ string" is a *profile*, not a truth

The primitive order (integer ≤ number, etc.) is a **partial order** on
primitive types (colloquially "the lattice"; pedantically it need not
have meets/joins). The key epistemic point: an order edge is a claim
about *decoder behavior*, not about mathematics. `integer ≤ string` is
TRUE for Jackson (which coerces scalars to strings by default) and FALSE
for Go's `encoding/json`, serde, pydantic v2, and JSON Schema validation.
So coercion edges are per-consumer **profiles** (strict default, lenient
opt-in), never axioms. Corollary that generalizes: *any* compatibility
judgment is relative to a runtime semantics; a static checker must name
the semantics it assumes. (Same reasoning killed `float ⊑ double` in the
proto order: float is wire-type I32, double I64 — "widening" across them
is silent data loss, per the protobuf encoding spec.)

Severity also lives here: some order violations are *range* risks rather
than *shape* breaks (int32 → int64 response widening can overflow an old
consumer but decodes fine) — hence WARN vs BREAK, and WARNs neither block
nor generate repair clauses.

> **Say it:** the primitive order is parameterized by a consumer decoding
> profile; strict is the default because soundness claims must hold for
> the least forgiving deployed decoder.

---

## 4. Recursive types and coinduction

`Category { name, children: [Category] }` is an equi-recursive type — an
infinite tree. You cannot check `T ≤ T′` by structural induction (no base
case). The standard move is **coinduction**: to check a claim that
unfolds forever, assume the claim at the point of recursion and verify
one unfolding; if no contradiction arises, the claim holds (it's the
greatest fixed point of the checking rules — the Amber rule). In the
implementation: the loader inlines one unfolding and leaves `Ref` nodes
at cycle back-edges (in *deterministic* order — resolution order changes
the AST shape under mutual recursion, which once made verdicts flip
run-to-run); the checker assumes compatibility when it re-encounters a
Ref pair it is already checking.

> **Say it:** inductive proofs consume structure, coinductive proofs
> defend an assumption through one unfolding; equirecursive subtyping is
> decidable this way on finite representations.

Reading: Pierce ch. 20–21 (recursive types, coinduction).

---

## 5. Session types — what we borrow and what we honestly don't

Gay & Hole (2005) defined subtyping for *binary session types*: when can
a channel endpoint be substituted for another, with input positions
covariant and output positions contravariant. One RPC = the degenerate
session `!Send.?Expect.end` against `?Accept.!Return.end`, so C1–C4 are
Gay–Hole subtyping instantiated per version pairing. **Do not cite
multiparty session types** (Honda–Yoshida–Carbone) for this: MPST's
substance is *global protocols* projected to local ones — sequencing,
choice, delegation across ≥3 parties — none of which per-edge
request/response checking uses. (The original deck cited MPST; a
formally-minded reader flags that instantly.) The honest MPST hook is
*future* work: rollout stages are a global ordering artifact, and an
identity chain is a degenerate global protocol — if chains ever acquire
ordering ("K must be minted before it is spent"), MPST machinery becomes
relevant.

> **Say it:** per-edge checking is Gay–Hole binary session subtyping;
> the mesh-global and temporal composition is what's new here, and it is
> *not* MPST — yet.

---

## 6. Horn logic: why "the" maximal safe subset exists at all

Propositional background you should have cold:

- A **Horn clause** has ≤1 positive literal. Three species:
  **definite** (¬a ∨ b, i.e. a → b), **negative/goal** (¬a ∨ ¬b … zero
  positive literals — *still Horn*), and **facts**.
- Horn **satisfiability** is decidable in linear time by unit propagation
  (Dowling–Gallier 1984); definite programs have a *least* model
  (intersection-closure of models).

MSS asks the dual question — maximize *true* variables (upgrades kept)
subject to the clauses. The load-bearing lemma:

**Union-closure lemma.** For clause sets of only definite clauses and
negative *units* (¬a), satisfying true-sets are closed under union.
*Proof:* if a ∈ T₁ ∪ T₂ then a ∈ Tᵢ for some i, so b ∈ Tᵢ ⊆ T₁ ∪ T₂ for
any clause a → b; a negative unit false in both stays false in the union.
∎ Hence the union of all models is itself a model — the **unique
maximum** — and falsity-propagation (dual to Dowling–Gallier) finds it in
O(|clauses| + |U|).

Where do the clauses come from? The **pinning rule**: every conjunct
fixes one schema at θ and one at θ′, so a violation names exactly one
batch member on its θ′ side — and an *ordering fact*. C1/C3 failure on
u→v: old-u can't face new-v ⇒ if u's contract can't change, unit ¬x_v;
otherwise definite ¬x_v ∨ x_u **plus precedence u ≺ v**. C2/C4 mirror.
The clause without its precedence is *unsound* (this was the original
POC's central bug: it emitted implications, satisfied by "keep both",
for edges broken in *both* directions — GUS said NO and MSS blessed the
same pair).

**The hard boundary.** TGT failures and precedence *cycles* mean "not
both": ¬x_u ∨ ¬x_v. Zero positive literals — still Horn, satisfiability
still linear (the original deck's "non-Horn" justification is formally
wrong; know this cold, it's the kind of slip a logician catches). What
actually breaks is union-closure ({u} and {v} are models, {u,v} isn't):
uniqueness dies, and maximizing true variables now encodes **maximum
independent set** (one conflict clause per graph edge) — NP-hard, per the
Max-Ones classification of Khanna–Sudan–Trevisan–Williamson. Design
consequence: propagate the easy fragment exactly; excise whole deadlock
SCCs conservatively (sound, deliberately not maximum — refusing to hide
an NP-hard choice inside a safety tool); leave preferences to weighted
MaxSAT as future work. Note the distinction *maximum-cardinality*
(NP-hard here) vs *inclusion-maximal* (still easy) — say the right one.

> **Say it:** definite-plus-negative-unit clauses are union-closed, so a
> unique maximum exists and propagation finds it; one "not both" clause
> destroys union-closure and puts maximum-cardinality in independent-set
> territory.

Reading: Dowling & Gallier 1984; Khanna et al., SICOMP 2001 (Max-Ones).

---

## 7. The order theory of rollouts

Precedences (u ≺ v: "u fully rolled before v starts") form a digraph over
the surviving batch. A valid *staged* schedule is a linear extension —
compute it as Kahn layers (all stage-i services roll concurrently, stage
i must complete before i+1). **A cycle is a proof that no schedule
exists**: e.g. C1 fails (u before v) *and* C4 fails (v before u) on one
edge — the pair can only ship by atomic switchover, which rolling
deployment doesn't offer. So: Tarjan SCC → excise components of size >1
→ re-propagate (exclusions trigger definite clauses) → repeat; the safe
set shrinks monotonically, so it terminates.

The output being a *plan* changes what verification means: the
certificate is checked by **replaying the stages** — verify all conjuncts
of stage i against the accumulated state, fold stage i in, continue. A
plan that only works sequenced passes exactly this replay and would
rightly fail a naive simultaneous re-check. (Also the honest framing of
"linear time": propagation is linear; the dominant cost is the schema
sweep over edges, and replay multiplies it by stages.)

> **Say it:** violations are ordering constraints; MSS is "largest
> subset whose precedence digraph is acyclic after propagation," and the
> schedule is its topological order, certified by staged replay.

---

## 8. Chains: invariants that belong to no edge

Some invariants span hops: checkout mints an order id that must arrive at
email intact. Every hop *tolerating* the field optional is good
engineering — and precisely why no per-edge check fires when the
guarantee erodes. This is not hypothetical: proto2 `required` enforced by
*middle* hops of multi-hop chains caused real Google outages, and
`required` was removed from proto3 because of it.

Design decisions worth defending:
- The sink's annotation (`x-requires`) *is* the requirement; its accept
  schema stays tolerant (else the direct edge would catch everything and
  the chain adds nothing).
- Hops are validated against what they **send onward** (their outbound
  contract toward the next hop) — that's what makes renames meaningful,
  and `x-alias` is the declared rename bridge.
- Identities are **strictly typed** even under lenient edge profiles: an
  identity is joined on/stored, not merely parsed; representation change
  is corruption even when decoding succeeds.
- A mesh can route an identity along several paths (diamonds), and
  statically you don't know which one traffic takes — so *all* simple
  paths must carry it (`AllPaths`, bounded).
- Known scope hole to volunteer before anyone asks: discovery walks
  forward call edges, so *response-carried* identities (flowing
  provider → caller) are out of scope.

> **Say it:** chains are end-to-end invariants deliberately invisible to
> edge-local checks; checkability comes from making origin and demand
> explicit and verifying the guarantee at every emitting hop, on every
> path.

---

## 9. Time, provenance, and counterfactual blame

The deepest idea, and the one to lead with in a conversation with Peter.

**Violations are temporally non-local.** Chain integrity at step k is a
predicate on state θₖ alone — but its *cause* can live in an earlier
diff. The canonical trace: step i weakens a guarantee nobody requires
(no chain exists → nothing fails → it ships); step k introduces a
requirer; step k's check fails. Any per-transition tool must blame step
k's diff — the only excludable change in that batch — which is exactly
backwards: the requirer is the victim. Formally: per-step checking
decides `Safe(θₖ₋₁ → θₖ)`, but the meaningful judgment is over the
*trace* θ₀ … θₖ. Safety composes over transitions; **blame does not**.

The fix is provenance. The **ledger** records, at every *shipped* state
(shipped = baseline ⊕ MSS, not the proposal), each provided identity's
guarantee tuple — provider, field, type, required/nullable, carrying
paths — whether or not anything demands it yet. Events: born, eroded,
restored, demanded, violated. When a violation finally fires, the ledger
answers "where did this guarantee last weaken?"

**Blame is counterfactual.** A shipped change is a culprit iff replaying
with that change reverted repairs — or dissolves — the chain. That is
but-for causation in the Halpern–Pearl structural sense, and it is
deliberately the reasoning pattern of Alvaro's lineage-driven fault
injection run in reverse and statically: LDFI asks *which injected fault
would break this good outcome*; we ask *which shipped change, had it not
shipped, would unbreak this bad one*. Two honest wrinkles: (a) reverting
the provider or the requirer both "fix" a chain (either dissolves it), so
minimal culprit sets are a hitting-set problem — NP-hard again — and the
conservative answer (exclude every single-revert repairer) is consistent
with the deadlock policy; (b) a chain that first *exists* at θ′ (new
requirer) counts against the batch even though the erosion is old —
that's the case where per-step semantics and trace semantics visibly
disagree, and the ledger is what reconciles them.

The CALM-flavored one-liner: consistency questions become easy when you
stop pretending time isn't there. Contract safety is a property of
traces; pretending it's a property of diffs forces the wrong blame.

> **Say it:** per-step checking is sound for *detection* but structurally
> wrong for *attribution*; the ledger is provenance over deployment
> history, and culprit analysis is static, reversed LDFI.

Reading: Alvaro–Rosen–Hellerstein, *Lineage-driven Fault Injection*
(SIGMOD 2015); Halpern & Pearl, *Causes and Explanations* (Part I);
Hellerstein & Alvaro, *Keeping CALM* (CACM 2020).

---

## 10. Threats you should raise before your audience does

1. **Specs are not behavior.** Measured OpenAPI↔production drift is
   large (APIContext: 75% of APIs deviate). A PASS is one-sided: "no
   statically visible hazard in the *declared* mesh." FAILs are
   near-certain wire breaks. The verdict asymmetry is a feature to state,
   not a flaw to hide; contract inference (traffic/traces/source) is the
   obvious next layer. Pact's counterpoint cuts both ways: it tests real
   behavior on a narrow slice; GUS covers the full type space of a
   possibly false document.
2. **Who has a batch?** Continuous per-service deployers have no reviewed
   U. The persona with batches: umbrella-chart/app-of-apps releases,
   vendor bundles, monorepo trains — where "exclude service X" is
   mechanically actionable.
3. **Two-versions assumption.** Canaries hold ≥3 live versions; the
   pairing enumeration generalizes to C(n,2) per edge but the tool
   doesn't do it yet.
4. **Annotation burden.** provides/requires/outbound contracts are
   hand-written; stale annotations silently corrupt chain verdicts
   (worse than Pact's executable contracts, which fail loudly when
   stale). Inferring provenance chains from telemetry is arguably the
   real research contribution hiding here.
5. **Conservative ≠ maximal.** Deadlock SCC excision and culprit-set
   exclusion both over-exclude by design; know why (NP-hardness +
   refusal to hide arbitrary choice), and know the escape hatch
   (weighted MaxSAT).
6. **Rollbacks.** An aborted rollout traverses the same pairings in
   reverse; the model covers it (swap θ, θ′), the tool doesn't yet.

---

## 11. Map from theory to code

| Idea | Where it lives |
|---|---|
| ≤_req / ≤_res structural rules | `pkg/compat/compat.go` |
| Coercion profiles, proto wire order | `pkg/lattice/lattice.go` |
| Coinductive Ref handling, deterministic resolution | `pkg/compat` (checkRef) + `pkg/schema/loader.go` |
| C1–C4 + TGT, chronology-correct labels | `pkg/edge/edge.go` |
| Pinning → clauses + precedences | `cmd/gus/main.go` (buildClauses) |
| Union-closure propagation, SCC deadlock excision, Kahn stages | `pkg/solver/horn.go` |
| Staged-replay certificate | `cmd/gus/main.go` (computeMSSWithPostHoc) |
| Chains, AllPaths, alias resolution | `pkg/chain/chain.go` |
| Ledger, erosion events, counterfactual culprits | `pkg/evolve/ledger.go`, `cmd/gus/evolve.go` |
| The living counterexamples | `scenarios/online-boutique/evolution/` (see its README's coverage matrix) |

The eleven-step evolution suite is the argument in executable form:
step 03 (violations as *order*), step 10 (only the target state breaks —
the conjunct pairwise tools never run), steps 07→11 (erosion, then
exposure; ledger blames 07). The review that motivated half of these
design decisions is `docs/review-notes.md` — read it once; it is the
list of mistakes this design has already made and paid for.
