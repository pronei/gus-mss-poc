"""Run IBM's jsonsubschema over the pairs listed by the Go harness.

    python jss.py pairs.csv jss.csv [--timeout 60]

Each pair is checked in both directions in a child process with a timeout;
a pair that times out or raises is recorded as unknown with the reason.
Iglu metadata ($schema pointing at the self-describing meta-schema, self)
is stripped and the draft-04 dialect declared, which is what the tool
supports.
"""
import csv, json, multiprocessing as mp, sys, time

DRAFT4 = "http://json-schema.org/draft-04/schema#"

def load(path):
    with open(path) as f:
        s = json.load(f)
    s.pop("self", None)
    s["$schema"] = DRAFT4
    return s

def worker(old_path, new_path, q):
    from jsonsubschema import isSubschema
    try:
        old, new = load(old_path), load(new_path)
        q.put(("ok", isSubschema(old, new), isSubschema(new, old)))
    except Exception as e:  # noqa: BLE001 - we want the reason, whatever it is
        q.put(("error", type(e).__name__ + ": " + str(e)[:160], None))

def check(old_path, new_path, timeout):
    q = mp.Queue()
    p = mp.Process(target=worker, args=(old_path, new_path, q))
    t0 = time.time(); p.start(); p.join(timeout)
    if p.is_alive():
        p.terminate(); p.join()
        return "unknown", "timeout", "timeout", time.time() - t0
    kind, a, b = q.get() if not q.empty() else ("error", "no result", None)
    dt = time.time() - t0
    if kind == "ok":
        return "ok", str(a), str(b), dt
    return "unknown", a, a, dt

def main():
    src, dst = sys.argv[1], sys.argv[2]
    timeout = int(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 60
    rows = list(csv.DictReader(open(src)))
    with open(dst, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vendor", "name", "old", "new", "jss_status", "jss_old_sub_new", "jss_new_sub_old", "seconds"])
        for i, r in enumerate(rows, 1):
            status, a, b, dt = check(r["old_path"], r["new_path"], timeout)
            w.writerow([r["vendor"], r["name"], r["old"], r["new"], status, a, b, f"{dt:.1f}"])
            f.flush()
            print(f"[{i}/{len(rows)}] {r['vendor']}/{r['name']} {r['old']}->{r['new']}: {status} {a} {b} ({dt:.1f}s)", flush=True)

if __name__ == "__main__":
    main()
