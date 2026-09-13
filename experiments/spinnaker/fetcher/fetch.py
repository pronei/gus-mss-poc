#!/usr/bin/env python3
"""G2 — the artifact fetcher.

BOM version in, corpus out:

    corpus/<bom>/<svc>/bin/<svc>     the start script (its CLASSPATH= line is the classpath)
    corpus/<bom>/<svc>/lib/*.jar
    corpus.lock                      one block per (bom, svc)

Standard library only, anonymous access only: no Docker, no gcloud, no Halyard,
no credentials.  Usage:

    python3 fetch.py 1.38.0
    python3 fetch.py --range 1.30.0..1.38.0
    python3 fetch.py --range 1.30.0..1.38.0 --dry-run      # resolve pins, pull nothing
    python3 fetch.py --range 1.30.0..1.38.0 --lock-only    # verify + lock, write no jars
    python3 fetch.py 1.38.0 --corpus-dir /volume/corpus
"""
import argparse, concurrent.futures, datetime, json, os, shutil, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bom as bom_mod
import image as image_mod
import lock as lock_mod
import registry

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # experiments/spinnaker
DEFAULT_CORPUS = os.path.join(ROOT, 'corpus')
DEFAULT_LOCK = os.path.join(ROOT, 'corpus.lock')


class Failure(Exception):
    pass


def today():
    return datetime.date.today().isoformat()


def human(n):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if n < 1024 or unit == 'TiB':
            return '%.1f %s' % (n, unit)
        n /= 1024.0


def resolve_service(release, svc, version):
    """(svc, version) -> the linux/amd64 image manifest, trying the era's registry first."""
    errors = []
    for reg in registry.registries_for(release):
        try:
            info = registry.resolve_image(reg, svc, version)
            info['registry_host'] = reg[0]
            return info
        except registry.AuthRequired:
            raise
        except registry.RegistryError as e:
            errors.append('%s %s' % (reg[0], 'HTTP %s' % e.status if e.status else str(e)[:80]))
    raise Failure('no registry served %s:%s (%s)' % (svc, version, ', '.join(errors)))


