#!/usr/bin/env python3
"""Compare the checker's verdicts and the ledger with the corpus ground truth.

Two comparisons:

1. Chains per scenario. An oracle re-derives, from the generated contracts
   alone, which identities must break at the target state of each batch
   under the intended chain semantics (source required and non-null; every
   hop forwards the field under its own name or an x-alias; the sink reads
   the delivered name; a demand with no provider is broken; chains already
   broken at the baseline are pre-existing). The oracle's broken set is
   compared with `gus check` and the safe subset `gus mss` returned is
   checked against the oracle (is it safe? is it as large as the largest
   oracle-safe subset?).

2. Ledger events against the ground truth. Each rename, requirement-level
   demotion/promotion, withdrawal and addition the corpus records should
   appear in the `gus evolve` ledger as a mutated / eroded / restored /
   withdrawn / born event at that step.
"""
import collections, glob, itertools, json, os, re, sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICES = ["sdk", "collector", "backend"]
BATCHES = {"sdk": ["sdk"], "collector": ["collector"], "backend": ["backend"],
           "sdk-collector": ["sdk", "collector"], "sdk-backend": ["sdk", "backend"],
           "collector-backend": ["collector", "backend"], "all": SERVICES}


def load_yaml(p):
    with open(p) as f:
        return yaml.safe_load(f)


class Contracts:
    """The generated OpenAPI documents of one profile, read back as contracts."""

    def __init__(self, gen):
        self.gen = gen
        self.cache = {}

    def spec(self, svc, ver):
        k = (svc, ver)
        if k not in self.cache:
            self.cache[k] = load_yaml(os.path.join(self.gen, "specs", svc, ver, "openapi.yaml"))
        return self.cache[k]

    @staticmethod
    def body(spec, path):
        op = spec["paths"].get(path)
        if not op:
            return None
        sch = op["post"]["requestBody"]["content"]["application/json"]["schema"]
        req = set(sch.get("required") or [])
        return {n: {"required": n in req, "provides": p.get("x-provides"), "requires": p.get("x-requires"),
                    "alias": p.get("x-alias"), "type": json.dumps({k: v for k, v in p.items() if not k.startswith("x-")}, sort_keys=True)}
                for n, p in sch["properties"].items()}


def simulate(contracts, paths, versions):
    """Oracle: {(key, provider svc, requirer svc): (ok, rule)} at one state."""
    sdk = contracts.spec("sdk", versions["sdk"])
    col = contracts.spec("collector", versions["collector"])
    be = contracts.spec("backend", versions["backend"])
    out = {}
    for path in paths:
        send = contracts.body(sdk, path) or {}
        fwd = contracts.body(col, "/_calls/backend" + path) or {}
        acc = contracts.body(be, path) or {}
        providers = collections.defaultdict(list)
        for n, p in send.items():
            if p["provides"]:
                providers[p["provides"]].append(n)
        for sink_name, p in acc.items():
            key = p["requires"]
            if not key:
                continue
            if key not in providers:
                out[(key, "", "backend")] = (False, "chain-no-provider")
                continue
            for src in providers[key]:
                cid = (key, "sdk", "backend")
                if not send[src]["required"]:
                    verdict = (False, "chain-weakened")
                else:
                    # collector hop: exact, case-normalized, then x-alias
                    hit = None
                    if src in fwd:
                        hit = src
                    else:
                        for n in fwd:
                            if n.lower() == src.lower():
                                hit = n
                                break
                        if hit is None:
                            for n, q in fwd.items():
                                if q["alias"] == src:
                                    hit = n
                                    break
                    if hit is None:
                        verdict = (False, "chain-field-missing")
                    elif not fwd[hit]["required"]:
                        verdict = (False, "chain-weakened")
                    elif not (hit.lower() == sink_name.lower() or p["alias"] == hit):
                        verdict = (False, "chain-field-missing")
                    elif send[src]["type"] != acc[sink_name]["type"]:
                        verdict = (False, "chain-type-mismatch")
                    else:
                        verdict = (True, "")
                # several providers for one key: the first failing one is what the checker reports
                if cid not in out or (out[cid][0] and not verdict[0]):
                    out[cid] = verdict
    return out


