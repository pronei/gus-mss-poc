# S1 memo — topology of the ten-service mesh

Method: shallow clone of each repository at its latest release tag, ripgrep over
`retrofit.http.*` / `retrofit2.http.*` imports to find every declared client,
then read the Spring configuration that instantiates each one to resolve its
target. No builds, no artifacts, source only. The parser and the hand-verified
interface→provider map are kept beside this memo in `scout/S1/tools/`
(`extract.py`, `build_edges.py`, `mesh.tsv`); re-running
`python3 tools/build_edges.py` from a directory holding the ten clones of
CLAIM-S1-001 regenerates `edges.tsv`. Every row the parser produced was
reconciled against a direct annotation count per file, and 25 rows were re-read
by hand against the source (see CLAIM-S1-020).

**CLAIM-S1-001**: the corpus is these ten repositories at these tags and
commits. source: `git ls-remote --tags` + `git rev-parse HEAD` on each clone,
2026-09-11.

| repo | tag | commit |
|---|---|---|
| gate | v6.69.0 | 1af7f70af0bec53e17f362beac5fd3d754fc6280 |
| orca | v8.64.0 | 2fdb327a9f67345c4919e1503ff5119fa3c31caf |
| clouddriver | v5.95.0 | 5e0ce2abb37cce236e4fb65b5f1ffa4ee781346e |
| front50 | v2.41.0 | ceda49e0cb67925d85f0dc7f928c8909f53f1813 |
| echo | v2.47.2 | 38c2df6d67593962b8d981526cbdd69805bf817a |
| igor | v4.22.0 | 627ec479540511c3b46708f56b3fd4967bf40e25 |
| fiat | v1.57.0 | 1c7fb38cd9bb3c3ea6c81d364612ca7abaadfe6a |
| rosco | v1.26.0 | 0ae53eb04d872050841dd813d993d7e5c38ea50f |
| kayenta | v2.46.0 | a69573be9d8fededacf80817e4151a2c8df41276 |
| keel | v1.4.1 | 1aa966989fc39cf9fb7abf35d3fdc856503ae0d8 |

**CLAIM-S1-002**: Gate creates every internal Retrofit client through one
private helper, `createClient(serviceName, type, dynamicName, forceEnabled)`,
which resolves the endpoint by `serviceConfiguration.getServiceEndpoint(name)`;
that method returns `Endpoints.newFixedEndpoint(service.getBaseUrl())`, i.e.
the config key `services.<name>.baseUrl`. source: gate@v6.69.0
gate-web/src/main/groovy/com/netflix/spinnaker/gate/config/GateConfig.groovy:254
and gate-core/src/main/java/com/netflix/spinnaker/gate/config/ServiceConfiguration.java:76

**CLAIM-S1-003**: Gate has no plain `OrcaService` bean; Orca is reached only
through `OrcaServiceSelector`, built from `createClientSelector("orca",
OrcaService)`. source: gate@v6.69.0
gate-web/src/main/groovy/com/netflix/spinnaker/gate/config/GateConfig.groovy:119

**CLAIM-S1-004**: Gate's `ClouddriverServiceSelector` builds one extra
`ClouddriverService` per entry of `services.clouddriver.config.dynamicEndpoints`
behind a `ByUserOriginSelector`; every one of them still targets Clouddriver, so
the dynamic selection changes the URL, not the provider. source: gate@v6.69.0
gate-web/src/main/groovy/com/netflix/spinnaker/gate/config/GateConfig.groovy:159

**CLAIM-S1-005**: `HealthCheckableService` is a single one-method interface
(`GET /health`) that `DownstreamServicesHealthIndicator` instantiates once per
enabled entry of `serviceConfiguration.healthCheckableServices`, whose default
value is `List.of("orca","clouddriver","echo","igor","flex","front50","mahe",
"mine","keel")`. It is the only interface in the corpus bound to more than one
provider. source: gate@v6.69.0
gate-web/src/main/groovy/com/netflix/spinnaker/gate/health/DownstreamServicesHealthIndicator.groovy:59
and gate-core/src/main/java/com/netflix/spinnaker/gate/config/ServiceConfiguration.java:52

**CLAIM-S1-006**: Gate's `/proxies/{proxyId}/**` proxying is not Retrofit and
declares no contract: `ProxyController` replays the inbound request with a raw
OkHttp client against a URI supplied by operator config or by a
`ProxyConfigProvider` plugin. It contributes no edges. source: gate@v6.69.0
gate-proxy/src/main/kotlin/com/netflix/spinnaker/gate/controllers/ProxyController.kt:53

