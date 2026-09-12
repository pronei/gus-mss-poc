# S3 — released artifacts: BOMs, registries, classpaths, go/no-go

All facts here are numbered in `memo.md` as `CLAIM-S3-nnn`. Every query below
was read-only and anonymous; nothing in this survey required a credential.
Survey date 2026-09-11/12.

---

## 1. The BOM source

The plan's hypothesis is confirmed and is the real source.

**Index.** The bucket is public and lists in one request:

```
curl -s "https://storage.googleapis.com/halconfig?prefix=bom/&max-keys=1000"
```

834 keys, `IsTruncated=false`. 346 of them match `bom/<major>.<minor>.<patch>.yml`
— those are the releases. The other 488 are nightly/branch BOMs
(`bom/master-<yyyymmddhhmmss>.yml`, `bom/io-codelab.yml`) and are not releases.

**A single BOM.**

```
curl -s https://storage.googleapis.com/halconfig/bom/1.38.0.yml
```

**The supported-version manifest** (what `hal version list` reads) is
`https://storage.googleapis.com/halconfig/versions.yml`. It carries only the
currently supported versions (~10 rows) plus `latestSpinnaker`,
`latestHalyard` and an `illegalVersions` list — it is *not* a release index.
Halyard is therefore unnecessary: the bucket listing is the index, and each
BOM is one plain GET. No Halyard install, no gcloud, no auth.

**BOM shape** (stable across the whole range):

```yaml
artifactSources:
  debianRepository: …
  dockerRegistry: us-docker.pkg.dev/spinnaker-community/docker
  gitPrefix: https://github.com/spinnaker
services:
  gate:   {commit: <sha>, version: 6.69.0}
  orca:   {commit: <sha>, version: 8.64.0}
  …
timestamp: '2025-04-18 20:25:26'
version: 1.38.0
```

52 BOMs in the 1.19.12–1.26.7 band quote their keys (`"gate":`); otherwise the
shape is identical. A parser must strip quotes.

**Release dates.** Use the BOM's own `timestamp`. It agrees with
`spinnaker/spinnaker` GitHub release `published_at` to within ~10 seconds on
39 of the 41 releases GitHub has (2025.0.0 onward); the two exceptions
(2025.0.1, 2025.0.2) are BOMs regenerated after the fact. GitHub releases do
not exist below 2025.0.0, so `timestamp` is the only uniform date source.
Do **not** use the GCS `LastModified` — the whole bom/ prefix was rewritten in
2020-11 and again later, so 238 objects carry a 2020-11 mtime regardless of age.

**Range and cadence.** 1.0.0 (2017-06-05) → 2026.3.0 (2026-09-07); 302 releases
on the 1.x train (1.0.0…1.38.0), then a rename to CalVer at 2025.0.0 (44
releases, 2025.0.0…2026.3.0). Minor lines land every 58 days (median; mean 72),
each carrying 1–16 patch releases. The one anomaly is a 371-day hole between
1.26.0 (2021-04-23) and 1.27.0 (2022-04-29) — the JCenter/Bintray sunset and
the registry migration. That hole is exactly where the artifacts are missing.

**What a BOM pins.** Twelve keys, of which nine are the JVM services in scope:
`clouddriver echo fiat front50 gate igor kayenta orca rosco`. Also `deck`
(the JS UI), `monitoring-daemon`, `monitoring-third-party` (Python), a
`defaultArtifact: {}` placeholder, and in the first 38 BOMs a `spinnaker`
meta-package.

