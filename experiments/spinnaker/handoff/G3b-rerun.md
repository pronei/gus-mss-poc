# Handoff — G3b, the re-run after the extractor fixes

For one Opus session at maximum effort, after G1b has re-extracted and
regenerated `projection/docs.lock`. Read `handoff/G3-projection.md` (still
the rules), `PLAN.md` §4 rulings (v)–(x) and §7, `projection/memo.md`,
`projection/decisions.md`, `extractor/memo.md` (G1b's before/after table).
You change only `projection/` (code, `graph/`, `scenarios/`, `results/`,
`triage/`, `README.md`, `memo.md`, `decisions.md`).

## What changes

1. **Drop the bytecode tables.** `gate.py`'s `PROVIDER_RESPONSE`,
   `PROVIDER_PARAMS` and `CALLER_PRIMITIVE_QUERY` are replaced by the
   documents' `x-return-kind`, `x-response-kind`, `x-param-optional`; the
   triage categories are assigned from the documents alone. Keep the old
   tables in `memo.md` as the record of what they said, and report any row
   where the document disagrees with the table.
2. **Gate again, then pairs.** Expected after G1b: no `projection defect`
   and no `checker limitation` rows; the edges the old gate excluded enter
   the pairs. Report per BOM: excluded edges before and after, by category.
3. **A lenient run as a third reading.** Run every scenario under strict and
   under `coercion: lenient`; in `compare.py` keep a `params`/`headers`
   finding only if it appears under both (text binding is the wire), keep
   `body`/`response` findings from the strict run only (Jackson truncates,
   which is a value change). State this per-component rule as a lossy step;
   report the findings that differ between the two runs.
4. **The headline live-leg reading** is the body-and-response reading; the
   per-component table stands beside it; the whole-wrapper figure and the
   review's 24.7 % are not headlines (ruling viii).
5. **Framing** (ruling v): the README leads with what the run shows —
   specificity on a real mesh, caller drift observed, the gate's audit of
   the corpus — and states that the documented breaks in range are outside
   declarations. No recall claim.
6. **Version order stays**; add `pairs.tsv` for the date-ordered mode (BOM
   `timestamp`) without running it, and list the pairs that exist in one
   mode only (§7 of the plan).

## Acceptance

- All scenarios of the 49 pairs evaluate (exit 0/1, never 2); no edge on
  Tier 3; the certificate passes or every FAIL is listed.
- P37's two artefact breaks are gone; any break on a live leg is traced to
  its declarations with `javap` evidence and either confirmed as a real
  hazard or attributed to a named lossy step.
- `results/compare.md` regenerates identically on a second run; `memo.md`
  ends with "## What I could not verify"; `decisions.md` marks `needs owner`.
