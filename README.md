# GUS / MSS — upgrade safety for microservice meshes

A static checker for **batched upgrades in a service mesh**. Give it the
mesh, one OpenAPI document per service version, and a proposed batch of
version changes. It reports every statically visible wire hazard the batch
would create across the mixed-version windows of a rolling deployment
(**GUS**, Global Upgrade Safety), and when the batch is hazardous it
computes the largest sub-batch it can prove safe together with a
stage-by-stage rollout order for it (**MSS**, Maximal Safe Subset), then
replays that plan stage by stage as its own certificate.

> **What a verdict means.** The checker reads *declared contracts*. A FAIL
> is a near-certain wire break. A PASS means "no statically visible hazard
> in the specs": it cannot vouch for behaviour, data migrations, or specs
> that have drifted from the code. GUS is a gate among gates, not a
> deployment safety oracle.

This repository is the reference implementation for the GUS/MSS work and is
Part I of the UCSC master's project report *Safe Evolution and
Interventional Fault Attribution in Microservice Meshes* (Pranay Mundra,
2026). It is a proof of concept: small, readable, and scoped to OpenAPI 3.0
with JSON bodies, validated on a nine-service port of Google's Online
Boutique.

---

## 1. Problem statement

A rolling deployment never replaces a service atomically. For a while, old
and new instances of the same service answer traffic side by side, so every
call edge in the mesh is exercised by **mixed version pairs**: an old caller
against a new provider, a new caller against an old provider. A release
train that ships several services at once multiplies those pairs, and the
question an operator actually asks is not "is this schema change
backward-compatible?" but three harder ones:

1. **Can this batch roll at all, and in what order?** A change that breaks
   the (old caller, new provider) pair is not a rejection; it is an ordering
   constraint (callers first). A change that breaks both mixed pairs in
   opposite directions is a deadlock: no rolling order exists.
2. **Do the two new versions even agree with each other?** When a caller and
   a provider change in the same batch, the (new, new) pair is a state no
   per-schema diff ever examines, because both sides are "new".
3. **Do end-to-end guarantees survive?** An identifier minted by one service
   and required by another three hops away can be silently dropped,
   renamed, or made optional at an intermediate hop while every individual
   boundary stays compatible. Worse, a guarantee can erode in one rollout
   and only break something several rollouts later, when a new consumer
   starts relying on it.

Per-boundary tools (Pact, Buf, oasdiff, schema registries) each answer one
pair at a time and stop there. None of them answers the batch question,
none relates two parties' new schemas to each other, and none follows a
value across hops or across rollouts. Those are the gaps this checker is
built for.

**Who has this problem.** Teams that own many independently deployed
services, roll them out gradually (rolling, canary, blue/green with
overlap), describe their APIs with OpenAPI, and ship release trains or
coordinated multi-service changes. If every deployment is an atomic
switchover of the whole system, most of this is moot.

## 2. Approach

**Four schemas per edge.** Each service version fixes, per edge it
participates in, what it *sends* and *expects back* as a caller and what it
*accepts* and *returns* as a provider. Compatibility is a pair relation with
a direction: a request is safe when everything the caller may send is
admitted by the provider (`Send ≤ Accept`), a response when everything the
provider may return is understood by the caller (`Return ≤ Expect`). The
subtype order is structural: fields, required-ness, enums as value sets,
nullability, unions by width, recursive types coinductively, primitives by a
deliberately strict JSON lattice (`integer ≤ number` only; the lenient
profile that also admits scalars into `string` is an explicit per-scenario
opt-in, because Go, serde and pydantic v2 all reject those coercions).

**Edge safety over live pairs.** For an edge `u → v` with baseline θ and
proposal θ′, the two mixed pairs are checked on both legs, plus the target
state:

```
C1   Send(θ_u)   ≤ Accept(θ'_v)   old caller  → new provider   (request)
C2   Send(θ'_u)  ≤ Accept(θ_v)    new caller  → old provider   (request)
C3   Return(θ'_v) ≤ Expect(θ_u)   new provider → old caller    (response)
C4   Return(θ_v)  ≤ Expect(θ'_u)  old provider → new caller    (response)
TGT  Send(θ') ≤ Accept(θ') ∧ Return(θ') ≤ Expect(θ')          (new, new)
```

The baseline pair (θ, θ) is a precondition, not a conjunct: `gus check`
verifies it first and refuses to judge an inconsistent baseline. GUS is the
conjunction over every edge touched by the batch plus every declared
data-flow chain.

