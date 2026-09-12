#!/usr/bin/env python3
"""Sensitivity of R1(a)/R1(b) to S2's Igor gap.  S2's scanner pruned the package
com.netflix.spinnaker.igor.build (extract.py:949 drops directories named 'build'), so
BuildController.groovy (12 mappings) and InfoController.groovy (4) are absent from endpoints.tsv.
The provider signatures below were read by hand from igor@v4.22.0 (an ESTIMATE that S2's
re-delivered endpoints.tsv must replace).  Re-runs the matcher for the unmatched Igor edges and
recomputes the untyped share on the enlarged reconciled set."""
import csv, re, json, os, sys, importlib.util
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('r', os.path.join(here, 'r1ab_reconcile.py'))
# reuse the classifier and normalizer without re-running the module's output section
src = open(os.path.join(here, 'r1ab_reconcile.py')).read().split('# cross-check my strict classifier')[0]
ns = {'__file__': os.path.join(here, 'r1ab_reconcile.py')}; exec(compile(src, 'r1ab', 'exec'), ns)
norm_path, template_regex, classify = ns['norm_path'], ns['template_regex'], ns['classify']
# hand-read from igor-web/src/main/groovy/com/netflix/spinnaker/igor/build/{BuildController,InfoController}.groovy @ v4.22.0
MISSING = [  # (method, path_template, body_type, return_type, source line)
 ('GET', '/builds/status/{buildNumber}/{master:.+}/**', '-', 'GenericBuild', 'BuildController.groovy:101'),
 ('GET', '/builds/status/{buildNumber}/{master}', '-', 'GenericBuild', 'BuildController.groovy:111'),
 ('GET', '/builds/artifacts/{buildNumber}/{master:.+}/**', '-', 'List<Artifact>', 'BuildController.groovy:121'),
 ('GET', '/builds/artifacts/{buildNumber}/{master}', '-', 'List<Artifact>', 'BuildController.groovy:137'),
 ('GET', '/builds/queue/{master}/{item}', '-', 'Object', 'BuildController.groovy:150'),
 ('GET', '/builds/all/{master:.+}/**', '-', 'List<Object>', 'BuildController.groovy:157'),
 ('PUT', '/masters/{name}/jobs/{jobName}/stop/{queuedBuild}/{buildNumber}', '-', 'String', 'BuildController.groovy:166'),
 ('PUT', '/masters/{master}/jobs/stop/{queuedBuild}/{buildNumber}', '-', 'String', 'BuildController.groovy:177'),
 ('PATCH', '/masters/{name}/jobs/**/update/{buildNumber}', 'UpdatedBuild', 'void', 'BuildController.groovy:216'),
 ('PUT', '/masters/{name}/jobs/**', '-', 'ResponseEntity<String>', 'BuildController.groovy:234'),
 ('GET', '/builds/properties/{buildNumber}/{fileName}/{master:.+}/**', '-', 'Map<String, Object>', 'BuildController.groovy:335'),
 ('GET', '/builds/properties/{buildNumber}/{fileName}/{master}', '-', 'Map<String, Object>', 'BuildController.groovy:353'),
 ('GET', '/masters', '-', 'List<String>', 'InfoController.groovy:56'),
 ('GET', '/buildServices', '-', 'List<BuildService>', 'InfoController.groovy:69'),
 ('GET', '/jobs/{master:.+}', '-', 'List<String>', 'InfoController.groovy:80'),
 ('GET', '/jobs/{master:.+}/**', '-', 'Object', 'InfoController.groovy:116'),
]
base = json.load(open(os.path.join(here, 'r1ab.json')))
unmatched = [r for r in csv.DictReader(open(os.path.join(here, 'r1a_unmatched.tsv')), delimiter='\t') if r['provider'] == 'igor' and r['category'] == 'no-provider-mapping']
edges = {(e['caller'], e['provider'], e['method'], e['path_template']): e for e in csv.DictReader(open(os.path.join(here, '..', 'S1', 'edges.tsv')), delimiter='\t')}
cands = [(m, norm_path(p, 'igor'), template_regex(norm_path(p, 'igor')), b, r, s) for m, p, b, r, s in MISSING]
newly, still = [], []
for u in unmatched:
    n = norm_path(u['caller_path'], 'igor')
    hits = [c for c in cands if c[0] == u['method'] and c[2].match(n)]
    if not hits: still.append(u); continue
    hits.sort(key=lambda c: -sum(1 for s in c[1].split('/') if s and s not in ('{}', '**')))
    e = edges[(u['caller'], u['provider'], u['method'], u['caller_path'])]
    m, np_, rx, body, ret, srcl = hits[0]
    strict = 'untyped' in (classify(e['body_type'], True), classify(e['return_type'], True), classify(body, True), classify(ret, True))
    refined = 'untyped' in (classify(e['body_type'], False), classify(e['return_type'], False), classify(body, False), classify(ret, False))
    newly.append({'caller': u['caller'], 'method': u['method'], 'caller_path': u['caller_path'], 'provider_template': hits[0][1], 'provider_src': srcl,
                  'caller_body': e['body_type'], 'caller_return': e['return_type'], 'provider_body': body, 'provider_return': ret, 'untyped_as_written': strict, 'untyped_refined': refined})
m0, r0 = base['matched'], base['resolved']
u0s, u0r = base['untyped_share_as_written']['untyped'], base['untyped_share_s5_refined']['untyped']
m1 = m0 + len(newly); u1s = u0s + sum(x['untyped_as_written'] for x in newly); u1r = u0r + sum(x['untyped_refined'] for x in newly)
act = base['unmatched_by_category'].get('actuator', 0)
res = {'igor_unmatched_before': len(unmatched), 'newly_matched_with_hand_read_igor_rows': len(newly), 'still_unmatched': [(u['caller'], u['method'], u['caller_path']) for u in still],
       'matched_after': m1, 'matched_share_after': round(m1 / r0, 4), 'matched_share_after_excluding_actuator': round(m1 / (r0 - act), 4),
       'untyped_share_as_written_after': {'untyped': u1s, 'of': m1, 'share': round(u1s / m1, 4)},
       'untyped_share_refined_after': {'untyped': u1r, 'of': m1, 'share': round(u1r / m1, 4)},
       'newly_matched': newly, 'note': 'ESTIMATE: provider rows hand-read from the two controllers S2 missed; S2 must re-deliver endpoints.tsv'}
json.dump(res, open(os.path.join(here, 'r1b_sensitivity_igor_gap.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != 'newly_matched'}, indent=1))
for x in newly: print('  ', x['caller'], x['method'], x['caller_path'], '->', x['provider_template'], '|', x['caller_body'], x['caller_return'], '|', x['provider_body'], x['provider_return'], '| untyped:', x['untyped_as_written'])
