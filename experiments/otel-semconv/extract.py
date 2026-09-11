#!/usr/bin/env python3
"""Extract the OpenTelemetry semantic-conventions attribute model per version.

For every git tag of the semantic-conventions repository (and, for the
pre-split versions, of the specification repository whose
`semantic_conventions/` directory held the same model), read the YAML
groups, resolve each group's attribute set (prefix, extends, ref) with the
effective requirement level, normalise attribute types, and write one JSON
document per version to --out. The declared rename maps of `schemas/<v>`
are written to --out/renames.json.

Nothing here knows about the checker; it is a faithful reading of the corpus.
"""
import argparse, io, json, os, re, subprocess, sys, tarfile
import yaml

LEVELS = ("required", "conditionally_required", "recommended", "opt_in")


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True).stdout


def vkey(v):
    return [int(x) for x in v.lstrip("v").split(".")]


def read_tree(repo, tag, subdir):
    """Return {path: text} for every YAML file under subdir at tag."""
    data = sh(["git", "archive", "--format=tar", tag, subdir], repo)
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.endswith((".yaml", ".yml")):
                out[m.name] = tf.extractfile(m).read().decode("utf-8")
    return out


def norm_type(t):
    """Normalise an attribute type to a small vocabulary.

    Returns (kind, members, open) where kind is one of string, int, double,
    boolean, string[], int[], double[], boolean[], template, any, enum:string,
    enum:int.
    """
    if isinstance(t, str):
        if t.startswith("template["):
            return "template", None, None
        return t, None, None
    if isinstance(t, dict) and "members" in t:
        members = [m.get("value") for m in t.get("members") or []]
        base = "int" if members and all(isinstance(v, int) and not isinstance(v, bool) for v in members) else "string"
        allow = t.get("allow_custom_values")
        return f"enum:{base}", members, (True if allow is None else bool(allow))
    return "unknown", None, None


RENAMED_RE = re.compile(r"(?:Replaced by|Renamed to|Use)\s+`([a-zA-Z0-9_.]+)`")


def deprecation(d):
    """Return (text, renamed_to) for a deprecated field in either format."""
    if d is None:
        return None, None
    if isinstance(d, dict):
        return (d.get("reason") or "deprecated"), d.get("renamed_to")
    text = str(d).strip()
    names = RENAMED_RE.findall(text)
    return text, (names[0] if len(names) == 1 else None)


def level_of(entry):
    rl = entry.get("requirement_level")
    if rl is None:
        return None
    if isinstance(rl, str):
        return rl
    if isinstance(rl, dict):
        for k in rl:
            return k
    return None


def load_groups(files):
    """Read every group in the model.

    Two file formats coexist: the original `groups:` list (an id, a type, an
    optional prefix/extends, and attributes defined inline or by ref) and,
    from 1.44.0, weaver's `file_format: definition/2`, where registry
    attributes sit in an `attributes:` list keyed by `key`, reusable sets in
    `attribute_groups:`, and spans in `spans:` (keyed by `type`, which plays
    the role the old `span.<name>` id played). Both are folded into the
    original shape so the rest of the pipeline sees one model. Refinements
    and metrics are not projected and are skipped.
    """
    groups = {}
    for path, text in sorted(files.items()):
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:  # a handful of old files have odd anchors
            print(f"warn: {path}: {e}", file=sys.stderr)
            continue
        if str(doc.get("file_format", "")).startswith("definition/2"):
            if doc.get("attributes"):
                attrs = []
                for a in doc["attributes"]:
                    a = dict(a)
                    a["id"] = a.pop("key")
                    attrs.append(a)
                gid = "registry.v2." + path
                groups[gid] = {"id": gid, "type": "attribute_group", "attributes": attrs, "_file": path}
            for g in doc.get("attribute_groups") or []:
                if "id" not in g:
                    continue
                g = dict(g)
                g["type"] = "attribute_group"
                g["_file"] = path
                groups[g["id"]] = g
            for s in doc.get("spans") or []:
                if "type" not in s:
                    continue
                g = dict(s)
                g["id"] = "span." + s["type"]
                g["type"] = "span"
                g["_file"] = path
                groups[g["id"]] = g
            continue
        for g in doc.get("groups") or []:
            if "id" not in g:
                continue
            g = dict(g)
            g.setdefault("type", "span")  # the old format defaulted to span
            g["_file"] = path
            groups[g["id"]] = g
    return groups


def build_registry(groups):
    """Every attribute defined inline (id + optional group prefix)."""
    reg = {}
    for gid, g in groups.items():
        prefix = g.get("prefix")
        for a in g.get("attributes") or []:
            if "id" not in a:
                continue
            fq = f"{prefix}.{a['id']}" if prefix else a["id"]
            kind, members, open_ = norm_type(a.get("type"))
            dep_text, renamed_to = deprecation(a.get("deprecated"))
            reg[fq] = {
                "type": kind,
                "members": members,
                "enum_open": open_,
                "stability": a.get("stability"),
                "deprecated": dep_text,
                "renamed_to": renamed_to,
                "level": level_of(a),
                "defined_in": gid,
            }
    return reg


