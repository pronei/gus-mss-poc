#!/usr/bin/env bash
# Fetch the two upstream repositories that hold the semantic-conventions
# model: the specification repository (releases up to 1.20.0 kept the model
# under semantic_conventions/) and the semantic-conventions repository
# (1.21.0 onwards, under model/, plus the cumulative schemas/ files).
# Usage: ./fetch.sh <dir>   then   ./extract.py --semconv <dir>/semantic-conventions --spec <dir>/otel-spec --out extracted
set -euo pipefail
dir=${1:?target directory}
mkdir -p "$dir"
[ -d "$dir/semantic-conventions" ] || git clone -q https://github.com/open-telemetry/semantic-conventions "$dir/semantic-conventions"
[ -d "$dir/otel-spec" ] || git clone -q --filter=blob:none --no-checkout https://github.com/open-telemetry/opentelemetry-specification "$dir/otel-spec"
echo "fetched into $dir; the commits used for the published results are listed in corpus.lock"
