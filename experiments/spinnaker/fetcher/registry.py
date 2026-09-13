#!/usr/bin/env python3
"""Anonymous, dependency-free access to the three registries Spinnaker's images live on.

No Docker, no credentials, no gcloud: manifests and blobs are plain HTTPS GETs.
GAR and GCR serve anonymously with no Authorization header at all and answer 405
to HEAD (so every request here is a GET); GHCR hands anonymous callers a bearer
token from a plain GET on ghcr.io/token (CLAIM-G2-002/003).
"""
import hashlib, json, os, ssl, time, urllib.error, urllib.parse, urllib.request

UA = 'gus-spinnaker-fetcher/1.0 (experiments/spinnaker; stdlib urllib)'
TIMEOUT = float(os.environ.get('GUS_HTTP_TIMEOUT', '120'))
RETRIES = int(os.environ.get('GUS_HTTP_RETRIES', '4'))

MANIFEST_ACCEPT = ', '.join([
    'application/vnd.docker.distribution.manifest.v2+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.v1+json',
])
INDEX_TYPES = {'application/vnd.docker.distribution.manifest.list.v2+json',
               'application/vnd.oci.image.index.v1+json'}
MANIFEST_TYPES = {'application/vnd.docker.distribution.manifest.v2+json',
                  'application/vnd.oci.image.manifest.v1+json'}

# The three eras (CLAIM-G2-001).  `artifactSources.dockerRegistry` in the BOM is
# not a record of where an old image lives — every BOM from 1.0.1 on names the GAR
# repo, including 2017 releases that only exist on GCR — so the registry is chosen
# by release version and the others are tried as fallbacks.
GAR = ('us-docker.pkg.dev', 'spinnaker-community/docker')
GCR = ('gcr.io', 'spinnaker-marketplace')
GHCR = ('ghcr.io', 'spinnaker')


class RegistryError(RuntimeError):
    """A registry answered in a way that is not a transport hiccup."""

    def __init__(self, msg, status=None, url=None, auth=False):
        super().__init__(msg)
        self.status, self.url, self.auth = status, url, auth


class AuthRequired(RegistryError):
    """Anonymous access was refused — record it and stop, never work around it."""


def registries_for(release):
    """Ordered candidates for a release version tuple, primary first."""
    if release >= (2026, 1, 0):
        return [GHCR, GAR, GCR]
    if release >= (1, 28, 0):
        return [GAR, GCR, GHCR]
    return [GCR, GAR, GHCR]


_tokens = {}


def _bearer(host, repo, name):
    """Anonymous pull token.  Only GHCR needs one; the Google registries take none."""
    if host != 'ghcr.io':
        return None
    key = (host, repo, name)
    if key not in _tokens:
        u = ('https://ghcr.io/token?scope=' +
             urllib.parse.quote('repository:%s/%s:pull' % (repo, name), safe='') +
             '&service=ghcr.io')
        _tokens[key] = json.loads(get(u).body)['token']
    return _tokens[key]


class Response:
    def __init__(self, status, headers, body, url):
        self.status, self.headers, self.body, self.url = status, headers, body, url

    def header(self, name, default=None):
        return self.headers.get(name, default)


def _request(url, headers, stream):
    req = urllib.request.Request(url, headers=dict(headers, **{'User-Agent': UA}))
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def get(url, headers=None, stream=False):
    """GET with bounded retries.  401/403 raise AuthRequired at once — an anonymous
    refusal is a fact to record, not something to retry around."""
    headers = headers or {}
    delay, last = 1.0, None
    for attempt in range(RETRIES):
        try:
            fp = _request(url, headers, stream)
            if stream:
                return fp
            with fp:
                return Response(fp.status, dict(fp.headers), fp.read(), fp.geturl())
        except urllib.error.HTTPError as e:
            body = b''
            try:
                body = e.read()[:400]
            except Exception:
                pass
            if e.code in (401, 403):
                raise AuthRequired('anonymous access refused: HTTP %d %s' % (e.code, body[:200]),
                                   status=e.code, url=url, auth=True)
            if e.code == 429:
                raise AuthRequired('rate limited: HTTP 429 %s' % body[:200], status=429, url=url)
            if e.code in (500, 502, 503, 504) and attempt < RETRIES - 1:
                last = e
            else:
                raise RegistryError('HTTP %d for %s: %s' % (e.code, url, body[:200]),
                                    status=e.code, url=url)
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, ConnectionError) as e:
            if attempt == RETRIES - 1:
                raise RegistryError('%s for %s' % (e, url), url=url)
            last = e
        time.sleep(delay)
        delay *= 2
    raise RegistryError('giving up after %d attempts on %s (%s)' % (RETRIES, url, last), url=url)