**Chains.** Three annotations declare a value that must survive a path:
`x-provides: <identity>` on the field that mints it, `x-requires:
<identity>` on the field where it must arrive present, non-null and of the
same type, and `x-alias: <previous-name>` at a hop that renames it.
Passthrough hops need nothing. Every simple call path from source to sink
is validated against what each hop *sends onward*, which is what makes a
rename detectable at all.

**From findings to a plan.** Each failing conjunct pins one side: a C1 or C3
failure says the provider may only finish rolling after the caller's old
contract is gone (roll `u` before `v`; with a non-upgrading caller, the
provider is simply excluded). These are definite Horn clauses plus
precedence edges; unit propagation gives the unique maximal safe subset of
the definite fragment in linear time, a topological sort gives the stages,
and mutually contradictory precedences (a C1 + C4 pair on one edge, or a
target-state conflict) are excised as a deadlock group. Deadlock exclusion
is deliberately conservative: once "not both" constraints appear, the
maximum-cardinality problem is NP-hard. The solver then **re-runs GUS stage
by stage on its own plan**, so the plan carries its certificate.

**Across rollouts.** `gus evolve` replays an ordered sequence of rollouts
and keeps a per-identity ledger: for every provided identity, the guarantee
(provider, field, type, required, nullable, carrying paths) at each shipped
state, with events `born`, `eroded`, `restored`, `demanded`, `violated`.
When a chain finally fails, the ledger names the rollout that last weakened
the guarantee rather than the one that exposed it.

**What exists elsewhere.** The per-edge ingredients are all in production
tools; the contribution is composing them mesh-wide over a batch, with a
subset and an order as the answer:

| Concern                                  | Pact broker | Buf | Schema registry | oasdiff | GUS |
|------------------------------------------|:----:|:----:|:---------------:|:-------:|:---:|
| Pairwise compat between two versions     | ✅   | ✅   | ✅              | ✅      | ✅  |
| Cross-version old↔new pairings           | ✅¹  | ✅²  | ✅³             | ❌      | ✅  |
| Direction-aware request/response rules   | partial | n/a | ✅³          | ✅      | ✅  |
| Multi-service batch as one question      | ✅¹  | ❌   | ❌              | ❌      | ✅  |
| Two parties' *new* schemas against each other (TGT) | ❌ | ❌ | ❌       | ❌      | ✅  |
| Data-flow chain (source→relay→sink)      | ❌   | ❌   | ❌              | ❌      | ✅  |
| Largest safe sub-batch + rollout order   | ❌   | ❌   | ❌              | ❌      | ✅  |
| Guarantee history across rollouts        | ❌   | ❌   | ❌              | ❌      | ✅  |

¹ `can-i-deploy` verifies candidates against everything deployed in an
environment and accepts several pacticipants per query: it answers the
batch question dynamically (example-based, yes/no, no subset or order).
² Buf's WIRE/WIRE_JSON categories exist to keep mixed old/new binaries
compatible. ³ Confluent's FULL/FULL_TRANSITIVE is the old↔new guarantee for
pub/sub, with direction-aware JSON Schema rules. `docs/review-notes.md`
carries the full prior-art survey.

## 3. The tool

```
gus check       --graph g.yaml --scenario s.yaml [--format json]
gus mss         --graph g.yaml --scenario s.yaml [--format json]
gus consistent  --graph g.yaml --scenario s.yaml [--state baseline|target]
gus validate    --graph g.yaml --scenario-dir dir/
gus evolve      --graph g.yaml --steps-dir dir/ [--ledger file]
gus viz         --graph g.yaml --scenario s.yaml --html out.html --template viz/viz.html
```

| Command | Answers | Exit code |
|---|---|---|
| `check` | Is this batch safe to roll unordered? Every finding, per edge and chain, with the failing pair (`[C1]`…`[TGT]`) and the field. | 0 clean · 1 hazards · 2 could not evaluate |
| `mss` | The check, then the safe subset, its stage order, exclusion reasons, and the staged-replay certificate. | 1 when the full batch cannot ship as proposed |
| `consistent` | Is one deployment state internally compatible? | as `check` |
| `validate` | Run a directory of cases against their asserted outcomes (verdict, exact safe set, stage order, chain results, and with `breaks_exact` the complete finding set). | 1 on any mismatch |
| `evolve` | Replay ordered rollouts, maintain `ledger.json`, print each identity's history. | 2 on evaluation errors |
| `viz` | A self-contained HTML page of the case: mesh, violation cards, plan, chains. | |

