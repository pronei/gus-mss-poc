#!/usr/bin/env python3
"""Check corpus.lock against S3's independently recorded digests and against the
files on disk.

    python3 verify.py                      # every BOM in the lock
    python3 verify.py 1.38.0 --materialised
    python3 verify.py --materialised --full   # re-hash every extracted jar

Three independent checks: (1) every manifest digest in the lock equals the one
`scout/S3/boms.tsv` recorded from a separate query weeks earlier; (2) every entry
of the `CLASSPATH=` line exists as an extracted jar and every extracted jar appears
on the classpath; (3) with --materialised, the tree on disk matches the sizes (and
with --full, the sha256s) the lock records.
"""
import argparse, csv, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lock as lock_mod

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def boms_tsv(path):
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f, delimiter='\t'):
            if r['artifact_kind'] == 'container-image':
                out[(r['release'], r['service'])] = r
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('boms', nargs='*')
    p.add_argument('--lock', default=os.path.join(ROOT, 'corpus.lock'))
    p.add_argument('--corpus-dir', default=os.path.join(ROOT, 'corpus'))
    p.add_argument('--boms-tsv', default=os.path.join(ROOT, 'scout', 'S3', 'boms.tsv'))
    p.add_argument('--materialised', action='store_true')
    p.add_argument('--full', action='store_true', help='re-hash every jar (slow)')
    a = p.parse_args(argv)

    lk = lock_mod.load(a.lock)
    s3 = boms_tsv(a.boms_tsv)
    want = a.boms or sorted(lk.get('boms', {}))
    n = dig_ok = dig_bad = dig_absent = cp_bad = mat_ok = mat_bad = 0
    jars = jar_bytes = 0
    for bomv in want:
        b = lk['boms'].get(bomv)
        if not b:
            print('!! %s not in the lock' % bomv)
            cp_bad += 1
            continue
        for svc, e in sorted(b['services'].items()):
            n += 1
            jars += e['jar_count']
            jar_bytes += e['jar_bytes']
            row = s3.get((bomv, svc))
            if not row:
                dig_absent += 1
            elif row['artifact_ref'].split('@')[-1] == e['manifest_digest'] and \
                    row['pinned_version'] == e['version']:
                dig_ok += 1
            else:
                dig_bad += 1
                print('!! %-8s %-12s lock %s != boms.tsv %s' % (
                    bomv, svc, e['manifest_digest'][:26], row['artifact_ref'].split('@')[-1][:26]))
            names = set(e['jars'])
            cp = [c for c in e['classpath'] if c != 'config']
            missing = [c for c in cp if c not in names]
            extra = [j for j in names if j not in set(cp)]
            if missing or extra:
                cp_bad += 1
                print('!! %-8s %-12s classpath/jars disagree: %d missing %s, %d extra %s' % (
                    bomv, svc, len(missing), missing[:2], len(extra), extra[:2]))
            if a.materialised:
                if lock_mod.materialised(a.corpus_dir, bomv, svc, e, full=a.full):
                    mat_ok += 1
                else:
                    mat_bad += 1
                    print('!! %-8s %-12s not materialised under %s' % (bomv, svc, a.corpus_dir))
    print('-- %d entries over %d BOMs: %d digests match boms.tsv, %d differ, %d not recorded there'
          % (n, len(want), dig_ok, dig_bad, dig_absent))
    print('-- classpath/jar-set disagreements: %d' % cp_bad)
    print('-- %d jars, %.2f GiB of extracted bytes described' % (jars, jar_bytes / 2 ** 30))
    if a.materialised:
        print('-- materialised%s: %d ok, %d missing or wrong' %
              (' (full hash)' if a.full else ' (sizes)', mat_ok, mat_bad))
    return 1 if (dig_bad or cp_bad or (a.materialised and mat_bad)) else 0


if __name__ == '__main__':
    sys.exit(main())