**CLAIM-S1-007**: Orca's seven Clouddriver interfaces (`OortService`,
`MortService`, `KatoRestService`, `CloudDriverCacheService`,
`CloudDriverCacheStatusService`, `CloudDriverTaskStatusService`,
`FeaturesRestService`) are all built by one helper that stamps
`new DefaultServiceEndpoint("clouddriver", url)`; the read-only and writeable
variants differ only in which configured URL list they draw from. source:
orca@v8.64.0
orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/config/CloudDriverConfiguration.java:203-209
(bean definitions at lines 219-272)

**CLAIM-S1-008**: `fiat-api`'s `FiatService` is the only Retrofit interface
published by one Spinnaker service and compiled into others. Its bean is
declared inside `fiat-api` at
`fiatConfigurationProperties.getBaseUrl()`, and `FiatClientConfigurationProperties`
carries `@ConfigurationProperties("services.fiat")`, so the binding key is
`services.fiat.baseUrl`. source: fiat@v1.57.0
fiat-api/src/main/java/com/netflix/spinnaker/fiat/shared/FiatAuthenticationConfig.java:65
and fiat-api/src/main/java/com/netflix/spinnaker/fiat/shared/FiatClientConfigurationProperties.java:26

**CLAIM-S1-009**: that bean is switched on by the `@EnableFiatAutoConfig`
annotation, which `@Import`s `FiatAuthenticationConfig`; six of the ten services
apply it — Orca (orca-web/…/web/config/WebConfiguration.groovy:47), Clouddriver
(clouddriver-security/…/security/config/SecurityConfig.groovy:31), Front50
(front50-web/…/config/Front50WebConfig.java:59), Echo
(echo-web/…/config/ComponentConfig.java:41), Igor
(igor-web/…/config/IgorConfig.java:49) and Keel
(keel-web/…/config/SecurityConfiguration.kt:12). Gate does not; it declares its
own `@Primary FiatService` from the same key. source: fiat@v1.57.0
fiat-api/src/main/java/com/netflix/spinnaker/fiat/shared/EnableFiatAutoConfig.java:43;
gate@v6.69.0 gate-web/src/main/groovy/com/netflix/spinnaker/gate/config/GateConfig.groovy:125

**CLAIM-S1-010**: Rosco and Kayenta have no dependency on fiat: no `.gradle`
file in either repository mentions `fiat`. source: `rg -n 'fiat' rosco --glob
'*.gradle'` and the same for kayenta on rosco@v1.26.0 / kayenta@v2.46.0, both
empty.

**CLAIM-S1-011**: Kayenta calls none of the other nine services. All twelve of
its Retrofit interfaces are metric or object stores built by
`RetrofitClientFactory.createClient` from a per-account
`RemoteService.getBaseUrl()`, and no Kayenta file references a Spinnaker
service base URL. Its Orca dependencies (`orca-core`, `orca-queue`,
`orca-retrofit`, `keiko-spring`) are library reuse and include none of the
Orca modules that declare Retrofit interfaces. source: kayenta@v2.46.0
kayenta-core/src/main/java/com/netflix/kayenta/retrofit/config/RetrofitClientFactory.java:99

**CLAIM-S1-012**: exactly one interface in the corpus cannot be resolved to a
provider. Echo's nested `InteractiveNotificationCallbackHandler.SpinnakerService`
(`POST notifications/callback`) picks its target at request time from the
inbound callback payload: `environment.getProperty(serviceId + ".baseUrl")`
where `serviceId` comes from `callback.getServiceId()`. source: echo@v2.47.2
echo-notifications/src/main/groovy/com/netflix/spinnaker/echo/notification/InteractiveNotificationCallbackHandler.groovy:120

**CLAIM-S1-013**: Igor binds its Keel client from `keel.base-url` via `@Value`
while gating it on `services.keel.enabled`, even though
`IgorConfigurationProperties` declares a `services.keel` block; its Echo,
Front50 and Clouddriver clients do read `services.<name>.baseUrl`. Nothing in
the repository reads `services.keel.baseUrl`. source: igor@v4.22.0
igor-web/src/main/java/com/netflix/spinnaker/igor/config/KeelConfig.java:29,35
and igor-web/src/main/java/com/netflix/spinnaker/igor/config/HelmConfig.java:45

