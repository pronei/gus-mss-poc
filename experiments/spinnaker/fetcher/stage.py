#!/usr/bin/env python3
"""Move one BOM at a time from the corpus of record to the local disk for analysis.

The corpus lives wherever there is room for it — an external volume, typically —
and analysis wants it on the fast local disk, one BOM at a time:

    python3 stage.py --list                     # what exists, what is staged, free space
    python3 stage.py 1.31.0                     # copy that BOM local and verify it
    python3 stage.py 1.31.0 --services gate     # one service of it
    python3 stage.py 1.31.0 --full              # verify by re-hashing, not by size
    python3 stage.py --release 1.31.0           # delete the local copy again
    python3 stage.py --release --keep 1         # drop every staged BOM but the newest

Nothing is ever deleted from the corpus of record; `--release` only removes the
local copy, which `corpus.lock` can always reproduce.  The `._*` sidecars macOS
leaves on exFAT are skipped, so the staged tree holds jars only.
"""
import argparse, hashlib, os, shutil, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bom as bom_mod
import lock as lock_mod

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_STORE = os.environ.get('GUS_CORPUS_STORE', '/Volumes/WDGDM/gus-spinnaker-corpus')
DEFAULT_LOCAL = os.path.join(ROOT, 'corpus')
DEFAULT_LOCK = os.path.join(ROOT, 'corpus.lock')


def human(n):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if n < 1024 or unit == 'TiB':
            return '%.1f %s' % (n, unit)
        n /= 1024.0


def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def tree_bytes(path):
    total = 0
    for dirpath, _d, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while (c := f.read(1 << 20)):
            h.update(c)
    return 'sha256:' + h.hexdigest()


def copy_service(src, dst, entry, full):
    """Copy bin/<svc> and the jars the lock names; verify each one."""
    svc = os.path.basename(dst)
    os.makedirs(os.path.join(dst, 'bin'), exist_ok=True)
    os.makedirs(os.path.join(dst, 'lib'), exist_ok=True)
    copied = bytes_ = 0
    problems = []
    pairs = [(os.path.join(src, 'bin', svc), os.path.join(dst, 'bin', svc), None)]
    for name, meta in sorted(entry['jars'].items()):
        pairs.append((os.path.join(src, 'lib', name), os.path.join(dst, 'lib', name), meta))
    for s, d, meta in pairs:
        base = os.path.basename(s)
        if base.startswith('._'):
            continue
        if not os.path.exists(s):
            problems.append('missing in the store: %s' % base)
            continue
        shutil.copyfile(s, d)             # bytes only: no xattrs, no permission bits
        size = os.path.getsize(d)
        bytes_ += size
        copied += 1
        want = (meta or entry['start_script'])
        if want.get('size') is not None and size != want['size']:
            problems.append('%s: %d bytes, lock says %d' % (base, size, want['size']))
        elif full and want.get('sha256') and sha256(d) != want['sha256']:
            problems.append('%s: sha256 differs from the lock' % base)
    return copied, bytes_, problems


def do_stage(a, lk):
    total_problems = 0
    for bomv in a.boms:
        b = lk['boms'].get(bomv)
        if not b:
            print('!! %s is not in %s' % (bomv, a.lock))
            total_problems += 1
            continue
        services = sorted(b['services'])
        if a.services:
            want = set(a.services.split(','))
            services = [s for s in services if s in want]
        need = sum(b['services'][s]['jar_bytes'] + b['services'][s]['start_script']['size']
                   for s in services)
        have = free_bytes(a.to if os.path.exists(a.to) else ROOT)
        print('== stage %s: %d services, %s (local free: %s)'
              % (bomv, len(services), human(need), human(have)))
        if need > have - (1 << 30):
            print('!! not enough room on the local disk for %s — release a staged BOM first '
                  '(python3 stage.py --release --keep 1)' % bomv)
            return 2
        for svc in services:
            src = os.path.join(a.store, bomv, svc)
            dst = os.path.join(a.to, bomv, svc)
            if not os.path.isdir(src):
                print('   %-12s !! not in the store at %s' % (svc, src))
                total_problems += 1
                continue
            t0 = time.time()
            n, size, problems = copy_service(src, dst, b['services'][svc], a.full)
            total_problems += len(problems)
            print('   %-12s %4d files %9s  %5.1fs%s'
                  % (svc, n, human(size), time.time() - t0,
                     '' if not problems else '  !! %d problems: %s' % (len(problems), problems[:2])))
    print('-- staged under %s; %d problems' % (a.to, total_problems))
    return 1 if total_problems else 0


