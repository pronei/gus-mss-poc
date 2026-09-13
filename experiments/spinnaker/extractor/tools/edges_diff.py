#!/usr/bin/env python3
"""Acceptance 4: the extracted caller endpoints against S1's edges.tsv, on
(provider, method, normalized path) under D3.

S1 emits one row per DECLARED Retrofit method; two overloads on one path
(FiatService.sync, Orca's three getPipelines) are distinct rows there and one
endpoint here, because the checker keys on {path, method}. The comparison is
therefore over the distinct keys, and the collapsed overloads are reported.

  edges_diff.py --doc out/front50-2.41.0.yaml --service front50 --edges ../scout/S1/edges.tsv
"""
import argparse
import collections
import csv
import re
import sys


def norm(p):
    p = (p or "").strip()
    q = p.find("?")
    if q >= 0:
        p = p[:q]
    if p in ("", ".", "./"):
        p = "/"
    if not p.startswith("/"):
        p = "/" + p
    p = re.sub(r"\{[^}]*\}", "{}", p)
    p = re.sub(r"/{2,}", "/", p)
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def read_clients(path):
    out = {}
    cur = None
    in_paths = False
    for line in open(path):
        if line.startswith("#"):
            continue
        if line.rstrip() == "paths:":
            in_paths = True
            continue
        if in_paths and line[:1] not in (" ", "\t") and line.strip():
            in_paths = False
        if not in_paths:
            continue
        m = re.match(r"^  (\S.*?):\s*$", line.rstrip("\n"))
        if m:
            cur = m.group(1).strip('"')
            continue
        m = re.match(r"^    (get|put|post|delete|patch|head|options):\s*$", line.rstrip("\n"))
        if m and cur is not None and cur.startswith("/_calls/"):
            rest = cur[len("/_calls/"):]
            prov, _, p = rest.partition("/")
            out[(prov, m.group(1).upper(), norm("/" + p))] = cur
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--service", required=True)
    ap.add_argument("--edges", required=True)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    got = read_clients(a.doc)
    rows = 0
    want = collections.defaultdict(list)
    with open(a.edges) as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["caller"] != a.service or r["provider"] == "unresolved":
                continue
            rows += 1
            want[(r["provider"], r["method"].upper(), norm(r["path_template"]))].append(
                r["interface"] + "." + r["method_name"])

    overloads = {k: v for k, v in want.items() if len(v) > 1}
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    print("S1 rows for %s: %d  (%d distinct keys, %d collapsed overloads)"
          % (a.service, rows, len(want), sum(len(v) - 1 for v in overloads.values())))
    print("extracted client endpoints: %d" % len(got))
    print("matched: %d   missing: %d   extra: %d"
          % (len(set(want) & set(got)), len(missing), len(extra)))
    if not a.quiet:
        for k in missing:
            print("  MISSING %-12s %-7s %-55s %s" % (k[0], k[1], k[2], ", ".join(want[k])))
        for k in extra:
            print("  EXTRA   %-12s %-7s %s" % (k[0], k[1], k[2]))
        if overloads:
            print("  collapsed overloads (one endpoint, several declared methods):")
            for k, v in sorted(overloads.items()):
                print("    %-12s %-7s %-45s %s" % (k[0], k[1], k[2], ", ".join(sorted(v))))
    return 1 if missing or extra else 0


sys.exit(main())
