#!/usr/bin/env python3
"""Stopgap corpus fetcher: pull the one /opt/<svc> layer of a Spinnaker service
image into G2's layout (corpus/<bom>/<svc>/{bin/<svc>,lib/*.jar}).

G2 owns this job (handoff/G2-fetcher.md).  This script exists only so that G1
can start before G2 delivers, and it implements the same steps in the same
order so the layouts are interchangeable.  Standard library only, anonymous
access only.

  pull_layer.py --bom 1.38.0 --service front50 --version 2.41.0 \
                [--digest sha256:...] [--root <corpus dir>]
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request

ACCEPT = ", ".join([
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.oci.image.index.v1+json",
])


def registry_for(version):
    """S3 CLAIM-S3-008/011: GAR from 1.28.0 of the BOM onward; the service
    versions in range are all GAR-era.  gcr.io is the pre-1.28 era."""
    return "us-docker.pkg.dev/spinnaker-community/docker"


def get(url, accept=None, token=None):
    req = urllib.request.Request(url)
    if accept:
        req.add_header("Accept", accept)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read(), dict(r.headers)


def fetch_manifest(registry, repo, ref):
    host, _, path = registry.partition("/")
    url = "https://%s/v2/%s/%s/manifests/%s" % (host, path, repo, ref)
    body, hdrs = get(url, ACCEPT)
    doc = json.loads(body)
    digest = hdrs.get("Docker-Content-Digest") or "sha256:" + hashlib.sha256(body).hexdigest()
    mt = doc.get("mediaType", hdrs.get("Content-Type", ""))
    # A manifest list / OCI index: pick linux/amd64, skipping unknown/unknown
    # attestation children.
    if "manifests" in doc:
        child = None
        for m in doc["manifests"]:
            p = m.get("platform", {})
            if p.get("os") == "linux" and p.get("architecture") == "amd64":
                child = m
                break
        if child is None:
            raise SystemExit("no linux/amd64 child in manifest list for %s:%s" % (repo, ref))
        print("  manifest list %s -> amd64 child %s" % (digest, child["digest"]))
        inner, _, imt, _ = fetch_manifest(registry, repo, child["digest"])
        # `top` stays the digest the BOM/boms.tsv names, which is the list's.
        return inner, child["digest"], imt, digest
    return doc, digest, mt, digest


def blob(registry, repo, digest):
    host, _, path = registry.partition("/")
    url = "https://%s/v2/%s/%s/blobs/%s" % (host, path, repo, digest)
    body, _ = get(url)
    actual = "sha256:" + hashlib.sha256(body).hexdigest()
    if actual != digest:
        raise SystemExit("blob digest mismatch: wanted %s got %s" % (digest, actual))
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bom", required=True)
    ap.add_argument("--service", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--digest", help="expected manifest digest from scout/S3/boms.tsv")
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "..", "..", "corpus"))
    a = ap.parse_args()

    registry = registry_for(a.version)
    print("%s:%s from %s" % (a.service, a.version, registry))
    man, mdigest, mt, top = fetch_manifest(registry, a.service, a.version)
    print("  manifest %s (%s)" % (top, mt))
    if a.digest and a.digest != top:
        print("  WARNING: manifest digest %s != expected %s" % (top, a.digest), file=sys.stderr)

    layers = sorted(man["layers"], key=lambda l: -l.get("size", 0))
    want = "opt/%s/bin/%s" % (a.service, a.service)
    out = os.path.abspath(os.path.join(a.root, a.bom, a.service))

    for i, layer in enumerate(layers):
        print("  probing layer %d/%d %s (%.1f MB)" % (i + 1, len(layers), layer["digest"],
                                                      layer.get("size", 0) / 1e6))
        raw = blob(registry, a.service, layer["digest"])
        data = gzip.decompress(raw) if layer["mediaType"].endswith("gzip") else raw
        tf = tarfile.open(fileobj=io.BytesIO(data))
        names = tf.getnames()
        if want not in names and "./" + want not in names:
            continue
        print("  hit: %s" % layer["digest"])
        n_jar = 0
        for m in tf.getmembers():
            nm = m.name[2:] if m.name.startswith("./") else m.name
            if nm == want:
                dest = os.path.join(out, "bin", a.service)
            elif nm.startswith("opt/%s/lib/" % a.service) and nm.endswith(".jar"):
                dest = os.path.join(out, "lib", os.path.basename(nm))
                n_jar += 1
            else:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                continue
            with open(dest, "wb") as fh:
                fh.write(src.read())
        os.chmod(os.path.join(out, "bin", a.service), 0o755)
        print("  extracted bin/%s and %d jars to %s" % (a.service, n_jar, out))
        print("LAYER %s" % layer["digest"])
        return 0
    raise SystemExit("no layer holds %s" % want)


sys.exit(main())