**CLAIM-S1-014**: base-URL config keys are not uniform across the mesh. Callers
of the same provider use different keys: Clouddriver is reached from
`services.clouddriver.baseUrl` (gate, igor), `clouddriver.baseUrl` (orca),
`services.clouddriver.base-url` (fiat, rosco) and `clouddriver.base-url` (keel).
Orca additionally falls back to the legacy `kato.baseUrl` / `oort.baseUrl` /
`mort.baseUrl`, all three mapped to `services.clouddriver.baseUrl` in the
shipped profile. source: orca@v8.64.0 orca-web/config/orca.yml:16-21 and
orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/config/CloudDriverConfigurationProperties.java:95-99;
rosco@v1.26.0 rosco-core/src/main/groovy/com/netflix/spinnaker/rosco/services/ServiceConfig.java:32;
keel@v1.4.1 keel-clouddriver/src/main/kotlin/com/netflix/spinnaker/config/ClouddriverConfiguration.kt:43

**CLAIM-S1-015**: Orca's `InstanceService` is not a mesh client — it is built ad
hoc against `http://<instanceHost>:5050`, the quip agent on a deployed
application instance. source: orca@v8.64.0
orca-clouddriver/src/main/groovy/com/netflix/spinnaker/orca/kato/tasks/quip/AbstractQuipTask.groovy:31

**CLAIM-S1-016**: two Spring MVC controllers import Retrofit's `@Query` and
apply it to handler-method parameters, which Spring does not bind. They are not
clients and are excluded from `edges.tsv`. source: orca@v8.64.0
orca-web/src/main/groovy/com/netflix/spinnaker/orca/controllers/OperationsController.groovy:50,116,121;
igor@v4.22.0 igor-web/src/main/java/com/netflix/spinnaker/igor/gcb/GoogleCloudBuildController.java:31,64

**CLAIM-S1-017**: no Retrofit interface in kork targets a Spinnaker service.
kork contributes the client *factory* (`ServiceClientProvider.getService`, used
by Gate, Clouddriver and Front50) and the `SpinnakerPluginDescriptor` DTO
returned by each service's own `/installedPlugins` declaration, but no
contract of its own. source: `rg 'serviceClientProvider.getService'` across all
ten repositories — every call site passes a locally declared interface.

**CLAIM-S1-018**: the corpus splits across two Retrofit generations. Orca,
Front50 and Kayenta declare `retrofit.http.*`; Gate, Clouddriver, Echo, Igor,
Fiat, Rosco and Keel declare `retrofit2.http.*`. source: `rg -l '^\s*import
\s*retrofit\.http\.'` vs `retrofit2\.http\.` per repository at the tags of
CLAIM-S1-001.

**CLAIM-S1-019**: 100 of the 534 rows carry a path template with **no leading
slash**, and several carry a baked-in query string (e.g.
`/v2/applications?restricted=false`,
`/pipelines/triggeredBy/{pipelineId}/{status}?restricted=false`). Both shapes
must be normalized before a caller path can be matched to a Spring mapping
under D3. source: computed over `scout/S1/edges.tsv`; examples at fiat@v1.57.0
fiat-api/src/main/java/com/netflix/spinnaker/fiat/shared/FiatService.java:36 and
gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/Front50Service.java:37

**CLAIM-S1-020**: the extraction reconciles. For each of the 47 source
interfaces, the number of emitted rows equals the number of HTTP annotations in
the file after comment stripping, with three explained differences:
`FiatService` (9 methods × 7 callers = 63 rows), `HealthCheckableService`
(1 method × 6 providers = 6 rows), and Gate's `ClouddriverService`, where a
74-annotation grep undercounts by one because
`@GET(value = "/functions")` uses the named-argument form. source:
gate@v6.69.0 gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/ClouddriverService.java:394

## Counts

534 rows in `edges.tsv`; 533 resolved to a provider, 1 unresolved.
41 distinct caller→provider pairs, over 47 distinct interface declarations
(interface *names* repeat across repos — six different `Front50Service`, five
`EchoService` — so declarations, not names, are the unit).

| caller | rows | resolved | unresolved |
|---|---|---|---|
| gate | 247 | 247 | 0 |
| orca | 139 | 139 | 0 |
| keel | 54 | 54 | 0 |
| echo | 32 | 31 | 1 |
| clouddriver | 25 | 25 | 0 |
| igor | 17 | 17 | 0 |
| front50 | 11 | 11 | 0 |
| fiat | 7 | 7 | 0 |
| rosco | 2 | 2 | 0 |
| **kayenta** | **0** | 0 | 0 |

