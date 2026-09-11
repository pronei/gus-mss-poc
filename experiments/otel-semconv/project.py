#!/usr/bin/env python3
"""Project the extracted semantic-conventions model onto a telemetry mesh.

Three services, versioned by the semantic-conventions release they implement:

  sdk ---> collector ---> backend

* sdk emits one payload per signal (an HTTP server span, a DB client span, a
  host resource, ...): an object whose properties are the attributes the
  convention defines for that signal at that version, typed from the
  registry. Every attribute carries `x-provides: <signal>/<identity>`.
* collector accepts each payload (open object, nothing required — an OTLP
  receiver validates nothing) and forwards it to the backend under the
  `/_calls/backend/...` outbound contract. It is a pass-through: it forwards
  every attribute of its own release and of the previous one, never drops
  any (all forwarded fields are required), and translates exactly the
  renames the release's schema file declares for that signal kind — the
  renamed attribute carries `x-alias: <previous name>` and the previous name
  is no longer forwarded. That is what a collector running the schema
  translation processor does; an undeclared rename passes through untouched.
* backend accepts each payload and marks the attributes its dashboards rely
  on with `x-requires: <signal>/<identity>`.

Two profiles decide what "required" means:

  spec  required := the convention's requirement level is `required`; the
        backend requires exactly those.
  full  every emitted attribute is required and the backend requires all of
        them — a stress profile that turns every declared rename into a chain
        the alias mechanism has to bridge.

Per consecutive release pair the projector writes a graph, seven upgrade
scenarios (every non-empty subset of the three services) and one rollout
step for `gus evolve`, plus the ground truth read directly from the corpus:
renames (declared in the schema file, implied by the model, or both),
withdrawals, additions, requirement-level and type changes. Identity keys
are `<signal>/<final name>`: an attribute keeps its key across the renames
the ground truth records for that signal.
"""
import argparse, collections, json, os, sys
import yaml

# (signal, kind, candidate group ids in the order they appeared in the corpus)
SIGNALS = [
    ("http.server", "span", ["http.server", "trace.http.server", "span.http.server"]),
    ("http.client", "span", ["http.client", "trace.http.client", "span.http.client"]),
    ("db.client", "span", ["db", "span.db.client"]),
    ("rpc.server", "span", ["rpc.server", "span.rpc.server", "span.rpc.call.server"]),
    ("rpc.client", "span", ["rpc.client", "span.rpc.client", "span.rpc.call.client"]),
    ("graphql.server", "span", ["graphql", "span.graphql.server"]),
    ("messaging", "span", ["messaging", "span.messaging"]),
    ("faas.server", "span", ["faas_span.in", "span.faas.server"]),
    ("service", "resource", ["service", "resource.service", "entity.service"]),
    ("host", "resource", ["host", "resource.host", "entity.host"]),
    ("container", "resource", ["container", "resource.container", "entity.container"]),
    ("k8s.pod", "resource", ["k8s.pod", "resource.k8s.pod", "entity.k8s.pod"]),
    ("k8s.node", "resource", ["k8s.node", "resource.k8s.node", "entity.k8s.node"]),
    ("k8s.deployment", "resource", ["k8s.deployment", "resource.k8s.deployment", "entity.k8s.deployment"]),
    ("k8s.namespace", "resource", ["k8s.namespace", "resource.k8s.namespace", "entity.k8s.namespace"]),
    ("k8s.cluster", "resource", ["k8s.cluster", "resource.k8s.cluster", "entity.k8s.cluster"]),
    ("cloud", "resource", ["cloud", "resource.cloud", "entity.cloud"]),
    ("process", "resource", ["process", "resource.process", "entity.process"]),
    ("os", "resource", ["os", "resource.os", "entity.os"]),
    ("device", "resource", ["device", "resource.device", "entity.device"]),
    ("deployment", "resource", ["deployment", "resource.deployment", "entity.deployment"]),
    ("browser", "resource", ["browser", "resource.browser", "entity.browser"]),
    ("faas", "resource", ["faas_resource", "resource.faas", "entity.faas"]),
    ("telemetry.sdk", "resource", ["telemetry", "telemetry.sdk", "resource.telemetry.sdk", "entity.telemetry.sdk"]),
    ("otel.scope", "resource", ["otel.scope", "resource.otel.scope", "entity.otel.scope"]),
    ("webengine", "resource", ["webengine_resource", "webengine", "resource.webengine", "entity.webengine"]),
]

APPLICABLE = {"span": {"all", "spans"}, "resource": {"all", "resources"}}
GROUP_TYPES = {"span": {"span"}, "resource": {"resource", "entity"}}

