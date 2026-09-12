# Handoff — G2, the artifact fetcher

For one Opus session at maximum effort. Self-contained: read this file, then
the files it names. Repository: `github.com/pronei/gus-mss-poc`, branch
`experiments`, directory `experiments/spinnaker/`. Everything you write goes
under `experiments/spinnaker/fetcher/` (source, tests, `memo.md`) plus
`experiments/spinnaker/corpus.lock`. The fetched artifacts go under
`experiments/spinnaker/corpus/`, which you add to `.gitignore` (tens of GB are
never committed). You do not modify the checker, any scout report, the review,
or the plan.

## Read first

1. `scout/S3/artifacts.md` — the BOM bucket, the three registries and their
   eras, the manifest shapes, the image layout, the digests already verified.
2. `scout/S3/boms.tsv` — one row per (release, service): pinned version,
   artifact reference, retrievability, digest where checked.
3. `PLAN.md` §4 D1 and D2 as revised; `scout/review.md` "First task for G2"
   and "Review pass 2".

## What you build

A Python 3 tool with no dependency beyond the standard library (`urllib`,
`tarfile`, `hashlib`, `json`) — no Docker, no credentials, anonymous access
only — that takes a BOM version and produces

    corpus/<bom>/<svc>/bin/<svc>       the start script (its CLASSPATH= line is the classpath)
    corpus/<bom>/<svc>/lib/*.jar
    corpus.lock                        one block per (bom, svc): pinned version, registry, manifest
                                       digest, selected platform and layer digest, sha256 of every
                                       extracted jar, the ordered jar list from CLASSPATH=, the BOM
                                       timestamp, fetch date

Steps, all decided:

1. `GET https://storage.googleapis.com/halconfig/bom/<bom>.yml`; parse the nine
   `services.<svc>.version` entries (keys may be quoted; ignore `deck`,
   `monitoring-*`, `defaultArtifact`, `spinnaker`; Keel is never pinned and
   is out of the corpus).
2. Resolve each (svc, version) to an image manifest:
   `us-docker.pkg.dev/spinnaker-community/docker/<svc>:<version>` for 1.28.0
   onward, `gcr.io/spinnaker-marketplace/<svc>:<version>` before, and
   `ghcr.io/spinnaker/<svc>` for 2026.1.0 onward (anonymous bearer token from
   `ghcr.io/token`). `HEAD` returns 405 on the Google registries: use `GET`.
   Accept the three manifest shapes (Docker v2 manifest, v2 manifest list,
   OCI index with `unknown/unknown` attestation children) and select
   `linux/amd64`.
3. Pull only the layer whose tar holds `opt/<svc>/bin/<svc>` (one `COPY` layer
   per image; probe layers from the largest down and stop at the first hit),
   verify `sha256(blob) == digest`, extract `opt/<svc>/bin/<svc>` and
   `opt/<svc>/lib/*.jar`, nothing else.
4. Write the lock block; the run is idempotent — an existing, verified entry
   is skipped, and two runs produce a byte-identical `corpus.lock`.
5. A `--range 1.30.0..1.38.0` mode iterates the BOMs in version order (the
   bucket listing gives the set: `?prefix=bom/&max-keys=1000`, releases are
   `bom/x.y.z.yml`), with a resumable progress file and a per-service failure
   table instead of an abort.

## Acceptance

- BOM 1.38.0: nine services fetched; the manifest digests equal those in
  `scout/S3/boms.tsv` (clouddriver:5.95.0 `sha256:4db25c29…`); Gate's
  `CLASSPATH=` lists `gate-web-6.69.0.jar` first after `config`.
- BOM 1.30.0: orca:8.31.0 is a manifest list; the amd64 child is
  `sha256:8e6f2a13…`; jar names there are unversioned (`gate-web.jar`), which
  must not matter to anything downstream.
- The full range 1.30.0…1.38.0 (50 BOMs) completes without a credential;
  report total bytes pulled (the single-layer pull should stay far below the
  ≈ 30 GB a whole-image pull would cost) and wall time.
- Tests: manifest-shape parsing on three recorded manifests (save them as
  fixtures), lock idempotence, and a dry run that resolves every pin of the
  range without downloading.

## Report back

`fetcher/memo.md`: sizes, times, every (bom, svc) that failed and why, and a
last section titled "## What I could not verify". Numbered claims
(`CLAIM-G2-NNN`) for every fact about the registries you relied on. If a
registry starts refusing anonymous access or rate-limits, record it and stop
rather than working around it.
