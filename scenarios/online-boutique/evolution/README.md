# Evolution suite — one mesh, eleven rollouts

The standard scenarios (B–I) are isolated case studies. This suite is a
*storyline*: the same Online Boutique mesh evolving sprint by sprint as
features land, with each step's `baseline` being the accumulated result of
what previous steps actually shipped (their MSS, not their proposal). The
changes are synthetic but shaped like real feature work — an accounts
launch, a payments migration, an expand/contract money refactor, a tracing
initiative — and together they exercise every rule the checker knows.

Run it:

```sh
gus validate --graph ../graph.yaml --scenario-dir .
gus evolve   --graph ../graph.yaml --steps-dir .        # provenance ledger
```

## The storyline

| Step | Feature | Outcome | What it demonstrates |
|------|---------|---------|----------------------|
| 01 `wishlist` | Recommendation adds wishlist hits + score map | **ships** | Additive response fields are safe; `Map` values enter the mesh |
| 02 `cart-regression` | Cart stops guaranteeing `items`; adds `source` (required, with default) | **blocked** | `RES.4` pins cart out; the defaulted required field rides along silently (`REQ.1`'s escape hatch) |
| 03 `account-quotes` | Shipping requires `priority` + `account_tier`; both callers upgrade their sends | **ships, staged** | `REQ.1`/`REQ.2` become *ordering constraints*: callers stage 1, shipping stage 2; post-hoc replays the stages |
| 04 `payment-methods` | Payment accepts card **or** wallet (`oneOf`), widens `status`, nullable `transaction_id` | **blocked** | Union request widening passes silently (width subtyping); `enum-response-widening` + `nullable-response-widening` pin payment |
| 05 `payment-rollout` | Checkout learns the new responses first | **ships, staged** | One definite clause → checkout before payment |
| 06 `money-expand` | Currency v3 accepts/returns both Money forms, `nanos` → int64; recommendation breaks its score map | **partial** | Expand phase of expand/contract is WARN-only (`format-change` range risk); map value type change (`prim-mismatch`) pins recommendation |
| 07 `money-contract` | Currency v4 drops `units`/`nanos`, closes the schema, bans null memos; callers migrate | **ships, staged** | `REQ.1` + `REQ.4` + `RES.1` + `nullable-request-narrowing`, all pointing callers-first; **checkout quietly weakens `shipment_ref` — nothing fails, the ledger remembers** |
| 08 `tracing-first-cut` | Frontend originates `session-trace`; checkout forwards it *renamed*, no alias; email requires it | **partial** | Every per-edge conjunct passes — only `chain-field-missing` fires; the solver keeps the harmless middle hop and conservatively drops both ends |
| 09 `tracing-aliased` | Checkout declares `x-alias: client_session_id` | **ships** | The rename bridge (deck slide 9, realized): the chain verifies through the intermediate hop |
| 10 `promo-tgt` | Shipping accepts enum promo codes; frontend always sends free strings | **blocked** | All four mixed pairings pass; only the `(θ',θ')` **target state** breaks — the TGT conjunct as a deadlock |
| 11 `delivery-notifications` | Email requires `shipment-tracking` | **blocked** | The step-07 erosion becomes a violation four rollouts later; per-step blame lands on email, `gus evolve` traces the true origin |

## Rule coverage

| Rule | Where |
|------|-------|
| `REQ.1` (required field missing) | 03, 07 (break); 02 (pass via default); scenario I |
| `REQ.2` (optional became load-bearing) | 03 |
| `REQ.4` (unknown field vs closed schema) | 07 |
| `RES.1` (expected field gone) | 07; scenario E |
| `RES.4` (guarantee weakened) | 02; scenario D lineage |
| `RES.5` (extra field vs closed consumer) | unit tests (`TestObjectResClosedConsumer`) — a closed-consumer step deadlocks by construction, see note below |
| enum request narrowing / response widening | scenario C / B; TGT variant in 10 |
| `nullable-request-narrowing` / `-response-widening` | 07 / 04 |
| union width subtyping (pass) / narrowing | 04 / unit tests |
| `prim-mismatch` + lattice asymmetry | scenario I (lenient profile) |
| `format-change` (range risk, WARN not BREAK) | 06 |
| map value type change | 06 |
| `kind-mismatch`, coinductive `$ref` | scenario F |
| chain: `chain-weakened` / `chain-type-mismatch` / `chain-field-missing` / x-alias bridge | scenario D / scenario I / 08 / 09 |
| TGT (target-state) conjunct | 10 |
| rollout ordering (precedence stages) | 03, 05, 07 |
| deadlock exclusion (precedence cycle) | scenario I (C1+C4), 10 (TGT) |
| cross-rollout erosion (ledger) | 07 → 11 |

Note on `RES.5`: a consumer that closes its response expectations while the
provider still returns the old wider shape pins the *consumer* after the
provider — combined with any callers-first rule on the same edge it forms a
deadlock, which is exactly why the suite demonstrates it in unit tests
rather than in a shippable step.

## The provenance ledger (`gus evolve`)

Per-step checks judge one transition; the ledger judges a lifetime. Step 07
weakens checkout's `shipment_ref` guarantee **while nothing requires it** —
no chain exists, nothing fails, the change ships. Step 11 introduces the
requirer; the per-step checker can only blame email (the only excludable
upgrade in that batch). The ledger has been carrying the history the whole
time:

```
identity "shipment-tracking" — EXPOSED
  born     @ 03: checkout provides it as string on "shipment_ref" (required)
  eroded   @ 07: shipment_ref went required→optional at checkout
  demanded @ 11: now required by [email] — REJECTED
  violated @ 11: chain-weakened — guarantee last weakened at step 07
```

The repair is restoring checkout's guarantee (or shipping a fallback), not
abandoning the email feature — a conclusion invisible to any single-step
check. The ledger persists in `ledger.json` between invocations (already-
recorded steps are skipped), and records *all* carrying paths per identity
(`chain.AllPaths`), since a diamond-shaped mesh can route an identity along
any of several upgrade paths.
