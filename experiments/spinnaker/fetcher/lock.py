#!/usr/bin/env python3
"""corpus.lock: what was fetched, from where, and what it hashed to.

The lock describes the *release*, not this machine: manifest and layer digests,
the ordered classpath, the sha256 of every jar.  Where those bytes currently sit
(or whether they were materialised at all) is local state and lives in the
progress file instead, so that a lock-only run and a full run produce the same
lock for the same BOM.
"""
import json, os

SCHEMA = 'gus-spinnaker-corpus-lock/1'


def empty():
    return {'schema': SCHEMA, 'services': list(), 'boms': {}}


def load(path):
    if not os.path.exists(path):
        return empty()
    with open(path) as f:
        d = json.load(f)
    if d.get('schema') != SCHEMA:
        raise RuntimeError('%s: unknown lock schema %r' % (path, d.get('schema')))
    return d


def dumps(lock):
    """Deterministic bytes: sorted keys everywhere, lists keep their order."""
    return json.dumps(lock, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def save(path, lock):
    data = dumps(lock)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(data)
    os.replace(tmp, path)
    return len(data)


def get_entry(lock, bom, svc):
    return (lock.get('boms', {}).get(bom, {}).get('services', {}) or {}).get(svc)


def put_bom(lock, bom, meta):
    b = lock.setdefault('boms', {}).setdefault(bom, {})
    b.update(meta)
    b.setdefault('services', {})
    return b


def put_entry(lock, bom, svc, entry):
    lock['boms'][bom]['services'][svc] = entry


def materialised(corpus_dir, bom, svc, entry, full=False):
    """Is this entry present on disk as corpus/<bom>/<svc>/{bin,lib}?

    `full` re-hashes every jar; otherwise sizes are compared, which catches a
    truncated or half-written tree without re-reading gigabytes.
    """
    import hashlib
    root = os.path.join(corpus_dir, bom, svc)
    script = os.path.join(root, 'bin', svc)
    if not os.path.exists(script) or os.path.getsize(script) != entry.get('start_script', {}).get('size'):
        return False
    for name, meta in (entry.get('jars') or {}).items():
        p = os.path.join(root, 'lib', name)
        if meta.get('size') is None:
            continue
        if not os.path.exists(p) or os.path.getsize(p) != meta['size']:
            return False
        if full:
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                while (c := f.read(1 << 20)):
                    h.update(c)
            if 'sha256:' + h.hexdigest() != meta['sha256']:
                return False
    return True
