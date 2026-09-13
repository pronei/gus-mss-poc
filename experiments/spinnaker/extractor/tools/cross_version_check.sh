#!/bin/sh
# A real GUS run over two extracted BOMs: orca and front50 at 1.30.0 against
# the same two at 1.38.0, with orca's own /_calls declarations supplying the
# caller side (tier 2).  Not an acceptance criterion of the handoff — it is
# the evidence that the documents G1 emits are comparable across a version
# pair, which is what G3 consumes.
#
#   cross_version_check.sh <out dir>
set -eu
out=${1:-$(cd "$(dirname "$0")/../out" && pwd)}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

(cd "$repo" && go build -o "$work/gus" ./cmd/gus)
for f in orca-8.31.0 orca-8.64.0 front50-2.28.0 front50-2.41.0; do
  cp "$out/$f.yaml" "$work/$f.yaml"
done

# Every orca -> front50 call orca declares at BOTH versions and front50
# exposes at BOTH versions.
python3 - "$work" <<'PY'
import sys, yaml, os
work = sys.argv[1]
def load(n): return yaml.safe_load(open(os.path.join(work, n + ".yaml")))
oc_old, oc_new = load("orca-8.31.0"), load("orca-8.64.0")
f_old, f_new = load("front50-2.28.0"), load("front50-2.41.0")
def calls(doc):
    out = set()
    for p, item in doc["paths"].items():
        if p.startswith("/_calls/front50"):
            rest = p[len("/_calls/front50"):] or "/"
            for verb in item:
                out.add((verb, rest))
    return out
def provides(doc):
    return {(v, p) for p, item in doc["paths"].items()
            if not p.startswith("/_calls") for v in item}
edges = sorted(calls(oc_old) & calls(oc_new) & provides(f_old) & provides(f_new))
with open(os.path.join(work, "graph.yaml"), "w") as fh:
    fh.write("services:\n")
    fh.write("  orca:\n    8.31.0: orca-8.31.0.yaml\n    8.64.0: orca-8.64.0.yaml\n")
    fh.write("  front50:\n    2.28.0: front50-2.28.0.yaml\n    2.41.0: front50-2.41.0.yaml\n")
    fh.write("edges:\n")
    for i, (verb, path) in enumerate(edges):
        fh.write("  - name: orca->front50-%d\n    from: orca\n    to: front50\n" % i)
        fh.write("    method: %s\n    path: \"%s\"\n" % (verb.upper(), path))
with open(os.path.join(work, "scenario.yaml"), "w") as fh:
    fh.write("id: G1-XV\nname: \"front50 1.30.0 -> 1.38.0 with orca's declared calls\"\n")
    fh.write("baseline: { orca: 8.31.0, front50: 2.28.0 }\n")
    fh.write("upgrades: { orca: 8.64.0, front50: 2.41.0 }\n")
print("%d orca->front50 edges declared on both sides at both versions" % len(edges))
PY

set +e
"$work/gus" check --graph "$work/graph.yaml" --scenario "$work/scenario.yaml"
rc=$?
set -e
echo "gus check exit $rc (0 clean, 1 hazards found, 2 could not evaluate)"
[ $rc -eq 2 ] && exit 1
exit 0
