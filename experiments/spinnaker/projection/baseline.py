#!/usr/bin/env python3
"""The baseline loop: every BOM's documents, then the consistency gate at every BOM.

    python3 baseline.py extract [--jobs 6] [--boms 1.38.0,1.30.0]
    python3 baseline.py lock                      # docs.lock from docs/
    python3 baseline.py verify-lock <bom>         # re-extract one BOM from scratch; regenerated docs.lock must equal the committed one
    python3 baseline.py gate [--presence none]    # normalise, graph, `gus consistent` at every BOM, triage/
    python3 baseline.py all [--jobs 6]            # extract, lock, gate

Extraction runs once per distinct pin, not once per BOM. corpus.lock shows that
the 450 (BOM, service) pins name 238 distinct service versions and that a
version always ships the same jar set, so a second BOM pinning gate 6.69.0 would
re-read byte-identical jars. Each pin is staged from the first BOM that pins it
(BOMs already staged locally first), extracted in three runs — the two presence
profiles and the client-only listing run (common.KEEP) — and every BOM's
document under docs/<run>/<bom>/ is a hard link to its pin's. The classpath is
passed as `classpath/<svc>-<version>`, a symlink under .work/, so the document
header does not name the BOM and a re-extraction from any BOM pinning that
version reproduces the same bytes; `verify-lock` is that test.
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (CORPUS_LOCK, DOCS, HERE, JAR, KEEP, MESH_TSV, PROFILES, RUNS, SERVICES, SPIN, STAGE, WORK,
                    bom_doc, boms, corpus_lock, java, parse_version, pin_doc, pins, sha256_file)

LOCK_PATH = os.path.join(HERE, 'docs.lock')
_log_lock = threading.Lock()


# --------------------------------------------------------------------------- extraction

def staged_complete(bom):
    """A BOM is usable in place only if every service's jar set is fully on the local disk."""
    entry = corpus_lock()['boms'][bom]['services']
    for s in SERVICES:
        d = os.path.join(SPIN, 'corpus', bom, s)
        if not os.path.isfile(os.path.join(d, 'bin', s)):
            return False
        lib = os.path.join(d, 'lib')
        if not os.path.isdir(lib) or len([n for n in os.listdir(lib) if not n.startswith('._')]) != entry[s]['jar_count']:
            return False
    return True


def plan():
    """[(source bom, [(svc, version), ...])] with every distinct pin exactly once."""
    staged = [b for b in boms() if os.path.isdir(os.path.join(SPIN, 'corpus', b)) and staged_complete(b)]
    order = sorted(staged, key=parse_version, reverse=True) + [b for b in boms() if b not in staged]
    source = {}
    for b in order:
        for s in SERVICES:
            source.setdefault((s, pins()[b][s]), b)
    per_bom = collections.OrderedDict((b, []) for b in order)
    for (s, v), b in source.items():
        per_bom[b].append((s, v))
    return [(b, sorted(ps)) for b, ps in per_bom.items() if ps], set(staged)


def done(run, s, v):
    return os.path.exists(pin_doc(run, s, v)) and os.path.exists(pin_doc(run, s, v, 'diag.json'))


def link_classpath(s, v, bom):
    d = os.path.join(WORK, 'classpath')
    os.makedirs(d, exist_ok=True)
    link = os.path.join(d, '%s-%s' % (s, v))
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(os.path.join(SPIN, 'corpus', bom, s), link)


def extract_cmd(run, s, v, out_yaml, out_diag):
    cmd = [java(), '-jar', JAR, '--classpath', 'classpath/%s-%s' % (s, v), '--service', s, '--version', v,
           '--mesh', MESH_TSV, '--out', out_yaml, '--diag', out_diag]
    if run == KEEP:
        cmd += ['--sides', 'client', '--presence', 'none', '--kork-rows', 'keep', '--indirect-fiat', 'keep']
    else:
        cmd += ['--presence', run, '--kork-rows', 'drop', '--indirect-fiat', 'drop']
    return cmd


