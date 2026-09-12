# S3 memo — released artifacts

Run 2026-09-11/12. Every query read-only and anonymous. Detail and the go/no-go
argument are in `artifacts.md`; per-row evidence (including digests) in `boms.tsv`.

CLAIM-S3-001: Spinnaker BOMs are objects under the `bom/` prefix of the public
GCS bucket `halconfig`; the bucket lists anonymously in one request.
source: `curl -s "https://storage.googleapis.com/halconfig?prefix=bom/&max-keys=1000"`
→ 200, 206943 B, `<Name>halconfig</Name>`, `<IsTruncated>false</IsTruncated>`, 834 `<Key>`.

CLAIM-S3-002: 346 of those keys match `bom/<x>.<y>.<z>.yml` and are the releases
(the other 488 are nightlies, `bom/master-<ts14>.yml`, plus `bom/io-codelab.yml`).
They span 1.0.0 → 2026.3.0: 302 on the 1.x train (1.0.0…1.38.0), 44 CalVer
(2025.0.0…2026.3.0). source: the listing above; all 346 then fetched from
`https://storage.googleapis.com/halconfig/bom/<v>.yml`, 0 failures.

CLAIM-S3-003: `https://storage.googleapis.com/halconfig/versions.yml` is the
supported-version manifest Halyard reads, not a release index — 730 B,
`latestSpinnaker: 2026.3.0`, ~10 entries plus `illegalVersions`. Halyard is not
needed to enumerate releases.

CLAIM-S3-004: A BOM pins twelve keys: the nine JVM services in scope, plus
`deck`, `monitoring-daemon`, `monitoring-third-party`, a `defaultArtifact: {}`
placeholder, and in the first 38 BOMs a `spinnaker` meta-package. Each entry has
`version` and (from 1.2.0) `commit`. 52 BOMs (1.19.12–1.26.7) quote their keys.
source: `curl -s https://storage.googleapis.com/halconfig/bom/1.38.0.yml`.