As provider: clouddriver 152, front50 120, fiat 65, igor 63, keel 44, orca 44,
kayenta 18, echo 17, rosco 10, unresolved 1. **Gate is never a provider** — no
service in the mesh calls Gate.

Verbs: GET 341, POST 117, PUT 38, DELETE 32, PATCH 5.

For orientation only, not as a finding: counting a row as untyped when its body
or its unwrapped return is `Map`, `Object`, `List<Map>`, a bare container or a
raw `Response`/`String`, 348 of 534 rows (65%) are untyped on at least one side.
This is a crude proxy computed from caller declarations alone; D5's threshold is
defined over S2's census reconciled by R1, and the two will not agree. It is
flagged here only because 65% sits above the 50% line and the review should
expect to have to compute it properly rather than assume headroom.

## Redo (2026-09-11)

Bounded redo after the review pass. R2 refuted CLAIM-S1-017 and found two
counts off by one; the original claims above are left as written and corrected
here as new numbered claims. Only `edges.tsv`, `tools/mesh.tsv`,
`tools/build_edges.py` and `clients.md` changed; `tools/extract.py` needed no
change (it parsed the kork interface unmodified). Regenerating `edges.tsv` now
needs an eleventh clone beside the ten — kork at v7.254.0, in `kork/` —
`python3 tools/build_edges.py` is otherwise unchanged.

**CLAIM-S1-021**: the ten services at the tags of CLAIM-S1-001 resolve kork at
two versions, not one. Eight declare `korkVersion=7.254.0` in
`gradle.properties` (gate, orca, clouddriver, front50, echo, igor, fiat,
rosco); keel declares `korkVersion=7.220.0`; kayenta declares none and inherits
kork through `enforcedPlatform("io.spinnaker.orca:orca-bom:$orcaVersion")` at
`build.gradle:82` with `orcaVersion=8.64.0`, i.e. orca's 7.254.0. No repository
in the corpus carries a dependency lock file (`find` for `*.lockfile`,
`gradle.lockfile`, `dependencies.lock` is empty in all ten). source:
`gradle.properties` of each repo at the tags of CLAIM-S1-001;
kayenta@v2.46.0 build.gradle:82.

**CLAIM-S1-022**: **CLAIM-S1-017 is false.** kork declares exactly one Retrofit
interface in its main sources, and it targets a Spinnaker service:
`kork-plugins/src/main/kotlin/com/netflix/spinnaker/kork/plugins/update/internal/Front50Service.kt`,
a retrofit2 interface with three methods — `@GET("/pluginInfo/{id}") getById`
→ `Call<SpinnakerPluginInfo>` (:35), `@GET("/pluginInfo") listAll` →
`Call<Collection<SpinnakerPluginInfo>>` (:41), and
`@PUT("/pluginVersions/{serverGroupName}") pinVersions` with body
`Map<String,String>` → `Call<PinnedVersions>` (:49, where
`typealias PinnedVersions = Map<String, SpinnakerPluginInfo.SpinnakerPluginRelease>`
at :58). The negative evidence behind CLAIM-S1-017 was sound as far as it went
— every `serviceClientProvider.getService` call site in the ten does pass a
locally declared interface — but this client is not built through
`ServiceClientProvider`, so that search could not have found it. What made the
claim false is the scope it asserted, not the evidence it cited. source:
kork@v7.254.0 (commit a7b6fdea15ec2e98c80093947f194afb0ee552f3)
kork-plugins/src/main/kotlin/com/netflix/spinnaker/kork/plugins/update/internal/Front50Service.kt:30-58;
exhaustiveness from `grep -rlE '@(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|HTTP|Url|Body|Path|Query|QueryMap|Header|Headers|FormUrlEncoded|Multipart|Streaming)\b'`
over every `*.java`, `*.kt`, `*.groovy` under `*/src/main/*` in the clone —
one hit, this file. (kork main sources are 400 java, 141 kt, 7 groovy; the
other eight files in kork that import `retrofit*.http.*` are all under
`src/test/`.)