def expected_breaks(contracts, paths, base, batch):
    """Chains the checker should count against the batch (pre-existing excluded)."""
    baseline = simulate(contracts, paths, {s: base for s in SERVICES})
    target_versions = {s: (batch.get(s) or base) for s in SERVICES}
    target = simulate(contracts, paths, target_versions)
    broken = {}
    for cid, (ok, rule) in target.items():
        if ok:
            continue
        if cid in baseline and not baseline[cid][0]:
            continue  # pre-existing
        broken[cid] = rule
    return broken


def parse_mss(text):
    dec = re.search(r"^Decision: (YES|NO)", text, re.M)
    safe = re.search(r"^Safe subset: \{(.*)\}", text, re.M)
    posthoc = re.search(r"^Post-hoc verification of the safe subset: (PASS|FAIL)", text, re.M)
    excluded = re.findall(r"^  (\w+) v\S+→v\S+ — (.*)$", text, re.M)
    r = {"decision": dec.group(1) if dec else None, "posthoc": posthoc.group(1) if posthoc else None,
         "excluded": {svc: why for svc, why in excluded}}
    if r["decision"] == "YES":
        r["safe"] = None  # everything
    elif safe:
        r["safe"] = sorted(m.group(1) for m in re.finditer(r"(\w+) v\S+→v\S+", safe.group(1)))
    else:
        r["safe"] = []
    return r


