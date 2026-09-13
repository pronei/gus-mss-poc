#!/bin/sh
# Acceptance 1: `gus` loads an emitted document without error.
#
# schema.Load is eager — it resolves every component in components/schemas and
# converts every request and response under paths before returning
# (loader.go:104-152) — so one successful load validates the whole document.
# A hard input error (allOf, an object mixing properties with an
# additionalProperties schema, a type list, a mixed oneOf/anyOf) fails here.
#
#   gus_load.sh <document.yaml> [<service> <version> <method> <path>]
set -eu

doc=$1
svc=${2:-front50}
ver=${3:-2.41.0}
method=${4:-GET}
path=${5:-/pipelines}

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

gus="$work/gus"
(cd "$repo" && go build -o "$gus" ./cmd/gus)

cp "$doc" "$work/spec.yaml"
cat > "$work/graph.yaml" <<YAML
services:
  $svc:
    $ver: spec.yaml
  probe:
    v1: spec.yaml
edges:
  - name: probe->$svc
    from: probe
    to: $svc
    method: $method
    path: $path
YAML
cat > "$work/scenario.yaml" <<YAML
id: G1-LOAD
name: "G1 load probe"
baseline: { $svc: $ver, probe: v1 }
upgrades: {}
YAML

set +e
out=$("$gus" consistent --graph "$work/graph.yaml" --scenario "$work/scenario.yaml" 2>&1)
rc=$?
set -e
if [ $rc -eq 2 ]; then
  echo "FAIL: gus could not evaluate the document (exit 2)"
  echo "$out"
  exit 1
fi
echo "OK: gus loaded $(basename "$doc") (consistent exit $rc)"
echo "$out" | tail -5
