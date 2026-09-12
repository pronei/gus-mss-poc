# S4 memo - Spinnaker release history as candidate ground truth

Claim numbering is shared between this memo and `ground-truth-candidates.md`:
**CLAIM-S4-003 through CLAIM-S4-040 are the thirty-eight rows of that table**, each
carrying its own verbatim quote and source URL. This memo numbers only its own
statements (001, 002, and 041 onward). No row was labelled from a code diff.

CLAIM-S4-001: The per-version Spinnaker changelogs are published at
`https://spinnaker.io/changelogs/<version>-changelog/` and their markdown sources
live in one directory of the docs repository, 346 files covering 1.0.0 to 2026.3.0.
source: https://github.com/spinnaker/spinnaker.io/tree/master/content/en/changelogs

CLAIM-S4-002: 121 Spinnaker releases have a changelog page dated inside the last
five years (1.25.8, 2021-12-15, through 2026.3.0, 2026-09-07); each release, its
date and its changelog URL are in `releases.tsv`, taken from the `version` and
`date` fields of that page's front matter. The train changes name at 2025.0.0,
which the project states is "the first version of Spinnaker released from the
monorepo" and "equivalent to version 1.38.0".
source: https://spinnaker.io/changelogs/2025.0.0-changelog/

CLAIM-S4-053: For all 41 monorepo releases (2025.0.0 onward) the changelog page date
in `releases.tsv` equals the `published_at` date of the matching
`spinnaker-release-<version>` GitHub release object, with no discrepancies. The
pre-monorepo 1.x releases have no such release objects, so their dates rest on the
changelog page alone.
source: https://github.com/spinnaker/spinnaker/releases

## Counts

CLAIM-S4-041: The 38 candidates break down as `compat-note` 21, `breaking` 14,
`deprecation-removed` 2, `upgrade-order` 1.
source: /Users/pronei/work/faults-lab/service-beds/gus/.claude/worktrees/experiments/experiments/spinnaker/scout/S4/ground-truth-candidates.md

CLAIM-S4-042: Sources that yielded candidates: the spinnaker.io changelog pages
(29 rows), spinnaker/spinnaker issues (6 rows, from issues 6970, 7021, 7054, 7226
and 7316 - 7226 supplies two rows, one of them a maintainer comment), two
spinnaker/spinnaker pull requests (7060 and 7201), and one spinnaker/spinnaker.io
pull request (504).
source: /Users/pronei/work/faults-lab/service-beds/gus/.claude/worktrees/experiments/experiments/spinnaker/scout/S4/ground-truth-candidates.md

## Two worked examples (the fixed R2 sample lands here)

CLAIM-S4-005 is the Orca-to-Igor row: "Introduce a feature flag in Orca to use the
new Igor `stop` endpoint. By default, if not enabled the existing endpoint (`PUT
/masters/{name}/jobs/{jobName}/stop/{queuedBuild}/{buildNumber}`) will be called".
source: https://spinnaker.io/changelogs/1.29.0-changelog/#orca

CLAIM-S4-008 is the trigger-artifact row: "If you've relied on this bug, you'll need
to add manually add all the artifact constraints to all triggers to replicate the
previous behavior."
source: https://spinnaker.io/changelogs/1.30.0-changelog/#changes-to-the-way-artifact-constraints-on-triggers-work

## Releases with no compatibility statement

CLAIM-S4-043: 101 of the 121 in-range releases are the target of no candidate row at
all. Only 20 are: 1.28.0, 1.29.0, 1.30.0, 1.31.0, 1.32.0, 1.34.0, 1.35.0, 1.35.1,
1.36.0, 1.37.0, 1.37.6, 1.38.0, 2025.0.3, 2025.1.0, 2025.1.2, 2025.1.3, 2025.2.0,
2025.2.2, 2026.2.0, 2026.3.0.
source: /Users/pronei/work/faults-lab/service-beds/gus/.claude/worktrees/experiments/experiments/spinnaker/scout/S4/releases.tsv

