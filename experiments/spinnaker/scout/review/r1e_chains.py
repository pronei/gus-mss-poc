#!/usr/bin/env python3
"""R1(e): for each S6 recommended chain, check that every hop's field exists in S2's endpoints.tsv
(body_type, path_params, query_params or header_params after D6 folding) or in S1's edges.tsv.
Body fields are checked in the declared type's source (the scouts' clones) because the TSVs carry
only the type name.  edges.tsv has no parameter columns, so a caller-side query field is checked
in the Retrofit source and flagged as 'source-only'."""
import csv, re, os, json, sys
here = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(here, '..')
CLONES = os.environ.get('SPINNAKER_CLONES', '/private/tmp/claude-501/-Users-pronei-work-faults-lab-service-beds-gus/01d8e507-e2b9-4543-baaa-b8859181517e/scratchpad/spinnaker')
edges = list(csv.DictReader(open(os.path.join(S, 'S1', 'edges.tsv')), delimiter='\t'))
eps = list(csv.DictReader(open(os.path.join(S, 'S2', 'endpoints.tsv')), delimiter='\t'))
def norm(p):
    p = p.split('?')[0]
    if p in ('', '.'): p = '/'
    if not p.startswith('/'): p = '/' + p
    p = re.sub(r'\{[^}]*\}', '{}', p)
    return p.rstrip('/') if len(p) > 1 else p
def s2(service, method, path):
    return [e for e in eps if e['service'] == service and e['method'] == method and norm(e['path_template']) == norm(path)]
def s1(caller, provider, method, path):
    return [e for e in edges if e['caller'] == caller and e['provider'] == provider and e['method'] == method and norm(e['path_template']) == norm(path)]
def params(ep):
    out = set()
    for col in ('path_params', 'query_params', 'header_params'):
        if ep[col] != '-': out |= {x.split(':')[0] for x in ep[col].split(',')}
    return out
def is_map(t): return bool(re.match(r'(Call<)?(List<|Collection<\?extends)?(Map|Object|Any)\b', t.replace(' ', '')))
def grep(sub, clone, path, pattern):
    p = os.path.join(CLONES, sub, clone, path)
    if not os.path.exists(p): return None
    return bool(re.search(pattern, open(p).read()))