**CLAIM-S1-023**: it is bound to Front50 by
`kork-plugins/src/main/java/com/netflix/spinnaker/config/Front50PluginsConfiguration.java`,
whose `@Bean pluginFront50Service` (:89) builds it with
`Retrofit.Builder().baseUrl(front50Url)` (:107-112). The class carries
`@ConditionalOnProperty("spinnaker.extensibility.repositories.front50.enabled")`
(:55), and `getFront50Url` (:159-176) resolves the URL in three steps, as its
own javadoc states: `spinnaker.extensibility.repositories.front50.url`
(`PluginRepositoryProperties.getUrl()`, :104 of `PluginsConfigurationProperties`,
under `CONFIG_NAMESPACE = "spinnaker.extensibility"` :35 and
`FRONT5O_REPOSITORY = "front50"` :37), then `front50.base-url` (:169), then
`services.front50.base-url` (:173). source: kork@v7.254.0
kork-plugins/src/main/java/com/netflix/spinnaker/config/Front50PluginsConfiguration.java:55,89,107-112,149-176
and .../config/PluginsConfigurationProperties.java:35,37,78-107.

**CLAIM-S1-024**: all ten services compile the interface in and can instantiate
it. Each declares `io.spinnaker.kork:kork-plugins` on a non-test configuration
(gate-web/-core/-plugins, orca-core `api` + orca-web, clouddriver-core `api` +
clouddriver-web, front50-core `api`, echo-core `api`, igor-web, fiat-web,
rosco-core `api`, kayenta-web, keel-core + keel-web), and each `@Import`s
`PluginsAutoConfiguration`, which carries
`@Import({Front50PluginsConfiguration.class, RemotePluginsConfiguration.class})`
at :80. source: kork@v7.254.0
kork-plugins/src/main/java/com/netflix/spinnaker/config/PluginsAutoConfiguration.java:80;
gate@v6.69.0 gate-web/…/gate/config/GateConfig.groovy:74;
orca@v8.64.0 orca-core/…/orca/config/OrcaConfiguration.java:93;
clouddriver@v5.95.0 clouddriver-core/…/clouddriver/config/CloudDriverConfig.java:137;
front50@v2.41.0 front50-web/…/front50/config/Front50WebConfig.java:61;
echo@v2.47.2 echo-web/…/echo/config/EchoCoreConfig.java:42;
igor@v4.22.0 igor-web/…/igor/config/IgorConfig.java:51;
fiat@v1.57.0 fiat-web/…/fiat/config/FiatConfig.java:46;
rosco@v1.26.0 rosco-core/…/rosco/config/RoscoConfiguration.groovy:43;
kayenta@v2.46.0 kayenta-web/…/kayenta/config/ApplicationConfiguration.java:15;
keel@v1.4.1 keel-web/…/keel/Main.kt:47.

**CLAIM-S1-025**: the enabling property is operator-supplied, so the client is
off in a stock deployment. `@ConditionalOnProperty` here has no
`matchIfMissing`, and no non-test `*.yml`, `*.yaml` or `*.properties` file in
any of the ten repositories mentions `spinnaker.extensibility` at all. source:
`grep -rn extensibility` over `--include='*.yml' --include='*.yaml'
--include='*.properties'` in the ten clones, excluding test trees — no hits;
kork@v7.254.0 Front50PluginsConfiguration.java:55.

**CLAIM-S1-026**: keel's older kork pin makes no difference to any of this. At
kork@v7.220.0 (commit e823562f7dd449b980708c1562b718c1e9da70e1) both
`Front50Service.kt` and `Front50PluginsConfiguration.java` are byte-identical
to v7.254.0, and v7.220.0 likewise declares exactly one Retrofit interface in
main sources. source: `diff` of the two files across the two clones (empty);
the same exhaustive grep of CLAIM-S1-022 run over the v7.220.0 clone.

**CLAIM-S1-027**: all three methods hit endpoints Front50 actually exposes at
the pinned tag, so none of the new rows enlarges the unmatched residue.
`PluginInfoController` is `@RequestMapping("/pluginInfo")` with
`GET ""` (:48) and `GET "/{id}"` (:55); `PluginVersionController` is
`@RequestMapping("/pluginVersions")` with `@PutMapping("/{serverGroupName}")`
(:40). All three appear in S2's `endpoints.tsv` (`PluginInfoController.list`,
`PluginInfoController.get`, `PluginVersionController.pinVersions`). source:
front50@v2.41.0
front50-web/src/main/java/com/netflix/spinnaker/front50/controllers/PluginInfoController.java:37,48,55
and .../PluginVersionController.java:30,40.

