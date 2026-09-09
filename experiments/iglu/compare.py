"""Merge the Go and jsonsubschema results and print the agreement tables.

    python compare.py pairs.csv jss.csv

Verdicts are normalized to true/false. Disagreements are classified by what
changed between the two schema files: refinement-only (keywords the GUS
grammar drops by design: bounds, lengths, patterns, item counts, format,
multipleOf, descriptions) or structural (anything else), so a structural
disagreement is a candidate false verdict to inspect by hand.
"""
import csv, json, sys
from collections import Counter, defaultdict

REFINEMENT = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
              "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
              "minProperties", "maxProperties", "format", "description", "title", "$schema", "self",
              "default", "examples", "example"}

def norm(v):
    return {"true": "true", "True": "true", "false": "false", "False": "false"}.get(v, v)

def structural_diff(a, b, path=""):
    """Return the set of keyword paths that differ outside the refinement set."""
    out = set()
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            if k in REFINEMENT:
                continue
            if k not in a or k not in b:
                out.add(path + "/" + k)
            else:
                out |= structural_diff(a[k], b[k], path + "/" + k)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.add(path + "[len]")
        for i, (x, y) in enumerate(zip(a, b)):
            out |= structural_diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.add(path)
    return out

def main():
    gus = {(r["vendor"], r["name"], r["old"], r["new"]): r for r in csv.DictReader(open(sys.argv[1]))}
    jss = {(r["vendor"], r["name"], r["old"], r["new"]): r for r in csv.DictReader(open(sys.argv[2]))}
    keys = [k for k in gus if k in jss]
    print(f"pairs: {len(gus)} from gus, {len(jss)} from jss, {len(keys)} joined")
    unknown = Counter(j["jss_old_sub_new"].split(":")[0] for j in jss.values() if j["jss_status"] != "ok")
    print("jsonsubschema undecided:", dict(unknown))
    for direction, gcol, jcol in (("old <: new (backward compatible)", "gus_old_sub_new", "jss_old_sub_new"),
                                  ("new <: old (forward compatible)", "gus_new_sub_old", "jss_new_sub_old")):
        table = Counter()
        dis = defaultdict(list)
        for k in keys:
            g, j = gus[k], jss[k]
            if g["error"]:
                table[("gus-error", "-")] += 1; continue
            if j["jss_status"] != "ok":
                table[(norm(g[gcol]), "undecided")] += 1; continue
            gv, jv = norm(g[gcol]), norm(j[jcol])
            table[(gv, jv)] += 1
            if gv != jv:
                old, new = json.load(open(g["old_path"])), json.load(open(g["new_path"]))
                sd = structural_diff(old, new)
                kind = "structural" if sd else "refinement-only"
                dis[(gv, jv, kind)].append((k, g[gcol + "_rules"] or "-", sorted(sd)[:3]))
        print(f"\n== {direction} ==")
        for (gv, jv), n in sorted(table.items()):
            print(f"  gus={gv:9} jss={jv:9} {n}")
        decided = sum(n for (gv, jv), n in table.items() if jv in ("true", "false") and gv in ("true", "false"))
        agree = table[("true", "true")] + table[("false", "false")]
        if decided:
            print(f"  agreement on decided pairs: {agree}/{decided} = {agree/decided:.1%}")
            print(f"  gus break disputed by jss (gus=false, jss=true): {table[('false','true')]}")
            print(f"  gus pass disputed by jss (gus=true, jss=false): {table[('true','false')]}")
        for (gv, jv, kind), items in sorted(dis.items(), key=lambda x: -len(x[1])):
            print(f"  disagreements gus={gv} jss={jv} [{kind}]: {len(items)}")
            for (k, rules, sd) in items[: (12 if kind == "structural" else 3)]:
                print(f"     {k[0]}/{k[1]} {k[2]}->{k[3]}  gus rules={rules}  structural diff={sd}")
    print("\n== SchemaVer bump vs old <: new (decided pairs) ==")
    t = Counter()
    for k in keys:
        g, j = gus[k], jss[k]
        if g["error"] or j["jss_status"] != "ok":
            continue
        t[(g["bump"], norm(g["gus_old_sub_new"]), norm(j["jss_old_sub_new"]))] += 1
    for (b, gv, jv), n in sorted(t.items()):
        print(f"  {b:9} gus={gv:6} jss={jv:6} {n}")

if __name__ == "__main__":
    main()
