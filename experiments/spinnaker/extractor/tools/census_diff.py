#!/usr/bin/env python3
"""Acceptance 2: the extracted provider endpoint set against S2's census, on
(method, normalized path) under D3.

  census_diff.py --doc out/front50-2.41.0.yaml --service front50 \
                 --endpoints ../scout/S2/endpoints.tsv
"""
import argparse
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


def read_doc(path):
    """Paths, verbs and the x-method-any marker out of the emitted document."""
    import yaml
    doc = yaml.safe_load(open(path))
    out = {}
    anypaths = set()
    for p, item in (doc.get("paths") or {}).items():
        for verb, op in item.items():
            out.setdefault((verb.upper(), norm(p)), []).append(p)
            if op.get("x-method-any"):
                anypaths.add(norm(p))
    return out, anypaths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--service", required=True)
    ap.add_argument("--endpoints", required=True)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    got, anypaths = read_doc(a.doc)
    got_provider = {k: v for k, v in got.items() if not k[1].startswith("/_calls/")}

    want = {}
    with open(a.endpoints) as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["service"] != a.service:
                continue
            want.setdefault((r["method"].upper(), norm(r["path_template"])), []).append(r["controller"])

    # D3: a census row recorded under the pseudo-method ANY (a @RequestMapping
    # that declares no method, 23 rows mesh-wide) is registered by Spring for
    # every verb.  The document has to spell those out, so such a row matches
    # when the path is present and marked x-method-any, and the extra verbs it
    # produces are reported as an expansion rather than as a difference.
    expanded = set()
    matched_any = 0
    for k in list(want):
        if k[0] == "ANY" and k[1] in anypaths:
            del want[k]
            matched_any += 1
            for verb in ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"):
                expanded.add((verb, k[1]))
    missing = sorted(set(want) - set(got_provider))
    extra = sorted(set(got_provider) - set(want) - expanded)
    common = set(want) & set(got_provider)

    print("census: %d rows (%d distinct keys)" % (sum(len(v) for v in want.values()), len(want)))
    print("extracted: %d provider endpoints (%d distinct keys)" % (
        sum(len(v) for v in got_provider.values()), len(got_provider)))
    print("matched: %d   missing: %d   extra: %d%s"
          % (len(common), len(missing), len(extra),
             "   ANY rows expanded over 7 verbs: %d" % matched_any if matched_any else ""))
    if not a.quiet:
        if missing:
            print("\nMISSING (in S2's census, not extracted):")
            for k in missing:
                print("  %-7s %-60s  %s" % (k[0], k[1], ", ".join(sorted(set(want[k])))))
        if extra:
            print("\nEXTRA (extracted, not in S2's census):")
            for k in extra:
                print("  %-7s %s" % (k[0], k[1]))
    return 0 if not missing and not extra else 1


sys.exit(main())
