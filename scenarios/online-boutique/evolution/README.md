# Evolution suite — one mesh, eleven rollouts

The standard cases (B–I) are isolated case studies. This suite is a
*storyline*: the same Online Boutique mesh evolving sprint by sprint as
features land, with each step's `baseline` being the accumulated result of
what previous steps actually shipped (their MSS, not their proposal). The
changes are synthetic but shaped like real feature work — an accounts
launch, a payments migration, an expand/contract money refactor, a tracing
initiative — and together they exercise every rule the checker knows.
Every step file declares an `id:` (`E01`–`E11`); the tool prints it in
every header and the ledger records steps under it.

Run it:

```sh
gus validate --graph ../graph.yaml --scenario-dir .
gus evolve   --graph ../graph.yaml --steps-dir .        # provenance ledger
```

## The storyline

| Case | Feature | Outcome | What it demonstrates |
|------|---------|---------|----------------------|
| E01 `wishlist` | Recommendation adds wishlist hits + score map | **ships** | Additive response fields are safe; `Map` values enter the mesh |
| E02 `cart-regression` | Cart stops guaranteeing `items`; adds `source` (required, with default) | **blocked** | `RES.4` pins cart out; the defaulted required field rides along silently (`REQ.1`'s escape hatch) |
| E03 `account-quotes` | Shipping requires `priority` + `account_tier`; both callers upgrade their sends | **ships, staged** | `REQ.1`/`REQ.2` become *ordering constraints*: callers stage 1, shipping stage 2; post-hoc replays the stages |
| E04 `payment-methods` | Payment accepts card **or** wallet (`oneOf`), widens `status`, nullable `transaction_id` | **blocked** | Union request widening passes silently (width subtyping); `enum-response-widening` + `nullable-response-widening` pin payment |
| E05 `payment-rollout` | Checkout learns the new responses first | **ships, staged** | One definite clause → checkout before payment |
| E06 `money-expand` | Currency v3 accepts/returns both Money forms, `nanos` → int64; recommendation breaks its score map | **partial** | Expand phase of expand/contract is WARN-only (`format-change` range risk); map value type change (`prim-mismatch`) pins recommendation |
| E07 `money-contract` | Currency v4 drops `units`/`nanos`, closes the schema, bans null memos; callers migrate | **ships, staged** | `REQ.1` + `REQ.4` + `RES.1` + `nullable-request-narrowing`, all pointing callers-first; **checkout quietly weakens `shipment_ref` — nothing fails, the ledger remembers** |
| E08 `tracing-first-cut` | Frontend originates `session-trace`; checkout forwards it *renamed*, no alias; email requires it | **partial** | Every per-edge conjunct passes — only `chain-field-missing` fires; the source and the rename hop ship, the demanding end is excluded (reverting the source would leave the demand unprovided, which is no repair) |
| E09 `tracing-aliased` | Checkout declares `x-alias: client_session_id` | **ships** | The rename bridge (deck slide 9, realized): the chain verifies through the intermediate hop; email's demand ships |
| E10 `promo-tgt` | Shipping accepts enum promo codes; frontend always sends free strings | **blocked** | All four mixed pairings pass; only the `(θ',θ')` **target state** breaks — the TGT conjunct as a deadlock |
| E11 `delivery-notifications` | Email requires `shipment-tracking` | **blocked** | The E07 erosion becomes a violation four rollouts later; per-step blame lands on email, `gus evolve` traces the true origin |

## Rule coverage

| Rule | Where |
|------|-------|
| `REQ.1` (required field missing) | E03, E07 (break); E02 (pass via default); case I |
| `REQ.2` (optional became load-bearing) | E03 |
| `REQ.4` (unknown field vs closed schema) | E07 |
| `RES.1` (expected field gone) | E07; case E |
| `RES.4` (guarantee weakened) | E02; case D lineage |
| `RES.5` (extra field vs closed consumer) | unit tests (`TestObjectResClosedConsumer`) — a closed-consumer step deadlocks by construction, see note below |
| enum request narrowing / response widening | case C / B; TGT variant in E10 |
| `nullable-request-narrowing` / `-response-widening` | E07 / E04 |
| union width subtyping (pass) / narrowing | E04 / unit tests |
| `prim-mismatch` + lattice asymmetry | case I (lenient profile) |
| `format-change` (range risk, WARN not BREAK) | E06 |
| map value type change | E06 |
| `kind-mismatch`, coinductive `$ref` | case F |
| chain: `chain-weakened` / `chain-type-mismatch` / `chain-field-missing` / x-alias bridge | case D / case I / E08 / E09 |
| TGT (target-state) conjunct | E10 |
| rollout ordering (precedence stages) | E03, E05, E07 |
| deadlock exclusion (precedence cycle) | case I (C1+C4), E10 (TGT) |
| cross-rollout erosion (ledger) | E07 → E11 |

Note on `RES.5`: a consumer that closes its response expectations while the
provider still returns the old wider shape pins the *consumer* after the
provider — combined with any callers-first rule on the same edge it forms a
deadlock, which is exactly why the suite demonstrates it in unit tests
rather than in a shippable step.

## The provenance ledger (`gus evolve`)

Per-step checks judge one transition; the ledger judges a lifetime. E07
weakens checkout's `shipment_ref` guarantee **while nothing requires it** —
no chain exists, nothing fails, the change ships. E11 introduces the
requirer; the per-step checker can only blame email (the only excludable
upgrade in that batch). The ledger has been carrying the history the whole
time:

```
identity "shipment-tracking" — EXPOSED
  now: checkout.shipment_ref : string (required=false, nullable=false)
  born           @ E03: checkout provides it as string on field "shipment_ref" (required=true, nullable=false)
  eroded         @ E07: field "shipment_ref" went required→optional at checkout — the identity is no longer guaranteed present
  demanded       @ E11: now required by [email] — the proposal was REJECTED because the guarantee no longer holds
  violated       @ E11: chain check fails (chain-weakened) — guarantee last weakened at step "E07" (field "shipment_ref" went required→optional at checkout — the identity is no longer guaranteed present)
```

The repair is restoring checkout's guarantee (or shipping a fallback), not
abandoning the email feature — a conclusion invisible to any single-step
check. The ledger persists in `ledger.json` between invocations (already-
recorded steps are skipped), and records *all* carrying paths per identity
(`chain.AllPaths`), since a diamond-shaped mesh can route an identity along
any of several upgrade paths.
