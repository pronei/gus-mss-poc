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
