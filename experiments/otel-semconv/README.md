# OpenTelemetry semantic conventions through the checker

The OpenTelemetry semantic conventions are a public, versioned attribute
vocabulary with a machine-readable history of its own breaking changes: every
release ships a `schemas/<version>` file that declares which attributes were
renamed, and the `model/` registry records each attribute's type,
requirement level, stability and deprecation. That makes the corpus a ground
truth for exactly the two mechanisms of the checker that the case suite could
only exercise synthetically: rename bridging with `x-alias` along a data-flow
chain, and the provenance ledger's erosion events.

This experiment projects 31 releases (1.16.0 through 1.44.0, 30 consecutive
release pairs) onto a three-service telemetry pipeline, runs every upgrade
batch of the pipeline through `gus check` / `gus mss`, replays the releases
through `gus evolve`, and compares the verdicts and the ledger with what the
corpus itself declares. Everything below is regenerable from two public
repositories pinned in `corpus.lock`.

## Corpus

| Source | Releases | What is read |
|---|---|---|
| `open-telemetry/opentelemetry-specification`, `semantic_conventions/` | 1.16.0 – 1.20.0 | the model before it moved to its own repository |
| `open-telemetry/semantic-conventions`, `model/` | 1.21.0 – 1.44.0 | attribute registry and signal groups (two file formats: the original `groups:` and, from 1.44.0, weaver `definition/2`) |
| `open-telemetry/semantic-conventions`, `schemas/` | all | the declared `rename_attributes` maps, per release and per signal section |

`extract.py` resolves every group's attribute set (prefix, `extends`, `ref`,
`ref_group`) with the effective requirement level and normalises types.
`project.py` selects 26 signals — six span kinds (HTTP server and client, DB
client, RPC server and client, GraphQL, messaging, FaaS server) and 18
resource kinds (service, host, container, k8s pod/node/deployment/namespace/
cluster, cloud, process, os, device, deployment, browser, faas, telemetry.sdk,
otel.scope, webengine) — following each across its changing group ids
(`http.server` → `trace.http.server` → `span.http.server`); 24 exist at every
release, RPC client (from 1.21.0) and messaging (until 1.30.0) are partial and
are used only for release pairs where both sides have them.

## The pipeline

```
sdk  ──POST /v1/traces/<signal>──▶  collector  ──/_calls/backend/v1/traces/<signal>──▶  backend
     ──POST /v1/resource/<kind>──▶             ──/_calls/backend/v1/resource/<kind>──▶
```

All three services are versioned by the semantic-conventions release they
implement.

* **sdk** (caller). One payload per signal: an object whose properties are the
  signal's attributes at that release, typed from the registry (`int` →
  `integer/int64`, `double` → `number/double`, arrays, enums as their base
  type since semantic-conventions enums are open sets of well-known values;
  `template[...]` attribute families are not projectable and are dropped).
  Every property carries `x-provides: <signal>/<identity>`.
* **collector** (provider to the sdk, caller of the backend). Accepts every
  payload as an open object with nothing required — an OTLP receiver
  validates nothing — and forwards it. It is a pass-through: it forwards every
  attribute of its own release and of the previous one, never drops any (all
  forwarded fields are required), and translates exactly the renames the
  release's schema file declares for that signal kind (`spans`/`all` for span
  signals, `resources`/`all` for resource kinds): the renamed attribute
  carries `x-alias: <previous name>` and the previous name is no longer
  forwarded. That is what a collector running the schema-translation
  processor does; an undeclared rename passes through untouched.
* **backend** (provider). Accepts every payload (open, nothing required) and
  marks the attributes its dashboards rely on with `x-requires`.

Identity keys are `<signal>/<final name>`: an attribute keeps its key across
the renames the ground truth records for that signal, so a chain follows the
concept, while the checker only ever sees field names and aliases.

Two profiles decide what "required" means:

| profile | sdk marks required | backend requires |
|---|---|---|
| `spec` | attributes at requirement level `required` | the same set, at its own release |
| `full` | every emitted attribute | every attribute at its own release |

