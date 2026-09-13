#!/usr/bin/env python3
"""The BOM bucket: the release index and what each release pins.

`https://storage.googleapis.com/halconfig` is public and lists in one request;
each BOM is one plain GET.  No Halyard, no gcloud, no auth (CLAIM-G2-006).
"""
import hashlib, re, xml.etree.ElementTree as ET

from registry import get

BUCKET = 'https://storage.googleapis.com/halconfig'
BOM_URL = BUCKET + '/bom/%s.yml'
LISTING = BUCKET + '?prefix=bom/&max-keys=1000'

# The nine JVM services a BOM pins that are in scope.  `deck` is the JS UI,
# `monitoring-daemon`/`monitoring-third-party` are Python, `defaultArtifact` is a
# placeholder and `spinnaker` a meta-package in the first 38 BOMs.  Keel is pinned
# by no BOM at all (S3-006, D2) and is out of the corpus.
SERVICES = ('clouddriver', 'echo', 'fiat', 'front50', 'gate', 'igor', 'kayenta', 'orca', 'rosco')
IGNORED = ('deck', 'monitoring-daemon', 'monitoring-third-party', 'defaultArtifact', 'spinnaker', 'keel')

RELEASE_KEY = re.compile(r'^bom/(\d+\.\d+\.\d+)\.yml$')


def parse_version(s):
    """'1.38.0' -> (1, 38, 0).  CalVer ('2025.0.0') shares the shape and sorts after."""
    parts = s.strip().split('.')
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError('not a release version: %r' % s)
    return tuple(int(p) for p in parts)


def format_version(v):
    return '%d.%d.%d' % v


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in '"\'':
        return s[1:-1]
    return s


def parse_bom(text):
    """Minimal, shape-specific parse of a BOM: version, timestamp, and the pinned
    services with their versions and commits.

    52 BOMs in the 1.19.12-1.26.7 band quote their keys ("gate":); the shape is
    otherwise identical across all 346 (CLAIM-G2-007).  A real YAML parser is not
    in the standard library and is not needed for this shape.
    """
    out = {'version': None, 'timestamp': None, 'services': {}, 'docker_registry': None}
    in_services = False
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        if indent == 0:
            in_services = body.rstrip(':') == 'services' and body.endswith(':')
            current = None
            if not in_services and ':' in body:
                k, _, v = body.partition(':')
                k, v = _unquote(k), _unquote(v)
                if k == 'version' and v:
                    out['version'] = v
                elif k == 'timestamp' and v:
                    out['timestamp'] = v
            continue
        if not in_services:
            if indent == 2 and body.startswith('dockerRegistry:'):
                out['docker_registry'] = _unquote(body.split(':', 1)[1])
            continue
        if indent == 2:
            key = _unquote(body.rstrip(':').strip()) if body.endswith(':') else _unquote(body.split(':', 1)[0])
            current = key
            out['services'].setdefault(current, {})
            continue
        if indent >= 4 and current and ':' in body:
            k, _, v = body.partition(':')
            k, v = _unquote(k), _unquote(v)
            if k in ('version', 'commit') and v:
                out['services'][current][k] = v
    return out


def pinned_services(bom):
    """(service, version) for the nine in scope, in a fixed order."""
    out = []
    for svc in SERVICES:
        d = bom['services'].get(svc) or {}
        if d.get('version'):
            out.append((svc, d['version']))
    return out


def fetch_bom(version):
    """Returns (parsed, url, sha256-of-the-yaml)."""
    url = BOM_URL % version
    r = get(url)
    return parse_bom(r.body.decode('utf-8')), url, 'sha256:' + hashlib.sha256(r.body).hexdigest()


def list_releases():
    """Every bom/x.y.z.yml key in the bucket, as version tuples, ascending.

    The listing is one request and is not truncated at max-keys=1000 (834 keys)."""
    r = get(LISTING)
    root = ET.fromstring(r.body)
    ns = {'s3': root.tag.split('}')[0].strip('{')} if root.tag.startswith('{') else {}
    keys = [e.text for e in root.iter('{%s}Key' % ns['s3'])] if ns else [e.text for e in root.iter('Key')]
    truncated = None
    for e in (root.iter('{%s}IsTruncated' % ns['s3']) if ns else root.iter('IsTruncated')):
        truncated = (e.text or '').lower() == 'true'
    rels = sorted({parse_version(m.group(1)) for k in keys if (m := RELEASE_KEY.match(k or ''))})
    return rels, {'keys': len(keys), 'truncated': truncated}


def range_releases(lo, hi):
    """Releases of the bucket within [lo, hi] in version order."""
    rels, meta = list_releases()
    lo_v, hi_v = parse_version(lo), parse_version(hi)
    return [r for r in rels if lo_v <= r <= hi_v], meta