**Reading a finding.** Every line names three coordinates: the edge, the
version pair, and the field.

```
Edge frontend->shipping-quote [http] — BREAK (conjuncts C1):
  [BREAK] [C1]$.account_tier
    receiver requires field the sender does not send (and no default is declared)
    old: <absent> → new: string
    rule: REQ.1
```

`[C1]` says *which pair* breaks: old caller against new provider. That is
exactly the pair a staged rollout can avoid, so `mss` turns it into "callers
before shipping" rather than a rejection. `[TGT]` names a conflict between
the two new versions themselves; no order avoids it. Warnings (`format-change`,
a range risk such as int32→int64) are printed but never fail an edge or feed
the solver. Broken chains print the path, the reason, and the upgrades in
the batch whose lone revert would repair or dissolve the chain.

Evaluation errors (unknown services or versions, missing specs or endpoints,
`allOf`, a schema mixing `oneOf` and `anyOf`, kafka edges) are hard failures
with exit code 2, never silent passes.

## 4. Architecture

```
graph.yaml + specs ─► pkg/schema (OpenAPI → type AST)
                          │
scenario.yaml ───────► cmd/gus executeGUS
                          │  per touched edge: pkg/edge  (C1–C4, TGT over pkg/compat)
                          │  per declared chain: pkg/chain (all simple paths, alias tiers)
                          ▼
                     GUSResult ── failed conjuncts ──► Horn clauses + precedences
                          │                                  │
                          │                          pkg/solver ComputeMSS
                          │                          (propagate, excise deadlock
                          │                           cycles, topo-sort stages)
                          │                                  │
                          │                    staged replay of GUS on the plan
                          └──────────────┬───────────────────┘
                                         ▼
                        pkg/report (text/JSON)   pkg/viz (JSON → viz/viz.html)
                        pkg/evolve (ledger, driven by gus evolve)
```

| Package | Carries |
|---|---|
| `pkg/types` | The type AST: Prim, Enum (with declared base), Array, Map, Object (open/closed), Union, Nullable, Ref, Any. |
| `pkg/lattice` | Primitive orders: strict and lenient JSON profiles, Protobuf widenings (no proto loader yet). |
| `pkg/compat` | The two directed relations. Sums (Nullable, Union) normalized to variant set + null flag; enums as value sets; objects by field presence, required-ness and openness (`REQ.1/2/4`, `RES.1/4/5`); coinductive recursive types. |
| `pkg/schema` | OpenAPI 3.0 loader: `$ref` inlining with cycle back-edges, `oneOf`/`anyOf` → Union, `additionalProperties` → closed object or Map, `x-role: client` outbound contracts, the `x-provides`/`x-requires`/`x-alias` extensions. |
| `pkg/graph` | Mesh and scenario YAML, path-confined spec resolution, case IDs. |
| `pkg/edge` | EdgeOK: the four mixed-pair conjuncts, TGT, chronology-correct labels, `Consistent(θ)`. |
| `pkg/chain` | Chain discovery, simple-path enumeration (bounded, shortest-first), per-hop presence/nullability/type checks. |
| `pkg/solver` | Dowling–Gallier propagation, Tarjan SCC deadlock excision, Kahn staging. |
| `pkg/report` | Text and JSON output. |
| `pkg/evolve` | The provenance ledger. |
| `pkg/viz`, `viz/` | JSON artifact and the self-contained frontend. |
| `cmd/gus` | Commands, clause generation from conjuncts, staged post-hoc replay, culprit attribution by revert-and-recheck, the validate oracle. |

## 5. Using it with your services

**What you need.**

1. **One OpenAPI 3.0 document per service per version**, checked in. The
   checker compares documents; it never reads code or traffic.
2. **A mesh description** (`graph.yaml`): each service's versions and the
   call edges between services.

   ```yaml
   services:
     checkout:
       v1: specs/checkout/v1/openapi.yaml
       v2: specs/checkout/v2/openapi.yaml
     shipping:
       v1: specs/shipping/v1/openapi.yaml
   edges:
     - name: checkout->shipping-quote
       from: checkout
       to: shipping
       method: POST
       path: /shipping/quote
   ```