# Attribute groups the corpus documents alongside a span group without an
# `extends` link (the rendered table is the union of both). From 1.19.0 to
# 1.25.0 the HTTP method, status code and protocol attributes lived in
# trace.http.common next to trace.http.{server,client}.
COMPANIONS = {"http.server": ["trace.http.common"], "http.client": ["trace.http.common"]}
SERVICES = ["sdk", "collector", "backend"]


def vkey(v):
    return [int(x) for x in v.lstrip("v").split(".")]


def path_for(signal, kind):
    return f"/v1/traces/{signal}" if kind == "span" else f"/v1/resource/{signal}"


def schema_for(t):
    """OpenAPI schema for a normalised attribute type; None = not projectable."""
    if t is None or t == "template":
        return None
    base = {
        "string": {"type": "string"},
        "int": {"type": "integer", "format": "int64"},
        "double": {"type": "number", "format": "double"},
        "boolean": {"type": "boolean"},
        "enum:string": {"type": "string"},   # semconv enums are open sets of well-known values
        "enum:int": {"type": "integer", "format": "int64"},
        "any": {},
        "unknown": {},
    }
    if t.endswith("[]"):
        inner = base.get(t[:-2])
        return {"type": "array", "items": inner} if inner is not None else None
    return base.get(t)


class Corpus:
    def __init__(self, extracted):
        self.dir = extracted
        self.versions = json.load(open(os.path.join(extracted, "versions.json")))
        self.docs = {v: json.load(open(os.path.join(extracted, f"{v}.json"))) for v in self.versions}
        self.renames = json.load(open(os.path.join(extracted, "renames.json")))
        self.canon = {}  # signal -> {name: final name}; filled from the ground truth

    def group_id(self, v, kind, cands):
        gs = self.docs[v]["groups"]
        for c in cands:
            if c in gs and gs[c]["type"] in GROUP_TYPES[kind]:
                return c
        return None

    def attrs(self, v, gid, companions=()):
        """{name: (level, type)} for the projectable attributes of a group.

        Companion groups contribute the attributes the group itself does not
        declare; the group's own levels win where both declare an attribute.
        """
        gs = self.docs[v]["groups"]
        reg = self.docs[v]["registry"]
        merged = {}
        for c in companions:
            if c in gs:
                merged.update(gs[c]["attributes"])
        merged.update(gs[gid]["attributes"])
        out = {}
        for fq, lvl in merged.items():
            t = (reg.get(fq) or {}).get("type")
            if schema_for(t) is None:
                continue
            out[fq] = (lvl, t)
        return out

    def declared(self, v):
        """Declared attribute renames introduced by release v: [(from, to, section)]."""
        return [(e["from"], e["to"], e["section"]) for e in self.renames.get(v, []) if e["kind"] == "attribute"]

    def model_rename(self, v, old):
        """The new name the model's deprecation entry for `old` points at (release v)."""
        return (self.docs[v]["registry"].get(old) or {}).get("renamed_to")

    def set_canonical(self, signal, pairs):
        """Key attributes of a signal by the last name in their rename chain.

        `pairs` are the (from, to) renames the ground truth records for the
        signal, in release order; each target is claimed by one source.
        """
        fwd = {}
        for a, b in pairs:
            fwd[a] = b

        def follow(a):
            seen = {a}
            while a in fwd and fwd[a] not in seen:
                a = fwd[a]
                seen.add(a)
            return a
        self.canon[signal] = {a: follow(a) for a in fwd}

    def key(self, signal, name):
        return f"{signal}/{self.canon.get(signal, {}).get(name, name)}"


def build_object(attrs, required, provides=None, requires=None, alias=None):
    props = {}
    for name in sorted(attrs):
        _, t = attrs[name]
        s = dict(schema_for(t))
        if provides and name in provides:
            s["x-provides"] = provides[name]
        if requires and name in requires:
            s["x-requires"] = requires[name]
        if alias and name in alias:
            s["x-alias"] = alias[name]
        props[name] = s
    obj = {"type": "object", "properties": props, "additionalProperties": True}
    req = sorted(n for n in required if n in attrs)
    if req:
        obj["required"] = req
    return obj


def operation(body, client=False):
    op = {}
    if client:
        op["x-role"] = "client"
    op["requestBody"] = {"required": True, "content": {"application/json": {"schema": body}}}
    op["responses"] = {"200": {"description": "accepted", "content": {"application/json": {
        "schema": {"type": "object", "additionalProperties": True}}}}}
    return op