def main():
    gt = json.load(open(os.path.join(HERE, "generated", "ground_truth.json")))
    versions = gt["versions"]
    report = []
    summary = {}

    profiles = [p for p in ("spec", "full") if os.path.exists(os.path.join(HERE, "results", p, "ledger.json"))]
    for profile in profiles:
        gen = os.path.join(HERE, "generated", profile)
        res = os.path.join(HERE, "results", profile)
        contracts = Contracts(gen)
        tallies = collections.Counter()
        rows = []
        disagreements = []
        for i in range(1, len(versions)):
            a, b = versions[i - 1], versions[i]
            step = f"{i:02d}"
            # Chains are scanned over every endpoint a service declares, not only
            # the graph's edges, so the oracle looks at every signal path either
            # release knows (a signal that appears or disappears at this step
            # produces unprovided demands, exactly as the checker sees them).
            paths = set()
            for svc in ("sdk", "backend"):
                for v in (a, b):
                    paths.update(p for p in contracts.spec(svc, f"v{v}")["paths"] if p.startswith("/v1/"))
            paths = sorted(paths)
            for name, svcs in BATCHES.items():
                batch = {s: f"v{b}" for s in svcs}
                exp = expected_breaks(contracts, paths, f"v{a}", batch)
                chk_path = os.path.join(res, step, f"{name}.check.json")
                mss_path = os.path.join(res, step, f"{name}.mss.txt")
                if not os.path.exists(chk_path) or not os.path.exists(mss_path):
                    continue
                try:
                    chk = json.load(open(chk_path))
                except json.JSONDecodeError:
                    chk = None
                err = open(chk_path.replace(".check.json", ".check.err")).read()
                if chk is None:
                    tallies["runs failed"] += 1
                    disagreements.append((step, name, "checker error", err.strip().splitlines()[-1:] if err.strip() else "no output"))
                    continue
                got = {}
                for cr in chk.get("Chains") or []:
                    if not cr["OK"]:
                        got[(cr["Key"], cr["Provider"]["Service"], cr["Requirer"]["Service"])] = cr["Rule"]
                edge_breaks = [e for e in chk.get("Edges") or [] if not e["OK"]]
                mss = parse_mss(open(mss_path).read())
                tallies["runs"] += 1
                tallies["chains expected broken"] += len(exp)
                tallies["chains reported broken"] += len(got)
                same_keys = set(exp) == set(got)
                same_rules = same_keys and all(exp[k] == got[k] for k in exp)
                tallies["scenarios: broken set agrees"] += same_keys
                tallies["scenarios: broken set and rules agree"] += same_rules
                tallies["decision NO"] += (chk["OK"] is False)
                tallies["edge (pair-relation) breaks"] += len(edge_breaks)
                if not same_rules:
                    only_exp = {k: v for k, v in exp.items() if k not in got}
                    only_got = {k: v for k, v in got.items() if k not in exp}
                    diff_rule = {k: (exp[k], got[k]) for k in exp if k in got and exp[k] != got[k]}
                    disagreements.append((step, name, f"{a}->{b}", {
                        "oracle only": sorted(f"{k[0]} [{v}]" for k, v in only_exp.items()),
                        "checker only": sorted(f"{k[0]} [{v}]" for k, v in only_got.items()),
                        "rule differs": sorted(f"{k[0]} oracle={v[0]} checker={v[1]}" for k, v in diff_rule.items())}))
                # safe subset check against the oracle
                if mss["decision"] == "NO":
                    safe = mss["safe"] or []
                    sub = {s: f"v{b}" for s in safe}
                    safe_ok = not expected_breaks(contracts, paths, f"v{a}", sub) if safe else True
                    best = 0
                    for r in range(len(svcs), 0, -1):
                        for combo in itertools.combinations(svcs, r):
                            if not expected_breaks(contracts, paths, f"v{a}", {s: f"v{b}" for s in combo}):
                                best = r
                                break
                        if best:
                            break
                    tallies["mss computed"] += 1
                    tallies["mss subset safe per oracle"] += safe_ok
                    tallies["mss subset maximal per oracle"] += (len(safe) == best)
                    tallies["post-hoc PASS"] += (mss["posthoc"] == "PASS")
                    rows.append((step, f"{a}->{b}", name, "NO", ",".join(safe) or "-", best, mss["posthoc"], safe_ok, sorted(set(got.values()))))
                else:
                    rows.append((step, f"{a}->{b}", name, "YES", "all", len(svcs), "-", True, []))
        summary[profile] = {"tallies": dict(tallies), "rows": rows, "disagreements": disagreements}

        # --- ledger vs ground truth ---
        ledger = json.load(open(os.path.join(res, "ledger.json")))
        events = collections.defaultdict(list)  # (step, key) -> [(kind, detail)]
        for key, h in ledger["identities"].items():
            for e in h["events"]:
                events[(e["step"], key)].append((e["kind"], e["detail"]))
        ltal = collections.Counter()
        misses = []
        canon_cache = {}

        def key_of(signal, name, step_entry):
            # identity keys as the projector wrote them: read from the sdk spec of the "to" release
            v = "v" + step_entry["to"]
            if (signal, v) not in canon_cache:
                spec = contracts.spec("sdk", v)
                kind = gt["signals"][signal]["kind"]
                path = f"/v1/traces/{signal}" if kind == "span" else f"/v1/resource/{signal}"
                body = Contracts.body(spec, path) or {}
                canon_cache[(signal, v)] = {n: p["provides"] for n, p in body.items()}
                vp = "v" + step_entry["from"]
                bodyp = Contracts.body(contracts.spec("sdk", vp), path) or {}
                canon_cache[(signal, v)].update({n: p["provides"] for n, p in bodyp.items() if n not in canon_cache[(signal, v)]})
            return canon_cache[(signal, v)].get(name)

        for entry in gt["steps"]:
            step = "T" + entry["step"]
            if step == "T01":
                continue  # the ledger starts at the first shipped state; it has no view of the first release pair
            for signal, d in entry["signals"].items():
                checks = []
                for r in d["renamed"]:
                    needle = f'"{r["from"]}" → "{r["to"]}"'
                    # a rename that also changes the requirement level is recorded as eroded/restored
                    checks.append(("renamed", r["from"], key_of(signal, r["to"], entry),
                                   lambda ks, needle=needle: any((k == "mutated" and needle in det) or k in ("eroded", "restored") for k, det in ks)))
                for w in d["withdrawn"]:
                    checks.append(("withdrawn", w["name"], key_of(signal, w["name"], entry), lambda ks: any(k == "withdrawn" for k, _ in ks)))
                for ad in d["added"]:
                    checks.append(("added", ad["name"], key_of(signal, ad["name"], entry), lambda ks: any(k == "born" for k, _ in ks)))
                if profile == "spec":
                    for c in d["level_changed"]:
                        if c["from"] == "required" and c["to"] != "required":
                            checks.append(("demoted", c["name"], key_of(signal, c["name"], entry), lambda ks: any(k == "eroded" for k, _ in ks)))
                        elif c["from"] != "required" and c["to"] == "required":
                            checks.append(("promoted", c["name"], key_of(signal, c["name"], entry), lambda ks: any(k == "restored" for k, _ in ks)))
                for kind, name, key, pred in checks:
                    ltal[f"{kind}: expected"] += 1
                    ks = events.get((step, key), [])
                    if key and pred(ks):
                        ltal[f"{kind}: found in ledger"] += 1
                    else:
                        misses.append((step, signal, kind, name, key, [k for k, _ in ks]))
        # ledger events the ground truth does not predict
        predicted = set()
        for entry in gt["steps"]:
            step = "T" + entry["step"]
            for signal, d in entry["signals"].items():
                for r in d["renamed"]:
                    predicted.add((step, key_of(signal, r["to"], entry), "mutated"))
                    if r["level_from"] != r["level_to"]:  # a rename with a level change is recorded as eroded/restored
                        predicted.add((step, key_of(signal, r["to"], entry), "eroded" if r["level_from"] == "required" else "restored"))
                for w in d["withdrawn"]:
                    predicted.add((step, key_of(signal, w["name"], entry), "withdrawn"))
                for ad in d["added"]:
                    predicted.add((step, key_of(signal, ad["name"], entry), "born"))
                for c in d["level_changed"]:
                    predicted.add((step, key_of(signal, c["name"], entry), "eroded" if c["from"] == "required" else "restored"))
        unpredicted = collections.Counter()
        unpredicted_examples = collections.defaultdict(list)
        for (step, key), ks in events.items():
            for kind, det in ks:
                if kind in ("demanded", "demand-dropped", "violated", "path-changed"):
                    continue
                if step == "T01":
                    continue  # the first step mints every identity; the ledger has no earlier state
                if (step, key, kind) not in predicted:
                    unpredicted[kind] += 1
                    if len(unpredicted_examples[kind]) < 4:
                        unpredicted_examples[kind].append((step, key, det[:90]))
        summary[profile]["ledger"] = {"tallies": dict(ltal), "misses": misses, "unpredicted": dict(unpredicted),
                                      "unpredicted_examples": dict(unpredicted_examples),
                                      "identities": len(ledger["identities"]), "steps": len(ledger["steps"])}

    # ---- write results/compare.txt ----
    lines = []
    for profile in profiles:
        s = summary[profile]
        lines.append(f"===== profile {profile} =====")
        for k in sorted(s["tallies"]):
            lines.append(f"  {s['tallies'][k]:6d}  {k}")
        lines.append("")
        lines.append("  ledger (%d identities, %d steps):" % (s["ledger"]["identities"], s["ledger"]["steps"]))
        for k in sorted(s["ledger"]["tallies"]):
            lines.append(f"  {s['ledger']['tallies'][k]:6d}  {k}")
        lines.append(f"  unpredicted ledger events by kind: {s['ledger']['unpredicted']}")
        for kind, exs in s["ledger"]["unpredicted_examples"].items():
            for ex in exs:
                lines.append(f"      {kind}: {ex}")
        if s["ledger"]["misses"]:
            lines.append("  ground-truth events missing from the ledger:")
            for m in s["ledger"]["misses"][:40]:
                lines.append(f"      {m}")
        lines.append("")
        if s["disagreements"]:
            lines.append("  oracle/checker disagreements:")
            for d in s["disagreements"][:40]:
                lines.append(f"      {d}")
        lines.append("")
        lines.append("  per scenario: step  releases  batch  decision  mss-safe  oracle-best-size  post-hoc  mss-safe-per-oracle  rules")
        for r in s["rows"]:
            if r[3] == "NO":
                lines.append("    " + "  ".join(str(x) for x in r))
        lines.append("")
    out = os.path.join(HERE, "results", "compare.txt")
    open(out, "w").write("\n".join(lines) + "\n")
    json.dump(summary, open(os.path.join(HERE, "results", "compare.json"), "w"), indent=1, default=str)
    print("\n".join(lines[:200]))


if __name__ == "__main__":
    main()
