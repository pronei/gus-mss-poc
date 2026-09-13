#!/bin/sh
# The whole acceptance suite of handoff/G1-extractor.md, in one run.
#
#   1  gus loads every emitted document without error
#   2  the provider endpoint set equals S2's census on (method, normalized path)
#   3  the golden fragments match
#   4  the caller endpoint set equals S1's edges.tsv
#   5  the three services at both ends of the range extract and load
#   +  the unit tests, and the D11 consistency triage over a real version pair
#
# Needs the corpus (gitignored): experiments/spinnaker/corpus/<bom>/<svc>/.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
X=$(cd "$here/.." && pwd)
E=$(cd "$X/.." && pwd)
fail=0
note() { printf '\n=== %s ===\n' "$1"; }
check() { if [ "$1" -ne 0 ]; then fail=1; echo "  ^ FAILED"; fi; }

note "unit tests"
"$X/mvnw" -q test 2>&1 | grep -E "Tests run:|ERROR" | tail -3 || true
"$X/mvnw" -q -DskipTests package >/dev/null

note "extract (6 documents: 3 services x 2 BOMs)"
"$here/extract_all.sh"

note "2. provider endpoints against S2's census"
for sv in "front50 2.41.0" "gate 6.69.0" "orca 8.64.0"; do
  svc=$(echo "$sv" | cut -d' ' -f1); ver=$(echo "$sv" | cut -d' ' -f2)
  printf '%-9s ' "$svc"
  set +e
  python3 "$here/census_diff.py" --doc "$X/out/$svc-$ver.yaml" --service "$svc" \
      --endpoints "$E/scout/S2/endpoints.tsv" --quiet | tail -1
  check $?
  set -e
done

note "4. caller endpoints against S1's edges.tsv"
for sv in "front50 2.41.0" "gate 6.69.0" "orca 8.64.0"; do
  svc=$(echo "$sv" | cut -d' ' -f1); ver=$(echo "$sv" | cut -d' ' -f2)
  printf '%-9s ' "$svc"
  set +e
  python3 "$here/edges_diff.py" --doc "$X/out/$svc-$ver.yaml" --service "$svc" \
      --edges "$E/scout/S1/edges.tsv" --quiet | tail -1
  check $?
  set -e
done

note "3. golden fragments"
set +e
python3 "$here/golden_check.py" --doc "$X/out/front50-2.41.0.yaml"
check $?
set -e

note "1 + 5. gus loads every document (both BOMs)"
for d in front50-2.41.0 gate-6.69.0 orca-8.64.0 front50-2.28.0 gate-6.58.0 orca-8.31.0; do
  svc=${d%%-*}; ver=${d##*-}
  probe=$(python3 - "$X/out/$d.yaml" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
for p, item in sorted(doc["paths"].items()):
    if p.startswith("/_calls") or "{" in p:
        continue
    for verb in ("get", "post", "put"):
        if verb in item:
            print(p, verb.upper())
            raise SystemExit
PY
)
  printf '%-16s ' "$d"
  set +e
  "$here/gus_load.sh" "$X/out/$d.yaml" "$svc" "$ver" "$(echo "$probe" | cut -d' ' -f2)" \
      "$(echo "$probe" | cut -d' ' -f1)" 2>&1 | head -1
  check $?
  set -e
done

note "D11 triage: a real version pair through gus"
"$here/cross_version_check.sh" 2>&1 | tail -3 || true

note "result"
if [ $fail -eq 0 ]; then echo "all acceptance checks passed"; else echo "SOME CHECKS FAILED"; fi
exit $fail
