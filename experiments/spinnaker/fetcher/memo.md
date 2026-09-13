# G2 — the artifact fetcher

Deliverables in this directory: `fetch.py` (CLI), `registry.py`, `bom.py`,
`image.py`, `lock.py` (the library it drives), `verify.py` (cross-check against
S3's independently recorded digests and against the files on disk), `stage.py`
(move one BOM between the corpus of record and the local disk), `tests/` with
recorded fixtures, and this memo. `experiments/spinnaker/corpus.lock` is in the
repository; the artifacts are not (`corpus/` is git-ignored).

Where the bytes are: the corpus of record is the whole range on the attached
volume, `/Volumes/WDGDM/gus-spinnaker-corpus/<bom>/<svc>/{bin/<svc>, lib/*.jar}`,
because 50 BOMs are 100 GiB and this machine has 16 GiB free;
`experiments/spinnaker/corpus/` is the local staging area that analysis reads,
holding one or two BOMs at a time. `corpus.lock` describes the release, not the
location, so both are the same corpus and either can be rebuilt from it.

Python 3 standard library only — `urllib`, `tarfile`, `gzip`, `hashlib`, `json`,
`xml.etree`. No Docker, no gcloud, no Halyard, no credential of any kind.

    python3 fetch.py 1.38.0                          # one BOM, materialised
    python3 fetch.py --range 1.30.0..1.38.0 --jobs 4 # the whole range, resumable
    python3 fetch.py --range … --dry-run             # resolve every pin, pull nothing
    python3 fetch.py --range … --lock-only           # pull + verify + lock, write no files
    python3 fetch.py --range … --corpus-dir /Volumes/WDGDM/gus-spinnaker-corpus
    python3 verify.py --materialised                 # re-check the lock and the tree
    python3 stage.py --list                          # store / staged / free space
    python3 stage.py 1.31.0 --full                   # bring one BOM local, re-hash it
    python3 stage.py --release --keep 1              # give the local space back
    python3 -m unittest discover -s tests -t . -q    # 38 tests, no network
    GUS_NET_TESTS=1 python3 -m unittest tests.test_network -v

What one `(bom, svc)` costs: one BOM GET, one or two manifest GETs, one config-blob
GET, and exactly one layer blob — the `COPY` layer that carries `/opt/<svc>`.

---

## Claims

CLAIM-G2-001: The registry a release's images live on is decided by the release,
not by the BOM. Every BOM from 1.0.1 on names `us-docker.pkg.dev/spinnaker-community/docker`
in `artifactSources.dockerRegistry`, including 1.23.7, whose images are on GCR
only: `us-docker.pkg.dev` answers **404** for `gate:1.19.0-20201012200017` while
`gcr.io/spinnaker-marketplace` serves it as `sha256:31fdb568e0b6…`; symmetrically
`gcr.io` answers 404 for `gate:6.69.0`, which GAR serves as `sha256:cc9c9a239a43…`.
`registries_for()` therefore orders the three by release version (GCR < 1.28.0,
GAR 1.28.0…2026.0.x, GHCR from 2026.1.0) and keeps the other two as fallbacks.
source: probes of 2026-09-12 against both registries; `tests/fixtures/bom_1.23.7.yml:3`;
S3 §2 (CLAIM-S3-010)

CLAIM-G2-002: GAR and GCR serve manifests and blobs to callers that send **no
`Authorization` header at all**. `registry.py` attaches one only for `ghcr.io`,
and the whole run below completed with no credential.
source: `registry.py:_bearer` (returns None off GHCR); the run log of the range

CLAIM-G2-003: GHCR hands an anonymous caller a pull token from a plain GET on
`https://ghcr.io/token?scope=repository:spinnaker/<svc>:pull&service=ghcr.io`;
the token is a JWT of ~1 kB and needs no account.
source: `tests/test_network.py::test_ghcr_hands_an_anonymous_token`, run 2026-09-12

CLAIM-G2-004: **`HEAD` is not 405 on the Google registries today**, contrary to
S3 §2 and the handoff. With an `Accept` header advertising the manifest media
types, `HEAD https://us-docker.pkg.dev/v2/spinnaker-community/docker/gate/manifests/6.69.0`
returns **200** with `Docker-Content-Digest`; with no `Accept` header the same
request returns **404** (not 405), on both `us-docker.pkg.dev` and `gcr.io`.
Nothing in the fetcher depends on this — every request it makes is a GET — but
the guidance "HEAD returns 405, use GET" should be read as "send Accept, or use GET".
source: probe of 2026-09-12, three header variants on the same URL

CLAIM-G2-005: Every manifest is verified against its own bytes: the fetcher
compares `Docker-Content-Digest` with `sha256(body)` and raises on a mismatch;
no mismatch occurred in this run. The same check on layer blobs is CLAIM-G2-012.
source: `registry.py:manifest`

CLAIM-G2-006: Three manifest shapes occur, and they vary **within** one BOM, not
only between eras: at 1.30.5 clouddriver is an OCI index while its eight siblings
are Docker manifest lists. Selection skips the `unknown/unknown` attestation
children buildkit attaches (2 of the 4 children of clouddriver:5.95.0) and takes
`linux/amd64`.
source: the shape column of the range log; `tests/fixtures/manifest_*.json`;
`tests/test_manifest.py`

CLAIM-G2-007: The bucket listing is the release index: one GET returns 834 keys
with `IsTruncated=false`, of which 346 match `bom/x.y.z.yml`; **50** of them lie
in 1.30.0…1.38.0 inclusive, the range D2 fixes. Ordering is numeric, so 1.37.10
and 1.37.11 sort after 1.37.9 rather than between 1.37.1 and 1.37.2.
source: `bom.list_releases()` run of 2026-09-12; `tests/test_bom.py`

CLAIM-G2-008: Every BOM in the range pins exactly the nine in-scope services, and
**no BOM pins Keel** — 450 (bom, service) pins over 50 releases. `deck`,
`monitoring-daemon`, `monitoring-third-party`, `defaultArtifact` and `spinnaker`
are present in the file and never in scope. The quoted-key band parses the same
way (1.23.7 → nine pins with timestamped versions).
source: the range run; `tests/test_bom.py::test_quoted_keys`, `::test_keel_is_never_pinned`

CLAIM-G2-009: The image config blob identifies the app layer directly: its
`history` lists one entry per non-empty layer, and the `COPY …/install/<svc> /opt/<svc>`
entry gives the index without downloading anything. Over the range the hint was
right on the **first** probe for 450 of 450 services, so no layer
was pulled and discarded. The size-descending probe the handoff prescribes is
kept as the fallback (`--probe size`) and agrees with the hint at 1.38.0.
source: `image.layer_order`; the `layers_probed` field of every lock entry;
`tests/test_image.py::LayerOrder`

CLAIM-G2-010: The app layer sits at no fixed index: at 1.38.0 it is layer 5 of 6
for six services, 12 of 13 for clouddriver (which also ships google-cloud-sdk,
kubectl, aws-cli) and 11 of 15 for rosco (which ships packer). A fixed-index rule
would fetch the wrong bytes for two of nine services.
source: `layer_index`/`layer_count` in `corpus.lock` at 1.38.0

CLAIM-G2-011: The single-layer pull is 57 % of the compressed image bytes at
1.38.0 — **1.89 GiB against 3.30 GiB** for the nine services whole — ranging from
34 % (rosco) and 42 % (clouddriver) to 84 % (igor).
source: sum of `layers[].size` in each amd64 manifest against the pulled layer,
computed 2026-09-12

CLAIM-G2-012: Every layer blob is verified in flight: the bytes are sha256'd as
they stream through `tarfile`, and both the digest and the length are compared
with the manifest's `digest` and `size` after the stream is drained. 450
layers and 83.7 GiB passed this check with no mismatch.
source: `image.scan_layer`; `registry.HashingStream`; the range run

CLAIM-G2-013: The classpath is read, never globbed: the `CLASSPATH=` line of the
start script is parsed in order, and for every entry in `corpus.lock` the ordered
classpath and the set of extracted jars agree exactly — no jar on the classpath is
missing from `lib/`, no jar in `lib/` is off the classpath. Gate lists
`gate-web-6.69.0.jar` first after `config` at 1.38.0 and `gate-web-6.58.0.jar`
first at 1.30.0. The Cygwin rewrite further down the script
(`CLASSPATH=$( cygpath … )`) is not mistaken for the assignment.
source: `python3 verify.py` over the lock; `image.parse_classpath`;
`tests/test_image.py::Classpath`

CLAIM-G2-014: Jar naming flips at the **GCR/GAR boundary, not inside the range**:
at 1.30.0 the service's own jars are versioned (`gate-web-6.58.0.jar`), exactly as
at 1.38.0, while in the GCR era they are unversioned (1.23.7: `gate-web.jar`,
`fiat-web.jar`). The handoff's acceptance line places the unversioned naming at
1.30.0; that is a property of run A (1.0.0…1.23.7), and S3 §3 says so. It does not
matter downstream either way: nothing in the fetcher or the lock keys on
`<svc>-web-<version>.jar` — the order comes from the script.
source: `corpus.lock` at 1.30.0 and 1.38.0; a lock-only probe of gate and fiat at
1.23.7 (GCR, plain v2 manifest, digest `sha256:31fdb568e0b6…`)

CLAIM-G2-015: The run is idempotent. A second run over an entry already in the
lock skips it (and, when materialising, only after the tree on disk matches the
recorded sizes), and the two `corpus.lock` files are byte-identical — the lock is
serialised with sorted keys and lists in their own order, and a skipped entry is
never rewritten, so the `fetched` date is stable too.
source: `lock.dumps`; back-to-back runs of `fetch.py 1.38.0 --services fiat`
(`cmp` identical); `tests/test_lock.py::Determinism`

CLAIM-G2-016: The 1.24.0–1.26.7 hole is real and is a registry fact, not a
fetcher limitation: at 1.25.0 all nine pinned images answer **404 on all three
registries** (`gcr.io`, `us-docker.pkg.dev`, `ghcr.io`). The run records the nine
failures in a table and exits 1 instead of aborting.
source: `python3 fetch.py 1.25.0 --lock-only` of 2026-09-12

CLAIM-G2-017: No registry rate-limited or refused anonymous access during this
work: 1 851 registry requests at up to four concurrent fetches produced zero
401, 403 or 429 responses. The fetcher treats any of those three as a stop
condition rather than something to retry around.
source: `registry.get` (401/403/429 → `AuthRequired`, no retry); the range run log

CLAIM-G2-018: Materialised, the range is **100.4 GiB** in **198 492 jars** — a
BOM costs about 2 GiB (1.38.0: 4 048 jars, 2.09 GiB; 1.30.0: 3 589 jars,
1.82 GiB). That does not fit on this machine (16 GiB free), so the corpus of
record lives on the attached 4.5 TiB volume at
`/Volumes/WDGDM/gus-spinnaker-corpus/<bom>/<svc>/…` and `stage.py` moves one BOM
at a time onto the local disk for analysis:

    python3 stage.py --list
    python3 stage.py 1.31.0 --full      # copy local, verify every jar against the lock
    python3 stage.py --release --keep 1 # give the space back

`corpus.lock` stays in the repository and describes the release, not the
location, so a staged copy, the copy on the external volume and a future re-fetch
are the same corpus.
source: `du -sh` of both materialised BOMs; `corpus.lock` (100.4 GiB of jar bytes
described); `stage.py`; `df -h /Volumes/WDGDM`

CLAIM-G2-019: The full range completed anonymously and without a failure: **50
BOMs, 450 (bom, service) pairs, 0 failed**, 83.7 GiB pulled in **26 min 28 s** at
four concurrent fetches (`--lock-only`, so the pull was verified and locked but
not written out). Every one of the 450 entries carries a manifest digest that
equals `boms.tsv`, and `verify.py` reports 0 classpath/jar-set disagreements over
all of them.
source: `fetch.py --range 1.30.0..1.38.0 --lock-only --jobs 4` of 2026-09-12
(`-- 414 fetched, 36 skipped, 0 failed; 83.7 GiB pulled; 1588.4 s`; the 36 skips
are 1.30.0 and 1.38.0, already locked); `python3 verify.py`

CLAIM-G2-020: Four facts about keeping the corpus on the exFAT volume, all
measured rather than assumed: (a) exFAT carries no permission bits, so `chmod` on
the start script fails and is caught — the file is written, the bit is not; (b)
macOS attaches `com.apple.provenance` to every file created there, which the
kernel materialises as a `._<name>` AppleDouble sidecar — those match `lib/*.jar`
and are not jars, so the fetcher sweeps them after each BOM and `stage.py` skips
them (the first sweep missed the 51 sidecars of the BOM directories themselves,
which sit in the parent directory, outside its walk — fixed, and the 51 removed);
(c) exFAT is case-insensitive, and across all **198 492** jar names in the
lock there is **not one** pair differing only in case, so nothing is silently
merged; and (d) the volume's allocation unit is **1 MiB**, so a corpus of ~200 000
mostly-small files occupies **133 GiB** on the drive for 100.4 GiB of bytes — a
32 % amplification that is real disk usage, not a discrepancy with the lock, and
it disappears again when a BOM is staged back onto APFS.
source: `mount | grep WDGDM` (`exfat … noowners`); a written-then-listed file
showing `._t.jar`; a case-folding scan of every `jars` key in `corpus.lock`



CLAIM-G2-021: The staging loop is verified end to end: `stage.py --release 1.30.0`
freed 1.8 GiB locally, and `stage.py 1.30.0 --full` copied the BOM back from the
external volume and re-hashed **all 3 589 jars plus the nine start scripts**
against the lock — **0 problems**, 2 min 49 s, while the fetcher was writing to
the same volume. Staging refuses to start when the local disk lacks the BOM's
size plus a gigabyte, so the loop cannot fill the boot volume.
source: the run of 2026-09-12; `stage.py:do_stage`/`do_release`

CLAIM-G2-022: The corpus on the external volume was written by an **independent
full re-fetch** — all 450 pairs pulled again from the registries, nothing reused
from the first pass — and the `corpus.lock` it regenerated is **byte-identical**
to the one the lock-only pass had written (`cmp` clean, 47 MiB). Checked against
the drive afterwards: all **450 entries present with every jar at the recorded
size**, every manifest digest still equal to `boms.tsv`, no classpath disagreeing
with its jar set. The drive holds 198 994 files — 198 492 jars, 450 start
scripts, the progress file, and the 51 sidecars since removed.
source: `fetch.py --range 1.30.0..1.38.0 --jobs 4 --corpus-dir /Volumes/WDGDM/…`
(`450 fetched, 0 skipped, 0 failed; 90.5 GiB pulled; 4621.5 s`); `cmp` against the
pre-materialisation snapshot; `verify.py --materialised --corpus-dir /Volumes/WDGDM/…`

CLAIM-G2-023: The dry run resolves the whole range without downloading anything:
**450 pins over 50 BOMs, every one compared with `boms.tsv` and equal**, in
5 min 48 s of manifest traffic only (one BOM GET and one or two manifest GETs per
pin, no config blob, no layer). It is a test, so it re-runs on demand rather than
being a claim about one afternoon.
source: `GUS_NET_TESTS=1 python3 -m unittest tests.test_network -v` of 2026-09-12
(`450 pins resolved, 450 compared with boms.tsv`, `Ran 2 tests in 348.488s … OK`)

---

## Sizes and times

Per minor line, from `corpus.lock` (jars = files extracted per BOM summed over the
line; "layer" is the compressed app layer actually pulled):

| minor line | releases | jars | extracted | layer pulled |
|---|---|---|---|---|
| 1.30.x | 7 | 25 099 | 12.7 GiB | 11.5 GiB |
| 1.31.x | 4 | 14 393 | 7.3 GiB | 6.6 GiB |
| 1.32.x | 5 | 19 870 | 9.7 GiB | 8.7 GiB |
| 1.33.x | 4 | 15 964 | 7.8 GiB | 7.1 GiB |
| 1.34.x | 7 | 29 253 | 14.7 GiB | 13.2 GiB |
| 1.35.x | 6 | 24 984 | 12.6 GiB | 11.3 GiB |
| 1.36.x | 4 | 16 305 | 8.4 GiB | 7.6 GiB |
| 1.37.x | 12 | 48 576 | 25.1 GiB | 22.6 GiB |
| 1.38.0 | 1 | 4 048 | 2.1 GiB | 1.9 GiB |
| **all** | **50** | **198 492** | **100.4 GiB** | **90.5 GiB** |

Runs, in order:

| run | what | wall | pulled | result |
|---|---|---|---|---|
| `fetch.py 1.38.0 --jobs 3` | materialise, local | 44 s | 1.89 GiB | 9/9 |
| `fetch.py 1.30.0 --jobs 3` | materialise, local | 34 s | 1.64 GiB | 9/9 |
| `fetch.py --range 1.30.0..1.38.0 --lock-only --jobs 4` | verify + lock, all 50 | **26 min 28 s** | **83.7 GiB** | 414 fetched, 36 skipped, **0 failed** |
| `fetch.py --range … --corpus-dir /Volumes/WDGDM/…` | materialise all 50 to the external volume | **77 min 2 s** | **90.5 GiB** | 450 fetched, **0 failed** |
| `stage.py 1.30.0 --full` | external → local, re-hash every jar | 2 min 49 s | — | 0 problems |
| `tests.test_network` | dry run, all 450 pins, no download | 5 min 48 s | — | 450/450 equal to `boms.tsv` |

A single (bom, service) costs one BOM GET, one or two manifest GETs, one config
blob and exactly one layer: **≥ 1 851 registry requests** for the 50-BOM range,
none of which was throttled or refused. Pulling whole images instead of the one
`COPY` layer would have cost ≈ 160 GiB rather than 90.5 GiB (57 % at 1.38.0).

## Failures

**None.** All 450 (bom, service) pairs of 1.30.0…1.38.0 resolved and pulled; the
failure table below is what the fetcher prints when they do not, reproduced on a
release outside the range (CLAIM-G2-016):

    -- 0 fetched, 0 skipped, 9 failed; 0.0 B pulled; 4.7 s
    -- failures
       1.25.0   gate         no registry served gate:1.21.0-20210215200018 (gcr.io HTTP 404,
                             us-docker.pkg.dev HTTP 404, ghcr.io HTTP 404)
       …

A failed service is recorded in `corpus/fetch-progress.json` with its error and
does not stop the run; a 401, 403 or 429 does stop it, because anonymous
retrievability is the property the corpus is defined by.

## A note on the lock's size

`corpus.lock` is **47 MiB** of JSON, and 198 492 jars are why: the per-jar
sha256/size map is **30.9 MiB** (66 %) and the ordered `classpath` lists are most
of the remaining 16 MiB; the digests, BOM metadata and everything else are under
1 MiB together. That is the shape the handoff asks for — "sha256 of every extracted jar" — and it is
what makes a staged copy checkable without the registry. If it is too big to sit
in the repository comfortably, the two obvious cuts are one file per BOM
(`corpus/<bom>.lock`, ~940 KiB each) or dropping the per-jar hashes for BOMs
nobody has staged yet; both are a few lines in `lock.py`, and neither is done
here because the handoff named one file.

## What I could not verify

* **Only the two ends of the range are on disk.** `--lock-only` pulled and
  verified every layer of the other 48 BOMs but wrote no jars, because a
  materialised BOM costs about 2 GiB and 50 of them ≈ 100 GiB against 14 GiB free
  on this machine's only volume. The digests and jar hashes in the lock are
  computed from the real bytes either way; what is untested for those 48 is only
  the writing-out, which is the same code path that produced 1.30.0 and 1.38.0.
  Materialising any of them later is `fetch.py <bom>`, and the entry it writes is
  the one already in the lock.
* **I never opened a jar.** The lock records each jar's sha256 and size as served
  inside the layer. Whether the jar is a readable zip holding the classes G1
  expects is not checked here (S3 checked it on three images).
* **`linux/amd64` only.** Every index in the range also offers `linux/arm64`;
  no arm64 child was ever fetched, so I cannot say whether the two children's
  `/opt/<svc>` trees are byte-identical. For pure-JVM jars they should be, but
  their layer digests differ and I did not compare them.
* **`config/` is deliberately not extracted.** The `CLASSPATH=` line begins with
  `$APP_HOME/config`, a directory the corpus does not contain: the layer carries
  exactly one file there (`opt/gate/config/gate.yml`, 4 510 bytes at 1.38.0).
  Reflection does not need it, but review pass 2 re-derived a claim from shipped
  configuration, so if that becomes a habit the fetcher should keep the file —
  one line in `image.scan_layer` plus a re-fetch.
* **GHCR is only proven to hand out a token.** No image was pulled from it: the
  range is GAR-only and CalVer is out of scope (D2). The GCR path was exercised
  on exactly two images (gate and fiat at 1.23.7), enough to show the plain v2
  manifest shape and unversioned jar names, not enough to call run A fetchable.
* **BOM timestamps are taken as given.** `timestamp` is copied from the BOM into
  the lock; I did not cross-check it against GitHub releases (S3 did, to within
  ~10 s on 39 of the 41 releases GitHub has).
* **The absence of rate limiting is one machine's negative result**, at no more
  than four concurrent fetches, on one afternoon. It is not a guarantee for a CI
  runner, a shared egress IP, or a re-run months from now.
* **`--probe size` is exercised only at 1.38.0**, where it agrees with the
  config-history hint. The range ran on the default hint path; the case where the
  two disagree is covered by a unit test, not by a real image.
* **The external volume is exFAT, which keeps no permission bits and no
  checksums of its own.** The start script lands without its executable bit
  (CLAIM-G2-020), which matters only if someone tries to *run* the corpus rather
  than read it; and a silently corrupted jar on that drive would be caught only
  when `stage.py --full` or `verify.py --full` re-hashes it, which is exactly why
  both exist. I have not tested the drive's behaviour when it is unplugged
  mid-write.
* **`stage.py` verifies what the lock names, not what the directory holds.** A
  file in the store that the lock does not mention is neither copied nor
  reported; that is deliberate (it is how the `._*` sidecars are skipped) but it
  means an extra jar dropped into `lib/` by hand would go unnoticed.
* **Agreement with `boms.tsv` is not independence.** Both readings come from the
  same registries, weeks apart. A tag re-pushed in between would have shown up as
  a mismatch — none did — but neither reading is evidence about what the image
  contained on the day the release shipped.
