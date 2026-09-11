#!/usr/bin/env bash
# Run the checker over every generated scenario and replay the rollout steps
# through `gus evolve`. Results land in results/<profile>/. Scenarios are
# independent, so release pairs run in parallel (JOBS, default 4).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
bin=${GUS_BIN:-$(mktemp -d)/gus}
jobs=${JOBS:-4}
(cd "$root" && go build -o "$bin" ./cmd/gus)

run_step() {  # <profile> <step>
  local profile=$1 step=$2
  local gen="$here/generated/$profile" out="$here/results/$profile/$step"
  mkdir -p "$out"
  for scn in "$gen/scenarios/$step"/*.yaml; do
    local name; name=$(basename "$scn" .yaml)
    # check first (JSON, machine-readable); the safe subset is only computed
    # when the batch as proposed is not safe.
    if "$bin" check --graph "$gen/graph.yaml" --scenario "$scn" --format json \
         > "$out/$name.check.json" 2> "$out/$name.check.err"; then
      printf 'Decision: YES\n\nAll upgrades are safe. No MSS computation needed.\n' > "$out/$name.mss.txt"
    else
      "$bin" mss --graph "$gen/graph.yaml" --scenario "$scn" \
        > "$out/$name.mss.txt" 2> "$out/$name.mss.err" || true
    fi
  done
}
export -f run_step; export here bin

for profile in spec full; do
  gen="$here/generated/$profile"; out="$here/results/$profile"
  rm -rf "$out"; mkdir -p "$out"
  ls "$gen/scenarios" | xargs -P "$jobs" -I{} bash -c 'run_step "$0" "$1"' "$profile" {}
  rm -f "$gen/steps/ledger.json"
  "$bin" evolve --graph "$gen/graph.yaml" --steps-dir "$gen/steps" --ledger "$out/ledger.json" \
    > "$out/evolve.txt" 2> "$out/evolve.err" || true
  echo "$profile: $(ls "$out"/*/*.check.json | wc -l | tr -d ' ') scenarios, ledger at $out/ledger.json"
done