CLAIM-S4-044: Even among the 21 minor releases in range, seven carry no candidate:
1.27.0, 1.33.0, 2025.0.0, 2025.3.0, 2025.4.0, 2026.0.0, 2026.1.0. The 1.27.0 page is
a bare gist embed with no prose at all, and 2025.0.0 states only that it equals
1.38.0. Patch releases below `.0` are almost always a bare commit list: of the 100
patch releases in range only six are named by a candidate - 1.35.1, 1.37.6, 2025.0.3,
2025.1.2, 2025.1.3 and 2025.2.2 - and every one of those six is named by an issue or
a pull request, never by its own changelog page.
source: https://spinnaker.io/changelogs/1.27.0-changelog/

## Patterns

CLAIM-S4-045: The recurring service pairs, counting a row once per pair of services
it names, are orca-clouddriver 12, orca-front50 6, deck-orca 6, echo-orca 5,
echo-front50 5, clouddriver-deck 4, orca-rosco 4, gate-fiat 4. Orca appears in 26 of
38 rows; kayenta appears in one and keel in none.
source: /Users/pronei/work/faults-lab/service-beds/gus/.claude/worktrees/experiments/experiments/spinnaker/scout/S4/ground-truth-candidates.md

CLAIM-S4-046: The single largest cause of documented cross-service breakage in range
is the Retrofit 1 to Retrofit 2 migration of the service clients, which the project
tracked as a multi-release effort: Echo, Fiat, Clouddriver and Gate in 1.37.0, Igor
in 1.38.0, and Orca, Kayenta and Halyard in 2025.1.0. Five candidate rows (CLAIM-S4-021, -023,
-024, -030 and -032) are failures of a caller's declared interface introduced by that
migration.
source: https://spinnaker.io/changelogs/2025.1.0-changelog/#retrofit2-upgrade

CLAIM-S4-047: Only one statement in five years of changelogs prescribes an upgrade
order, and it names three services: "it is recommended first to deploy `clouddriver`,
followed by `orca`, then lastly `rosco`" (1.32.0, artifact store). No other release
note, issue or pull request found in this survey states an ordering constraint.
source: https://spinnaker.io/changelogs/1.32.0-changelog/#artifact-store

## Rows that need the reviewer's attention

CLAIM-S4-048: CLAIM-S4-019 (orca-to-front50 okhttp timeout properties) is quoted
from a documentation pull request that was **closed without merging** on 2025-05-12,
so the statement is public but never appeared on the published 1.36.0 changelog; the
live page contains no "Breaking Changes" section.
source: https://github.com/spinnaker/spinnaker.io/pull/504

CLAIM-S4-049: CLAIM-S4-032 uses the pair 2025.1.1 -> 2025.1.2 because that is the
release boundary at which the fix (backport pull request 7204, merged to
`release-2025.1.x` on 2025-08-19, two days before 2025.1.2) landed. No source states
which release introduced the parameter-order defect, so the pair marks the repair,
not the break.
source: https://github.com/spinnaker/spinnaker/pull/7204

CLAIM-S4-050: Plan D10 requires two independent labelers once S4's list exceeds
twenty claims. This list has 38 rows, so the threshold is crossed and a second
labeler is required before these rows are treated as ground truth.
source: /Users/pronei/work/faults-lab/service-beds/gus/.claude/worktrees/experiments/experiments/spinnaker/PLAN.md (section 4, D10)

CLAIM-S4-051: Read and deliberately excluded, as build- or configuration-surface
changes rather than inter-service HTTP: the Spring Boot / Spring Security upgrades
and their Redis session invalidation (1.29, 1.30, 1.34, 1.35, 2025.2.0, 2025.4.0),
the Java, Groovy, Kotlin and Gradle upgrades, the removal of retrofit1 from
spinnaker-dependencies (2025.1.0), the AWS credential constructor changes and
`S3ArtifactValidator` (2025.2.0, 2025.3.0), the GAR-to-GHCR image move, Halyard's
deprecation and removal, Angular removal, and the 2027.0.0 storage deprecations.
source: https://spinnaker.io/changelogs/2026.3.0-changelog/#removals-and-deprecations

