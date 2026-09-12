#!/bin/sh
# R2 re-derivation of the artifact and web claims (S3-002/005/008, S4-002/005/008), anonymous, read-only.
# usage: sh r2_fetch.sh <outdir>
set -e; out=${1:-./r2_fetch}; mkdir -p "$out"; cd "$out"
ACC="Accept: application/vnd.docker.distribution.manifest.v2+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.index.v1+json"
echo "# S3-001/002 bucket listing"; curl -s -o bomlist.xml -w "http=%{http_code} bytes=%{size_download}\n" "https://storage.googleapis.com/halconfig?prefix=bom/&max-keys=1000"
python3 - <<'PY'
import re
x=open('bomlist.xml').read(); keys=re.findall(r'<Key>([^<]+)</Key>',x)
rel=[k for k in keys if re.fullmatch(r'bom/\d+\.\d+\.\d+\.yml',k)]
vs=sorted(tuple(int(p) for p in k[4:-4].split('.')) for k in rel)
print('keys',len(keys),'release boms',len(rel),'min',vs[0],'max',vs[-1],'1.x',sum(v[0]==1 for v in vs),'calver',sum(v[0]>=2025 for v in vs),'truncated',re.findall(r'<IsTruncated>([^<]+)',x))
PY
echo "# S3-005 manifests (expect 200 + digests 31fdb568… and 4db25c29…)"
curl -s -D - -o /dev/null -H "$ACC" https://gcr.io/v2/spinnaker-marketplace/gate/manifests/1.19.0-20201012200017 | grep -i -E '^HTTP|docker-content-digest'
curl -s -D - -o /dev/null -H "$ACC" https://us-docker.pkg.dev/v2/spinnaker-community/docker/clouddriver/manifests/5.95.0 | grep -i -E '^HTTP|docker-content-digest'
echo "# S3-008 tag counts (expect 4608 / 626 / 514) and oldest gcr tag digest 4477cb5b…"
curl -s https://gcr.io/v2/spinnaker-marketplace/gate/tags/list | python3 -c 'import sys,json;print("gcr",len(json.load(sys.stdin)["tags"]))'
curl -s https://us-docker.pkg.dev/v2/spinnaker-community/docker/gate/tags/list | python3 -c 'import sys,json;print("gar",len(json.load(sys.stdin)["tags"]))'
TOK=$(curl -s "https://ghcr.io/token?scope=repository:spinnaker/gate:pull&service=ghcr.io" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOK" "https://ghcr.io/v2/spinnaker/gate/tags/list?n=10000" | python3 -c 'import sys,json;print("ghcr",len(json.load(sys.stdin)["tags"]))'
curl -s -D - -o /dev/null -H "$ACC" https://gcr.io/v2/spinnaker-marketplace/gate/manifests/0.4.0-411 | grep -i -E '^HTTP|docker-content-digest'
echo "# D2: keel registry presence (expect GAR 199 tags from 2025.0-0; GHCR 370)"
curl -s https://us-docker.pkg.dev/v2/spinnaker-community/docker/keel/tags/list | python3 -c 'import sys,json;t=sorted(json.load(sys.stdin)["tags"]);print("gar keel",len(t),t[:2])'
echo "# S4-002/005/008 changelog quotes"
for v in 2025.0.0 1.29.0 1.30.0; do curl -sL -o cl-$v.html -w "$v http=%{http_code}\n" https://spinnaker.io/changelogs/$v-changelog/; done
python3 - <<'PY'
import re,html
def txt(f): t=open(f,errors='replace').read(); return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',t))).replace('’',"'")
for f,q in [('cl-2025.0.0.html','first version of Spinnaker released from the monorepo'),('cl-2025.0.0.html','equivalent to version 1.38.0'),
            ('cl-1.29.0.html','Introduce a feature flag in Orca to use the new Igor stop endpoint. By default, if not enabled the existing endpoint'),
            ('cl-1.30.0.html',"If you've relied on this bug, you'll need to add manually add all the artifact constraints to all triggers to replicate the previous behavior.")]:
    print(f, 'FOUND' if q in txt(f) else 'NOT FOUND', '|', q[:60])
PY
