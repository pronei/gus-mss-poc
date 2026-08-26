# gus-mss-poc

A static compatibility checker for batched microservice upgrades.
Given a service mesh and a proposed set of version changes, GUS (Global
Upgrade Safety) reports every statically visible wire hazard the batch
would create across the mixed-version windows of a rolling deployment;
when the batch is hazardous, MSS (Maximal Safe Subset) computes a safe
sub-batch plus a rollout order for it.

This repository is the reference implementation accompanying the
GUS/MSS paper. It's a proof of concept — small, readable, and
intentionally scoped to OpenAPI + JSON Schema — designed to validate the
formalism on scenarios derived from Google's Online Boutique demo.

> **What a PASS means.** GUS reads *declared contracts*. A FAIL is a
> near-certain wire break; a PASS means "no statically visible hazard in
> the specs" — it cannot vouch for behavior, data migrations, or specs
> that have drifted from the code (empirically common; see
> `docs/review-notes.md` §A1). GUS is a gate among gates, not a
> deployment safety oracle.

## The idea in one paragraph

Per-boundary compatibility tools (Pact, Buf, oasdiff, schema registries)
check one caller/provider pair at a time. A batched rolling deployment
adds three things at once: **multiple services upgrade together**, **old
and new instances coexist during the roll**, and **data flows through
chains** of services. GUS models the whole batch as one predicate: every
edge must type-check under both mixed version pairings (old caller/new
provider and new caller/old provider, request and response legs — the
C1–C4 conjuncts), under the target state (both new), and every declared
data-flow chain must still hold end-to-end. When GUS fails, MSS turns
each failed conjunct into a Horn clause plus a rollout-ordering
constraint, propagates, excludes ordering deadlocks, and returns the
surviving sub-batch with a stage-by-stage rollout order.

## What exists elsewhere (honest version)

The per-edge ingredients all exist in production tools; GUS's
contribution is composing them mesh-wide over a *batch* with subset and
ordering output. Concretely:

| Concern                                  | Pact broker | Buf | Schema registry | oasdiff | GUS |
|------------------------------------------|:----:|:----:|:---------------:|:-------:|:---:|
| Pairwise compat between two versions     | ✅   | ✅   | ✅              | ✅      | ✅  |
| Cross-version old↔new pairings           | ✅¹  | ✅²  | ✅³             | ❌      | ✅  |
| Direction-aware request/response rules   | partial | n/a | ✅³          | ✅      | ✅  |
| Multi-service batch as one question      | ✅¹  | ❌   | ❌              | ❌      | ✅  |
| Data-flow chain (source→relay→sink)      | ❌   | ❌   | ❌              | ❌      | ✅  |
| Largest safe sub-batch + rollout order   | ❌   | ❌   | ❌              | ❌      | ✅  |

¹ `can-i-deploy` verifies candidate versions against everything deployed
in an environment and accepts multiple pacticipants per query — it
answers the batch question dynamically (example-based, yes/no, no subset
or ordering). ² Buf's WIRE/WIRE_JSON categories exist precisely to keep
mixed old/new binaries compatible. ³ Confluent's FULL/FULL_TRANSITIVE is
the old↔new pairing guarantee for pub/sub, with direction-aware JSON
Schema rules. See `docs/review-notes.md` for the full prior-art survey
(incl. Gay & Hole subtyping, Dowling–Gallier propagation, the SOSP'21
upgrade-failure study that motivates the problem, and Service Weaver,
which dissolves it by construction).

## How the answer is shaped

For an edge `u → v` with baseline θ and proposal θ′, the two mixed
deployment pairings are checked on both legs:

- `C1  Send(θ_u) ≤ Accept(θ'_v)` — old caller → new provider (request)
- `C2  Send(θ'_u) ≤ Accept(θ_v)` — new caller → old provider (request)
- `C3  Return(θ'_v) ≤ Expect(θ_u)` — new provider → old caller (response)
- `C4  Return(θ_v) ≤ Expect(θ'_u)` — old provider → new caller (response)
- `TGT Send(θ') ≤ Accept(θ') ∧ Return(θ') ≤ Expect(θ')` — target state