`spec` is the faithful reading of the convention; `full` is a stress profile
that turns every declared rename into a chain the alias mechanism has to
bridge.

For each release pair the projector writes a graph, seven scenarios (every
non-empty subset of the three services upgrades, the rest stay), and one
rollout step in which all three move; `run.sh` runs `gus check` on all 210
scenarios per profile, `gus mss` on those that are not safe, and replays the
30 steps through `gus evolve`. `compare.py` re-derives from the generated
contracts alone which chains must break at each target state under the
intended chain semantics and compares that oracle with the checker; it also
matches every rename, requirement-level change, withdrawal and addition the
corpus records against the ledger's events.

## Lossy steps, stated first

* Requirement levels `conditionally_required`, `recommended` and `opt_in` all
  become optional; only `required` becomes `required`.
* Enumerations become their base type; member additions and removals are
  invisible (they are compatible under the convention's open-enum rule).
* `template[string]` families (`http.request.header.<key>`) are dropped.
* The backend's demands are synthetic: "a backend built against release *v*
  relies on exactly what *v* guarantees". No real dashboard corpus was used.
* Chains are evaluated at the target state of a batch, as the formalism
  defines them; a rollout passes through mixed states the seven partial
  batches approximate but the `all` batch does not see.

## Ground truth in scope

Within the projected signals, across the 30 release pairs:

| Change kind | Count | Notes |
|---|---|---|
| renamed attributes | 49 | 43 declared in the schema file for the signal's own section (`spans`/`resources`/`all`); 2 declared only under `metrics` (`db.system` → `db.system.name` at 1.30.0, `messaging.client_id` → `messaging.client.id` at 1.26.0), so a span-side schema translator would not apply them; 4 recorded only by the registry's deprecation entries and never in a schema file (`db.name` → `db.namespace`, `db.operation` → `db.operation.name`, `db.statement` → `db.query.text`, `messaging.operation` → `messaging.operation.type`, all 1.26.0) |
| requirement-level changes | 38 | 7 promotions to `required` (telemetry.sdk name/version/language at 1.20.0, `server.port` for HTTP clients at 1.23.0, `messaging.operation.name` at 1.27.0, `process.pid` and `process.creation.time` at 1.41.0) and 3 demotions from it (`messaging.operation.type` at 1.27.0, `server.address` for RPC at 1.39.0); the rest move between the optional levels |
| withdrawn attributes | 121 | includes 4 that were `required`: `messaging.destination` (1.17.0), `http.target` (1.21.0, split into `url.path` and `url.query`), and `net.peer.name` on HTTP-client and RPC-server spans (1.21.0, where the schema file can only declare the server-side `net.host.name` → `server.address` because a rename map cannot depend on span kind); the messaging span group itself leaves the model at 1.31.0 (25 identities) |
| added attributes | 137 | including the 1.21.0 `url.*`/`client.*`/`server.*` families and the RPC client span group entering the model at 1.21.0 |
| type changes | 0 | no attribute in scope changed its base type; the pair relation therefore reports nothing on this corpus and every finding below is a chain or ledger finding |

Attributes per release across the 26 signals: 143 at 1.20.0, 182 at 1.30.0,
162 at 1.44.0; of these 20–22 are at level `required` (the `spec` profile's
identities with a demand).

## Results

`run.sh` with six parallel jobs takes about five minutes for both profiles
(420 `gus check` runs, 130 `gus mss` runs, two 30-step `gus evolve` replays).

### The checker against the oracle

| | `spec` | `full` |
|---|---|---|
| scenarios (30 release pairs × 7 batches) | 210 | 210 |
| scenarios whose set of broken chains **and** rules match the oracle | 210 | 210 |
| chains counted against a batch | 87 | 854 |
| batches not safe as proposed | 37 (10 release pairs) | 93 (21 release pairs) |
| pair-relation (edge) breaks | 0 | 0 |
| safe subsets computed | 37 | 93 |
| safe subset safe and maximal per the oracle | 35 | 82 |
| post-hoc certificate FAIL | 2 | 11 |
| unsafe subset reported as safe (certificate silent) | 0 | 0 |

Every chain verdict the checker gives agrees with the oracle: the same
identities break, for the same reason, in every one of the 420 scenarios.
The `all` batch is safe at every release pair in both profiles: at the target
state every service speaks the new release. The partial batches are where
the corpus bites, and the pattern is the one the design predicts:

| batch | not safe (`spec`) | typical cause |
|---|---|---|
| sdk only | 7 | the new sdk emits a renamed attribute an old collector does not forward (`chain-field-missing`), or a required attribute demoted to optional (`chain-weakened`), or stops emitting one the old backend still reads (`chain-no-provider`) |
| collector only | 2 | the collector translates a declared rename in front of an old backend that still reads the old name (`chain-field-missing` at the sink) |
| backend only | 8 | the new backend relies on an attribute promoted to `required` that the old sdk only emits optionally (`chain-weakened`), or on one that did not exist (`chain-no-provider`) |
| sdk + collector | 7 | as sdk only, plus the translated name reaching an old sink |
| sdk + backend | 5 | the old collector between two new ends forwards neither the renamed nor the added attribute |
| collector + backend | 8 | as backend only |

The release pairs with a break in the `spec` profile, and which of the six
partial batches survive, read as a rollout guide the corpus itself does not
give:

| pair | what changed (required-level identities) | safe partial batches |
|---|---|---|
| 1.16→1.17 | `messaging.destination` withdrawn, `messaging.operation` added, both required | collector only |
| 1.19→1.20 | `telemetry.sdk.{name,version,language}` promoted to required | everything except a backend upgrade before the sdk's |
| 1.20→1.21 | the HTTP wave: `http.method`→`http.request.method`, `http.scheme`→`url.scheme`, `http.url`→`url.full`, `net.host.name`→`server.address` (also demoted on server spans, promoted on RPC server spans), `http.target` split into `url.path`+`url.query`, `net.peer.name` gone on client spans | none — only the atomic `all` batch |
| 1.22→1.23 | `server.port` promoted on HTTP client spans | everything except backend-first |
| 1.25→1.26 | `messaging.operation`→`messaging.operation.type`, undeclared | collector only |
| 1.26→1.27 | `messaging.operation.name` promoted, `messaging.operation.type` demoted | collector; sdk+backend |
| 1.29→1.30 | `db.system`→`db.system.name`, declared only for metrics | collector only |
| 1.30→1.31 | the messaging span group leaves the model | everything except an sdk upgrade before the backend's |
| 1.38→1.39 | `rpc.system`→`rpc.system.name`, declared for all signals; `server.address` demoted on RPC spans | backend; collector+backend |
| 1.40→1.41 | `process.pid`, `process.creation.time` promoted | everything except backend-first |

Two readings of that table matter for the checker. A rename that the schema
file declares for the right signal kind (1.38→1.39) has a safe order —
backend, then collector, then sdk — and the batch results show it; a rename
declared for the wrong section (1.29→1.30) or not at all (1.25→1.26) has
none, because no hop can translate it. The 1.21.0 wave has no safe order
either, for a different reason: the new backend needs `url.path`, which no
old sdk emits, while every old hop needs the old names — the corpus's own
release notes recommend exactly the flag-day the checker finds.

### The safe subset

Of the 130 safe subsets the solver computed, 117 are safe and as large as
any oracle-safe subset. The other 13 (2 in `spec`, 11 in `full`) are all of
one shape: the oracle finds **no** safe subset, the solver proposes one
service, and the post-hoc certificate rejects it. Excluding one culprit
changes which mixed state the remaining upgrade would ship into, and that
state has a chain break the full target state did not — a new backend that
requires an added attribute is excluded, leaving a new sdk in front of an
old backend that still reads a withdrawn one (1.16→1.17 `sdk+backend`), or
a translating collector in front of an old sink (1.20→1.21
`collector+backend`). Chain constraints are not local to one service the
way a per-edge conjunct is; the certificate exists for exactly this and
caught every case.

### The ledger against the ground truth

`gus evolve` replays the 30 all-service steps; the ledger's first shipped
state is 1.17.0, so the comparison covers steps 2–30 (270 identities).

| ground truth (steps 2–30) | ledger event expected | `spec` | `full` |
|---|---|---|---|
| attribute added | `born` | 135 / 135 | 135 / 135 |
| attribute renamed | `mutated` (field a → b), or `eroded`/`restored` when the requirement level changed in the same release | 43 / 43 | 43 / 43 |
| attribute withdrawn | `withdrawn` | 117 / 117 | 117 / 117 |
| `required` → optional | `eroded` | 3 / 3 | — |
| optional → `required` | `restored` | 7 / 7 | — |
| ledger events the ground truth does not predict | | 0 | 0 |

Every rename, demotion, promotion, withdrawal and addition the corpus
records appears in the ledger at the step it happened, and the ledger
records nothing the corpus does not explain. The survival report at 1.44.0
(`spec`): 13 identities surviving with a demand, 7 eroded (their guarantee
weakened while a backend relied on it, all demand later dropped), 108
withdrawn, the rest provided without a demand.

## What the corpus exposed in the checker

The first runs did not look like the table above. Six defects in the chain
machinery surfaced, each on the first release pair that exercised it, and
were fixed on `main` (changelog 0.3.5) with regression tests; the case suite
and its ledger are unchanged by all of them.

1. **Dotted property names.** An annotation's field path is dot-joined, and
   the walk recovered the field name by taking the last segment — so
   `http.request.method` was looked up as `method` and never found. Every
   OpenTelemetry chain broke at the first hop.
2. **The sink was never checked.** After the intermediates, the walk compared
   types and stopped; a rename at the last hop into an unchanged sink passed
   every check. `collector` upgrades that translate `http.method` to
   `http.request.method` in front of a 1.20.0 backend were "safe".
3. **Unprovided demands were silence.** A requirer with no provider produced
   no chain at all, so `http.target` disappearing while a backend still read
   it was invisible (and, in the ledger, such an identity simply vanished
   instead of being recorded as withdrawn).
4. **One outbound contract per hop.** With 26 edges between the same two
   services the resolver looked only at the first, then, once it searched
   all of them, a same-named attribute of another signal answered for a
   missing one (`server.address` of DB spans for `server.address` of HTTP
   spans). The identity's arrival path now selects the contract.
5. **Chains named by field.** Attribution reverts each on-path upgrade and
   asks whether the chain is repaired; a chain identified by its field names
   "vanished" when the revert restored the old name, which counted as
   repaired and produced an unsafe subset that the post-hoc certificate then
   rejected. Chains are named by identity and endpoint services.
6. **No suspect for a provider-less chain.** A chain with no path had no
   on-path upgrades to revert, so nothing was excluded; every upgrading
   service is now a candidate and the revert test picks the one whose
   rollback restores the provider or withdraws the demand.

Two limits remain and are visible in the tables:

* **Chains are judged at the target state.** The `all` batch of the 1.21.0
  wave passes — at the target every service speaks 1.21.0 — while all six
  partial batches of the same pair break. The rollout has to pass through
  those partial states; the pair conjuncts C1–C4 quantify over them, the
  chain check does not. The natural repair is a chain conjunct per mixed
  state of the on-path upgrades, yielding precedences (backend before
  collector before sdk for a declared rename) instead of a target-only
  verdict.
* **Chain exclusions are not local.** Removing a culprit can create a chain
  break that the full target state did not have (T05 `collector-backend`:
  excluding the backend leaves a translating collector in front of an old
  sink). The Horn encoding assumes each break pins one service; the post-hoc
  certificate catches the case and reports it as such.

## Reproducing

```sh
./fetch.sh /tmp/otel                      # clone the two repositories
python3 extract.py --semconv /tmp/otel/semantic-conventions --spec /tmp/otel/otel-spec --out extracted
python3 project.py                        # generated/{spec,full}/..., ground_truth.json, coverage.json
./run.sh                                  # results/{spec,full}/...
python3 compare.py                        # results/compare.txt, results/compare.json
```

`extracted/` is not committed (9 MB of derived JSON); `generated/` and
`results/` are.
