#!/bin/sh
# Re-extract every document the acceptance suite uses.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
X=$(cd "$here/.." && pwd)
E=$(cd "$X/.." && pwd)
JAVA_HOME=${JAVA_HOME:-$(ls -d "$E"/.jdk/*/Contents/Home 2>/dev/null | head -1)}
mkdir -p "$X/out"
for sv in "1.38.0 front50 2.41.0" "1.38.0 gate 6.69.0" "1.38.0 orca 8.64.0" \
          "1.30.0 front50 2.28.0" "1.30.0 gate 6.58.0" "1.30.0 orca 8.31.0"; do
  bom=$(echo "$sv" | cut -d' ' -f1); svc=$(echo "$sv" | cut -d' ' -f2); ver=$(echo "$sv" | cut -d' ' -f3)
  "$JAVA_HOME/bin/java" -jar "$X/target/gus-contract-extractor.jar" \
    --classpath "$E/corpus/$bom/$svc" --service "$svc" --version "$ver" \
    --mesh "$E/scout/S1/tools/mesh.tsv" \
    --out "$X/out/$svc-$ver.yaml" --diag "$X/out/$svc-$ver.diag.json"
done
