"""Paths and corpus facts shared by the G3 scripts.

Everything here is read from files already in the repository: the release
order and the pins come from `corpus.lock` (G2), the interface -> provider
binding from S1's `mesh.tsv`, the checker from `cmd/gus` (built, never edited).
"""
import functools
import glob
import hashlib
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))       # experiments/spinnaker/projection
SPIN = os.path.dirname(HERE)                            # experiments/spinnaker
REPO = os.path.dirname(os.path.dirname(SPIN))           # repository root
WORK = os.path.join(HERE, '.work')                      # regenerable scratch: classpath links, gus binary
DOCS = os.path.join(HERE, 'docs')                       # extractor output (gitignored; docs.lock records it)

SERVICES = ('clouddriver', 'echo', 'fiat', 'front50', 'gate', 'igor', 'kayenta', 'orca', 'rosco')
PROFILES = ('declared', 'none')
# A listing run, not a third profile. The owner's two dropped client families
# (kork-plugins Front50Service, indirect FiatService) are absent from the
# profile documents by construction (--kork-rows drop --indirect-fiat drop),
# so unmatched.tsv enumerates them from a client-only run that keeps both.
KEEP = 'keep-client'
RUNS = PROFILES + (KEEP,)

MESH_TSV = os.path.join(SPIN, 'scout', 'S1', 'tools', 'mesh.tsv')
JAR = os.path.join(SPIN, 'extractor', 'target', 'gus-contract-extractor.jar')
CORPUS_LOCK = os.path.join(SPIN, 'corpus.lock')
STAGE = os.path.join(SPIN, 'fetcher', 'stage.py')


def parse_version(v):
    return tuple(int(x) for x in v.split('.'))


@functools.lru_cache(maxsize=None)
def corpus_lock():
    with open(CORPUS_LOCK) as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def boms():
    """The 50 releases of D2 in version order (1.37.9 < 1.37.10 < 1.37.11 < 1.38.0)."""
    return tuple(sorted(corpus_lock()['boms'], key=parse_version))


@functools.lru_cache(maxsize=None)
def pins():
    """{bom: {service: pinned version}}."""
    lk = corpus_lock()['boms']
    return {b: {s: lk[b]['services'][s]['version'] for s in SERVICES} for b in boms()}


def pairs():
    """Consecutive pairs in version order as (NN, from, to), NN = 01 … 49."""
    bs = boms()
    return [('%02d' % (i + 1), bs[i], bs[i + 1]) for i in range(len(bs) - 1)]


def java():
    homes = sorted(glob.glob(os.path.join(SPIN, '.jdk', '*', 'Contents', 'Home')))
    if not homes:
        raise SystemExit('no JDK under %s (see extractor/memo.md, CLAIM-G1-001)' % os.path.join(SPIN, '.jdk'))
    return os.path.join(homes[0], 'bin', 'java')


def pin_doc(run, svc, ver, ext='yaml'):
    """The one real file per (run, service, version)."""
    return os.path.join(DOCS, 'pins', run, svc, '%s.%s' % (ver, ext))


def bom_doc(run, bom, svc, ext='yaml'):
    """docs/<presence>/<bom>/<svc>.yaml, a hard link to the pin's document."""
    return os.path.join(DOCS, run, bom, '%s.%s' % (svc, ext))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


@functools.lru_cache(maxsize=None)
def gus_bin():
    """The checker, built from the repository into .work/bin (the source is not touched)."""
    out = os.path.join(WORK, 'bin', 'gus')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(['go', 'build', '-o', out, './cmd/gus'], cwd=REPO, check=True)
    return out