def dump_yaml(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(obj, f, sort_keys=False, default_flow_style=False, width=100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extracted", default="extracted")
    ap.add_argument("--out", default="generated")
    args = ap.parse_args()

    corpus = Corpus(args.extracted)
    versions = corpus.versions
    print(f"{len(versions)} releases: {versions[0]} .. {versions[-1]}")

    # Signal coverage: which group realises each signal at each release.
    coverage = {}
    for signal, kind, cands in SIGNALS:
        coverage[signal] = {v: corpus.group_id(v, kind, cands) for v in versions}
    full = [s for s, _, _ in SIGNALS if all(coverage[s].values())]
    partial = [s for s, _, _ in SIGNALS if s not in full]
    for s in partial:
        missing = [v for v in versions if not coverage[s][v]]
        print(f"  partial coverage: {s} absent at {len(missing)} releases ({missing[0]}..{missing[-1]})")
    print(f"  {len(full)} signals cover every release; {len(partial)} are partial (empty payloads where a release lacks them)")

    ground_truth = {"versions": versions, "signals": {s: {"kind": k, "groups": coverage[s]} for s, k, _ in SIGNALS}, "steps": []}
    stats = collections.Counter()

    # --- ground truth per step per signal (profile-independent) ---
    for i in range(1, len(versions)):
        a, b = versions[i - 1], versions[i]
        declared = corpus.declared(b)
        entry = {"step": f"{i:02d}", "from": a, "to": b, "signals": {}}
        for signal, kind, _ in SIGNALS:
            ga, gb = coverage[signal][a], coverage[signal][b]
            if not ga and not gb:
                continue
            A = corpus.attrs(a, ga, COMPANIONS.get(signal, ())) if ga else {}
            B = corpus.attrs(b, gb, COMPANIONS.get(signal, ())) if gb else {}
            gone, new = set(A) - set(B), set(B) - set(A)
            renamed, withdrawn = [], []
            for old in sorted(gone):
                decl = [(t, sec) for (f, t, sec) in declared if f == old and t in new]
                model_to = corpus.model_rename(b, old)
                target = decl[0][0] if decl else (model_to if model_to in new else None)
                if target is None:
                    withdrawn.append({"name": old, "level": A[old][0], "model_renamed_to": model_to})
                    continue
                sections = sorted({sec for (t, sec) in decl if t == target})
                renamed.append({
                    "from": old, "to": target,
                    "declared_sections": sections,
                    "applicable": bool(set(sections) & APPLICABLE[kind]),
                    "model": model_to == target,
                    "level_from": A[old][0], "level_to": B[target][0],
                    "type_from": A[old][1], "type_to": B[target][1],
                })
            # One target is the rename of one source: a declared rename wins,
            # then the first model-implied one; the rest are withdrawals.
            claimed, kept = {}, []
            for r in sorted(renamed, key=lambda r: (not r["declared_sections"], r["from"])):
                if r["to"] in claimed:
                    withdrawn.append({"name": r["from"], "level": r["level_from"], "model_renamed_to": r["to"],
                                      "note": f"{r['to']} is already the rename of {claimed[r['to']]}"})
                    continue
                claimed[r["to"]] = r["from"]
                kept.append(r)
            renamed = sorted(kept, key=lambda r: r["from"])
            withdrawn.sort(key=lambda w: w["name"])
            targets = {r["to"] for r in renamed}
            added = [{"name": n, "level": B[n][0]} for n in sorted(new) if n not in targets]
            level_changed = [{"name": n, "from": A[n][0], "to": B[n][0]} for n in sorted(set(A) & set(B)) if A[n][0] != B[n][0]]
            type_changed = [{"name": n, "from": A[n][1], "to": B[n][1]} for n in sorted(set(A) & set(B))
                            if schema_for(A[n][1]) != schema_for(B[n][1])]
            entry["signals"][signal] = {
                "group_from": ga, "group_to": gb,
                "attrs_from": {n: A[n][0] for n in sorted(A)}, "attrs_to": {n: B[n][0] for n in sorted(B)},
                "renamed": renamed, "withdrawn": withdrawn, "added": added,
                "level_changed": level_changed, "type_changed": type_changed,
            }
            stats["renamed"] += len(renamed)
            stats["renamed (declared for this signal kind)"] += sum(r["applicable"] for r in renamed)
            stats["withdrawn"] += len(withdrawn)
            stats["added"] += len(added)
            stats["level_changed"] += len(level_changed)
            stats["type_changed"] += len(type_changed)
        ground_truth["steps"].append(entry)

    for signal, _, _ in SIGNALS:
        pairs = []
        for e in ground_truth["steps"]:
            for r in (e["signals"].get(signal) or {}).get("renamed", []):
                pairs.append((r["from"], r["to"]))
        corpus.set_canonical(signal, pairs)

    for profile in ("spec", "full"):
        out = os.path.join(args.out, profile)
        os.makedirs(out, exist_ok=True)

        # --- specs: one document per service per release ---
        for i, v in enumerate(versions):
            prev = versions[i - 1] if i > 0 else None
            docs = {svc: {"openapi": "3.0.0", "info": {"title": svc, "version": v, "description":
                          f"{svc} implementing OpenTelemetry semantic conventions {v} ({corpus.docs[v]['source']})"},
                          "paths": {}} for svc in SERVICES}
            for signal, kind, cands in SIGNALS:
                gid = coverage[signal][v]
                # A signal the release does not define is an empty payload: the
                # endpoint exists (one graph serves every release pair) and the
                # ledger sees the group enter or leave the model.
                attrs = corpus.attrs(v, gid, COMPANIONS.get(signal, ())) if gid else {}
                path = path_for(signal, kind)
                if profile == "spec":
                    required = {n for n, (lvl, _) in attrs.items() if lvl == "required"}
                else:
                    required = set(attrs)
                keys = {n: corpus.key(signal, n) for n in attrs}
                # Alias = the previous name of a renamed attribute, taken from the
                # release's own schema file, restricted to the sections a schema
                # translator would apply to this signal kind.
                alias = {}
                prev_attrs = corpus.attrs(prev, coverage[signal][prev], COMPANIONS.get(signal, ())) if prev and coverage[signal][prev] else {}
                for a, b, sec in corpus.declared(v):
                    if b in attrs and sec in APPLICABLE[kind]:
                        if b not in alias or a in prev_attrs:
                            alias[b] = a
                stats[f"{profile}: fields"] += len(attrs)
                stats[f"{profile}: aliases"] += len(alias)

                # The collector forwards its own release's attributes and the
                # previous release's, minus the names it translates.
                forwarded = dict(attrs)
                for n, (lvl, t) in prev_attrs.items():
                    if n not in forwarded and n not in alias.values():
                        forwarded[n] = (lvl, t)
                docs["sdk"]["paths"][path] = {"post": operation(build_object(attrs, required, provides=keys), client=True)}
                docs["collector"]["paths"][path] = {"post": operation(build_object(forwarded, set(), alias=alias))}
                docs["collector"]["paths"]["/_calls/backend" + path] = {"post": operation(
                    build_object(forwarded, set(forwarded), alias=alias), client=True)}
                docs["backend"]["paths"][path] = {"post": operation(
                    build_object(attrs, set(), requires={n: keys[n] for n in required}, alias=alias))}
            for svc in SERVICES:
                dump_yaml(docs[svc], os.path.join(out, "specs", svc, f"v{v}", "openapi.yaml"))

        # --- graphs, scenarios, steps ---
        def services_block(rel=""):  # spec paths are resolved relative to the graph file
            return {svc: {f"v{v}": f"{rel}specs/{svc}/v{v}/openapi.yaml" for v in versions} for svc in SERVICES}

        def edges_for(signals):
            es = []
            for signal, kind, _ in SIGNALS:
                if signal not in signals:
                    continue
                path = path_for(signal, kind)
                es.append({"name": f"sdk-collector/{signal}", "from": "sdk", "to": "collector", "method": "POST", "path": path})
                es.append({"name": f"collector-backend/{signal}", "from": "collector", "to": "backend", "method": "POST", "path": path})
            return es

        dump_yaml({"services": services_block(""), "edges": edges_for({s for s, _, _ in SIGNALS})},
                  os.path.join(out, "graph.yaml"))  # beside specs/: paths may not escape the graph directory

        for i in range(1, len(versions)):
            a, b = versions[i - 1], versions[i]
            step = f"{i:02d}"
            baseline = {svc: f"v{a}" for svc in SERVICES}
            batches = {"sdk": ["sdk"], "collector": ["collector"], "backend": ["backend"],
                       "sdk-collector": ["sdk", "collector"], "sdk-backend": ["sdk", "backend"],
                       "collector-backend": ["collector", "backend"], "all": SERVICES}
            for name, svcs in batches.items():
                dump_yaml({
                    "id": f"T{step}-{name}",
                    "name": f"{a} -> {b}: upgrade {'+'.join(svcs)}",
                    "description": f"Semantic conventions {a} -> {b}; {', '.join(svcs)} move to {b}, the rest stay at {a}.",
                    "baseline": baseline,
                    "upgrades": {svc: f"v{b}" for svc in svcs},
                }, os.path.join(out, "scenarios", step, f"{name}.yaml"))
            dump_yaml({
                "id": f"T{step}",
                "name": f"{a} -> {b}",
                "description": f"Rollout step: every service moves from semantic conventions {a} to {b}.",
                "baseline": baseline,
                "upgrades": {svc: f"v{b}" for svc in SERVICES},
            }, os.path.join(out, "steps", f"step-{step}.yaml"))

    json.dump(ground_truth, open(os.path.join(args.out, "ground_truth.json"), "w"), indent=1)
    json.dump({"full_coverage": full, "partial": partial, "coverage": coverage},
              open(os.path.join(args.out, "coverage.json"), "w"), indent=1)
    for k in sorted(stats):
        print(f"  {stats[k]:6d}  {k}")


if __name__ == "__main__":
    main()
