#!/usr/bin/env python3
"""Join the hand-verified interface->provider map (mesh.tsv) with the parsed
Retrofit declarations to produce edges.tsv."""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from extract import parse_file  # noqa: E402

TAGS = {
    "gate": "v6.69.0", "orca": "v8.64.0", "clouddriver": "v5.95.0",
    "front50": "v2.41.0", "echo": "v2.47.2", "igor": "v4.22.0",
    "fiat": "v1.57.0", "rosco": "v1.26.0", "kayenta": "v2.46.0",
    "keel": "v1.4.1",
}

FIAT_API = "fiat-api/src/main/java/com/netflix/spinnaker/fiat/shared/FiatService.java"
HEALTH = ("gate-web/src/main/groovy/com/netflix/spinnaker/gate/services/internal/"
          "HealthCheckableService.groovy")


def clean(s):
    return (s or "-").replace("\t", " ").replace("\n", " ").strip() or "-"


def main():
    mesh = []
    with open(os.path.join(ROOT, "tools", "mesh.tsv")) as fh:
        next(fh)
        for line in fh:
            if line.strip():
                mesh.append(line.rstrip("\n").split("\t"))

    rows = []
    problems = []
    claim_n = [0]

    for caller, rel, provider, resolved_by in mesh:
        if rel == "FIATAPI":
            src_repo, src_rel = "fiat", FIAT_API
        elif rel.startswith("HEALTH:"):
            src_repo, src_rel = "gate", HEALTH
        else:
            src_repo, src_rel = caller, rel
        path = os.path.join(ROOT, src_repo, src_rel)
        if not os.path.exists(path):
            problems.append("MISSING FILE %s" % path)
            continue
        parsed, probs = parse_file(path, os.path.join(ROOT, src_repo))
        problems.extend("%s:%s %s" % p[0:3] for p in probs)
        for r in parsed:
            claim_n[0] += 1
            claim = "%s@%s %s:%d" % (src_repo, TAGS[src_repo], r["file"], r["line"])
            rows.append([
                caller, provider, r["verb"], clean(r["path"]), r["iface"],
                r["name"], clean(r["body"]), clean(r["ret"]),
                resolved_by, claim,
            ])
    hdr = ["caller", "provider", "method", "path_template", "interface",
           "method_name", "body_type", "return_type", "resolved_by", "claim"]
    out = os.path.join(ROOT, "edges.tsv")
    with open(out, "w") as fh:
        fh.write("\t".join(hdr) + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    print("wrote %d rows to %s" % (len(rows), out))
    for p in sorted(set(problems)):
        print("PROBLEM " + p, file=sys.stderr)


main()