3. **Caller-side contracts, where they matter.** By default a caller is
   anchored to the provider's *old* contract (the checker assumes the caller
   did not move, which is a self-diff of the provider: what a schema
   registry's FULL mode gives you, mesh-wide). To check what a caller
   actually sends and expects, declare the outbound call in the caller's own
   document, either as the provider's path marked `x-role: client` or under
   `/_calls/<provider>/<path>`:

   ```yaml
   paths:
     /shipping/quote:            # the provider's path, in the CALLER's spec
       post:
         x-role: client
         requestBody: { ... }    # what this service sends
         responses:
           "200": { ... }        # what this service expects back
   ```

   Only with caller contracts can the checker see caller-side changes (C2,
   C4) and the target-state conflict (TGT).

4. **Chain annotations** on the identities you care about: `x-provides` at
   the source field, `x-requires` at the sink field, `x-alias` where a hop
   renames the field.

5. **A scenario per proposed batch**: the deployed baseline and the
   upgrades. The `expect` block is optional and turns the file into a
   regression assertion for `gus validate`.

   ```yaml
   id: R42
   name: "Release train 42"
   baseline: { checkout: v1, shipping: v1, frontend: v2 }
   upgrades: { checkout: v2, shipping: v2 }
   ```

**A working loop.**

```sh
go build -o gus ./cmd/gus
./gus consistent --graph graph.yaml --scenario train-42.yaml   # is the baseline sane?
./gus mss        --graph graph.yaml --scenario train-42.yaml   # what can ship, in what order?
./gus viz        --graph graph.yaml --scenario train-42.yaml --html train-42.html --template viz/viz.html
```

- **As a pre-merge gate on spec changes**: run `gus check` in CI with the
  batch being proposed; exit code 1 blocks, 2 means the inputs need fixing.
  `--format json` feeds annotations or dashboards.
- **As a release-train planner**: run `gus mss` on the whole train and ship
  the stages it prints; the staged replay in the output is the evidence.
- **As a regression oracle**: keep scenario files with `expect` blocks and
  run `gus validate` on every change to the specs or the checker.
  `breaks_exact: true` asserts the complete finding set, so a new false
  positive fails the build.
- **After each shipped rollout**: append a step file and run `gus evolve`,
  so guarantees that erode while unused are on record before anything
  depends on them.

**Adoption path.** Start with specs and `graph.yaml` alone: every provider
change is judged against every caller edge mesh-wide with no caller work.
Add `x-role: client` contracts on the edges where callers change (or where
you have been bitten). Add chain annotations for the handful of identifiers
that cross service boundaries. Each step is a few lines of YAML on
documents you already keep, and each step strictly widens what the checker
can see.

## 6. Case studies

All cases run against a 9-service port of Google's **Online Boutique**
(`scenarios/online-boutique/`) with 14 RPC edges. Each case declares an
`id:` (`B`–`I`, `E01`–`E11`) that the tool prints in its headers and that
the ledger uses as its step key, and each asserts its verdict, exact safe
set, stage order, chain results, and complete finding set under `gus
validate`.

**Standard cases (`scenarios/`)**, one change each:

- **B — response enum widening.** ProductCatalog v2 adds `new-arrivals` to
  the `categories` response enum; old consumers with closed switch
  statements crash on it. Caught on the response leg (`C3`) on all three
  caller edges at once. (oasdiff also warns on response-enum additions; the
  mesh-wide batch verdict is the GUS-specific part, not the rule.)
- **C — enum migration with a straggler.** Shipping v2 replaces `express`
  with `same-day`; the co-developed Frontend v2 narrows its sends to
  `[standard]`. Checkout stays at v1 and still sends `express`, so shipping
  is excluded, but the conjunct-aware clause keeps **frontend in the safe
  set**. A conjunct-blind "exclude both endpoints" encoding would wrongly
  drag it out.
- **D — chain-only break.** Checkout v2 stops guaranteeing `order_id` on
  the confirmation call; Email's accept schema tolerates the absence, so
  **every per-edge conjunct passes**, and only the chain fires
  (`chain-weakened`). The finding inventory asserts zero edge findings.
- **E — hasty schema refactor.** Currency v2 restructures `Money`; both
  caller edges break on the request leg (`REQ.1`) and the response leg
  (`RES.1`). The safe set is empty.
- **F — recursive types.** ProductCatalog v3 replaces the flat enum with a
  recursive `Category` tree: `kind-mismatch`. The loader emits `Ref` nodes
  only at cycle back-edges and the checker compares the one-step unfolding
  coinductively.