def run_extraction(run, s, v, bom, out_yaml, out_diag, log_path):
    os.makedirs(os.path.dirname(out_yaml), exist_ok=True)
    tmp_y, tmp_d = out_yaml + '.tmp', out_diag + '.tmp'
    t0 = time.time()
    p = subprocess.run(extract_cmd(run, s, v, tmp_y, tmp_d), cwd=WORK, capture_output=True, text=True)
    dt = time.time() - t0
    last = (p.stderr.strip().splitlines() or [''])[-1]
    if p.returncode == 0:
        os.replace(tmp_y, out_yaml)
        os.replace(tmp_d, out_diag)
    with _log_lock:
        with open(log_path, 'a') as f:
            f.write('\t'.join([run, s, v, bom, str(p.returncode), '%.1f' % dt, last.replace('\t', ' ')]) + '\n')
    return run, s, v, p.returncode, dt, (last if p.returncode == 0 else p.stderr[-3000:])


def link_boms():
    missing = []
    for b in boms():
        for s in SERVICES:
            v = pins()[b][s]
            for r in RUNS:
                for ext in ('yaml', 'diag.json'):
                    src, dst = pin_doc(r, s, v, ext), bom_doc(r, b, s, ext)
                    if not os.path.exists(src):
                        missing.append(dst)
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.lexists(dst):
                        os.remove(dst)
                    os.link(src, dst)
    return missing


def do_extract(args):
    t_all = time.time()
    os.makedirs(DOCS, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    log_path = os.path.join(DOCS, 'extract-log.tsv')
    rows, staged = plan()
    only = set(args.boms.split(',')) if args.boms else None
    pool = ThreadPoolExecutor(max_workers=args.jobs)
    outstanding = []                      # [bom, futures, release, t_submit]
    stats = collections.Counter()
    seconds = collections.defaultdict(float)
    failures = []

    def reap(block=False):
        for item in list(outstanding):
            bom, futs, release, t_sub = item
            if block:
                wait(futs)
            if not all(f.done() for f in futs):
                continue
            nfail = 0
            for f in futs:
                run, s, v, rc, dt, tail = f.result()
                stats['runs'] += 1
                seconds[run] += dt
                if rc != 0:
                    nfail += 1
                    failures.append((bom, run, s, v, rc, tail))
            stats['failed'] += nfail
            if release:
                subprocess.run([sys.executable, STAGE, '--release', bom], capture_output=True, text=True)
            print('   %-8s %2d runs done, %d failed, %.0fs since submit%s' % (
                bom, len(futs), nfail, time.time() - t_sub, ', released' if release else ''), flush=True)
            outstanding.remove(item)

    for bom, pinlist in rows:
        if only and bom not in only:
            continue
        need = [(s, v) for s, v in pinlist if not all(done(r, s, v) for r in RUNS)]
        if not need:
            continue
        while len(outstanding) >= 2:      # at most two BOMs on the local disk waiting for their extractions
            time.sleep(1)
            reap()
        if bom not in staged:
            t0 = time.time()
            p = subprocess.run([sys.executable, STAGE, bom, '--services', ','.join(s for s, _ in need), '--full'],
                               capture_output=True, text=True)
            seconds['stage'] += time.time() - t0
            stats['staged services'] += len(need)
            last = (p.stdout.strip().splitlines() or [''])[-1]
            print('== %-8s staged %d services in %.0fs: %s' % (bom, len(need), time.time() - t0, last), flush=True)
            if p.returncode != 0:
                failures.append((bom, 'stage', ','.join(s for s, _ in need), '', p.returncode, p.stdout[-3000:] + p.stderr[-3000:]))
                print('!! staging %s failed; stopping before extracting from it' % bom, flush=True)
                break
        else:
            print('== %-8s already staged; %d pins' % (bom, len(need)), flush=True)
        for s, v in need:
            link_classpath(s, v, bom)
        futs = [pool.submit(run_extraction, r, s, v, bom, pin_doc(r, s, v), pin_doc(r, s, v, 'diag.json'), log_path)
                for s, v in need for r in RUNS if not done(r, s, v)]
        outstanding.append([bom, futs, bom not in staged, time.time()])
        reap()
    reap(block=True)
    pool.shutdown()
    missing = link_boms()
    summary = {'wall_seconds': round(time.time() - t_all, 1), 'runs': stats['runs'], 'failed': stats['failed'],
               'staged_services': stats['staged services'], 'seconds': {k: round(v, 1) for k, v in seconds.items()},
               'jobs': args.jobs, 'missing_bom_docs': len(missing),
               'failures': [list(map(str, f[:5])) + [f[5][-500:]] for f in failures]}
    with open(os.path.join(DOCS, 'extract-summary.json'), 'w') as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != 'failures'}, indent=1))
    for f in failures:
        print('!! %s %s %s@%s rc=%s\n%s' % (f[0], f[1], f[2], f[3], f[4], f[5][-1500:]))
    return 1 if failures or missing else 0


