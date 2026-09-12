# S1 — Retrofit clients per caller, and how each is bound

Corpus: shallow clones of the ten repositories at their latest release tag
(see memo.md CLAIM-S1-001 for tag and commit per repo). Every path below is
relative to its repository root; prefix it with `<repo>@<tag>` to get a claim
source.

Scope rule used throughout: an **in-mesh** interface is one whose target is one
of the ten services (Gate, Orca, Clouddriver, Front50, Echo, Igor, Fiat, Rosco,
Kayenta, Keel). Interfaces pointing at third-party systems (Jenkins, Slack,
Cloud Foundry, Atlas, …) or at Spinnaker services outside the ten (Swabbie,
Mine, Flex) are listed under "out of mesh" and are **not** in `edges.tsv`.

Retrofit generation: Orca, Front50 and Kayenta still declare `retrofit.http.*`
(Retrofit 1); Gate, Clouddriver, Echo, Igor, Fiat, Rosco and Keel declare
`retrofit2.http.*`. Both dialects use the same annotation names, so the row
shape is identical; the difference shows up in `return_type`
(Retrofit 1 returns the payload or `retrofit.client.Response` directly;
Retrofit 2 wraps it in `Call<T>`; Keel and Orca-Kotlin use `suspend fun` and
return the payload directly).

---

## Gate — `gate@v6.69.0`

