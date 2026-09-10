"""Join, per consecutive commit pair, three verdicts on the same change:
the authors' commit message, the checker on the OpenAPI projection, and the
wire-level comparator (protobuf's documented compatibility rules by field
number). Writes results/summary.md and prints it.

    python summarize.py
"""
import os, re, sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
GEN, RES, HIST = [os.path.join(ROOT, d) for d in ("generated", "results", "history")]

def read(p):
    return open(p).read() if os.path.exists(p) else ""

index = {}
for line in read(os.path.join(HIST, "index.tsv")).splitlines():
    f = line.split("\t")
    if len(f) >= 4:
        index[f[0][:2]] = (f[2][:7], f[3])

changes = {}
cur = None
for line in read(os.path.join(GEN, "changes.txt")).splitlines():
    if re.match(r"^\d\d-\d\d ", line):
        cur = line[:5]; changes.setdefault(cur, [])
    elif line.strip() and cur:
        changes[cur].append(line.strip())

rows = []
for fn in sorted(os.listdir(os.path.join(GEN, "scenarios"))):
    pair = fn[:-5]
    a, b = pair.split("-")
    sha, msg = index[b]
    out = read(os.path.join(RES, pair + ".txt"))
    decision = (re.search(r"^Decision: (\w+)", out, re.M) or [None, "error"])[1] if "Decision" in out else "error: " + out.strip().splitlines()[0][:60]
    rules = sorted(set(re.findall(r"rule: (\S+)", out)))
    safe = (re.search(r"^Safe subset: (.*)$", out, re.M) or [None, ""])[1]
    edges_broken = len(re.findall(r"^Edge .* — BREAK", out, re.M))
    wire = read(os.path.join(GEN, "wire", pair + ".txt"))
    wire_n = len(re.findall(r"^WIRE ", wire, re.M))
    sem_n = len(re.findall(r"^SEMANTIC ", wire, re.M))
    endpoint_notes = [c for c in changes.get(pair, []) if "endpoint" in c or "service" in c]
    upgrades = re.search(r"upgrades=\[(.*?)\]", read(os.path.join(GEN, "changes.txt")).split(pair, 1)[1].splitlines()[0]).group(1)
    authors = "breaking" if "breaking" in msg.lower() else ("no-op" if not upgrades and not endpoint_notes else "unlabelled")
    # agreement classification
    wire_break = wire_n > 0
    gus_break = decision == "NO"
    channel = bool(endpoint_notes)
    if not wire_break and not gus_break:
        agree = "agree: no wire break" if sem_n == 0 else "agree on wire; semantic-only change both miss"
    elif wire_break and gus_break:
        agree = "agree: break"
    elif wire_break and channel and not gus_break:
        agree = "agree via endpoint channel"
    elif wire_break and not gus_break:
        agree = "MISS: wire break, projection passes"
    else:
        agree = "projection break, wire passes"
    rows.append(dict(pair=pair, sha=sha, msg=msg, authors=authors, upgrades=upgrades or "-", decision=decision,
                     rules=", ".join(rules) or "-", edges=edges_broken, safe=safe, wire=wire_n, sem=sem_n,
                     notes="; ".join(endpoint_notes) or "-", agree=agree))

lines = ["| pair | commit | authors | upgraded | checker (projection) | rules | wire | semantic | outside the per-edge model | agreement |",
         "|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    lines.append(f"| {r['pair']} | `{r['sha']}` {r['msg'][:48]} | {r['authors']} | {r['upgrades']} | {r['decision']} | {r['rules']} | {r['wire']} | {r['sem']} | {r['notes'][:90]} | {r['agree']} |")
tally = Counter(r["agree"] for r in rows)
lines += ["", "Agreement tally: " + "; ".join(f"{k}: {v}" for k, v in sorted(tally.items()))]
text = "\n".join(lines) + "\n"
os.makedirs(RES, exist_ok=True)
open(os.path.join(RES, "summary.md"), "w").write(text)
print(text)
