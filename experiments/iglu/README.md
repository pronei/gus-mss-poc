# Iglu Central vs jsonsubschema: a differential run of the pair relation

**Question.** Does `pkg/compat` decide the subschema relation the way an
independent checker does, on real schema evolutions nobody wrote for it?

**Corpus.** [Iglu Central](https://github.com/snowplow/iglu-central) at
`db4d2f7`: 683 schema files, 522 schema lineages, 74 with more than one
version, giving 142 consecutive-version pairs. Each version is named
`MODEL-REVISION-ADDITION` (SchemaVer), which states the publisher's intent:
an ADDITION must stay backward compatible, a MODEL bump is breaking.

**Oracle.** IBM's [jsonsubschema](https://github.com/IBM/jsonsubschema)
(Habib, Shinnar, Hirzel, Pradel, ISSTA 2021), installed from PyPI into a
venv. It decides `s <: t` semantically, with refinement keywords,
negation and uninhabited schemas, and answers three ways: subschema, not,
or undecided.

**Method.** `main.go` loads both files of every pair through
`schema.LoadSchema` under `DialectJSONSchema` and asks `compat.Check` in
both directions
under the strict JSON lattice; a pair is a subschema when no BREAK-severity
finding is reported (warnings are format range risks, which the subschema
relation does not see). `jss.py` asks jsonsubschema the same two
questions per pair in a child process with a timeout. `compare.py` joins
the two and classifies each disagreement by what changed between the files:
*refinement-only* (bounds, lengths, patterns, item counts, format, prose)
or *structural*.

```sh
go run ./experiments/iglu --iglu /path/to/iglu-central --out results/pairs.csv
python jss.py results/pairs.csv results/jss.csv --timeout 90     # needs: pip install jsonsubschema
python compare.py results/pairs.csv results/jss.csv
```

## Results (`results/compare.txt`)

| | old <: new (backward) | new <: old (forward) |
|---|---|---|
| decided by both | 122 | 122 |
| agree | 94 (77.0%) | 100 (82.0%) |
| GUS break disputed by jsonsubschema | **0** | **0** |
| GUS pass disputed by jsonsubschema | 28 | 22 |
| undecided by jsonsubschema | 19 | 19 |
| GUS load error | 1 | 1 |

Every break the checker reports is confirmed by the oracle, in both
directions. Every disagreement is a pass the oracle rejects, and all of
them fall into two classes:

- **Refinement-only changes: 12 backward, 15 forward.** `maxLength`,
  `minimum`, `pattern`, `minItems`. The loader drops these keywords by
  design (report §3.5), so a schema that only tightens a bound is invisible
  to it. This is the documented blind spot, now measured.
- **Open objects: 16 backward, 7 forward.** The checker reads an open
  object as emitting only its declared fields. The subschema relation reads
  it as admitting any value under any undeclared name, so adding a typed
  optional property to an open schema (all 16 backward cases: SendGrid,
  Iterable, Optimizely, Snowplow) or dropping `additionalProperties: false`
  (7 of the 8 forward cases: Mandrill) is a narrowing to the oracle and a
  no-op to the checker. The remaining forward case (`ua_parser_config`
  1-0-0 to 1-0-1) is a refinement case the classifier missed: the old
  `parameters` object carried `maxProperties: 0`, a keyword the loader
  drops, so the new object's properties are a narrowing only the oracle
  sees. This open-object deviation was not stated in the report before
  this run.

The 19 undecided pairs are jsonsubschema's own limits: 18 raise
`UnsupportedNegatedObject` and one fails to parse a regular expression.
The one load error is a schema mixing named properties with an
`additionalProperties` schema, which the loader refuses by design.

**SchemaVer as ground truth.** Of 79 ADDITION pairs decided by both tools,
74 are backward compatible for both. Two are not, for both tools:
`loader_runtime_error` 1-0-0 to 1-0-1 and
`bot_detection_enrichment_config` 1-0-0 to 1-0-1 add a required field
under an ADDITION bump, the class of labelling bug the ISSTA paper reported.
Three more add typed properties to open schemas, breaking under the letter
of the subschema relation and not under the checker's reading. Of 39 MODEL
pairs, 24 are compatible for the checker and not for the oracle, almost all
`format` or bound changes that Snowplow treats as breaking for warehouse
loading rather than for validation.

## What this does and does not show

It shows that on 244 decided pair-direction verdicts the checker never
reports a break the oracle disputes, and that its misses are confined to
two named, deliberate deviations, one of which (open objects) the report
must now state. It does not evaluate anything above the pair relation:
mixed-version pairs, batches, ordering, chains and the ledger have no
counterpart in a single-lineage corpus.

## Fixes this run produced

Both landed on `main` (v0.3.4), since they are properties of the loader and
the relation rather than of this experiment. Only the harness lives here.

- The dialect-driven loader: `schema.Config{Dialect: DialectJSONSchema}`
  reads a standalone draft-04 document, with `type` lists including `null`,
  `definitions` and `$defs` references, and JSON indented with tabs. Under
  the default OpenAPI dialect those syntaxes are refused with an error
  naming the dialect to use.
- The bare `null` type: `type: "null"` loaded as "nullable anything"
  before this run, which made the `oneOf` ambiguity rule fire on every
  `oneOf` with a null alternative. It is now the value set {null}.

Rerunning the harness after that refactor reproduces all 142 pairs'
verdicts unchanged.
