# gus-mss-poc

A static compatibility checker for simultaneous microservice upgrades.
Given a service mesh and a proposed set of version changes, GUS (Global
Upgrade Safety) decides whether the whole batch can roll safely; when it
can't, MSS (Maximal Safe Subset) picks the largest subset that can.

This repository is the reference implementation accompanying the
GUS/MSS paper. It's a proof of concept — small, readable, and
intentionally scoped to OpenAPI + JSON Schema — designed to validate the
formalism and the Horn-SAT solver on realistic scenarios derived from
Google's Online Boutique microservice demo.

## The idea in one paragraph

Schema compatibility tools (Pact, Buf, JSON Schema registries) check one
boundary at a time between two versions. Real rolling deployments break
that model in three ways at once: **multiple services upgrade together**,
**old and new instances coexist during the rollout**, and **data flows
through chains** of services. A change that's safe for each individual
edge can still break when several old + new instance combinations run
concurrently, or when a typed payload threads through three hops and the
middle one reinterprets it. GUS models this as a single predicate over
the full mesh: the proposed deployment is safe iff every edge is
compatible under *all four* cross-version pairings (old↔new on each end)
*and* every data-flow chain still holds end-to-end. When GUS fails, MSS
runs a Horn-clause propagation to find the largest subset of the
proposed upgrades that still satisfies GUS — a linear-time answer to
"what can we ship today?".

## Why it's relevant

**The gap isn't detection accuracy — it's scope.** Pact and Buf find
genuine problems when they look; they just don't look at the right thing
for a mesh-wide rolling upgrade. Concretely:

| Concern                                | Pact | Buf  | Schema registry | GUS |
|----------------------------------------|:----:|:----:|:---------------:|:---:|
| Pairwise compat between two versions   | ✅   | ✅   | ✅              | ✅  |
| 4-pairing cross-version (old↔new)       | ❌   | ❌   | ❌              | ✅  |
| JSON primitive lattice (asymmetry)      | ❌   | ❌   | ❌              | ✅  |
| Multi-service upgrade batches           | ❌   | ❌   | ❌              | ✅  |
| Data-flow chain (producer→relay→sink)   | ❌   | ❌   | ❌              | ✅  |
| Recursive / `$ref` cycles (coinductive) | partial | ❌ | ❌           | ✅  |
| "Largest safe subset" when batch fails  | ❌   | ❌   | ❌              | ✅  |

**The 4-pairing is the central GUS idea.** For an edge `A → B`, pairwise
tools check `A_new` against `B_new`. During a rollout the four interesting
pairs are `(A_old, B_new)`, `(A_new, B_old)`, `(A_new, B_new)`, and
`(A_old, B_old)` — each with a direction (request or response). JSON
primitive widening is *asymmetric*: `integer` is safely widened to `string`
(a JSON parser tolerates it), but `string` is not safely narrowed to
`integer`. The same field change produces a pass in one pairing and a
break in another. Scenario I below exercises exactly this.

## How the answer is shaped

GUS = `∧ EdgeOK(e, θ, θ')` over all edges, where `θ` is the current
deployment state and `θ'` is the proposed one. `EdgeOK` has four conjuncts
per RPC edge (C1–C4) checking the cross-version pairings in both
directions. A violation tags which conjunct broke — the visualizer
surfaces this as `[C3]` or `[C4]` in each tooltip.

MSS solves `HORN_MSS(U, clauses)`: each broken edge becomes a Horn
clause (`¬x_A ∨ x_B` when upgrading A only works if B also upgrades; a
unit clause `¬x_A` when nothing in the batch can save A). Unit
propagation is O(|clauses| + |U|). No backtracking, no search.

```
proposed upgrades U
        │
        ▼
   executeGUS ──── broken edges ────► Horn clauses
        │                                  │
        ▼                                  ▼
    GUSResult                        HORN_MSS(U, clauses)
        │                                  │
        └──────────────┬───────────────────┘
                       ▼
               pkg/viz.Build()   ──►  JSON artifact
                                         │
                                         ▼
                              viz/viz.html (static, p5.js)
```

## Case studies

All scenarios run against a 9-service port of Google's **Online Boutique**
(`scenarios/online-boutique/`): `frontend`, `checkout`, `shipping`,
`productcatalog`, `currency`, `cart`, `recommendation`, `payment`, `email`
with 14 RPC edges. Each scenario ships a YAML definition, OpenAPI specs
for the baseline + upgraded versions, and a pre-rendered interactive view
in `viz/scenario-*.html`.

### Scenario B — Response enum widening (silent data hazard)
ProductCatalog v2 adds `new-arrivals` to the `categories` enum it returns.
Old frontend callers haven't got a case for that value and will crash on
parse. Pairwise tools pass this change (request side is unchanged; new
values are only *added* to the response). GUS catches it via the
response-direction conjunct: `Return(new) ⊑ Expect(old)` fails.