CLAIM-S4-052: Quotes taken from spinnaker.io changelog pages are transcribed from
the markdown source of that page in the docs repository rather than from the
rendered HTML, so they keep backtick code spans and straight apostrophes where the
rendered page shows `<code>` spans and typographic apostrophes; the wording is
identical. A reviewer matching a quote against the rendered page must normalise
apostrophes (for example CLAIM-S4-008 renders as "If you’ve relied on this bug").
source: https://github.com/spinnaker/spinnaker.io/blob/master/content/en/changelogs/1.30.0-changelog.md

## What I could not verify

1. **Release dates are changelog page dates, not verified ship dates.** `releases.tsv`
   takes `release_date` from each changelog page's `date:` front-matter field. Several
   of these are visibly the date the page was written rather than the date the release
   shipped: 1.27.0's page is dated 2022-05-02 while 1.27.1's is dated 2022-08-18 and
   1.28.0's 2022-08-21, and 1.25.8/1.26.7 both carry 2021-12-15. I could not find a
   machine-readable ship-date list for them: `https://storage.googleapis.com/halconfig/versions.yml`
   returns only the five currently supported versions, and `spinnaker/spinnaker` has
   GitHub release objects only from 2025.0.0 onward (CLAIM-S4-053), which is exactly
   the range where I could confirm the dates. For 1.25.8 through 1.38.0 the dates are
   unconfirmed; S3 should be treated as the authority on dates and BOM ordering.
2. **Ordering of the pairs across trains.** Spinnaker maintains several release lines
   at once, so "consecutive by date" and "consecutive by version" disagree (1.28.10 is
   dated 2024-08-09, after 1.35.0). I recorded the pair as the source states it and
   used the `1.N.x -> 1.M.0` form for minor-release notes; I did not verify against the
   BOM sequence, which is S3's output.
3. **The three gist-hosted changelogs (1.25.8, 1.26.7, 1.27.0) were not opened.**
   Their pages embed `gist.github.com/spinnaker-release/...` scripts rather than
   inline markdown; the released text is a per-service commit list. I did not fetch
   and read the gist bodies, so a prose compatibility note inside them would have been
   missed.
4. **No Slack or forum evidence.** `spinnakerteam.slack.com` has no public archive,
   and `community.spinnaker.io`, the Discourse forum the project's own community page
   points at, no longer resolves in DNS. The `spinnaker-announce` Google Group was not
   read. Any compatibility guidance that lived only in those channels is absent here.
5. **Issue and pull-request search is keyword-bounded, so recall is unknown.** I
   searched the `spinnaker` org for "breaking change", "backwards incompatible",
   "upgrade order", "version skew", "after upgrading to", "X-SPINNAKER-ACCOUNTS", and
   for `spin-<service>` hostnames with HTTP status codes. Only `spinnaker/keel` has a
   `breaking` label and its single tagged issue is from 2019, outside the window; none
   of the other ten repositories has a compatibility, breaking-change or upgrade-order
   label at all, so there is no label-complete list to enumerate against. Rows drawn
   from issues are therefore a sample, not a census.
6. **Whether an issue-reported failure is a genuine interface change.** Rows CLAIM-S4-016, -021,
   -023, -030 and -035 quote user reports. A maintainer acknowledged -021, -023 and
   -030 and fixes were merged for -023 and -030; I reproduced none of them, and -016
   and -035 carry no maintainer confirmation of root cause.
7. **Which concrete release first shipped each documented change.** Changelog prose
   attributes a change to the minor line (for example "Spinnaker 1.30"), not to a
   patch. Where an issue names versions I used them; elsewhere the left side of a pair
   is written `1.N.x` because I could not verify the exact predecessor patch.