# hop = (label, side, service/caller->provider, method, path, field, kind, source check)
CHAINS = {
 '1 correlationId Keel->Orca': [
   ('mint', 'caller', ('keel', 'orca'), 'POST', '/ops', 'trigger.correlationId', 'body', ('S6', 'keel', 'keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/model/OrchestrationRequest.kt', r'val correlationId: String\?')),
   ('sink-1', 'provider', 'orca', 'POST', '/ops', 'trigger.correlationId', 'body', None),
   ('sink-2', 'provider', 'orca', 'GET', '/executions/correlated/{correlationId}', 'correlationId', 'path', None),
   ('reader', 'caller', ('keel', 'orca'), 'GET', '/executions/correlated/{correlationId}', 'correlationId', 'path', ('S6', 'keel', 'keel-orca/src/main/kotlin/com/netflix/spinnaker/keel/orca/OrcaService.kt', r'@GET\("/executions/correlated/\{correlationId\}"\)'))],
 '2 application Gate->Orca->Front50': [
   ('mint', 'caller', ('gate', 'orca'), 'POST', '/ops', 'application', 'body', None),
   ('hop-in', 'provider', 'orca', 'POST', '/ops', 'application', 'body', None),
   ('hop-out', 'caller', ('orca', 'front50'), 'PATCH', '/v2/applications/{applicationName}', 'name', 'body', ('S6', 'orca', 'orca-front50/src/main/groovy/com/netflix/spinnaker/orca/front50/model/Application.groovy', r'public String name')),
   ('hop-out-path', 'caller', ('orca', 'front50'), 'PATCH', '/v2/applications/{applicationName}', 'applicationName', 'path', None),
   ('sink', 'provider', 'front50', 'PATCH', '/v2/applications/{applicationName}', 'name', 'body', ('S6', 'front50', 'front50-core/src/main/java/com/netflix/spinnaker/front50/model/application/Application.java', r'private String name')),
   ('sink-path', 'provider', 'front50', 'PATCH', '/v2/applications/{applicationName}', 'applicationName', 'path', None)],
 '3 clientRequestId Orca->Clouddriver': [
   ('mint', 'caller', ('orca', 'clouddriver'), 'POST', '/{cloudProvider}/ops', 'clientRequestId', 'query', ('S6', 'orca', 'orca-clouddriver/src/main/java/com/netflix/spinnaker/orca/clouddriver/KatoRestService.java', r'@Query\("clientRequestId"\)')),
   ('sink', 'provider', 'clouddriver', 'POST', '/{cloudProvider}/ops', 'clientRequestId', 'query', None)],
 '4 artifactAccount Orca/Rosco->Clouddriver': [
   ('mint-A', 'caller', ('orca', 'clouddriver'), 'PUT', '/artifacts/fetch/', 'artifactAccount', 'body', ('S2', 'kork', 'kork-artifacts/src/main/java/com/netflix/spinnaker/kork/artifacts/model/Artifact.java', r'private final String artifactAccount')),
   ('mint-B', 'caller', ('rosco', 'clouddriver'), 'PUT', '/artifacts/fetch/', 'artifactAccount', 'body', ('S2', 'kork', 'kork-artifacts/src/main/java/com/netflix/spinnaker/kork/artifacts/model/Artifact.java', r'private final String artifactAccount')),
   ('sink', 'provider', 'clouddriver', 'PUT', '/artifacts/fetch', 'artifactAccount,type', 'body', ('S2', 'kork', 'kork-artifacts/src/main/java/com/netflix/spinnaker/kork/artifacts/model/Artifact.java', r'private final String type;[\s\S]*private final String artifactAccount'))],
 '5 source.executionId Orca->Echo': [
   ('mint', 'caller', ('orca', 'echo'), 'POST', '/notifications', 'source.executionId', 'body', ('S6', 'orca', 'orca-echo/src/main/groovy/com/netflix/spinnaker/orca/echo/EchoService.groovy', r'static class Source \{[\s\S]*?String executionId')),
   ('sink', 'provider', 'echo', 'POST', '/notifications', 'source.executionId', 'body', ('S6', 'echo', 'echo-notifications/src/main/groovy/com/netflix/spinnaker/echo/api/Notification.groovy', r'static class Source \{[\s\S]*?String executionId'))],
 'alt application+parentPipelineExecutionId Echo->Orca->Kayenta': [
   ('mint', 'caller', ('echo', 'orca'), 'POST', 'orchestrate', 'application', 'body', ('S6', 'echo', 'echo-model/src/main/java/com/netflix/spinnaker/echo/model/Pipeline.java', r'String application')),
   ('hop-in', 'provider', 'orca', 'POST', '/orchestrate', 'application', 'body', None),
   ('hop-out', 'caller', ('orca', 'kayenta'), 'POST', '/canary/{canaryConfigId}', 'application,parentPipelineExecutionId', 'query', ('S6', 'orca', 'orca-kayenta/src/main/kotlin/com/netflix/spinnaker/orca/kayenta/KayentaService.kt', r'@Query\("parentPipelineExecutionId"\)')),
   ('sink', 'provider', 'kayenta', 'POST', '/canary/{canaryConfigId}', 'application,parentPipelineExecutionId', 'query', None)],
}
out = {}
for name, hops in CHAINS.items():
    res = []
    for label, side, who, method, path, field, kind, src in hops:
        r = {'hop': label, 'side': side, 'method': method, 'path': path, 'field': field, 'kind': kind}
        if side == 'provider':
            rows = s2(who, method, path)
            r['s2_rows'] = len(rows)
            if not rows: r['result'] = 'FAIL: endpoint absent from endpoints.tsv'
            elif kind == 'body':
                types = sorted(set(x['body_type'] for x in rows))
                r['s2_body_types'] = types
                if all(is_map(t) or t == '-' for t in types): r['result'] = 'FAIL: provider body is Map/absent, field not declared'
                elif src and grep(*src) is False: r['result'] = 'FAIL: field not found in declared type source'
                elif src and grep(*src) is None: r['result'] = 'NOT CHECKED: source file missing'
                else: r['result'] = 'OK: declared type ' + '/'.join(types) + (' (field verified in source)' if src else '')
            else:
                have = set.union(*[params(x) for x in rows])
                missing = [f for f in field.split(',') if f not in have]
                r['result'] = 'OK: ' + kind + ' param in endpoints.tsv' if not missing else 'FAIL: missing ' + ','.join(missing)
        else:
            rows = s1(who[0], who[1], method, path)
            r['s1_rows'] = len(rows)
            if not rows: r['result'] = 'FAIL: edge absent from edges.tsv'
            elif kind == 'body':
                types = sorted(set(x['body_type'] for x in rows)); r['s1_body_types'] = types
                if all(is_map(t) or t == '-' for t in types): r['result'] = 'FAIL: caller body is Map/absent, field not declared'
                elif src and grep(*src) is False: r['result'] = 'FAIL: field not found in declared type source'
                elif src and grep(*src) is None: r['result'] = 'NOT CHECKED: source file missing'
                else: r['result'] = 'OK: declared type ' + '/'.join(types) + (' (field verified in source)' if src else '')
            elif kind == 'path':
                r['result'] = 'OK: path variable present in caller template' if '{' + field + '}' in ''.join(x['path_template'] for x in rows) else 'FAIL: not in caller template'
            else:
                g = grep(*src) if src else None
                r['result'] = ('OK (source-only: edges.tsv has no parameter columns)' if g else 'FAIL: @Query not found in caller source' if g is False else 'NOT CHECKED')
        res.append(r)
    fails = [r['hop'] for r in res if r['result'].startswith('FAIL')]
    out[name] = {'hops': res, 'fails': fails, 'verdict': 'passes' if not fails else 'fails at ' + ', '.join(fails)}
json.dump(out, open(os.path.join(here, 'r1e_chains.json'), 'w'), indent=1)
for n, v in out.items():
    print(n, '=>', v['verdict'])
    for r in v['hops']: print('   ', r['hop'], r['side'], r['method'], r['path'], r['field'], '->', r['result'])