def fetch_service(release, bomv, svc, version, corpus_dir, materialise, probe='config'):
    """Resolve, pull the one layer that holds /opt/<svc>, and build the lock entry."""
    info = resolve_service(release, svc, version)
    reg = tuple(info['registry'].split('/', 1))
    manifest = info['manifest']
    cfg_digest = (manifest.get('config') or {}).get('digest')
    config = {}
    if cfg_digest:
        try:
            config = json.loads(registry.blob(reg, svc, cfg_digest))
        except registry.RegistryError:
            config = {}
    layers = manifest.get('layers') or []
    order, probe_meta = image_mod.layer_order(manifest, config if probe == 'config' else {}, svc)
    dest = os.path.join(corpus_dir, bomv, svc) if materialise else None
    if dest:
        # start from an empty lib/ so the tree matches the entry exactly, with no
        # jar left over from an earlier version or a half-finished run
        shutil.rmtree(os.path.join(dest, 'lib'), ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
    pulled, probes, found = 0, [], None
    for idx in order:
        lay = layers[idx]
        got = image_mod.scan_layer(reg, svc, lay['digest'], svc, dest=dest,
                                   expect_size=lay.get('size'))
        pulled += got['compressed_bytes'] if got else (lay.get('size') or 0)
        probes.append(idx)
        if got:
            found = (idx, lay, got)
            break
    if not found:
        raise Failure('no layer of %s:%s contains opt/%s/bin/%s (%d layers probed)'
                      % (svc, version, svc, svc, len(probes)))
    idx, lay, got = found
    classpath, raw_cp = image_mod.parse_classpath(got['script'])
    entry = {
        'version': version,
        'registry': info['registry'],
        'image': '%s:%s' % (info['image'], version),
        'manifest_digest': info['manifest_digest'],
        'manifest_media_type': info['manifest_media_type'],
        'manifest_shape': info['shape'],
        'platform': info['platform'],
        'image_manifest_digest': info.get('child_digest') or info['manifest_digest'],
        'config_digest': cfg_digest,
        'layer_digest': lay['digest'],
        'layer_size': lay.get('size'),
        'layer_index': idx,
        'layer_count': len(layers),
        'layers_probed': probes,
        'start_script': {'path': 'bin/%s' % svc, 'sha256': got['script_sha256'],
                         'size': got['script_size']},
        'classpath': classpath,
        'classpath_raw': raw_cp,
        'jars': {k: v for k, v in sorted(got['jars'].items())},
        'jar_count': len(got['jars']),
        'jar_bytes': got['jar_bytes'],
        'fetched': today(),
    }
    if info.get('attestation_children'):
        entry['index_attestation_children'] = info['attestation_children']
    return entry, pulled, probe_meta


def sweep_appledouble(root):
    """Remove the ._<name> sidecars macOS leaves on filesystems without xattrs.

    Every file written to an exFAT volume picks up `com.apple.provenance`, which
    the kernel stores in an AppleDouble file beside it; those match `lib/*.jar`
    and are not jars.  Returns how many were removed.
    """
    n = 0
    walk = os.walk(root) if os.path.isdir(root) else []
    for dirpath, _dirnames, filenames in walk:
        for f in filenames:
            if f.startswith('._'):
                try:
                    os.unlink(os.path.join(dirpath, f))
                    n += 1
                except OSError:
                    pass
    # the sidecar of the directory itself lives in its parent, out of the walk
    parent, base = os.path.split(root.rstrip('/'))
    try:
        os.unlink(os.path.join(parent, '._' + base))
        n += 1
    except OSError:
        pass
    return n


def dry_service(release, svc, version):
    info = resolve_service(release, svc, version)
    return {'version': version, 'registry': info['registry'],
            'manifest_digest': info['manifest_digest'], 'manifest_shape': info['shape'],
            'image_manifest_digest': info.get('child_digest') or info['manifest_digest']}


def load_progress(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'runs': [], 'boms': {}}


def save_progress(path, prog):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(prog, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def run(args):
    started = time.time()
    corpus_dir = os.path.abspath(args.corpus_dir)
    lock_path = os.path.abspath(args.lock)
    materialise = not (args.lock_only or args.dry_run)
    if materialise or args.lock_only:
        os.makedirs(corpus_dir, exist_ok=True)
    progress_path = os.path.join(corpus_dir, 'fetch-progress.json') if not args.dry_run else None
    prog = load_progress(progress_path) if progress_path else {'runs': [], 'boms': {}}

    if args.range:
        lo, hi = args.range.split('..')
        releases, listing = bom_mod.range_releases(lo, hi)
        print('# bucket listing: %d keys, truncated=%s -> %d releases in %s..%s'
              % (listing['keys'], listing['truncated'], len(releases), lo, hi))
    else:
        releases = [bom_mod.parse_version(v) for v in args.boms]
    if not releases:
        print('nothing to do', file=sys.stderr)
        return 2

    lock = lock_mod.load(lock_path)
    lock['services'] = list(bom_mod.SERVICES)
    total_pulled, failures, done, skipped = 0, [], 0, 0

    for rel in releases:
        bomv = bom_mod.format_version(rel)
        try:
            parsed, url, bom_sha = bom_mod.fetch_bom(bomv)
        except (registry.RegistryError, Failure) as e:
            failures.append((bomv, '-', 'bom: %s' % e))
            print('!! %-8s BOM unavailable: %s' % (bomv, e))
            continue
        all_pins = bom_mod.pinned_services(parsed)
        pins = all_pins
        if args.services:
            want = set(args.services.split(','))
            pins = [(s, v) for s, v in pins if s in want]
        head = '%-8s %s  %d services' % (bomv, parsed.get('timestamp') or '-', len(pins))
        print('== ' + head)
        if not args.dry_run:
            lock_mod.put_bom(lock, bomv, {'timestamp': parsed.get('timestamp'), 'bom_url': url,
                                          'bom_sha256': bom_sha,
                                          'services_pinned': len(all_pins)})
        bom_prog = prog.setdefault('boms', {}).setdefault(bomv, {})
        todo = []
        for svc, version in pins:
            if args.dry_run:
                todo.append((svc, version))
                continue
            entry = lock_mod.get_entry(lock, bomv, svc)
            if entry and not args.reverify and entry.get('version') == version and (
                    not materialise or lock_mod.materialised(corpus_dir, bomv, svc, entry)):
                skipped += 1
                bom_prog[svc] = {'state': 'ok', 'skipped': True, 'materialised': bool(materialise)}
                print('   %-12s %-10s skip (locked %s)' % (svc, version, entry['layer_digest'][:19]))
                continue
            todo.append((svc, version))

        def work(svc, version):
            t0 = time.time()
            if args.dry_run:
                return ('dry', svc, version, dry_service(rel, svc, version), 0, time.time() - t0)
            entry, pulled, _pm = fetch_service(rel, bomv, svc, version, corpus_dir,
                                               materialise, probe=args.probe)
            return ('fetch', svc, version, entry, pulled, time.time() - t0)

        results, auth_stop = [], None
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = {pool.submit(work, svc, version): (svc, version) for svc, version in todo}
            for fut in concurrent.futures.as_completed(futures):
                svc, version = futures[fut]
                try:
                    results.append(fut.result())
                except registry.AuthRequired as e:
                    # A registry refusing anonymous access (or rate-limiting) is a fact
                    # about the corpus, not an obstacle to route around.
                    auth_stop = e
                    failures.append((bomv, svc, 'AUTH/RATE: %s' % e))
                    bom_prog[svc] = {'state': 'failed', 'error': str(e), 'auth': True}
                    print('!! %-12s %-10s anonymous access refused: %s' % (svc, version, e))
                except (Failure, registry.RegistryError, OSError) as e:
                    failures.append((bomv, svc, str(e)))
                    bom_prog[svc] = {'state': 'failed', 'error': str(e)}
                    print('!! %-12s %-10s %s' % (svc, version, e))
        for kind, svc, version, payload, pulled, secs in sorted(results, key=lambda r: r[1]):
            if kind == 'dry':
                print('   %-12s %-10s %s %s' % (svc, version, payload['manifest_shape'],
                                                payload['manifest_digest'][:19]))
                done += 1
                continue
            total_pulled += pulled
            lock_mod.put_entry(lock, bomv, svc, payload)
            done += 1
            bom_prog[svc] = {'state': 'ok', 'skipped': False, 'materialised': bool(materialise),
                             'seconds': round(secs, 1), 'pulled_bytes': pulled}
            print('   %-12s %-10s %-14s layer %d/%d %s  %d jars, %s  (%s pulled, %.1fs)'
                  % (svc, version, payload['manifest_shape'], payload['layer_index'] + 1,
                     payload['layer_count'], payload['layer_digest'][7:19], payload['jar_count'],
                     human(payload['jar_bytes']), human(pulled), secs))
        if auth_stop is not None:
            print('!! stopping: the corpus is defined by anonymous retrievability', file=sys.stderr)
            _finish(lock, lock_path, prog, progress_path, args, started, total_pulled,
                    done, skipped, failures)
            return 3
        if not args.dry_run:
            if materialise and not args.no_sweep:
                swept = sweep_appledouble(os.path.join(corpus_dir, bomv))
                if swept:
                    print('   (swept %d AppleDouble sidecars)' % swept)
            lock_mod.save(lock_path, lock)
            save_progress(progress_path, prog)
    return _finish(lock, lock_path, prog, progress_path, args, started, total_pulled,
                   done, skipped, failures)


def corpus_root(args):
    return os.path.abspath(args.corpus_dir)


def _finish(lock, lock_path, prog, progress_path, args, started, total_pulled, done, skipped, failures):
    elapsed = time.time() - started
    if not args.dry_run and not args.no_sweep:
        root = corpus_root(args)
        for f in os.listdir(root) if os.path.isdir(root) else []:
            if f.startswith('._'):
                try:
                    os.unlink(os.path.join(root, f))
                except OSError:
                    pass
    if not args.dry_run:
        size = lock_mod.save(lock_path, lock)
        prog.setdefault('runs', []).append(
            {'at': datetime.datetime.now().isoformat(timespec='seconds'),
             'argv': sys.argv[1:], 'seconds': round(elapsed, 1), 'pulled_bytes': total_pulled,
             'fetched': done, 'skipped': skipped, 'failed': len(failures)})
        save_progress(progress_path, prog)
        print('-- corpus.lock %s (%s)' % (lock_path, human(size)))
    print('-- %d fetched, %d skipped, %d failed; %s pulled; %.1f s'
          % (done, skipped, len(failures), human(total_pulled), elapsed))
    if failures:
        print('-- failures')
        for b, s, e in failures:
            print('   %-8s %-12s %s' % (b, s, e[:160]))
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('boms', nargs='*', help='BOM versions, e.g. 1.38.0')
    p.add_argument('--range', help='LO..HI, iterated in version order')
    p.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    p.add_argument('--lock', default=DEFAULT_LOCK)
    p.add_argument('--dry-run', action='store_true', help='resolve every pin, download nothing')
    p.add_argument('--lock-only', action='store_true',
                   help='pull and verify the layer, write the lock, write no corpus files')
    p.add_argument('--reverify', action='store_true', help='re-fetch even when the lock has the entry')
    p.add_argument('--services', help='comma-separated subset, for debugging')
    p.add_argument('--no-sweep', action='store_true',
                   help='keep the ._* AppleDouble sidecars a non-xattr volume collects')
    p.add_argument('--jobs', type=int, default=1,
                   help='services fetched concurrently within one BOM (default 1)')
    p.add_argument('--probe', choices=('config', 'size'), default='config',
                   help='layer probe order: image-config history (default) or largest-first')
    args = p.parse_args(argv)
    if not args.boms and not args.range:
        p.error('give a BOM version or --range')
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