CLAIM-S3-005: Pinned versions resolve to live manifests with digests.
`gcr.io/spinnaker-marketplace/gate:1.19.0-20201012200017` (1.23.7's pin) → 200,
`sha256:31fdb568e0b687dd45da245705cc9414aa51aa6d770b149ea3ce246842416635`;
`us-docker.pkg.dev/spinnaker-community/docker/clouddriver:5.95.0` (1.38.0's pin)
→ 200, `sha256:4db25c293d928c32a7b60cfeb9bdbd408726b53f871e5b4b2da4bfa607e82e99`.
No `Authorization` header on either. source: `curl -s -D - -o /dev/null -H
"Accept: application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.index.v1+json"
https://<host>/v2/<repo>/<svc>/manifests/<tag>`.

CLAIM-S3-006: **No BOM pins Keel — 0 of 346.** source: parse of all 346; the
`services:` census is clouddriver/deck/echo/fiat/front50/gate/igor/orca/rosco/
monitoring-daemon/monitoring-third-party = 346 each, kayenta 325, spinnaker 38,
defaultArtifact 211, keel 0.

CLAIM-S3-007: Kayenta is absent from the 21 BOMs 1.0.0…1.6.2, pinned from 1.7.0.
source: same parse.

CLAIM-S3-008: Images live in three registries in sequence, all anonymously
readable: `gcr.io/spinnaker-marketplace` (4608 gate tags; oldest, `0.4.0-411`,
resolves → `sha256:4477cb5b8508743b9327a55e6a6cab572df45e3c9406abd99cfe6eb965177f69`),
`us-docker.pkg.dev/spinnaker-community/docker` (626 gate tags), `ghcr.io/spinnaker`
(514 gate tags, bearer token issued to anonymous callers by
`https://ghcr.io/token?scope=repository:spinnaker/gate:pull&service=ghcr.io`).
source: `GET /v2/<repo>/gate/tags/list` on each.

CLAIM-S3-009: `artifactSources.dockerRegistry` does not record where an old
image lives: 337 BOMs (1.0.1–2026.0.4) all name `us-docker.pkg.dev/…`, including
2017 releases whose images exist only on gcr.io; only 2026.1.0–2026.3.0 name
`ghcr.io/spinnaker`; 1.0.0 names none. The historical BOMs were rewritten.

CLAIM-S3-010: `tags/list` is unpaginated on GAR/GCR (no `Link` header; `?n=10000`
returns the same 626 gate tags), `HEAD` on these endpoints returns 405, and
`_catalog` is closed (GAR 302, GCR `UNAUTHORIZED`). Enumerate by service name.

CLAIM-S3-011: The 346 BOMs contain 1470 distinct (service, pinned version) pairs
for the nine pinned services. 1265 appear in a tag list, and a manifest GET for
**every one returned 200 with a digest** — no failures, no rate limiting at 14
concurrent. source: `verify.py` → `verified 1265 Counter({'200': 1265})`; digests
recorded per row in `boms.tsv` as `<ref>@sha256:<digest>`.

CLAIM-S3-012: 296 of 346 releases have every pinned service retrievable as an
image. The 50 that do not are exactly the consecutive block 1.24.0…1.29.7.

CLAIM-S3-013: Nothing recovers that block from a registry. Direct GETs 404
(`gate:6.54.2`, `6.55.2`, `6.57.0`, `orca:8.27.0`, `fiat:1.31.5`,
`gate:1.20.0-20201208200018` on GAR); alternate GAR repos
(`…/docker-unvalidated`, `…/community-docker`, `…/spinnaker`,
`spinnaker-marketplace/docker`) and other GAR regions all 401; and no
`spinnaker-<release>` alias tag covers any of the 50 across all nine services.

CLAIM-S3-014: Maven Central carries every module as `io.spinnaker.<svc>:<module>`;
150 of the 205 image-less pairs have a `<svc>-web` jar at 200, covering
1.27.0…1.29.7 completely. `gate-web-6.54.2.jar` = 508209 B; its POM (26539 B)
declares 16 dependencies, 14 sibling `io.spinnaker` modules plus `kork-bom 7.115.2`.
source: `curl -sI https://repo1.maven.org/maven2/io/spinnaker/gate/gate-web/6.54.2/gate-web-6.54.2.jar`;
`mvnverify.py` over 205 pairs → `Counter({'200': 150, '404': 55})`.

CLAIM-S3-015: 55 pairs exist nowhere — exactly the pins of 1.24.0…1.26.7 (24
releases, the timestamped-version era). Maven's floor per service (gate 6.52.0,
orca 8.15.0, clouddriver 5.74.0, front50 2.23.1, echo 2.32.1, igor 4.5.0, fiat
1.27.0, rosco 1.7.2, kayenta 2.28.0, keel 0.185.1) is above every 1.26.7 pin.
source: `maven-metadata.xml` per `io.spinnaker.<svc>:<svc>-web`.

CLAIM-S3-016: Two dead ends. `https://dl.bintray.com/spinnaker-releases/debians/dists/trusty/Release`
→ 404. `GET /repos/spinnaker/{gate,spinnaker}/releases` returns entries with
`assets = 0` throughout — tags and notes only, no jars or debs.

CLAIM-S3-017: BOM `timestamp` is a sound `release_date`: for the 41 releases
GitHub has (2025.0.0+) it matches `published_at` within ~10 s on 39; the two
exceptions (2025.0.1, 2025.0.2) are BOMs regenerated 9 and 4 days late. GCS
`LastModified` is useless — 238 of 346 objects carry a 2020-11 bulk-rewrite mtime.
source: `curl -s "https://api.github.com/repos/spinnaker/spinnaker/releases?per_page=100"`.

CLAIM-S3-018: Cadence: minor lines every 58 days (median of 47 intervals; mean
72), 1–16 patches each; 1.0.0 = 2017-06-05, 2026.3.0 = 2026-09-07. One anomaly:
371 days between 1.26.0 (2021-04-23) and 1.27.0 (2022-04-29) — the same window
as the artifact hole. source: BOM `timestamp`s.

CLAIM-S3-019: Images are an exploded Gradle `installDist` tree, never a Spring
Boot fat jar. Image A (`gcr.io/…/gate:1.19.0-20201012200017`, Alpine 3.11.6,
`apk add openjdk11-jre`) unpacks to `/opt/gate/{bin,lib,config,plugins}` with 324
jars; `gate-web.jar` has no `BOOT-INF/`, classes at `com/netflix/spinnaker/…`.
Same shape in image B (`…/orca:8.31.0`, Alpine 3.16.4, 345 jars) and image C
(`…/clouddriver:5.95.0`, Alpine 3.20.6, `/usr/lib/jvm/java-17-openjdk`, 867 jars).
source: layers pulled and unpacked under `scratchpad/spinnaker/S3/img/`.

CLAIM-S3-020: The runtime classpath is written out literally:
`/opt/gate/bin/gate` contains `CLASSPATH=$APP_HOME/config:$APP_HOME/lib/gate-web.jar:
$APP_HOME/lib/gate-x509.jar:…` in dependency order. G2 should parse that, not glob.

CLAIM-S3-021: App-jar naming changes at the registry boundary: GCR era the
service's own jars are unversioned (`gate-web.jar`) with versioned dependencies
(`kork-core-7.78.0.jar`); GAR era all versioned (`orca-web-8.31.0.jar`).

CLAIM-S3-022: The metadata the extractor needs is in the released bytecode.
`gate-core.jar!…/services/internal/OrcaService.class` (6200 B, major 55) has
`RuntimeVisibleAnnotations`, `RuntimeVisibleParameterAnnotations`, `Signature`,
descriptors `Lretrofit/http/{GET,POST,PUT,DELETE,Path,Query,Body,Headers};`, and
literal templates `/pipelines/{id}`, `/tasks/{id}/cancel`, `/v2/pipelineTemplates/plan`
and 15 more. `gate-web.jar` holds 66 `*Controller.class`; `PipelineController`
carries `RequestMapping`, `RequestBody`, `PathVariable`, `RequestParam`,
`RuntimeVisibleAnnotations`, `Signature`. source: constant-pool scan of those jars.

CLAIM-S3-023: `MethodParameters` is **absent** (not compiled with `-parameters`);
`LocalVariableTable` and `LineNumberTable` are present. Parameter names must come
from annotation values or the debug table. source: same scan.

CLAIM-S3-024: All ten services retain the metadata, checked on the Maven `-web`
jars at the 1.38.0 pins (Keel at 2025.0.0): all class major 61, Spring MVC
annotations on 3–74 classes each, `Signature` on 4–148. Retrofit annotations in
gate-web (5) and igor-web (22); other services keep their Retrofit interfaces in
non-`web` modules. `keel-web-2025.0.0.jar` has `kotlin.Metadata` on **all 333**
classes; `orca-core-8.31.0.jar` on 55 of 232.

CLAIM-S3-025: JDK, sampled at one release per minor line × nine services (371
image config blobs): Java 8 from 1.0.0; Java 11 from 1.19.0 (front50, igor one
line earlier at 1.18.0); Java 17 from 1.33.0 (front50, igor at 1.32.0). Nothing
needs newer than 17.

CLAIM-S3-026: Size. Nine services per release = 2.10 GB (1.10.0), 2.65 (1.23.0),
3.20 (1.30.0), 3.54 (1.38.0) compressed. Clouddriver alone is 1.32 GB at 5.95.0
and unpacks to 2.1 GB. The `/opt/<svc>` COPY is one layer — 4 of 6 in A and B,
11 of 13 in C — at 59%, 70% and 42% of compressed total.

CLAIM-S3-027: Longest contiguous runs where every pinned service is retrievable.
Images only: **1.0.0…1.23.7, 202 releases / 201 pairs**; then 1.30.0…2026.3.0,
94 / 93. With the Maven fallback the second becomes 1.27.0…2026.3.0, 120 / 119;
the first is unchanged and the two never join. Over minor-line heads only:
1.0.0…1.23.0, 24 / 23. First and last retrievable release: 1.0.0 and 2026.3.0.

CLAIM-S3-028: This machine has no JDK — `java -version` and `javap` both fail
("Unable to locate a Java Runtime") though shims exist at `/usr/bin/`. Every
bytecode fact above was derived by reading class files with Python. G1 needs a
real JDK 17.

**Verdict: GO on reflection over released artifacts.** Recommended range
`1.30.0…1.38.0` (all images, one registry, uniform jar naming), with
`1.0.0…1.23.7` as the deep-history extension. D2 must be corrected: the
BOM-driven mesh is **nine** services; Keel is in no BOM and can only be added
synthetically.

## What I could not verify

* **That an artifact is complete, not merely present.** I confirmed a live
  manifest and digest for all 1265 pairs; I unpacked the layers of only three.
  A blob could be garbage-collected behind a live manifest. Cheap guard for G2:
  HEAD the `/opt/<svc>` layer blob, not just the manifest.
* **That the Maven fallback yields a usable classpath.** Jars and POMs download
  and the POM names the sibling modules and `kork-bom`, but I ran no resolve, so
  I cannot say the transitive graph still resolves for 2022-era versions. The
  1.27.0–1.29.7 band is unproven; the recommendation does not depend on it.
* **The exact patch release at each JDK boundary.** Sampled at 48 minor-line
  anchors, so CLAIM-S3-025 is exact to the minor line only. `boms.tsv` fills
  `jdk` on those 1063 rows and leaves the rest blank rather than interpolating.
* **Release dates below 2025.0.0 against an independent source.** Cross-checked
  only where GitHub releases exist (41 of 346); for 1.x I rely on the BOM's
  self-reported build time. The spinnaker.io changelog pages would be the
  independent check and I did not fetch them.
* **Why 1.24–1.26 vanished.** The dates coincide with the Bintray/JCenter sunset
  and the GCR→GAR migration, but I found no project statement saying so. That
  inference is unsourced and should not be repeated as fact.
* **Whether the GCR-era images are safe to depend on.** gcr.io is a deprecated
  Google product being folded into Artifact Registry. It served every request
  today, but the 201-pair run rests entirely on it and I found no commitment or
  mirror.
* **arm64.** I resolved and inspected `linux/amd64` only; multi-arch children
  exist from the GAR era on and I did not check they carry the same classpath.
* **`retrievable = unknown`.** Nothing required auth, so that value never occurs
  in `boms.tsv`. I cannot rule out a repository I did not name that would.