def resolve_group(gid, groups, reg, seen=None):
    """Effective attribute set of a group: {fq: level} following extends."""
    seen = seen or set()
    if gid in seen or gid not in groups:
        return {}
    seen.add(gid)
    g = groups[gid]
    acc = {}
    if g.get("extends"):
        acc.update(resolve_group(g["extends"], groups, reg, seen))
    prefix = g.get("prefix")
    for a in g.get("attributes") or []:
        if "ref_group" in a:  # definition/2: inline another group's attributes
            for fq, lvl in resolve_group(a["ref_group"], groups, reg, set(seen)).items():
                if fq in acc and lvl is None:
                    continue
                acc[fq] = lvl
            continue
        if "ref" in a:
            fq = a["ref"]
        elif "id" in a:
            fq = f"{prefix}.{a['id']}" if prefix else a["id"]
        else:
            continue
        lvl = level_of(a)
        if fq in acc and lvl is None:
            continue  # inherited level stands
        acc[fq] = lvl
    return acc


def finalize_levels(attrs, reg):
    out = {}
    for fq, lvl in attrs.items():
        if lvl is None:
            lvl = (reg.get(fq) or {}).get("level") or "recommended"
        if lvl not in LEVELS:
            lvl = "recommended"
        out[fq] = lvl
    return out


def extract_version(repo, tag, subdir, version, source):
    files = read_tree(repo, tag, subdir)
    groups = load_groups(files)
    reg = build_registry(groups)
    resolved = {}
    for gid, g in groups.items():
        attrs = finalize_levels(resolve_group(gid, groups, reg), reg)
        resolved[gid] = {
            "type": g.get("type"),
            "extends": g.get("extends"),
            "stability": g.get("stability"),
            "attributes": attrs,
        }
    sha = sh(["git", "rev-list", "-n", "1", tag], repo).decode().strip()
    return {
        "version": version,
        "tag": tag,
        "source": f"{source}@{sha[:12]}",
        "registry": reg,
        "groups": resolved,
    }


def extract_renames(semconv):
    out = {}
    sdir = os.path.join(semconv, "schemas")
    for v in sorted(os.listdir(sdir), key=vkey):
        doc = yaml.safe_load(open(os.path.join(sdir, v))) or {}
        body = (doc.get("versions") or {}).get(v) or {}
        entries = []
        for sec in ("all", "resources", "spans", "span_events", "logs", "metrics"):
            for ch in (body.get(sec) or {}).get("changes") or []:
                amap = (ch.get("rename_attributes") or {}).get("attribute_map") or {}
                for a, b in amap.items():
                    entries.append({"from": a, "to": b, "section": sec, "kind": "attribute"})
                for a, b in (ch.get("rename_metrics") or {}).items():
                    entries.append({"from": a, "to": b, "section": sec, "kind": "metric"})
        out[v] = entries
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semconv", required=True, help="checkout of open-telemetry/semantic-conventions")
    ap.add_argument("--spec", help="checkout of open-telemetry/opentelemetry-specification (pre-split model)")
    ap.add_argument("--spec-tags", default="v1.16.0,v1.17.0,v1.18.0,v1.19.0,v1.20.0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    versions = []
    if args.spec:
        for tag in args.spec_tags.split(","):
            tag = tag.strip()
            if not tag:
                continue
            v = tag.lstrip("v")
            doc = extract_version(args.spec, tag, "semantic_conventions", v, "opentelemetry-specification")
            json.dump(doc, open(os.path.join(args.out, f"{v}.json"), "w"), indent=1, sort_keys=True)
            versions.append(v)
            print(f"{v}: {len(doc['groups'])} groups, {len(doc['registry'])} attributes (spec repo)")
    tags = sh(["git", "tag", "--sort=v:refname"], args.semconv).decode().split()
    for tag in tags:
        if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            continue
        v = tag.lstrip("v")
        doc = extract_version(args.semconv, tag, "model", v, "semantic-conventions")
        json.dump(doc, open(os.path.join(args.out, f"{v}.json"), "w"), indent=1, sort_keys=True)
        versions.append(v)
        print(f"{v}: {len(doc['groups'])} groups, {len(doc['registry'])} attributes")
    json.dump(extract_renames(args.semconv), open(os.path.join(args.out, "renames.json"), "w"), indent=1)
    json.dump(sorted(versions, key=vkey), open(os.path.join(args.out, "versions.json"), "w"))


if __name__ == "__main__":
    main()