Every internal client is created by `GateConfig.createClient(name, type)`,
which looks the service up in `ServiceConfiguration` and takes
`services.<name>.baseUrl`; the client itself is instantiated through kork's
`ServiceClientProvider.getService(type, DefaultServiceEndpoint(name, url))`.

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `ClouddriverService` | `gate-core/src/main/java/com/netflix/spinnaker/gate/services/internal/ClouddriverService.java` | clouddriver | `services.clouddriver.baseUrl` — `GateConfig.clouddriverService` / `clouddriverServiceSelector` |
| `OrcaService` | `gate-core/…/internal/OrcaService.java` | orca | `services.orca.baseUrl` — only via `GateConfig.orcaServiceSelector` (`createClientSelector`) |
| `Front50Service` | `gate-core/…/internal/Front50Service.java` | front50 | `services.front50.baseUrl` — `GateConfig.front50Service` |
| `EchoService` | `gate-core/…/internal/EchoService.java` | echo | `services.echo.baseUrl` — `GateConfig.echoService` (`@ConditionalOnProperty services.echo.enabled`) |
| `IgorService` | `gate-core/…/internal/IgorService.java` | igor | `services.igor.baseUrl` — `GateConfig.igorService` |
| `KeelService` | `gate-core/…/internal/KeelService.java` | keel | `services.keel.baseUrl` — `GateConfig.keelService` |
| `RoscoService` | `gate-core/…/internal/RoscoService.java` | rosco | `services.rosco.baseUrl` — `GateConfig.roscoService` / `roscoServiceSelector` |
| `ExtendedFiatService` | `gate-core/…/internal/ExtendedFiatService.java` | fiat | `services.fiat.baseUrl` — `GateConfig.extendedFiatService` (`forceEnabled = true`) |
| `KayentaService` | `gate-web/src/main/groovy/…/internal/KayentaService.groovy` | kayenta | `services.kayenta.baseUrl` — `GateConfig.kayentaService` |
| `FiatService` (from `fiat-api`) | `fiat@v1.57.0 fiat-api/src/main/java/com/netflix/spinnaker/fiat/shared/FiatService.java` | fiat | `services.fiat.baseUrl` — `GateConfig.fiatService` (`@Primary`, overrides fiat-api's own bean) |
| `HealthCheckableService` | `gate-web/src/main/groovy/…/internal/HealthCheckableService.groovy` | orca, clouddriver, echo, igor, front50, keel | `DownstreamServicesHealthIndicator` instantiates it once per enabled entry of `serviceConfiguration.healthCheckableServices` at `services.<name>.baseUrl` |

Notes:

* **`HealthCheckableService` is one declaration bound to six providers.** It has
  a single method, `GET /health`, and `DownstreamServicesHealthIndicator` builds
  one client per service in `healthCheckableServices`, whose default is
  `["orca","clouddriver","echo","igor","flex","front50","mahe","mine","keel"]`.
  `edges.tsv` carries six rows for it — the six list members that are in the ten.
  `flex`, `mahe` and `mine` are dropped as out of mesh. The list is
  operator-overridable, so this fan-out is a *default*, not a fixed fact.
* **`OrcaService` has no plain bean.** Gate reaches Orca only through
  `OrcaServiceSelector`, built from `createClientSelector("orca", OrcaService)`,
  which iterates `Service.getBaseUrls()` — i.e. `services.orca.baseUrl`, or the
  `services.orca.shards.baseUrls` list when sharding is configured. Every
  selector still points at Orca, so the provider is unambiguous.
* **`ClouddriverServiceSelector` has a second, dynamic path.** If
  `services.clouddriver.config.dynamicEndpoints` is set, Gate builds an extra
  `ClouddriverService` per `{sourceApp: url}` entry behind a
  `ByUserOriginSelector`. All of them are Clouddriver, so the provider stays
  resolved; only the URL varies by request origin.
* **`selectorClass` reflection.** Both `createClientSelector` and Orca's
  equivalent will instantiate an arbitrary `ServiceSelector` class named in
  config. That changes *which instance* of a provider is chosen, never which
  provider — so it does not create unresolved edges.

Out of mesh (present, not in `edges.tsv`): `SwabbieService` (→ Swabbie),
`MineService` (→ Mine), `GremlinService`, `SlackService`, `PagerDutyService`
(third-party), `gate-web/src/test/groovy/…/Api.groovy` (test fixture).

**Gate's proxying is not Retrofit.** `ProxyController`
(`gate-proxy/src/main/kotlin/com/netflix/spinnaker/gate/controllers/ProxyController.kt`)
serves `/proxies/{proxyId}/**` by replaying the request with a raw OkHttp
client against a URI taken from operator config (`proxies:` list, read by
`DefaultProxyConfigProvider`) or from a `ProxyConfigProvider` plugin. There is
no declared method, path template or body type, and the target is an arbitrary
external URI, not one of the ten. It contributes no edges and cannot be
resolved statically. The Deck/plugin routes under `gate-plugins` read plugin
artifacts through Gate's own `Front50Service`, which is already counted.

## Orca — `orca@v8.64.0`

| Interface | Path (all under `orca-*/src/main/…`) | Provider | Bound by |
|---|---|---|---|
| `OortService` | `orca-clouddriver/…/clouddriver/OortService.java` | clouddriver | `clouddriver.baseUrl` — `CloudDriverConfiguration.oortDeployService`, read-only selector |
| `MortService` | `orca-clouddriver/…/clouddriver/MortService.java` | clouddriver | `clouddriver.baseUrl` — `mortDeployService`, read-only selector |
| `KatoRestService` | `orca-clouddriver/…/clouddriver/KatoRestService.java` | clouddriver | `clouddriver.baseUrl` — `katoDeployService`, writeable selector |
| `CloudDriverCacheService` | `orca-clouddriver/…/clouddriver/CloudDriverCacheService.java` | clouddriver | `clouddriver.baseUrl` — `clouddriverCacheService`, writeable selector |
| `CloudDriverCacheStatusService` | `orca-clouddriver/…/clouddriver/CloudDriverCacheStatusService.java` | clouddriver | `clouddriver.baseUrl` — read-only selector |
| `CloudDriverTaskStatusService` | `orca-clouddriver/…/clouddriver/CloudDriverTaskStatusService.java` | clouddriver | `clouddriver.baseUrl` — read-only selector |
| `FeaturesRestService` | `orca-clouddriver/…/clouddriver/FeaturesRestService.java` | clouddriver | `clouddriver.baseUrl` — writeable selector |
| `Front50Service` | `orca-front50/…/front50/Front50Service.groovy` | front50 | `front50.baseUrl` — `Front50Configuration.front50Endpoint` |
| `EchoService` | `orca-echo/…/echo/EchoService.groovy` | echo | `echo.base-url` — `EchoConfiguration.echoEndpoint` |
| `IgorService` | `orca-igor/…/igor/IgorService.java` | igor | `igor.base-url` — `IgorConfiguration.igorEndpoint` |
| `KeelService` | `orca-keel/…/orca/KeelService.kt` | keel | `services.keel.base-url` — `KeelConfiguration.keelEndpoint` |
| `KayentaService` | `orca-kayenta/…/kayenta/KayentaService.kt` | kayenta | `kayenta.base-url` — `KayentaConfiguration.kayentaEndpoint` |
| `BakeryService` | `orca-bakery/…/bakery/api/BakeryService.groovy` | rosco | `bakery.base-url` — `BakeryConfiguration.bakery`, plus `BakerySelector` |
| `FiatService` (from `fiat-api`) | see Fiat below | fiat | `services.fiat.baseUrl` — fiat-api's own bean, enabled by `@EnableFiatAutoConfig` on `orca-web/…/web/config/WebConfiguration.groovy` |

Notes:

* The seven Clouddriver interfaces all funnel through
  `CloudDriverConfiguration.ClouddriverRetrofitBuilder.buildService`, which
  stamps `DefaultServiceEndpoint("clouddriver", url)`. The read-only/writeable
  split reads `clouddriver.readonly.baseUrls` / `clouddriver.writeonly.baseUrls`
  and falls back to `clouddriver.baseUrl`; `CloudDriverConfigurationProperties`
  additionally falls back to the legacy `kato.baseUrl`, `oort.baseUrl` and
  `mort.baseUrl`. In the shipped `orca.yml` all four resolve to
  `services.clouddriver.baseUrl`. Every branch targets Clouddriver.
* `BakerySelector` builds an additional `BakeryService` per configured
  `bakery.baseUrls` entry, selected per-execution; all point at Rosco.
* `BakeryService` carries methods the comments mark as "not supported by the
  Netflix Bakery, only available iff `bakery.roscoApisEnabled` is true". They
  are declared, so they are rows; whether they are called is a runtime matter.

Out of mesh: `InstanceService` (targets the deployed *application instance*'s
quip agent at `http://<host>:5050`, built ad hoc in
`orca-clouddriver/…/kato/tasks/quip/AbstractQuipTask.groovy`), `MineService`
(→ Mine), `FlexService` (→ Flex), `DeploymentMonitorService` and
`GremlinService` (third-party), `BaseRetrofitExceptionHandler` and
`DummyRetrofitApi` (not clients).

## Clouddriver — `clouddriver@v5.95.0`

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `Front50Service` | `clouddriver-core/src/main/groovy/…/core/services/Front50Service.groovy` | front50 | `services.front50.baseUrl` — `RetrofitConfig.front50Service` (`Front50ConfigurationProperties`, prefix `services.front50`), gated on `services.front50.enabled` (default true) |
| `FiatService` (from `fiat-api`) | see Fiat below | fiat | `services.fiat.baseUrl` — `@EnableFiatAutoConfig` on `clouddriver-security/…/security/config/SecurityConfig.groovy` |

Out of mesh: the Cloud Foundry client package (13 interfaces), Consul (3),
Docker registry (2), Eureka (2), Edda, and the App Engine GCP metadata
interface — all third-party.

## Front50 — `front50@v2.41.0`

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `EchoService` | `front50-core/src/main/java/…/front50/echo/EchoService.java` | echo | `services.echo.base-url` — `EchoConfiguration.echoService`, gated on `services.echo.enabled` |
| `FiatService` (from `fiat-api`) | see Fiat below | fiat | `services.fiat.baseUrl` — `@EnableFiatAutoConfig` on `front50-web/…/config/Front50WebConfig.java` |

## Echo — `echo@v2.47.2`

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `Front50Service` | `echo-core/src/main/java/…/echo/services/Front50Service.java` | front50 | `front50.base-url` — `echo-web/…/config/Front50Config.java` |
| `IgorService` | `echo-core/src/main/java/…/echo/services/IgorService.java` | igor | `igor.base-url` — `echo-pipelinetriggers/…/config/IgorConfig.java` |
| `OrcaService` | `echo-pipelinetriggers/…/pipelinetriggers/orca/OrcaService.java` | orca | `orca.base-url` — `PipelineTriggerConfiguration.orca` |
| `KeelService` | `echo-artifacts/src/main/java/…/echo/services/KeelService.java` | keel | `keel.base-url` — `echo-artifacts/…/config/KeelConfig.java` |
| `FiatService` (from `fiat-api`) | see Fiat below | fiat | `services.fiat.baseUrl` — `@EnableFiatAutoConfig` on `echo-web/…/config/ComponentConfig.java` |

Note: `DryRunConfig` builds a **second** `OrcaService` instance bound to
`dryrun.baseUrl` (gated on `dryrun.enabled`). It is the same interface and the
same provider role (an Orca), so it adds no distinct rows; it is recorded here
because the URL comes from a different key than `orca.base-url`.

Out of mesh: Slack, PagerDuty, Bearychat, Twilio, Jira, GitHub, Google Chat,
Microsoft Teams, CDEvents, the generic `RestService` (operator-configured
webhook sink) and `TelemetryService`.

## Igor — `igor@v4.22.0`

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `EchoService` | `igor-core/src/main/java/…/igor/history/EchoService.java` | echo | `services.echo.baseUrl` — `igor-web/…/config/EchoConfig.groovy` (`IgorConfigurationProperties.services.echo`) |
| `KeelService` | `igor-core/src/main/java/…/igor/keel/KeelService.java` | keel | `keel.base-url` — `igor-web/…/config/KeelConfig.java`, gated on `services.keel.enabled` |
| `Front50Service` | `igor-monitor-plugins/src/main/java/…/igor/plugins/front50/Front50Service.java` | front50 | `services.front50.baseUrl` — `PluginMonitorConfig.pluginReleaseService` |
| `ClouddriverService` | `igor-web/src/main/groovy/…/igor/docker/service/ClouddriverService.groovy` | clouddriver | `services.clouddriver.baseUrl` — `DockerRegistryConfig.dockerRegistryProxyService` |
| `HelmAccountsService` | `igor-web/src/main/java/…/igor/helm/accounts/HelmAccountsService.java` | clouddriver | `services.clouddriver.baseUrl` — `HelmConfig.helmAccountsService`, gated on `helm.enabled` |
| `FiatService` (from `fiat-api`) | see Fiat below | fiat | `services.fiat.baseUrl` — `@EnableFiatAutoConfig` on `igor-web/…/config/IgorConfig.java` |

Note the key inconsistency: Igor's Echo, Front50 and Clouddriver clients read
`services.<name>.baseUrl` through `IgorConfigurationProperties`, but its Keel
client reads a *different* key, `keel.base-url`, via `@Value` — while its
enablement flag is still `services.keel.enabled`. `IgorConfigurationProperties`
declares a `services.keel` block that nothing reads.

Out of mesh: Travis, Jenkins, GitLab CI, GitLab, GitHub, Stash, BitBucket,
Wercker, the eleven Concourse interfaces. `BuildController` and
`GoogleCloudBuildController` import `retrofit2.http.Query` but are Spring MVC
controllers, not clients (see memo CLAIM-S1-016).

## Fiat — `fiat@v1.57.0`

Two distinct roles.

**(a) Fiat as a caller** — `fiat-roles`, wired in
`fiat-web/src/main/java/…/fiat/config/ResourcesConfig.java`:

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `ClouddriverApi` | `fiat-roles/…/providers/internal/ClouddriverApi.java` | clouddriver | `services.clouddriver.base-url` — `ResourcesConfig.clouddriverApi` |
| `Front50Api` | `fiat-roles/…/providers/internal/Front50Api.java` | front50 | `services.front50.base-url` — `ResourcesConfig.front50Api` |
| `IgorApi` | `fiat-roles/…/providers/internal/IgorApi.java` | igor | `services.igor.base-url` — `ResourcesConfig.igorApi`, gated on `services.igor.enabled` |

**(b) `fiat-api` as the shared client library.** `FiatService`
(`fiat-api/src/main/java/com/netflix/spinnaker/fiat/shared/FiatService.java`,
9 methods) is the one interface published by one service and compiled into
others. `FiatAuthenticationConfig` declares the bean at
`FiatClientConfigurationProperties.getBaseUrl()` — prefix `services.fiat`, so
`services.fiat.baseUrl` — and is switched on by `@EnableFiatAutoConfig` in
Orca, Clouddriver, Front50, Echo, Igor and Keel. Gate does not use
`@EnableFiatAutoConfig`; it declares its own `@Primary FiatService` bean in
`GateConfig`, from the same key.

`edges.tsv` therefore carries the nine `FiatService` methods **seven times**,
once per calling service (gate, orca, clouddriver, front50, echo, igor, keel),
with `claim` pointing at the fiat-api source in all seven. Four of those seven
call it only indirectly: in Clouddriver, Echo, Igor and Keel no application
code injects `FiatService` — the calls are issued by `FiatPermissionEvaluator`,
which also lives inside `fiat-api`. The declaration is still on the caller's
classpath and the HTTP traffic still leaves the caller, so the rows are kept;
a projection that wants only directly-injected clients should restrict to gate,
orca and front50.

Rosco and Kayenta have no dependency on fiat at all — no `fiat-api` in any
`.gradle` file — so they contribute no fiat edges.

Out of mesh: `fiat-github/…/GitHubClient.java`.

## Rosco — `rosco@v1.26.0`

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `ClouddriverService` | `rosco-core/src/main/groovy/…/rosco/services/ClouddriverService.java` | clouddriver | `services.clouddriver.base-url` (default `http://localhost:7002`) — `ServiceConfig.clouddriverService` |

Rosco's only in-mesh client, two methods.

## Kayenta — `kayenta@v2.46.0`

**No in-mesh Retrofit clients.** All twelve Retrofit interfaces are metric
stores or object stores (Atlas, Datadog, Graphite, InfluxDB, New Relic,
Prometheus, SignalFx, Wavefront, ConfigBin, remote judge), built by
`kayenta-core/…/retrofit/config/RetrofitClientFactory.createClient` from a
`RemoteService.getBaseUrl()` supplied per configured account. Kayenta depends on
Orca artifacts (`orca-core`, `orca-queue`, `orca-retrofit`, `keiko-spring`) but
none of the Orca modules that declare Retrofit interfaces, and no Kayenta file
references any Spinnaker service base URL. Kayenta appears in `edges.tsv` only
as a provider (of Gate and Orca).

## Keel — `keel@v1.4.1`

All Kotlin, all `suspend fun`, all built with a plain `Retrofit.Builder` in
`keel-*/src/main/kotlin/com/netflix/spinnaker/config/`.

| Interface | Path | Provider | Bound by |
|---|---|---|---|
| `CloudDriverService` | `keel-clouddriver/…/keel/clouddriver/CloudDriverService.kt` | clouddriver | `clouddriver.base-url` — `ClouddriverConfiguration.clouddriverEndpoint` |
| `Front50Service` | `keel-front50/…/keel/front50/Front50Service.kt` | front50 | `front50.base-url` — `Front50Config.front50Endpoint` |
| `OrcaService` | `keel-orca/…/keel/orca/OrcaService.kt` | orca | `orca.base-url` — `OrcaConfiguration.orcaEndpoint` |
| `EchoService` | `keel-echo/…/keel/echo/EchoService.kt` | echo | `echo.base-url` — `EchoConfiguration.echoEndpoint` |
| `ArtifactService` | `keel-igor/…/keel/igor/artifact/ArtifactService.kt` | igor | `igor.base-url` — `IgorConfiguration.artifactService` |
| `ScmService` | `keel-igor/…/keel/igor/ScmService.kt` | igor | `igor.base-url` — `IgorConfiguration.scmService` |
| `BuildService` | `keel-igor/…/keel/igor/BuildService.kt` | igor | `igor.base-url` — `IgorConfiguration.buildService` |
| `FiatService` (from `fiat-api`) | see Fiat above | fiat | `services.fiat.baseUrl` — `@EnableFiatAutoConfig` on `keel-web/…/config/SecurityConfiguration.kt` |

The three Igor interfaces share one `igorEndpoint` bean via an inlined
`buildService<T>` helper.

Out of mesh: `LemurService` (Netflix-internal certificate service), plus two
test files.

---

## Unresolved interfaces

One, and it is a genuine dynamic selector rather than a gap in the search.

**`InteractiveNotificationCallbackHandler.SpinnakerService`** — Echo,
`echo-notifications/src/main/groovy/com/netflix/spinnaker/echo/notification/InteractiveNotificationCallbackHandler.groovy:142`.
A nested Retrofit interface with one method, `POST notifications/callback`,
body `InteractiveActionCallback`, plus an `X-SPINNAKER-USER` header. The target
is chosen at request time from the inbound callback payload:
`getSpinnakerService(callback.getServiceId())` looks up
`environment.getProperty(serviceId + ".baseUrl")` and caches a client per
`serviceId` (line 120). `serviceId` is attacker-adjacent runtime data carried in
the notification callback, not a compile-time constant, so no static analysis
can name the provider. In practice the property naming implies it is some
Spinnaker service (the code comment says "downstream Spinnaker service"), and
the only plausible callers of interactive notifications are Orca and Gate — but
that is inference, not evidence, so the row is emitted with
`provider = unresolved` and `resolved_by = unresolved`.

Everything else resolved. Specifically, nothing was left unresolved because a
config class could not be found: the extraction started from the set of files
that import `retrofit.http.*` or `retrofit2.http.*` and each one was traced to
either a `@Bean` definition with a literal config key, or an out-of-mesh target.

## Things that look like unresolved edges but are not

* **Gate `/proxies/**`** — not Retrofit, arbitrary operator-configured URI, no
  declared contract. Described above.
* **`selectorClass` / `dynamicEndpoints` / shard `baseUrls`** — vary the URL
  within one provider, never the provider.
* **Echo `DryRunConfig`** — a second Orca client at `dryrun.baseUrl`.
* **Orca `InstanceService`** — a per-instance agent, not a service.
* **`@Query` on Spring controllers** — `OperationsController.groovy:50` and
  `GoogleCloudBuildController.java:31` import Retrofit's `@Query` and apply it
  to parameters of Spring MVC handler methods (`@RequestMapping` /
  `@PathVariable` are on the same methods). Spring has no binding for Retrofit's
  annotation, so these read as mistakes in Spinnaker rather than client
  declarations. Either way they are not Retrofit clients, and they are excluded.

## Conventions a consumer of edges.tsv needs

1. **`return_type` is verbatim as declared**, wrapper included: `Call<T>`
   (Retrofit 2), bare `T` or `retrofit.client.Response` (Retrofit 1), `T` or
   `Unit` (Kotlin `suspend`). Unwrap `Call<…>` before comparing with a
   provider's return type. `Unit` means the Kotlin method declares no return.
2. **`body_type` is `-` when the method has no `@Body`.**
3. **`path_template` is verbatim**, which means two things the D3 normalization
   must handle: (a) 100 of 534 rows have **no leading slash** (Retrofit 2
   relative paths — all of `FiatService`, Echo's Front50/Igor/Keel/Orca clients),
   433 have one; (b) some templates carry a **baked-in query string**, e.g.
   `/v2/applications?restricted=false` and
   `/pipelines/triggeredBy/{pipelineId}/{status}?restricted=false`. Both must be
   stripped before matching a Spring mapping.
4. **Overloads share a path.** Orca's `Front50Service.getPipelines` appears three
   times on `/pipelines/{applicationName}` with different query parameters;
   `FiatService.sync` appears twice on `roles/sync`. These are distinct rows by
   `method_name`, and they collapse to one endpoint after normalization.
5. **`claim` names the file that *declares* the method**, which for the 63
   `FiatService` rows is the fiat repo, not the caller's repo.