**CLAIM-S1-028**: the interface is **in scope and in `edges.tsv`**, on the same
rule that put `FiatService` there (CLAIM-S1-008/009): a Retrofit interface
declared in one artifact, compiled into consumers, and bound to an in-mesh
provider by a config key. It contributes 3 methods × 10 callers = **30 rows**,
carrying the full condition in `resolved_by`
(`spinnaker.extensibility.repositories.front50.url -> front50.base-url ->
services.front50.base-url (kork Front50PluginsConfiguration.pluginFront50Service,
@ConditionalOnProperty spinnaker.extensibility.repositories.front50.enabled)`)
and a `claim` pointing at the kork source. `edges.tsv` goes from 534 rows to
**564**, 563 resolved and 1 unresolved; the regeneration is a pure addition
(`diff` old→new: 30 added, 0 removed, 0 changed). source: `tools/mesh.tsv`
(ten new `KORK` rows) + `python3 tools/build_edges.py`.

**CLAIM-S1-029**: **CLAIM-S1-011's headline is now false**, as a consequence of
CLAIM-S1-024. Kayenta *does* call another of the ten: it compiles
`kork-plugins` in at `kayenta-web/kayenta-web.gradle:37` and `@Import`s
`PluginsAutoConfiguration` at `ApplicationConfiguration.java:15`, so it carries
the three kork rows against Front50 and is no longer a caller-of-nothing. The
rest of CLAIM-S1-011 stands unchanged: all twelve Retrofit interfaces *declared
in kayenta* are metric or object stores, and no Kayenta file names a Spinnaker
service base URL. Kayenta was the only caller with no rows at all before this
redo; after it every one of the ten is a caller. source: kayenta@v2.46.0
kayenta-web/kayenta-web.gradle:37 and
kayenta-web/src/main/java/com/netflix/kayenta/config/ApplicationConfiguration.java:15.

**CLAIM-S1-030**: three of the thirty rows are the **self-edge
front50 → front50**. Front50 imports `PluginsAutoConfiguration` like the other
nine (`Front50WebConfig.java:61`), so its own plugin framework resolves
`services.front50.base-url` back to itself. The rows are kept because the
declaration and the binding are real and identical to the other nine, but a
self-edge cannot carry cross-service drift — both sides move in one commit — so
G3 should drop `caller == provider` from `graph.yaml`, as it already must drop
the 17 stale declarations of R1(a). This is a projection decision, flagged, not
resolved here. source: front50@v2.41.0
front50-web/src/main/java/com/netflix/spinnaker/front50/config/Front50WebConfig.java:61;
`awk -F'\t' '$1==$2' edges.tsv` → 3 rows, all `Front50Service`.

**CLAIM-S1-031**: **CLAIM-S1-019's count was wrong by one**: 101 of the 534
rows lacked a leading slash, not 100. The same error appears in `clients.md`
§Conventions 3, whose own sentence contradicted it ("100 … 433 have one" over a
534-row file); 101 + 433 = 534 is the consistent reading. The thirty new rows
all carry a leading slash, so the count is unchanged at **101 of 564** (463
with one). The 17 baked-in query strings are also unchanged. source:
`awk -F'\t' 'NR>1 && substr($4,1,1)!="/"' edges.tsv | wc -l` over both the
534-row and the 564-row file.

**CLAIM-S1-032**: **the verb tally in §Counts was wrong by one**: POST was 118,
not 117 — 341 + 117 + 38 + 32 + 5 = 533, one short of the 534 rows the same
section reports. Over the 564-row file the tally is **GET 361, POST 118,
PUT 48, DELETE 32, PATCH 5** (sum 564). source:
`awk -F'\t' 'NR>1{c[$3]++} END{for(v in c) print v, c[v]}' edges.tsv` over both
files.