### Scenario C — Enum narrowing with a straddled version
Shipping v2 narrows `priority` from `[standard, express]` to
`[standard, same-day]`. Frontend v2 widens its view to
`[standard, express, same-day]`. Checkout stays at v1 (still sending
`express`). The pairwise check `frontend_v2 ↔ shipping_v2` looks fine;
the checkout→shipping edge breaks because v1 callers still send values
v2 no longer accepts. MSS excludes shipping; frontend stays safe.

### Scenario D — Deep data-flow chain break
Checkout v2 drops `order_id` from *required* to *optional*. Email still
requires it (`x-requires: "order-identity"`). Neither direct edge
appears broken — but the chain `checkout → email` via the `order-identity`
identity breaks when Checkout v2 produces a response without `order_id`.
This is the kind of break pairwise contract testing can't see because no
two-service contract spans the chain.

### Scenario E — Hasty schema refactor (object restructure)
Currency v2 "cleans up" `Money` from `{currency_code, units, nanos}` to
`{currency_code, amount}`. Multiple edges regress: `checkout→currency`
breaks on REQ.1 (new required field in the restructured request);
`frontend→currency` breaks on RES.1 (required fields vanish from the
response). This is what happens when a team thinks "we're just
simplifying Money" in a sprint. A schema registry might accept the new
version if it's treated as a fresh type; GUS treats it as the same
endpoint and reports the break.

### Scenario F — Recursive types (coinductive compatibility)
ProductCatalog v3 replaces a flat `categories: string` enum with a
recursive `Category{name, children: [Category]}` tree. `kind-mismatch`
fires on `frontend→productcatalog`: the type *kind* changed, and no
4-pairing direction can bridge it. Recursive types stress the
`$ref`-cycle handling in the compat checker — GUS resolves these
coinductively (cycle detection on the Ref graph), which most pairwise
tools don't attempt.

### Scenario G — Composite upgrade, non-trivial MSS
Three services upgrade together: `currency v2` (Money restructure),
`productcatalog v2` (response enum widening), `email v2` (safe optional
field). The currency + productcatalog changes each break distinct edges
with non-upgrading callers, producing two unit clauses. Email's change
is safe and shares no violation-linked edge. MSS = `{email}` — the
largest ship-today subset.

### Scenario H — Positive control (safe upgrade)
Frontend v2 alone, no mesh partners upgrading. Expected outcome: GUS
passes, MSS = full upgrade set. Sanity check that the checker isn't
trigger-happy.

### Scenario I — Full-mesh upgrade storm (the 4-pairing showpiece)
Six of nine services upgrade simultaneously; recommendation stays at v1
and triggers a cascade: `productcatalog v2` widens `categories` (response
enum), generating a unit clause on `recommendation→productcatalog`.
Bidirectional clauses propagate the exclusion to `frontend`, `checkout`,
and `currency`. `shipping v3` and `email v2` survive because their
changes are safe and they share no violation-linked edges with the
excluded cluster. The scenario also exercises:

- **`checkout v3` order_id: `string → integer`** — C3 (response direction)
  *passes* because `integer ≤ string` in the JSON lattice; C4 *fails*
  because `string ≰ integer`. A 4-pairing asymmetry unique to GUS.
- **x-provides / x-requires chain mismatch** — `checkout v3` declares
  `order-identity` as `integer`, `email v2` requires it as `string`.
  The direct compat check says "safe" via the lattice, but the data-flow
  chain has a type mismatch that neither Pact nor Buf can detect.

Expected MSS: `{shipping, email}`.

## Repository layout

```
cmd/gus/              CLI: check, mss, consistent, validate, viz
pkg/
  types/              Type AST (Prim, Literal, Enum, Array, Object, Map,
                        Union, Nullable, Ref, Any)
  lattice/            JSON + proto primitive lattices
  compat/             The four-pairing compatibility rules
  schema/             OpenAPI loader → types.SchemaNode
  graph/              Mesh + scenario YAML loaders
  edge/               EdgeOK (RPC + pub/sub) + Consistent(θ)
  chain/              x-provides / x-requires BFS
  solver/             Horn-SAT MSS
  report/             Structured output
  viz/                JSON artifact builder for the frontend
scenarios/
  online-boutique/    Service mesh + OpenAPI specs + scenario YAMLs
viz/                  Static p5.js frontend + pre-rendered scenarios
```

## Getting started

Minimal invocation — the `viz/` README has the fuller walkthrough:

```sh
go build -o gus ./cmd/gus

# Run all scenarios against their expected outcomes
./gus validate --graph scenarios/online-boutique/graph.yaml \
               --scenario-dir scenarios/online-boutique/scenarios

# Interactive view of Scenario I
./gus viz --graph scenarios/online-boutique/graph.yaml \
          --scenario scenarios/online-boutique/scenarios/scenario-i.yaml \
          --html viz/scenario-i.html --template viz/viz.html
open viz/scenario-i.html
```

## Status & scope

Proof of concept. OpenAPI 3.0 + JSON Schema only (proto loader is on
the roadmap). Pub/sub edges are defined in the formalism; the current
solver path focuses on RPC. Contributions, bug reports, and scenario
ideas welcome.

## License

Apache 2.0 — see `LICENSE`.