def manifest(reg, name, reference):
    """GET a manifest or index by tag or digest.  Returns (parsed, raw_bytes, digest, media_type).

    The digest is taken from Docker-Content-Digest when present and always checked
    against sha256 of the body we actually read (CLAIM-G2-004)."""
    host, repo = reg
    url = 'https://%s/v2/%s/%s/manifests/%s' % (host, repo, name, reference)
    headers = {'Accept': MANIFEST_ACCEPT}
    tok = _bearer(host, repo, name)
    if tok:
        headers['Authorization'] = 'Bearer ' + tok
    r = get(url, headers)
    body = r.body
    computed = 'sha256:' + hashlib.sha256(body).hexdigest()
    declared = r.header('Docker-Content-Digest') or r.header('docker-content-digest')
    if declared and declared != computed:
        raise RegistryError('manifest digest mismatch at %s: header %s, body %s'
                            % (url, declared, computed), url=url)
    parsed = json.loads(body)
    mt = parsed.get('mediaType') or r.header('Content-Type', '').split(';')[0]
    return parsed, body, computed, mt


def select_platform(index, os_='linux', arch='amd64'):
    """Pick the linux/amd64 child of a manifest list or OCI index.

    OCI indexes from buildkit carry attestation children whose platform is
    unknown/unknown (CLAIM-G2-005); they are skipped."""
    for m in index.get('manifests', []):
        p = m.get('platform') or {}
        if p.get('os') == os_ and p.get('architecture') == arch and p.get('variant') in (None, '', 'v8'):
            return m
    raise RegistryError('no %s/%s child in index (children: %s)' % (
        os_, arch, ', '.join('%s/%s' % ((m.get('platform') or {}).get('os'),
                                        (m.get('platform') or {}).get('architecture'))
                             for m in index.get('manifests', []))))


def resolve_image(reg, name, tag):
    """Tag -> the image manifest actually describing linux/amd64.

    Returns a dict with the top digest (what boms.tsv records), the child digest
    when the top level was an index, the media types, and the image manifest."""
    top, _raw, top_digest, mt = manifest(reg, name, tag)
    out = {'registry': '%s/%s' % reg, 'image': '%s/%s/%s' % (reg[0], reg[1], name), 'tag': tag,
           'manifest_digest': top_digest, 'manifest_media_type': mt,
           'platform': 'linux/amd64', 'child_digest': None, 'shape': 'manifest'}
    if mt in INDEX_TYPES or 'manifests' in top:
        child = select_platform(top)
        img, _raw2, child_digest, child_mt = manifest(reg, name, child['digest'])
        if child['digest'] != child_digest:
            raise RegistryError('child digest mismatch: index says %s, body is %s'
                                % (child['digest'], child_digest))
        out.update(shape='index' if mt == 'application/vnd.oci.image.index.v1+json' else 'manifest-list',
                   child_digest=child_digest, child_media_type=child_mt,
                   attestation_children=sum(1 for m in top.get('manifests', [])
                                            if (m.get('platform') or {}).get('os') == 'unknown'))
        out['manifest'] = img
    else:
        out['manifest'] = top
    return out


def blob_url(reg, name, digest):
    return 'https://%s/v2/%s/%s/blobs/%s' % (reg[0], reg[1], name, digest)


def blob(reg, name, digest):
    """Small blob (image config) with digest verification."""
    headers = {}
    tok = _bearer(reg[0], reg[1], name)
    if tok:
        headers['Authorization'] = 'Bearer ' + tok
    r = get(blob_url(reg, name, digest), headers)
    got = 'sha256:' + hashlib.sha256(r.body).hexdigest()
    if got != digest:
        raise RegistryError('blob digest mismatch: asked %s, got %s' % (digest, got))
    return r.body


class HashingStream:
    """Read-through wrapper that sha256s and counts every byte that passes.

    tarfile('r|gz') reads the compressed layer through this, so the digest covers
    exactly the bytes the registry served."""

    def __init__(self, fp):
        self.fp, self.h, self.n = fp, hashlib.sha256(), 0

    def read(self, size=-1):
        b = self.fp.read(size)
        if b:
            self.h.update(b)
            self.n += len(b)
        return b

    def drain(self):
        while True:
            b = self.read(1 << 20)
            if not b:
                return

    @property
    def digest(self):
        return 'sha256:' + self.h.hexdigest()


def open_layer(reg, name, digest):
    """Streaming HTTP response for a layer blob, wrapped for digest verification."""
    headers = {}
    tok = _bearer(reg[0], reg[1], name)
    if tok:
        headers['Authorization'] = 'Bearer ' + tok
    fp = get(blob_url(reg, name, digest), headers, stream=True)
    return HashingStream(fp), fp