# --------------------------------------------------------------------------- docs.lock

COMMANDS = {
    'declared': 'java -jar extractor/target/gus-contract-extractor.jar --classpath classpath/<svc>-<version> --service <svc> '
                '--version <version> --mesh scout/S1/tools/mesh.tsv --presence declared --kork-rows drop --indirect-fiat drop',
    'none': 'java -jar extractor/target/gus-contract-extractor.jar --classpath classpath/<svc>-<version> --service <svc> '
            '--version <version> --mesh scout/S1/tools/mesh.tsv --presence none --kork-rows drop --indirect-fiat drop',
    KEEP: 'java -jar extractor/target/gus-contract-extractor.jar --classpath classpath/<svc>-<version> --service <svc> '
          '--version <version> --mesh scout/S1/tools/mesh.tsv --sides client --presence none --kork-rows keep --indirect-fiat keep',
}


def lock_data(overrides=None):
    """The manifest. `overrides` maps (run, bom, svc) to (yaml, diag) paths that replace docs/ for that entry."""
    cache = {}

    def sha(path):
        st = os.stat(path)
        k = (st.st_dev, st.st_ino)
        if k not in cache:
            cache[k] = sha256_file(path)
        return cache[k]

    docs = {}
    for r in RUNS:
        docs[r] = {}
        for b in boms():
            docs[r][b] = {}
            for s in SERVICES:
                y, d = (overrides or {}).get((r, b, s), (bom_doc(r, b, s), bom_doc(r, b, s, 'diag.json')))
                docs[r][b][s] = {'pin': '%s@%s' % (s, pins()[b][s]), 'yaml_sha256': sha(y), 'diag_sha256': sha(d)}
    return {
        'schema': 'g3-docs-lock/1',
        'note': 'sha256 of every extractor output under projection/docs/<run>/<bom>/<svc>.{yaml,diag.json}; '
                'the documents are not committed and regenerate from corpus.lock, the jar and mesh.tsv (baseline.py extract)',
        'inputs': {'extractor_jar_sha256': sha256_file(JAR), 'corpus_lock_sha256': sha256_file(CORPUS_LOCK),
                   'mesh_tsv_sha256': sha256_file(MESH_TSV)},
        'commands': COMMANDS,
        'docs': docs,
    }


def dumps(data):
    return json.dumps(data, indent=1, sort_keys=True) + '\n'


def do_lock(args):
    text = dumps(lock_data())
    with open(LOCK_PATH, 'w') as f:
        f.write(text)
    distinct = {e['yaml_sha256'] for r in PROFILES for b in lock_data_cached(text)['docs'][r].values() for e in b.values()}
    print('wrote %s (%d bytes; %d distinct profile documents)' % (LOCK_PATH, len(text), len(distinct)))
    return 0


