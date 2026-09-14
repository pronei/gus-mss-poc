#!/usr/bin/env bash
# Every scenario of every pair through the checker, and the rollout steps through `gus evolve`.
#
#   ./run.sh [presence ...]            # default: none declared; JOBS (default 6) pairs run in parallel
#   PAIRS="P01 P02" ./run.sh none      # a subset of pairs; other pairs' results are left alone
#   NO_EVOLVE=1 ./run.sh               # skip `gus evolve`
#
# Inputs: graph/<presence>/P<NN>.yaml (graph.py pairs) and scenarios/ (scenarios.py).
# Output: results/<presence>/P<NN>/<batch>.{check.json,check.err,check.rc,mss.txt,mss.err},
#         results/<presence>/{ledger.json,evolve.txt,evolve.err,run-times.txt}.
#
# `gus check --format json` runs on every scenario. `gus mss` runs where check
# says the batch is not safe (exit 1); where it is safe, mss would print the
# check and "All upgrades are safe. No MSS computation needed." and nothing
# else (main.go:126-130), so that sentence is written instead of a second run.
# Exit 2 (could not evaluate) stays in check.rc and check.err, is never
# retried, and compare.py reports it with the scenario.
#
# `gus evolve` needs one graph whose edges exist at every step, and the edge set
# changes across the range (graph.py), so each pair's step is replayed against
# that pair's graph, in version order, through one ledger; the ledger skips
# recorded steps, so the order of the invocations is the order of the history.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
bin="$here/.work/bin/gus"
jobs=${JOBS:-6}
mkdir -p "$(dirname "$bin")"
(cd "$root" && go build -o "$bin" ./cmd/gus)

run_pair() {  # <presence> <PNN>
  local presence=$1 pair=$2
  local graph="$here/graph/$presence/$pair.yaml" out="$here/results/$presence/$pair"
  rm -rf "$out"
  mkdir -p "$out"
  for scn in "$here/scenarios/pairs/$pair"/*.yaml; do
    local name rc=0
    name=$(basename "$scn" .yaml)
    "$bin" check --graph "$graph" --scenario "$scn" --format json > "$out/$name.check.json" 2> "$out/$name.check.err" || rc=$?
    echo "$rc" > "$out/$name.check.rc"
    if [ "$rc" -eq 1 ]; then
      "$bin" mss --graph "$graph" --scenario "$scn" > "$out/$name.mss.txt" 2> "$out/$name.mss.err" || true
    elif [ "$rc" -eq 0 ]; then
      printf 'Decision: YES\n\nAll upgrades are safe. No MSS computation needed.\n' > "$out/$name.mss.txt"
    fi
  done
}
export -f run_pair
export here bin

presences=${*:-none declared}
for presence in $presences; do
  mkdir -p "$here/results/$presence"
  if [ -n "${PAIRS:-}" ]; then
    selected=$PAIRS
  else
    selected=$(ls "$here/scenarios/pairs" | sort)
    rm -rf "$here/results/$presence"/P* "$here/results/$presence"/ledger.json
  fi
  t0=$(date +%s)
  printf '%s\n' $selected | xargs -P "$jobs" -I{} bash -c 'run_pair "$0" "$1"' "$presence" {}
  t1=$(date +%s)
  if [ -z "${NO_EVOLVE:-}" ]; then
    ledger="$here/results/$presence/ledger.json"
    : > "$here/results/$presence/evolve.txt"
    : > "$here/results/$presence/evolve.err"
    for pair in $(printf '%s\n' $selected | sort); do
      rc=0
      "$bin" evolve --graph "$here/graph/$presence/$pair.yaml" --steps-dir "$here/scenarios/steps/$pair" \
        --ledger "$ledger" >> "$here/results/$presence/evolve.txt" 2>> "$here/results/$presence/evolve.err" || rc=$?
      echo "$pair evolve exit $rc" >> "$here/results/$presence/evolve.err"
    done
  fi
  t2=$(date +%s)
  n=$(printf '%s\n' $selected | wc -l | tr -d ' ')
  printf '%s: %s pairs x 46 batches, check+mss %ss with %s jobs; evolve %ss\n' \
    "$presence" "$n" "$((t1 - t0))" "$jobs" "$((t2 - t1))" | tee "$here/results/$presence/run-times.txt"
done