def do_release(a, lk):
    staged = sorted((d for d in os.listdir(a.to) if os.path.isdir(os.path.join(a.to, d))
                     and not d.startswith('.')), key=bom_mod.parse_version)
    drop = a.boms
    if a.keep is not None:
        drop = staged[:-a.keep] if a.keep else staged
    freed = 0
    for bomv in drop:
        p = os.path.join(a.to, bomv)
        if not os.path.isdir(p):
            print('   %s is not staged' % bomv)
            continue
        if bomv not in lk.get('boms', {}):
            print('!! %s is staged but not in the lock — leaving it alone' % bomv)
            continue
        size = tree_bytes(p)
        shutil.rmtree(p)
        freed += size
        print('   released %s (%s)' % (bomv, human(size)))
    print('-- freed %s; local free now %s' % (human(freed), human(free_bytes(ROOT))))
    return 0


def do_list(a, lk):
    locked = sorted(lk.get('boms', {}), key=bom_mod.parse_version)
    store = []
    if os.path.isdir(a.store):
        store = sorted((d for d in os.listdir(a.store)
                        if os.path.isdir(os.path.join(a.store, d)) and not d.startswith('.')),
                       key=bom_mod.parse_version)
    staged = []
    if os.path.isdir(a.to):
        staged = sorted((d for d in os.listdir(a.to)
                         if os.path.isdir(os.path.join(a.to, d)) and not d.startswith('.')),
                        key=bom_mod.parse_version)
    print('lock   : %d BOMs (%s … %s)' % (len(locked), locked[0], locked[-1]) if locked else 'lock   : empty')
    print('store  : %s — %d BOMs%s' % (a.store, len(store),
                                       ', free %s' % human(free_bytes(a.store))
                                       if os.path.isdir(a.store) else ' (not mounted)'))
    print('staged : %s — %d BOMs: %s' % (a.to, len(staged), ', '.join(staged) or '-'))
    print('local free: %s' % human(free_bytes(ROOT)))
    missing = [b for b in locked if b not in store]
    if missing:
        print('in the lock but not in the store (%d): %s%s'
              % (len(missing), ', '.join(missing[:8]), ' …' if len(missing) > 8 else ''))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('boms', nargs='*')
    p.add_argument('--store', default=DEFAULT_STORE, help='the corpus of record')
    p.add_argument('--to', default=DEFAULT_LOCAL, help='local staging directory')
    p.add_argument('--lock', default=DEFAULT_LOCK)
    p.add_argument('--services', help='comma-separated subset')
    p.add_argument('--full', action='store_true', help='verify by sha256, not by size')
    p.add_argument('--release', action='store_true', help='delete local copies instead of making them')
    p.add_argument('--keep', type=int, help='with --release: keep the N newest staged BOMs')
    p.add_argument('--list', action='store_true')
    a = p.parse_args(argv)
    lk = lock_mod.load(a.lock)
    if a.list:
        return do_list(a, lk)
    if a.release:
        if not a.boms and a.keep is None:
            p.error('--release needs a BOM version or --keep N')
        return do_release(a, lk)
    if not a.boms:
        p.error('give a BOM version, --list, or --release')
    return do_stage(a, lk)


if __name__ == '__main__':
    sys.exit(main())