def lock_data_cached(text):
    return json.loads(text)


def do_verify_lock(args):
    """Acceptance: a second run of one BOM regenerates docs.lock byte-identically."""
    bom = args.bom
    t0 = time.time()
    staged_here = False
    if not staged_complete(bom):
        p = subprocess.run([sys.executable, STAGE, bom, '--full'], capture_output=True, text=True)
        print((p.stdout.strip().splitlines() or [''])[-1], flush=True)
        if p.returncode != 0:
            print(p.stdout[-3000:], p.stderr[-3000:])
            return 2
        staged_here = True
    out = os.path.join(WORK, 'verify', bom)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    log_path = os.path.join(out, 'extract-log.tsv')
    for s in SERVICES:
        link_classpath(s, pins()[bom][s], bom)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run_extraction, r, s, pins()[bom][s], bom, os.path.join(out, r, s + '.yaml'),
                            os.path.join(out, r, s + '.diag.json'), log_path) for s in SERVICES for r in RUNS]
        results = [f.result() for f in futs]
    failed = [x for x in results if x[3] != 0]
    if failed:
        for x in failed:
            print('!! %s %s@%s rc=%d\n%s' % (x[0], x[1], x[2], x[3], x[5][-1500:]))
        return 2
    overrides = {(r, bom, s): (os.path.join(out, r, s + '.yaml'), os.path.join(out, r, s + '.diag.json'))
                 for s in SERVICES for r in RUNS}
    regenerated = dumps(lock_data(overrides))
    with open(LOCK_PATH) as f:
        committed = f.read()
    differing = []
    old = json.loads(committed)['docs']
    new = json.loads(regenerated)['docs']
    for r in RUNS:
        for s in SERVICES:
            if old[r][bom][s] != new[r][bom][s]:
                differing.append((r, s, old[r][bom][s], new[r][bom][s]))
    with open(os.path.join(out, 'docs.lock.regenerated'), 'w') as f:
        f.write(regenerated)
    identical = regenerated == committed
    report = {'bom': bom, 'identical': identical, 'documents_rerun': len(results), 'differing': differing,
              'wall_seconds': round(time.time() - t0, 1), 'staged_for_this_run': staged_here}
    print(json.dumps(report, indent=1))
    with open(os.path.join(HERE, 'docs.lock.verify.json'), 'w') as f:
        json.dump(report, f, indent=1)
        f.write('\n')
    if staged_here:
        subprocess.run([sys.executable, STAGE, '--release', bom], capture_output=True, text=True)
    return 0 if identical else 1


# --------------------------------------------------------------------------- gate

def do_gate(args):
    import gate  # normalise + graph + gus consistent + triage; kept in its own module
    return gate.run(args)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('extract')
    p.add_argument('--jobs', type=int, default=6)
    p.add_argument('--boms', help='comma-separated source BOMs to process (default: all)')
    sub.add_parser('lock')
    p = sub.add_parser('verify-lock')
    p.add_argument('bom')
    p.add_argument('--jobs', type=int, default=6)
    p = sub.add_parser('gate')
    p.add_argument('--presence', choices=PROFILES)
    p.add_argument('--boms')
    p.add_argument('--jobs', type=int, default=6)
    p = sub.add_parser('all')
    p.add_argument('--jobs', type=int, default=6)
    p.add_argument('--boms')
    p.add_argument('--presence', choices=PROFILES)
    a = ap.parse_args(argv)
    if a.cmd == 'extract':
        return do_extract(a)
    if a.cmd == 'lock':
        return do_lock(a)
    if a.cmd == 'verify-lock':
        return do_verify_lock(a)
    if a.cmd == 'gate':
        return do_gate(a)
    rc = do_extract(a)
    if rc:
        return rc
    do_lock(a)
    return do_gate(a)


if __name__ == '__main__':
    sys.exit(main())