(That is 2 pairings × 2 legs plus the target state — not "four
pairings"; the (θ,θ) pairing is the baseline, checked by
`gus consistent`.) Caller-side `Send`/`Expect` schemas come from the
caller's spec when it declares the outbound call (`x-role: client` on
the provider's path, or a `/_calls/<provider>/<path>` entry). Without a
caller declaration, GUS anchors the caller to the *old provider
contract* for both states — C2/C4/TGT then hold trivially and C1/C3
degenerate to an honest bidirectional provider self-diff (what a schema
registry's FULL mode gives you), with no fabricated caller drift.

**Clause generation follows the conjunct** (the deck's pinning rule): a
C1/C3 failure pins the provider's θ′ side — the provider may only ship
if the caller's old contract is fully gone first (`¬x_v ∨ x_u`, roll
`u` before `v`); with a non-upgrading caller it's a unit exclusion. A
C1+C4 co-failure on one edge is a **rollout deadlock**: each side must
finish before the other starts, so no rolling order exists and the
solver excludes the pair (only an atomic switchover could ship it).
Propagation is Dowling–Gallier unit propagation — linear-time and
uniquely maximal for the definite+unit fragment; once deadlock ("not
both") constraints appear, maximum-cardinality is NP-hard, so the
deadlock exclusion is deliberately conservative. `mss` re-verifies its
own answer by re-running GUS restricted to the safe subset (post-hoc
check), and emits the rollout order stages.

The strict JSON lattice admits only `integer ≤ number`. The lenient
profile (`coercion: lenient` in a scenario) additionally admits
`int/num/bool ≤ string` — Jackson-style consumers only; Go, serde and
pydantic v2 all reject those coercions, which is why lenient is opt-in
rather than the default.

```
proposed upgrades U
        │
        ▼
   executeGUS ──── failed conjuncts ───► Horn clauses + precedences
   (C1–C4, TGT,                               │
    chains)                                   ▼
        │                              ComputeMSS (propagate,
        ▼                               exclude deadlock cycles,
    GUSResult                           topo-sort rollout order)
        │                                     │
        │                       post-hoc GUS on the safe subset
        └──────────────┬──────────────────────┘
                       ▼
               pkg/viz.Build()   ──►  JSON artifact ──► viz/viz.html
```

## Case studies

All scenarios run against a 9-service port of Google's **Online
Boutique** (`scenarios/online-boutique/`) with 14 RPC edges. Each ships
a YAML definition with **exact** expected outcomes (`gus validate`
checks MSS set equality — including emptiness — plus expected edge and
chain violations, and post-hoc verifies every computed subset).

### Scenario B — Response enum widening (silent data hazard)
ProductCatalog v2 adds `new-arrivals` to the `categories` response enum.
Old consumers with closed switch statements crash on the unknown value.
Caught on the response leg (`C3`): `Return(θ') ⊑ Expect(θ)` fails.
(Honesty note: oasdiff also warns on response-enum additions; GraphQL
Inspector classifies it "dangerous". The mesh-wide batch verdict is the
GUS-specific part, not the rule itself.)

### Scenario C — Enum migration with a straggler
Shipping v2 replaces `express` with `same-day`. Frontend v2
(co-developed) narrows its sends to `[standard]`, compatible with every
shipping version. Checkout stays at v1 and still sends `express`, so
shipping is pinned out by a unit clause — but the conjunct-aware clause
`¬x_shipping ∨ x_frontend` is satisfied once shipping is excluded, so
**frontend stays in the MSS** (`mss: [frontend]`). A conjunct-blind
"exclude both endpoints" encoding would wrongly drag frontend out.

### Scenario D — Chain-only break (no edge fires)
Checkout v2 stops guaranteeing `order_id` on the confirmation call
(optional in its client send). Email's accept schema tolerates the
absence — **every per-edge conjunct passes** — but email declares
`x-requires: order-identity`, and the chain check reports
`chain-weakened` with checkout as the culprit. This is the bug class
per-edge tools are structurally blind to, now actually computed by
`pkg/chain` (wired into `check`, `mss`, `validate`, and the viz).

### Scenario E — Hasty schema refactor (object restructure)
Currency v2 "cleans up" `Money` from `{currency_code, units, nanos}` to
`{currency_code, amount}`. Both calling edges break on the request leg
(REQ.1: new required `amount`) and the response leg (RES.1: required
fields vanish). MSS is empty.

### Scenario F — Recursive types
ProductCatalog v3 replaces the flat `categories` enum with a recursive
`Category{name, children: [Category]}` tree — `kind-mismatch`, no
pairing direction can bridge it. The loader inlines `$ref`s and emits
`Ref` nodes only at cycle back-edges (in deterministic sorted order);
the checker compares the one-step unfolding and assumes same-named
back-edges coinductively.

### Scenario G — Composite upgrade, non-trivial MSS
Currency v2 and productcatalog v2 are each pinned by non-upgrading
callers (unit clauses); email v2's optional response addition is safe.
MSS = exactly `{email}`.

### Scenario H — Positive control (safe upgrade)
Frontend v2 alone. Its client declarations (narrowed shipping sends,
unchanged checkout expectations) pass every conjunct against the v1
providers. With caller schemas actually consumed, this control is now
meaningful — the earlier revision only passed because the caller-spec
path was dead code.

### Scenario I — Full-mesh upgrade storm
Six of nine services upgrade under the lenient coercion profile;
recommendation stays at v1 and pins productcatalog. The showpieces:

- **Rollout deadlock.** `frontend v3 ↔ checkout v3` fail C1 (old
  frontend lacks the new required `idempotency_key`) *and* C4 (old
  checkout returns `order_id: string`, new frontend expects `integer` —
  `string ≰ integer` even leniently, while C3 passes because
  `integer ≤ string` *under the lenient profile only*). C1 wants
  frontend first; C4 wants checkout first — no rolling order exists,
  and the solver excludes the pair with an explicit deadlock reason.
- **Chain type mismatch.** Checkout v3 provides `order-identity` as
  `integer`; email requires `string`. The direct edge passes under
  lenient coercion, but identities are strictly typed end-to-end:
  `chain-type-mismatch`, culprit checkout.

Expected (and exactly validated): MSS = `{shipping, email}`.

## Repository layout

```
cmd/gus/              CLI: check, mss, consistent, validate, evolve, viz
pkg/
  types/              Type AST (Prim, Literal, Enum, Array, Object, Map,
                        Union, Nullable, Ref, Any)
  lattice/            JSON primitive order (strict + lenient profiles),
                        proto varint widenings
  compat/             Role-based subtyping rules (REQ/RES directions)
  schema/             OpenAPI loader → types.SchemaNode (x-role aware)
  graph/              Mesh + scenario YAML loaders (path-confined specs)
  edge/               EdgeOK conjuncts C1–C4 + TGT, Consistent(θ)
  chain/              x-provides / x-requires chain integrity (typed)
  solver/             Unit propagation + deadlock cycles + rollout order
  report/             Structured output
  viz/                JSON artifact builder for the frontend
scenarios/
  online-boutique/    Service mesh + OpenAPI specs + scenario YAMLs
    evolution/        11-step feature-evolution storyline + provenance ledger
viz/                  Self-contained SVG frontend + pre-rendered scenarios
docs/
  gus-mss-deck.pdf    The paper deck (see review-notes.md for errata)
  review-notes.md     Slide-by-slide review: corrections, prior art,
                        significance assessment
```

## The evolution suite and the provenance ledger

`scenarios/online-boutique/evolution/` replays the same mesh through eleven
feature rollouts (accounts, payment methods, an expand/contract Money
migration, session tracing, promo codes), each step's baseline being what
the previous steps actually shipped. Together they cover every rule the
checker knows — including the ones single scenarios can't show: staged
rollout orders, target-state (TGT) deadlocks, x-alias rename bridging, and
a guarantee that erodes silently in step 07 and only explodes in step 11.

```sh
./gus validate --graph scenarios/online-boutique/graph.yaml \
               --scenario-dir scenarios/online-boutique/evolution
./gus evolve   --graph scenarios/online-boutique/graph.yaml \
               --steps-dir scenarios/online-boutique/evolution
```

`gus evolve` maintains a ledger (persisted between invocations) tracking
every x-provides identity's guarantee — field, type, required/nullable,
carrying paths — at every shipped state. Its purpose is the class of bug
per-step checks structurally cannot see: a guarantee weakened while nothing
requires it ships without a single failing check; when a requirer appears
rollouts later, the per-step tool can only blame the requirer. The ledger
answers with the true origin ("guarantee last weakened at step 07") and
records all carrying paths per identity, since a diamond mesh can route an
identity along any of several upgrade paths. See
`scenarios/online-boutique/evolution/README.md` for the full storyline.

## Getting started

```sh
go build -o gus ./cmd/gus

# Run all scenarios against their exact expected outcomes
./gus validate --graph scenarios/online-boutique/graph.yaml \
               --scenario-dir scenarios/online-boutique/scenarios

# Interactive view of Scenario I
./gus viz --graph scenarios/online-boutique/graph.yaml \
          --scenario scenarios/online-boutique/scenarios/scenario-i.yaml \
          --html viz/scenario-i.html --template viz/viz.html
open viz/scenario-i.html
```

Exit codes: `0` clean, `1` hazards found (for `mss`: the full batch is
not shippable), `2` inputs could not be evaluated. Evaluation errors —
unknown services or versions, missing specs or endpoints, `allOf`/
`anyOf` (unsupported), kafka edges (no topic→schema resolution yet) —
are hard failures, never silent passes.

## Status & scope

Proof of concept. Known limits, deliberately explicit:

- **Specs are trusted.** No Tier-1 source extraction or traffic
  validation yet; a drifted spec yields a verdict about a document.
- **OpenAPI 3.0 subset.** `allOf`/`anyOf` rejected, query/path
  parameters ignored, first-2xx JSON response only, OpenAPI 3.1 null
  unions unsupported. gRPC/proto meshes are unrepresentable (the proto
  lattice exists for the formalism but has no loader).
- **Two versions per service.** Canary rollouts with 3+ live versions
  need C(n,2) pairings; the model hardcodes n=2. Rollbacks are not
  distinguished from upgrades.
- **Chains** cover request-carried identities on forward call paths,
  matched by name/case/x-alias; response-carried identities and
  diamond topologies are out of scope.
- **Deadlock exclusion is conservative** (drops every cycle member);
  a weighted MaxSAT solver could ship more.

## License

Apache 2.0 — see `LICENSE`.

## Project report

This component is documented in the UCSC master's project report
*Safe Evolution and Interventional Fault Attribution in Microservice
Meshes* (Pranay Mundra, 2026) — Part I, as the reference implementation:
the worked examples, evaluation timings, and appendices A–C draw on the
scenario suite and proofs in this repository.
