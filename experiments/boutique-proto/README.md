# Online Boutique's real proto history, projected onto the checker

**Question.** Run the checker on the one public mesh whose contract history is
real: Google's `microservices-demo`, whose nine services share a single
`demo.proto`. What does the OpenAPI projection catch, what does it miss, and
why?

**Corpus.** `history/`: every commit that touched the proto, fetched from
GitHub at its own SHA (15 versions, 2018-06 to 2024-09, `index.tsv`). Ten
consecutive pairs change the interface; four are no-ops (licenses, comments,
a `go_package` option) and serve as negative controls. Three commit messages
say "breaking" in the authors' own words. Every semantic change predates the
first tagged release: the 32 releases since 2020 never touched the contract.

**Projection (`gen/`).** A pure-Go reader (`bufbuild/protocompile`, no
`protoc` plugins) emits one OpenAPI 3.0 document per service per commit,
under a mapping chosen to lose as little as the grammar allows, which is
deliberately *not* the proto3 JSON encoding:

| proto | projection | note |
|---|---|---|
| `rpc M(Req) returns (Res)` in service S | `POST /pkg.S/M`, body `Req`, 200 `Res` | the gRPC HTTP/2 path itself |
| message | open object, no `required` | proto3 has no required; unknown fields are ignored on the wire |
| field | snake_case name, `x-proto-field-number: N` | number kept for the reader; the checker ignores it |
| int64, uint64 | `integer` with format | not the strings of proto3 JSON |
| enum | closed string enum, `x-proto-open-enum: true` | proto3 enums are open; the grammar has no open enum |
| oneof member | plain optional property, `x-proto-oneof` | exactly-one is not expressible without `required` |
| map, repeated, bytes | `additionalProperties`, array, `string/byte` | |

Each service's document carries only the messages reachable from its own
RPCs, so a document changes exactly when that service's interface does. The
frontend has no proto and gets an empty document: it is a pure caller with no
declared outbound contract, so every edge runs under the Tier-3 fallback
(provider self-diff; no C2, C4 or TGT). The call graph is taken from
`src/frontend` and `src/checkoutservice` at the commits of this history.

Per consecutive pair the generator writes a mesh (`graph-NN-MM.yaml`, edges
whose RPC path exists at both versions), a scenario (baseline everywhere at
NN, upgrades = services whose document changed), and a note of endpoint
additions, removals and path changes, which the per-edge model cannot
express and which are reported as a separate channel.

**Wire comparator (`gen/wire.go`).** The same two proto versions compared by
field *number* under protobuf's documented compatibility rules: varint kinds
are mutually compatible, `sint32/sint64`, `fixed32/sfixed32`,
`fixed64/sfixed64`, `string/bytes`, and a message with a structurally
compatible message. Anything else at the same number is a WIRE break. A
field deleted, renamed, or a number reused under a new name, and an enum
value removed, keep the wire parseable but change meaning: SEMANTIC.

```sh
go run ./experiments/boutique-proto/gen --history experiments/boutique-proto/history --out experiments/boutique-proto/generated
for sc in experiments/boutique-proto/generated/scenarios/*.yaml; do p=$(basename $sc .yaml); \
  gus mss --graph experiments/boutique-proto/generated/graph-$p.yaml --scenario $sc > experiments/boutique-proto/results/$p.txt; done
python3 experiments/boutique-proto/summarize.py
```

## Results (`results/summary.md`)

Ten semantic pairs, three verdicts each: the authors' message, the checker
on the projection, the wire comparator.

| | pairs |
|---|---|
| wire-breaking pairs | 6 |
| of which the checker reports a break | 1 (`02-03`, `Product.id` int32 to string) |
| of which the endpoint channel reports | 2 (`06-07` RPC removed, `09-10` service renamed) |
| of which the projection **passes** | **3** (`01-02`, `03-04`, `04-05`) |
| semantic-only pair both miss | 1 (`05-06`, `Address` renumbered) |
| clean pairs both pass | 3 semantic (`07-08`, `08-09`, `10-11`) and 4 no-ops |

Two of the three commits the authors call breaking pass the projection.

## Why the three misses happen, and why it is one cause

`01-02`: `ListRecommendationsResponse` field 1 goes from `repeated Product
products` to `repeated string product_ids`. `03-04`: `Convert`'s response
field 1 goes from `Money result` to `string currency_code`. `04-05`:
`Money` field 2 goes from `MoneyAmount amount` to `int64 units`. In every
case a field's *type* changed together with its *name*.

The wire identifies a field by its number, so it sees a type change at the
same number: a message became a scalar, and an old reader cannot parse the
payload. JSON identifies a field by its name, so the projection sees one
optional field deleted and another added, which under proto3 (nothing
required, every message open) is not a shape break. The checker's rules are
right about the document they were given; the document has already lost
the fact that decides the case. The same loss makes `05-06` invisible to
both views: `Address` keeps three string fields at numbers 1 to 3 but moves
`city` from 3 to 2 and puts `state` at 3, so an old reader takes the state
as the city with no parse error anywhere. Only a name-aware semantic rule
could report it.

**This is the hand-conversion of the testbed, seen from the other side.**
The Online Boutique corpus under `scenarios/online-boutique/` was translated
from these protos by hand into OpenAPI. That translation performed the
name-for-number substitution above on every message, and it also invented
`required` lists that no proto ever declared. Everything the presence rules
(`REQ.1`, `REQ.2`, `RES.1`, `RES.4`) report on that corpus rests on the
second choice; everything about type changes rests on the first. Neither is
wrong as a model of a REST mesh. Both are absent from the proto contract.

## What this does and does not show

It shows the projection is exact where a change stays inside one name and
one type, silent where a change crosses names, and that for Protobuf the
shape rules need two additions before a verdict means what it does for
REST: a field's identity must be its number, and a deleted or renamed field
must be a finding with its own severity, since the wire tolerates it and the
reader does not. It also shows the batch layer running on real changes:
`04-05` upgrades six services at once, and the checker's verdict on that
batch is only as good as the pair relation underneath it.

It does not exercise C2, C4, TGT, chains or the ledger, because the frontend
has no contract and the proto declares no identities. The corpus is small:
ten changes in one repository over four months of 2018.