- **G — composite upgrade.** Three unrelated upgrades; two are pinned by
  non-upgrading callers, email's optional response addition is safe. The
  safe set is exactly `{email}`.
- **H — negative control.** Frontend v2 alone; its client declarations pass
  every conjunct against the v1 providers. The checker must stay silent.
- **I — full-mesh upgrade storm** (lenient profile). Six services upgrade.
  `frontend ↔ checkout` fails C1 *and* C4 in opposite directions, a rollout
  deadlock; a chain type flip (`integer` provided, `string` required) fires
  even though the direct edge passes under lenient coercion. Safe set
  `{shipping, email}`.

**The evolution suite (`evolution/`)** replays the same mesh through eleven
rollouts shaped like feature work, each step's baseline being what the
previous steps actually shipped. It covers every rule, including the ones
single cases cannot show: staged rollout orders (E03, E05, E07), the
target-state deadlock (E10), rename bridging with `x-alias` (E08, E09), and
a guarantee that erodes silently in E07 and only explodes in E11, where
the per-step checker can only blame the new consumer and the ledger names
the origin:

```
identity "shipment-tracking" — EXPOSED
  born     @ E03: checkout provides it as string on field "shipment_ref" (required=true, ...)
  eroded   @ E07: field "shipment_ref" went required→optional at checkout — ...
  demanded @ E11: now required by [email] — the proposal was REJECTED ...
  violated @ E11: chain check fails (chain-weakened) — guarantee last weakened at step "E07" ...
```

The storyline, the rule-coverage matrix and the full ledger are in
`scenarios/online-boutique/evolution/README.md`; rendered pages for every
case are under `viz/`.

```sh
./gus validate --graph scenarios/online-boutique/graph.yaml --scenario-dir scenarios/online-boutique/scenarios
./gus validate --graph scenarios/online-boutique/graph.yaml --scenario-dir scenarios/online-boutique/evolution
./gus evolve   --graph scenarios/online-boutique/graph.yaml --steps-dir   scenarios/online-boutique/evolution
```

## 7. Limits, and what adoption still needs

Known limits, deliberately explicit:

- **Specs are trusted.** No extraction from code or traffic; a drifted spec
  yields a verdict about a document. Pair the checker with contract tests or
  traffic-derived schemas if drift is a live risk.
- **OpenAPI 3.0 JSON subset.** `allOf` is rejected (it must be flattened),
  query/path/header parameters are ignored, only the lowest 2xx JSON
  response schema is compared, value refinements (`minimum`, `pattern`,
  `maxLength`) are not modelled, OpenAPI 3.1 type arrays are unsupported.
  gRPC/Protobuf meshes are unrepresentable: the proto lattice exists, the
  loader does not. Kafka edges are refused rather than guessed at.
- **Two live versions per service.** Canaries with three or more live
  versions need every pairing; the model hardcodes two. Rollbacks are not
  distinguished from upgrades.
- **Chains** cover request-carried identities along forward call paths,
  judged in the baseline and target states only; a chain that breaks solely
  in a transient mixture, or an identity carried back in a response, is out
  of scope.
- **Deadlock exclusion drops every member of a cycle**; a weighted solver
  could ship more.
- **Inputs are hand-written.** `graph.yaml` is not derived from mesh
  configuration (Istio, Linkerd, Kubernetes services), versions are not
  read from a registry or git tags, and scenario files are authored, not
  generated from a deployment plan.
- **Measured at nine services.** Checks run in tens of milliseconds on the
  corpus; cost should grow with mesh and spec size rather than
  combinatorially, but that is an argument, not a measurement.

## Repository layout

```
cmd/gus/              CLI: check, mss, consistent, validate, evolve, viz
pkg/                  types, lattice, compat, schema, graph, edge, chain, solver, report, evolve, viz
scenarios/online-boutique/
  graph.yaml          the mesh
  specs/<svc>/<ver>/  one OpenAPI document per service version (38 in total)
  scenarios/          cases B–I
  evolution/          cases E01–E11, README with the storyline, ledger.json
viz/                  self-contained frontend template + a rendered page per case
docs/                 workshop paper (docs/paper), first-principles primer, review notes, deck
```

## License

Apache 2.0 — see `LICENSE`.

## Project report

This component is documented in the UCSC master's project report
*Safe Evolution and Interventional Fault Attribution in Microservice
Meshes* (Pranay Mundra, 2026) — Part I, as the reference implementation:
the worked examples, evaluation timings, and appendices A–C draw on the
scenario suite and proofs in this repository.
