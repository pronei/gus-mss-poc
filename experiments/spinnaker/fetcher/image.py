#!/usr/bin/env python3
"""Finding and unpacking the one layer that carries /opt/<svc>.

Every Spinnaker image is a Gradle `installDist` tree copied in by a single COPY
layer (S3 §3): /opt/<svc>/bin/<svc>, /opt/<svc>/lib/*.jar.  Pulling that one layer
costs 42-70 % of the image instead of 100 %, and only the start script and the
jars are ever written out.
"""
import hashlib, os, posixpath, re, tarfile

import registry

CLASSPATH_RX = re.compile(r'^\s*CLASSPATH=(.*)$')


def layer_order(manifest, config, svc):
    """Layer indices to probe, best first.

    Primary: the image config's `history` names the build step of every non-empty
    layer, so the COPY that lands /opt/<svc> identifies the layer directly
    (CLAIM-G2-008).  Fallback (and tie-break): largest compressed layer first, as
    the handoff prescribes — the app layer is the biggest or near it in every image.
    """
    layers = manifest.get('layers') or []
    by_size = sorted(range(len(layers)), key=lambda i: -(layers[i].get('size') or 0))
    hinted = []
    hist = (config or {}).get('history') or []
    idx = -1
    for h in hist:
        if h.get('empty_layer'):
            continue
        idx += 1
        if idx >= len(layers):
            break
        created = (h.get('created_by') or '')
        if ('/opt/%s' % svc) in created or ('opt/%s' % svc) in created:
            hinted.append(idx)
    order = hinted + [i for i in by_size if i not in hinted]
    return order, {'hinted': hinted, 'by_size': by_size[:3]}


def _norm(name):
    while name.startswith('./'):
        name = name[2:]
    return name.lstrip('/')


def scan_layer(reg, image_name, digest, svc, dest=None, expect_size=None):
    """Stream one layer; extract the start script and lib/*.jar of `svc`.

    Returns None when the layer does not hold opt/<svc>/bin/<svc> (a wrong probe),
    otherwise a dict with the start script, the jar hashes and the byte counts.
    The whole blob is always read to the end so that sha256(blob) == digest is
    checked over the bytes actually served (CLAIM-G2-009); a mismatch raises.
    """
    want_bin = 'opt/%s/bin/%s' % (svc, svc)
    lib_prefix = 'opt/%s/lib/' % svc
    stream, raw = registry.open_layer(reg, image_name, digest)
    script = None
    script_mode = 0o755
    jars = {}
    links = []
    written = []
    jar_bytes = 0
    bin_dir = lib_dir = None
    if dest:
        bin_dir, lib_dir = os.path.join(dest, 'bin'), os.path.join(dest, 'lib')
    try:
        with tarfile.open(fileobj=stream, mode='r|gz') as tar:
            for m in tar:
                name = _norm(m.name)
                base = posixpath.basename(name)
                if base.startswith('.wh.'):            # whiteout marker, not a file
                    continue
                if name == want_bin and m.isreg():
                    script = tar.extractfile(m).read()
                    script_mode = m.mode or 0o755
                    continue
                if not name.startswith(lib_prefix) or not base.endswith('.jar'):
                    continue
                if m.islnk() or m.issym():
                    links.append((base, _norm(m.linkname)))
                    continue
                if not m.isreg():
                    continue
                h = hashlib.sha256()
                size = 0
                out = None
                if lib_dir:
                    os.makedirs(lib_dir, exist_ok=True)
                    path = os.path.join(lib_dir, base)
                    written.append(path)
                    out = open(path, 'wb')
                src = tar.extractfile(m)
                try:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        h.update(chunk)
                        size += len(chunk)
                        if out:
                            out.write(chunk)
                finally:
                    if out:
                        out.close()
                jars[base] = {'sha256': 'sha256:' + h.hexdigest(), 'size': size}
                jar_bytes += size
        stream.drain()
    finally:
        raw.close()
    if stream.digest != digest:
        raise registry.RegistryError('layer digest mismatch: asked %s, served %s'
                                     % (digest, stream.digest))
    if expect_size is not None and stream.n != expect_size:
        raise registry.RegistryError('layer size mismatch: manifest %d, served %d'
                                     % (expect_size, stream.n))
    if script is None:
        # a wrong probe: this layer holds jars of some other tree, or none at all
        for path in written:
            try:
                os.unlink(path)
            except OSError:
                pass
        return None
    for base, target in links:                      # hardlinks inside lib/
        tbase = posixpath.basename(target)
        if tbase in jars:
            jars[base] = dict(jars[tbase])
            if lib_dir:
                src = os.path.join(lib_dir, tbase)
                dst = os.path.join(lib_dir, base)
                if os.path.exists(src) and not os.path.exists(dst):
                    with open(src, 'rb') as a, open(dst, 'wb') as b:
                        while (c := a.read(1 << 20)):
                            b.write(c)
            jar_bytes += jars[base]['size']
        else:
            jars[base] = {'sha256': None, 'size': None, 'hardlink_to': target}
    if bin_dir:
        os.makedirs(bin_dir, exist_ok=True)
        p = os.path.join(bin_dir, svc)
        with open(p, 'wb') as f:
            f.write(script)
        try:
            os.chmod(p, (script_mode | 0o755) & 0o777)
        except OSError:
            pass                        # exFAT and friends carry no permission bits
    return {'script': script, 'script_sha256': 'sha256:' + hashlib.sha256(script).hexdigest(),
            'script_size': len(script), 'jars': jars, 'jar_bytes': jar_bytes,
            'compressed_bytes': stream.n, 'hardlinks': len(links)}


def parse_classpath(script_bytes):
    """The ordered classpath the service actually runs with.

    The Gradle start script writes one literal `CLASSPATH=` line in dependency
    order (S3 §3); that order is the corpus's classpath, not a glob of lib/.
    Entries are returned as basenames, so `config` stays `config` and
    `$APP_HOME/lib/gate-web-6.69.0.jar` becomes `gate-web-6.69.0.jar`.
    """
    text = script_bytes.decode('utf-8', 'replace')
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = CLASSPATH_RX.match(line)
        if not m:
            continue
        value = m.group(1)
        if value.lstrip().startswith('$('):
            continue                      # the cygpath rewrite further down the script
        j = i
        while value.endswith('\\') and j + 1 < len(lines):    # continued line
            j += 1
            value = value[:-1] + lines[j].strip()
        value = value.strip().strip('"').strip("'")
        entries = [e for e in value.split(':') if e]
        if not any(e.endswith('.jar') for e in entries):
            continue                      # not the classpath assignment
        return [posixpath.basename(e.replace('\\', '/')) for e in entries], value
    return [], None