**Keel is never pinned — by any of the 346 BOMs.** This is the single largest
correction to the plan. D2 anticipates "a service absent from a BOM (Keel,
Kayenta in early releases)"; in fact Keel is absent from *every* BOM, so the
BOM-driven mesh is nine services, not ten. Keel images do exist
(`ghcr.io/spinnaker/keel`, 370 tags; `us-docker.pkg.dev/.../keel`, 199 tags) but
only from `2025.0-0` onward, and they carry no `spinnaker-<release>` alias, so
no released BOM ties a Keel version to a Spinnaker release. Keel can only enter
the corpus by an invented pin (e.g. "the Keel tag whose CalVer equals the
release"), which is a synthetic step and should be declared as one.

Kayenta is absent from the first 21 BOMs (1.0.0…1.6.2) and pinned from 1.7.0 on.

---

## 2. The registry situation

Three registries, in sequence. All three serve anonymously.

| era | registry | evidence |
|---|---|---|
| 1.0.0 … ~1.23.x | `gcr.io/spinnaker-marketplace/<service>` | 4608 tags for gate; oldest tag `0.4.0-411` still resolves |
| ~1.28.6 … 2026.0.4 | `us-docker.pkg.dev/spinnaker-community/docker/<service>` | 626 tags for gate |
| 2026.1.0 … | `ghcr.io/spinnaker/<service>` | 514 tags for gate, needs an anonymous bearer token |

The `artifactSources.dockerRegistry` field is **not** a reliable record of where
an old image actually lives: every BOM from 1.0.1 to 2026.0.4 names
`us-docker.pkg.dev/spinnaker-community/docker`, including 2017 releases whose
images only exist on `gcr.io`. The historical BOMs were rewritten during the
migration. A fetcher must try all three registries, not read the field.

Access mechanics:
* GAR and GCR: plain `GET /v2/<repo>/<name>/tags/list` and
  `GET /v2/<repo>/<name>/manifests/<tag>`, no `Authorization` header at all.
  `HEAD` returns 405 — use `GET` with `-o /dev/null -D -` to read the digest.
  `tags/list` is not paginated for these repos (no `Link` header; `?n=10000`
  returns the same count).
* GHCR: fetch `https://ghcr.io/token?scope=repository:spinnaker/<svc>:pull&service=ghcr.io`,
  which returns a token to anonymous callers, then pass it as a bearer.
* `_catalog` is closed on both Google registries (302 / UNAUTHORIZED). Enumerate
  by service name, not by catalog.

**Verification performed.** Of 1470 distinct `(service, pinned_version)` pairs
across all 346 BOMs, 1265 were listed in a tag list, and a manifest `GET` for
every one of those 1265 returned **HTTP 200 with a content digest** — no
partial availability, no rate limiting observed at 14 concurrent requests.
The digests are recorded per row in `boms.tsv` (`artifact_ref` is written as
`<ref>:<tag>@sha256:<digest>`, so each row is self-verifying).

**The hole.** 205 pairs are in no registry. They fall entirely inside
1.24.0–1.29.7 (50 consecutive releases). Nothing recovers them from a registry:
the alternate GAR repo names, the other GAR regions, and the
`spinnaker-<release>` alias tags all 401 or 404.

**The Maven fallback.** Spinnaker publishes every service module to Maven
Central under `io.spinnaker.<service>:<module>`. 150 of the 205 image-less
pairs have a `repo1.maven.org` `<service>-web` jar (HTTP 200), which covers
1.27.0–1.29.7 completely. The remaining 55 — all of 1.24.0–1.26.7, the
timestamped-version era — exist nowhere. Maven Central's floor per service is
gate 6.52.0, orca 8.15.0, clouddriver 5.74.0, front50 2.23.1, echo 2.32.1,
igor 4.5.0, fiat 1.27.0, rosco 1.7.2, kayenta 2.28.0, keel 0.185.1.

A Maven jar is *not* a classpath: `gate-web-6.54.2.jar` is one module. Its POM
does list all 14 sibling `io.spinnaker` modules plus `kork-bom`, so a Gradle or
Maven resolve reconstructs the classpath — but that is a second, different
extraction path with its own fidelity risk, and it should not be mixed silently
with the image path.

Two dead ends worth recording so nobody re-checks them: the Debian repository
named by pre-1.27 BOMs (`dl.bintray.com/spinnaker-releases/debians`) is gone,
and the `spinnaker/*` GitHub releases carry **zero assets** — they are tag +
notes only.

---

## 3. Classpath layout inside the images

Three images were downloaded in full and unpacked (one per era). The layout is
identical in all three and is the friendliest possible shape for reflection.

| | A | B | C |
|---|---|---|---|
| image | `gcr.io/spinnaker-marketplace/gate:1.19.0-20201012200017` | `us-docker.pkg.dev/…/orca:8.31.0` | `us-docker.pkg.dev/…/clouddriver:5.95.0` |
| release | 1.23.7 (end of run A) | 1.30.0 (start of run B) | 1.38.0 (end of 1.x) |
| digest | `sha256:31fdb568e0b6…` | `sha256:8e6f2a13637a…` (amd64 child) | `sha256:4db25c293d92…` (index) |
| base | Alpine 3.11.6 | Alpine 3.16.4 | Alpine 3.20.6 |
| JDK | `apk add openjdk11-jre` | `apk add openjdk11-jre` | `/usr/lib/jvm/java-17-openjdk` |
| class file major | 55 (Java 11) | 55 (Java 11) | 61 (Java 17) |
| app root | `/opt/gate` | `/opt/orca` | `/opt/clouddriver` |
| jars in `lib/` | 324 | 345 | 867 |
| compressed layers | 163 MB | 211 MB | 1322 MB |

* **Exploded, never a fat jar.** Every image is a Gradle `installDist` tree:
  `/opt/<svc>/bin/<svc>` (the generated start script), `/opt/<svc>/lib/*.jar`,
  `/opt/<svc>/config`, `/opt/<svc>/plugins`. `gate-web.jar` has no `BOOT-INF/`;
  classes sit at `com/netflix/spinnaker/…` at the jar root.
* **The classpath is written down.** The start script contains one literal
  line, `CLASSPATH=$APP_HOME/config:$APP_HOME/lib/<first>.jar:…`, in dependency
  order. G2 should parse that line rather than globbing `lib/`, so that the
  extracted classpath is the runtime classpath.
* **App-jar naming changes at the registry boundary.** In the GCR era the
  service's own jars are unversioned (`gate-web.jar`, `gate-core.jar`) while
  dependencies carry versions (`kork-core-7.78.0.jar`, `fiat-api-1.26.0.jar`).
  In the GAR era everything is versioned (`orca-web-8.31.0.jar`). A fetcher that
  keys on `<svc>-web-<version>.jar` breaks on run A.
* **`Cmd` is `["/opt/<svc>/bin/<svc>"]`, `User` is `spinnaker` (uid 10111).**
  Nothing needs to run: unpacking the layers is enough.
* Clouddriver is the outlier — it also ships google-cloud-sdk, five kubectl
  releases, aws-cli and python, which is why it is 4–6x the size of the others.

**The reflection route works on these bytes.** Checked on
`gate-core.jar!com/netflix/spinnaker/gate/services/internal/OrcaService.class`
(image A): `RuntimeVisibleAnnotations` and `RuntimeVisibleParameterAnnotations`
present; the constant pool holds `Lretrofit/http/GET;`, `POST;`, `PUT;`,
`DELETE;`, `Path;`, `Query;`, `Body;`, `Headers;`; `Signature` attributes are
present (so generic return types survive); the literal path templates
(`/pipelines/{id}`, `/tasks/{id}/cancel`, `/v2/pipelineTemplates/plan`, …) are
readable. On the provider side, `gate-web.jar` holds 66 `*Controller.class`
with `RequestMapping`, `RequestBody`, `PathVariable`, `RequestParam` and
`Signature`.

One real caveat for G1: **`MethodParameters` is absent** (the services are not
compiled with `-parameters`). Parameter *names* must come from the annotation
value (`@Path("id")`, `@RequestParam("expand")`) or from `LocalVariableTable`,
which is present. A Spring parameter annotation written without an explicit
name will therefore not yield a name from the annotation alone — S5 should cost
the `LocalVariableTable` fallback.

All ten services (Keel included) were confirmed to retain Spring/Retrofit/
`Signature` metadata, using the small Maven `-web` jars rather than more full
images. `keel-web-2025.0.0.jar` carries `kotlin.Metadata` on **all 333** of its
classes, so D8's Kotlin nullability plan is viable on Keel; the other nine are
predominantly Java/Groovy with Kotlin pockets (orca-core: 55 of 232 classes).

**JDK by era** (sampled at one release per minor line, so a boundary is exact
to the minor line, not to the patch): Java 8 from 1.0.0; Java 11 from 1.19.0
(front50 and igor moved one line earlier, at 1.18.0); Java 17 from 1.33.0
(front50 and igor at 1.32.0). Nothing in the range needs a JDK newer than 17,
and an extractor built on Java 17 reads class files of major 52/55/61 without
trouble.

---

## 4. GO / NO-GO on the reflection route

**GO**, with one correction to D2 and one choice to make about the middle of
the range.

The route is confirmed, not assumed: released artifacts are retrievable
anonymously for 296 of 346 releases; the classpath inside them is an exploded
Gradle tree with the runtime classpath written out in plain text; and the
annotation and generic-signature metadata the extractor needs is present in
every one of the ten services' compiled classes.

**First and last retrievable release: 1.0.0 and 2026.3.0.** Every release in
between is retrievable except the 50 in 1.24.0–1.29.7.

**Longest contiguous run, container images only: `1.0.0 … 1.23.7` — 202
consecutive releases, 201 consecutive pairs**, every one of the nine pinned
services present with a live digest. Second-longest: `1.30.0 … 2026.3.0`, 94
releases / 93 pairs. Restricting to minor-line heads only, the longest run is
`1.0.0 … 1.23.0` — 24 heads / 23 pairs.

**With the Maven Central fallback**, the second run extends to `1.27.0 …
2026.3.0` — 120 releases / 119 pairs. The first run is unchanged, and the two
still do not join: 1.24.0–1.26.7 (24 releases) has no artifact of any kind.

Either run clears R4's eight-pair minimum by more than an order of magnitude,
so the range is not the binding constraint. **Recommendation: build on
`1.30.0 … 1.38.0`** (9 minor lines, 50 releases including patches, so 49
consecutive pairs; all images, Java 11→17, all nine services, GAR only, one
auth story) **and treat `1.0.0 … 1.23.7` as the deep-history extension** once
G1 is stable. Reasons to prefer the recent run over the longer old one: it is
the era S1/S2/S6 are reading, the app-jar naming is uniform, the images are
multi-arch with content digests, and it does not require the extractor to also
handle Java 8 bytecode and unversioned jars. The 201-pair run is the fallback
if the recent run turns out to be too short for a prevalence claim — which D12
already says will not be made.

Conditions that would flip this to SCOPED-GO: if Keel must be in the mesh, the
run is scoped to CalVer (2025.0.0 onward) and the Keel pin is synthetic; if the
extractor turns out to need the full transitive classpath rather than the
service jars alone, the Maven fallback dies and the middle run is 1.30.0–2026.3.0.

---

## 5. What a fetcher (G2) needs

* **No credentials, anywhere.** GAR and GCR are open; GHCR hands anonymous
  callers a token from a plain GET. Record this as a property of the corpus:
  if any query ever needs auth, that release is `unknown`, not `no`.
* **No Halyard, no gcloud, no docker daemon.** Everything in this survey was
  `curl` plus `tarfile`. Layer blobs are gzipped tars; digests verify
  (`sha256(blob) == layer.digest`) on every layer of all three images pulled.
* **Handle three manifest shapes**: v2 manifest (GCR era), v2 manifest *list*
  (GAR, e.g. orca 8.31.0), and OCI image index with attestation children whose
  platform is `unknown/unknown` (GAR 1.38.0, GHCR). Select
  `platform.os == linux && platform.architecture == amd64`.
* **Sizes.** One release across the nine services is 2.1 GB (1.10.0), 2.7 GB
  (1.23.0), 3.2 GB (1.30.0), 3.5 GB (1.38.0) of *compressed* layers; the
  unpacked clouddriver rootfs alone is 2.1 GB. A nine-release run
  (1.30.0…1.38.0) is roughly 30 GB compressed if pulled whole. Pull only the
  layer that contains `/opt/<service>` — it is a single `COPY` layer in every
  image (layer 4 of 6 in A and B; layer 11 of 13 in C) and is 59% of A,
  70% of B and 42% of C by compressed bytes. Better still, extract
  only `opt/<svc>/bin/<svc>` and `opt/<svc>/lib/*.jar`.
* **Rate limits.** None hit. 1265 manifest GETs at 14 concurrent, 371 config-blob
  probes, and 346 BOM GETs all completed with zero non-200s. GitHub's API is the
  one limited surface (60/hour unauthenticated) and is only needed for release
  notes (S4), not for artifacts.
* **Cache key.** The BOM version plus the per-service manifest digest already
  recorded in `boms.tsv` — that is `corpus.lock`, already computed for the whole
  range.
* **This machine has no JDK.** `java`/`javap` are shims that fail
  ("Unable to locate a Java Runtime"). Every bytecode fact above was derived by
  reading class files with Python. G1 will need a real JDK 17 installed.

---

## 6. Schema note

`boms.tsv` has one row per (release, service) for all ten services and all 346
releases (3460 rows). Two deviations from the schema's parenthetical, both
deliberate and both flagged here:

* For a service the BOM does not pin, `artifact_kind` is `not-pinned`,
  `pinned_version` is `-`, and **`retrievable` is `n/a`** rather than one of
  yes/no/unknown. "No" would be false (there is no version to fail to retrieve)
  and would corrupt R1's "longest run with retrievable = yes for every pinned
  service". Filter on `artifact_kind != 'not-pinned'` to apply R1. 367 rows:
  346 Keel + 21 Kayenta.
* `artifact_kind` takes four values: `container-image` (2658 rows),
  `maven-jar` (219), `not-pinned` (367), `none` (216, the 1.24.0–1.26.7 hole).

`jdk` is filled on the 1063 rows whose image config blob was actually read
(one release per minor line × nine services); it is blank elsewhere rather
than interpolated.