**CLAIM-S1-033**: the counts of §Counts, restated over the 564-row file. 44
distinct resolved caller→provider pairs (was 41; the three new ones are
front50 → front50, kayenta → front50 and rosco → front50 — the other seven
callers already had a Front50 edge), over 48 distinct interface declaration
files (was 47 — kork's is the one added). Gate is still never a provider.

| caller | rows | resolved | unresolved |
|---|---|---|---|
| gate | 250 | 250 | 0 |
| orca | 142 | 142 | 0 |
| keel | 57 | 57 | 0 |
| echo | 35 | 34 | 1 |
| clouddriver | 28 | 28 | 0 |
| igor | 20 | 20 | 0 |
| front50 | 14 | 14 | 0 |
| fiat | 10 | 10 | 0 |
| rosco | 5 | 5 | 0 |
| kayenta | 3 | 3 | 0 |

As provider: clouddriver 152, **front50 150** (was 120), fiat 65, igor 63,
keel 44, orca 44, kayenta 18, echo 17, rosco 10, unresolved 1. source: `edges.tsv`.

**CLAIM-S1-034**: re-running the review's `scout/review/r1ab_reconcile.py`
unmodified over the new `edges.tsv` **raises the matched share and adds nothing
to the unmatched residue**. All 30 new rows match; the unmatched set stays the
same rows, byte-identical on `caller/provider/method/caller_path/normalized_path`.
S2 re-delivered `endpoints.tsv` at 23:09 while this redo was running (748 rows,
Igor 51 — CLAIM-S2-003's fix), so both bases are reported: the pre-redo file is
the one the review's published figures were computed on, the re-delivered file
is the current state of the tree.

| | edges | matched | unmatched | share of resolved | excl. 14 actuator |
|---|---|---|---|---|---|
| ten services, S2 pre-redo (732 rows) — **review's baseline** | 534 | 470 | 63 | 88.18 % | 90.56 % |
| ten services, S2 pre-redo, **with kork** | 564 | **500** | **63** | **88.81 %** | **91.07 %** |
| ten services, S2 re-delivered (748 rows) | 534 | 494 | 39 | 92.68 % | 95.18 % |
| ten services, S2 re-delivered, **with kork** | 564 | **524** | **39** | **93.07 %** | **95.45 %** |
| nine-service mesh (D2), S2 re-delivered | 435 | 407 | 28 | 93.56 % | 96.22 % |
| nine-service mesh (D2), S2 re-delivered, **with kork** | 462 | **434** | **28** | **93.94 %** | **96.44 %** |

Front50 as a provider goes from 112/120 (93.3 %) to 142/150 (**94.7 %**);
ambiguous matches stay at 4; the unmatched split is 25 `no-provider-mapping` +
14 `actuator` on the re-delivered file (49 + 14 before S2's redo), and the 30
kork rows and S2's 24 recovered rows are disjoint. R4's "reconciled edges at or
above 90 % of resolved edges" is met on both populations without the actuator
exclusion. source: `scout/review/r1ab_reconcile.py` and
`r1_nine_service_mesh.py`, both run unmodified against mirrors of the tree in
the scratchpad so that nothing under `scout/review/` was written; run first
against the pre-redo `edges.tsv` with the pre-redo `endpoints.tsv`, where they
reproduced the review's published `r1ab.json` and `r1_nine_service_mesh.json`
exactly, and then in the three other combinations.

**CLAIM-S1-035**: the addition moves R1(b)'s untyped share, but not across the
50 % line on the population D2 puts in force. The numerator is unchanged under
S5's refinement — all 30 new rows are typed under it — so the share falls purely
by dilution.

| population / basis | as written | S5 refinement |
|---|---|---|
| ten services, S2 pre-redo | 51.06 % → **50.00 %** | 50.64 % → **47.60 %** |
| ten services, S2 re-delivered | 51.01 % → **50.00 %** | 50.61 % → **47.71 %** |
| nine-service mesh, S2 pre-redo | 57.44 % → **55.85 %** | 56.92 % → **53.17 %** |
| nine-service mesh, S2 re-delivered | 57.00 % → **55.53 %** | 56.51 % → **53.00 %** |

Under the definition *as written* ten of the thirty rows do count as untyped
(the ten-service figure lands exactly on 50.00 % — 250 of 500 pre-redo, 262 of
524 re-delivered), because `pinVersions` carries `Map<String,String>` over
`Map<String, PluginInfo.Release>` and a strict reading counts every `Map`;
both-sides-untyped rises 21 → 30 on the nine-service mesh for the same reason.
The nine-service mesh — the population the first run actually uses — stays above
50 % under every reading, so R3's D5 ruling and §5's scoping are unaffected. The
ten-service figure now sits below the threshold; it is not the population the
run uses, and which figure the gate is read against is the plan owner's call,
not mine. source: `r1ab_reconcile.py` and `r1_nine_service_mesh.py`, run
unmodified, all four combinations.

## What I could not verify

* **Runtime provider identity.** Every binding above is read from source. I ran
  nothing, so I cannot confirm that a deployment actually points
  `services.clouddriver.baseUrl` at Clouddriver. Halyard, which generates these
  profiles, is not in the ten and I did not inspect it.
* **Which declared methods are actually called.** `edges.tsv` is one row per
  declared Retrofit method, because the declaration is the caller contract the
  checker consumes. I did not trace call sites, so some rows are dead code. The
  `BakeryService` methods gated on `bakery.roscoApisEnabled` are a known example.
* **The `HealthCheckableService` fan-out is a default, not a fact.**
  `healthCheckableServices` is operator-overridable; the six rows reflect the
  hard-coded default list filtered to the ten. A deployment could health-check
  fewer or more.
* **The four indirect fiat callers.** For Clouddriver, Echo, Igor and Keel I
  verified that `fiat-api` is a compile dependency and `@EnableFiatAutoConfig`
  is applied, but no application code in those repositories injects
  `FiatService`; the calls come from `FiatPermissionEvaluator` inside fiat-api.
  I did not confirm by execution that those services issue Fiat HTTP traffic at
  runtime, nor which of the nine methods each reaches. Whether these 36 rows
  belong in the graph is a projection decision, not something I resolved.
* **Echo's unresolved `SpinnakerService` target.** I could not determine which
  service receives `POST notifications/callback`. The property naming and a code
  comment suggest a Spinnaker service, and Orca or Gate are the plausible
  candidates, but nothing in the source names one.
* **kork's own contents.** I did not clone kork. CLAIM-S1-017 is negative
  evidence gathered from the ten consumers (every `getService` call site passes
  a locally declared interface); I did not read kork to confirm it declares no
  Retrofit interface of its own. If kork ships one that some service picks up by
  autoconfiguration without naming it, I would have missed it.
* **Other releases.** Everything here is the latest tag of each repo, which is
  not a coherent BOM. Whether these interfaces, keys and bean names are stable
  across the BOM range S3 proposes is unknown; the Retrofit 1 → 2 migration is
  visibly mid-flight (CLAIM-S1-018), so the shape of `return_type` almost
  certainly changes within any multi-release window.
* **Provider-side existence.** I did not check that any provider actually
  exposes the paths its callers declare. That is S2's surface, and D3's
  reconciliation in R1 — the unmatched residue is a finding, and I have made no
  prediction about its size.
* **Query and header parameters.** `edges.tsv` records method, path, body and
  return only, per the schema. `@Query`, `@Path` and `@Header` parameters were
  parsed (they were needed to find `@Body`) but are not in the output, so D6's
  parameter folding cannot be driven from this file alone.

### Redo (2026-09-11) — what the redo resolved, and what it did not

**Resolved.** The sixth bullet above ("kork's own contents. I did not clone
kork.") is closed: kork is cloned at v7.254.0 and v7.220.0 and read
exhaustively (CLAIM-S1-022, CLAIM-S1-026). It was right to flag, and the risk
it named is exactly what happened — kork ships one Retrofit interface that a
service picks up by `@Import` without naming it.

Still open, and now with a kork-shaped addition:

* **Whether any deployment turns the kork client on.** CLAIM-S1-025 shows no
  shipped profile in the ten sets `spinnaker.extensibility.*`, so the thirty
  rows describe a client that a stock install never instantiates. Halyard and
  the operator-supplied profiles that would set it are outside the ten and I
  did not inspect them. Whether these rows belong in `graph.yaml` is the same
  projection decision as the four indirect fiat callers, and I have not made it.
* **Whether the pinned kork version is stable across the BOM range.** kork is
  pinned per service in `gradle.properties`, and the ten already disagree at
  1.38.0 (7.254.0 vs keel's 7.220.0). I checked those two tags only. A range of
  releases will move `korkVersion` independently of the service versions, so
  G2 must resolve kork per service per BOM rather than assuming one kork per
  release — and `edges.tsv`'s kork rows are sourced to one tag, not to a range.
* **Other shared libraries.** I read kork because R2 named it. `keiko`,
  `spinnaker-gradle-project` and the several `*-api` artifacts each service
  publishes are unread; the same failure mode — an interface declared in a
  library and compiled into consumers — could hide in any of them. The two I
  know of (`fiat-api`, `kork-plugins`) were both found only after someone went
  looking for them by name.
* **The self-edge.** I have not established what Front50 pointing this client
  at itself does at runtime, only that the binding resolves that way
  (CLAIM-S1-030). It may be dead in practice.
