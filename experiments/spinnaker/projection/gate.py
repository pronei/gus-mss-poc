#!/usr/bin/env python3
"""D11: `gus consistent` at every BOM baseline, and a triage row for every failure.

    python3 gate.py [--presence none] [--boms 1.38.0,1.37.11]     # graphs, `gus consistent`, triage/<presence>/<bom>.tsv
    python3 gate.py --provisional --boms 1.38.0                   # edge names over the BOMs extracted so far

For each BOM the nine loaded copies and the BOM's graph are written
(graph.py), `gus consistent` runs on the baseline scenario, and every finding
it prints becomes one triage row with the context the documents give: the leg,
the component (`params`, `headers`, `body`, response), the parameter and
whether it is a path variable, the two schemas at the finding's path, the
collision diagnostics. The category is assigned by `classify` from those facts
and two small tables read off the bytecode where the documents cannot tell
(`PROVIDER_RESPONSE`, `PROVIDER_PARAMS`); nothing is assigned by hand per row.

Categories (D11): projection defect, normalization defect, opaque response,
real inconsistency — plus `warning` (a WARN-only finding: `gus consistent`
prints it, but the baseline gate inside `check`/`mss` counts only BREAKs,
main.go:469, so the edge stays) and `checker limitation` (both declarations are
what the rules say and agree on the wire, and the checker still breaks them —
decisions.md, needs owner). Every BREAK row excludes its edge from the pair
whose baseline this BOM is: `gus check` refuses an inconsistent baseline
(main.go:476), and a normalization defect is fixed in normalize.py/graph.py
rather than excluded, so none should remain.
"""
import argparse
import collections
import csv
import json
import os
import re
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graph as G
import normalize as N
from common import HERE, PROFILES, SERVICES, boms, gus_bin, pin_doc, pins

LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)

# Provider operations whose response the extractor writes as a contentless 200 for different Java
# reasons the document does not record, read off the bytecode at 1.38.0 (javap -v; see memo.md).
# Keyed on (provider, VERB, match path).
PROVIDER_RESPONSE = {
    ('orca', 'PUT', '/tasks/{}/cancel'): ('void', 'orca-web TaskController.cancelTask: void, @ResponseStatus(ACCEPTED)'),
    ('orca', 'PUT', '/tasks/cancel'): ('void', 'orca-web TaskController.cancelTasks: void, @ResponseStatus(ACCEPTED)'),
    ('orca', 'DELETE', '/tasks/{}'): ('void', 'orca-web TaskController.deleteTask: void'),
    ('orca', 'DELETE', '/pipelines/{}'): ('void', 'orca-web TaskController.deletePipeline: void (8.31.0 and 8.64.0)'),
    ('orca', 'PUT', '/pipelines/{}/cancel'): ('void', 'orca-web TaskController.cancel: void, @ResponseStatus(ACCEPTED) (8.31.0 and 8.64.0)'),
    ('orca', 'PUT', '/pipelines/{}/pause'): ('void', 'orca-web TaskController.pause: void, @ResponseStatus(ACCEPTED) (8.31.0 and 8.64.0)'),
    ('orca', 'PUT', '/pipelines/{}/resume'): ('void', 'orca-web TaskController.resume: void, @ResponseStatus(ACCEPTED) (8.31.0 and 8.64.0)'),
    ('echo', 'POST', '/'): ('void', 'echo-web HistoryController.saveHistory(@RequestBody Event): void'),
    ('kayenta', 'PUT', '/pipelines/{}/cancel'): ('void', 'kayenta-orca PipelineController.cancel: void, @ResponseStatus(ACCEPTED)'),
    ('clouddriver', 'PUT', '/artifacts/fetch'): ('stream', 'clouddriver-web ArtifactController.fetch: StreamingResponseBody'),
    ('clouddriver', 'GET', '/applications/{}/clusters/{}/{}/aws/serverGroups/{}/scalingActivities'):
        ('raw', 'clouddriver-aws AmazonClusterController.getScalingActivities: raw ResponseEntity'),
    ('clouddriver', 'GET', '/applications/{}/serverGroups/{}/{}/events'):
        ('raw', 'clouddriver-ecs EcsServerGroupController.getServerGroupEvents: raw ResponseEntity'),
}
# Provider parameters the document misstates, read off the bytecode. Keyed on (provider, VERB, match path, name).
PROVIDER_PARAMS = {
    ('clouddriver', 'GET', '/credentials', 'expand'):
        'clouddriver-web CredentialsController.listAccountCredentials(@RequestParam Optional<Boolean> expand): '
        'an Optional parameter is optional in Spring and typed by its argument; the document has a required string',
}
# Caller query parameters declared on a Java primitive, read off the bytecode of the Retrofit interface at 1.30.0 and
# 1.38.0: Retrofit omits a @Query only when its argument is null, and a primitive never is, so the caller always sends
# it; the document marks every @Query optional (G1 decisions.md 5). Keyed on (caller, VERB, provider match path, name).
CALLER_PRIMITIVE_QUERY = {
    ('orca', 'PUT', '/pluginInfo/{}/releases/{}', 'preferred'):
        'orca-front50 Front50Service.setPreferredPluginVersion(@Query("preferred") boolean): a primitive @Query is always sent, '
        'and the document marks it optional (G1 decisions.md 5)',
}
RAW_BODY_TYPES = {'okhttp3.RequestBody', 'retrofit.mime.TypedInput', 'retrofit.mime.TypedString', 'retrofit.mime.TypedByteArray'}

TRIAGE_COLUMNS = ['bom', 'presence', 'edge', 'caller', 'provider', 'verb', 'path', 'caller_path', 'caller_interface',
                  'leg', 'component', 'severity', 'rule', 'violation_path', 'old', 'new', 'category', 'basis', 'excluded']

VIOLATION = re.compile(r'^  \[(BREAK|WARN|INFO)\] \[(CONSIST-REQ|CONSIST-RES)\](\S*): (.*) \(old: (.*), new: (.*)\) \[([^\]]+)\]$')


def parse_consistent(text):
    out, edge = [], None
    for ln in text.splitlines():
        m = re.match(r'^Edge (\S+) — INCONSISTENT:$', ln)
        if m:
            edge = m.group(1)
            continue
        m = VIOLATION.match(ln)
        if m:
            out.append({'edge': edge, 'severity': m.group(1), 'leg': 'request' if m.group(2) == 'CONSIST-REQ' else 'response',
                        'path': m.group(3), 'message': m.group(4), 'old': m.group(5), 'new': m.group(6), 'rule': m.group(7)})
        elif ln.startswith('  ['):
            raise ValueError('unparsed consistent line: %r' % ln)
    return out


# --------------------------------------------------------------------------- schema walking

def tokens(vpath):
    """'$.body.a[*].b' -> ['body', 'a', '[*]', 'b']."""
    return re.findall(r'\[\*\]|[^.\[\]]+', vpath[1:])


def walk(schema, toks, components):
    """Every schema node the finding's path can denote (oneOf variants, $ref, map values)."""
    nodes = [schema] if schema is not None else []
    for t in toks:
        nxt = []
        for n in _expand(nodes, components):
            if t == '[*]':
                if isinstance(n.get('items'), dict):
                    nxt.append(n['items'])
            elif t in ('value', 'key') and isinstance(n.get('additionalProperties'), dict) and not n.get('properties'):
                nxt.append(n['additionalProperties'] if t == 'value' else {'type': 'string'})
            elif isinstance(n.get('properties'), dict) and t in n['properties']:
                nxt.append(n['properties'][t])
        nodes = nxt
    return list(_expand(nodes, components))


def _expand(nodes, components, depth=0):
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if '$ref' in n and depth < 4:
            ref = components.get(n['$ref'].rsplit('/', 1)[-1])
            yield from _expand([ref], components, depth + 1)
        elif n.get('oneOf') and depth < 4:
            yield from _expand(n['oneOf'], components, depth + 1)
        else:
            yield n


def kind_of(summary):
    """The checker's kind of a type summary: prim, enum, array, map, object, union, ref, any."""
    m = re.match(r'^(nullable\()?([a-z]+)', summary)
    k = m.group(2) if m else summary
    return 'prim' if k in ('string', 'integer', 'number', 'boolean', 'null') else k


# --------------------------------------------------------------------------- classification

def classify(v, c):
    """(category, basis) for one finding, from its context `c` (see enrich)."""
    rule, comp = v['rule'], c['component']
    if v['severity'] != 'BREAK':
        return 'warning', 'WARN only (%s): the baseline gate inside check/mss counts BREAKs alone (main.go:469)' % rule
    if c['provider_collision']:
        return 'projection defect', 'same-key collision: the provider maps two handlers on %s %s and the document keeps one (%s; CLAIM-G1-009)' % (
            c['verb'], c['path'], c['provider_collision'])
    if c['caller_collision']:
        return 'projection defect', 'caller-side collision: several caller declarations answer to this edge; one is loaded (%s)' % c['caller_collision']

    if comp in ('params', 'headers'):
        name = c['param']
        fact = PROVIDER_PARAMS.get((c['provider'], c['verb'], c['provider_mpath'], name)) if name else None
        if fact is None and name is None:
            facts = [PROVIDER_PARAMS[k] for k in PROVIDER_PARAMS if k[:3] == (c['provider'], c['verb'], c['provider_mpath'])]
            fact = facts[0] if facts else None
        if fact:
            return 'projection defect', fact
        primitive = CALLER_PRIMITIVE_QUERY.get((c['caller'], c['verb'], c['provider_mpath'], name)) if name else None
        if primitive and rule == 'REQ.2':
            return 'projection defect', primitive
        if name and c['param_is_path_var'] and rule == 'REQ.1':
            return 'normalization defect', 'path variable {%s} not aligned by position with the caller' % name
        if rule == 'REQ.2':
            what = ('%s.%s' % (comp, name)) if name else comp
            return 'real inconsistency', 'declared: the provider requires %s; the caller declares it optional (a Retrofit @Query/@Header is omitted when null; G1 decisions.md 5)' % what
        if rule == 'REQ.1':
            what = ('%s.%s' % (comp, name)) if name else '%s (%s)' % (comp, v['new'])
            return 'real inconsistency', 'declared: the provider requires %s, which the caller never sends' % what
        if rule == 'kind-mismatch' and {kind_of(v['old']), kind_of(v['new'])} == {'array', 'prim'}:
            return 'projection defect', ('query parameter arity: %s against %s; Spring binds repeated or comma-separated values to both '
                                         'a String and a List parameter, and the extractor types parameters by their Java type (G1 decisions.md 8)') % (v['old'], v['new'])
        if rule == 'prim-mismatch':
            if v['new'].startswith('string'):
                return 'projection defect', ('parameter text binding: a %s argument is sent as text and Spring binds any text to a String parameter; '
                                             'the strict lattice compares Java types (G1 decisions.md 8)') % v['old']
            return 'real inconsistency', 'declared: the caller passes %s where the provider converts to %s' % (v['old'], v['new'])
        if rule == 'enum-request-narrowing':
            return 'real inconsistency', 'declared: the caller passes any %s where the provider converts to %s' % (v['old'], v['new'])

    if comp == 'body':
        if rule == 'kind-mismatch' and c['provider_body_raw_string']:
            return 'projection defect', ('@RequestBody String: Spring reads the raw text of any payload into it, and the document '
                                         'declares a JSON string, so the caller\'s %s is refused' % v['old'])
        if c['caller_body_java'] in RAW_BODY_TYPES:
            return 'projection defect', '%s is raw bytes on the wire and is projected as a bean %s' % (c['caller_body_java'], v['old'])
        if rule == 'kind-mismatch' and {kind_of(v['old']), kind_of(v['new'])} == {'object', 'map'}:
            return 'checker limitation', 'object against map: %s vs %s; the wire shape agrees, the checker compares kinds' % (v['old'], v['new'])

    if comp == 'response':
        if rule == 'presence-mismatch' and v['new'] == '<nil>':
            fact = PROVIDER_RESPONSE.get((c['provider'], c['verb'], c['provider_mpath']))
            if fact is None:
                return 'untriaged', 'the caller reads %s; the provider document has a contentless 200 and PROVIDER_RESPONSE has no row' % v['old']
            if fact[0] == 'void':
                return 'real inconsistency', 'declared: the caller reads a %s body; the provider sends none (%s)' % (v['old'], fact[1])
            if fact[0] == 'stream':
                return 'opaque response', 'D6: the provider streams a non-JSON body (%s) that the caller reads as %s' % (fact[1], v['old'])
            return 'projection defect', 'a raw ResponseEntity has an untyped body, and the document has a contentless 200 (%s)' % fact[1]
        if rule == 'presence-mismatch':
            return 'opaque response', 'D6 not applied: the caller declares no body, the provider returns %s' % v['new']
        if rule == 'kind-mismatch':
            kinds = {kind_of(v['old']), kind_of(v['new'])}
            if kinds == {'object', 'map'}:
                return 'checker limitation', 'object against map: %s vs %s; a JSON object either way, the checker compares kinds' % (v['old'], v['new'])
            if 'object(open){}' in (v['old'], v['new']) or c['untyped_side']:
                return 'checker limitation', ('an untyped side (D5: an open object) of another JSON kind: %s vs %s; the leg is vacuous '
                                              'under the D5 ruling, which assumed such a leg can only pass' % (v['old'], v['new']))
            return 'real inconsistency', 'declared: the caller reads %s where the provider returns %s' % (v['old'], v['new'])
        if rule == 'nullable-response-widening':
            return 'projection defect', ('D8: the caller\'s field carries no nullability annotation and is projected non-nullable ("unknown"), '
                                         'while the provider marks it nullable (%s vs %s)' % (v['old'], v['new']))
        if rule == 'enum-response-widening':
            return 'real inconsistency', 'declared: the provider returns %s where the caller enumerates %s' % (v['new'], v['old'])
        if rule in ('prim-mismatch', 'enum-prim-mismatch'):
            return 'real inconsistency', 'declared: the caller reads %s where the provider returns %s' % (v['old'], v['new'])
        if rule in ('RES.1', 'RES.4'):
            return 'real inconsistency', 'declared presence: %s' % v['message']
    return 'untriaged', v['message']


# --------------------------------------------------------------------------- one BOM

class Docs:
    def __init__(self, presence, bom):
        self.presence, self.bom, self.cache = presence, bom, {}

    def loaded(self, svc):
        if svc not in self.cache:
            with open(os.path.join(HERE, 'graph', self.presence, 'loaded', self.bom, svc + '.yaml')) as f:
                self.cache[svc] = yaml.load(f, Loader=LOADER)
        return self.cache[svc]


def _wrapper(op):
    return (((op.get('requestBody') or {}).get('content') or {}).get('application/json') or {}).get('schema') or {}


def _response(op):
    return ((((op.get('responses') or {}).get('200') or {}).get('content') or {}).get('application/json') or {}).get('schema')


def enrich(v, e, docs, idx):
    caller_doc, provider_doc = docs.loaded(e['caller']), docs.loaded(e['provider'])
    cop = caller_doc['paths'][N.calls_key(e['provider'], e['path'])][e['verb'].lower()]
    pop = provider_doc['paths'][e['path']][e['verb'].lower()]
    toks = tokens(v['path'])
    c = {'caller': e['caller'], 'provider': e['provider'], 'verb': e['verb'], 'path': e['path'],
         'provider_mpath': e['provider_mpath'], 'caller_path': e['caller_path'], 'caller_interface': e['caller_iface'],
         'caller_collision': ', '.join(e.get('collision') or []), 'param': None, 'param_is_path_var': False,
         'provider_body_raw_string': False, 'caller_body_java': '', 'untyped_side': False}
    dup = [d for d in idx[e['provider']]['duplicate_endpoints'] if d.split(' (')[0] == '%s %s' % (e['verb'], e['path'])]
    c['provider_collision'] = '; '.join(dup)
    if v['leg'] == 'request':
        c['component'] = toks[0] if toks else 'wrapper'
        rest = toks[1:]
        if c['component'] in ('params', 'headers') and rest:
            c['param'] = rest[0]
            c['param_is_path_var'] = rest[0] in re.findall(r'\{([^}:]*)', e['path'])
        if c['component'] == 'body':
            pbody = (_wrapper(pop).get('properties') or {}).get('body') or {}
            cbody = (_wrapper(cop).get('properties') or {}).get('body') or {}
            c['provider_body_raw_string'] = pbody.get('type') == 'string' and 'enum' not in pbody and not rest
            c['caller_body_java'] = cbody.get('x-java-type', '')
            cn = walk(_wrapper(cop), toks, (caller_doc.get('components') or {}).get('schemas') or {})
            pn = walk(_wrapper(pop), toks, (provider_doc.get('components') or {}).get('schemas') or {})
            c['untyped_side'] = any(n.get('x-untyped') for n in cn + pn)
    else:
        c['component'] = 'response'
        cn = walk(_response(cop), toks, (caller_doc.get('components') or {}).get('schemas') or {})
        pn = walk(_response(pop), toks, (provider_doc.get('components') or {}).get('schemas') or {})
        c['untyped_side'] = any(n.get('x-untyped') for n in cn + pn)
    return c


def gate_bom(bom, presence, names, gus):
    t0 = time.time()
    m = G.match(bom, presence)
    graph_path, d6 = G.write_bom_graph(bom, presence, m, names)
    scenario = G.baseline_scenario(bom)
    p = subprocess.run([gus, 'consistent', '--graph', graph_path, '--scenario', scenario], capture_output=True, text=True)
    if p.returncode not in (0, 1):
        raise SystemExit('gus consistent could not evaluate %s (%s): exit %d\n%s' % (bom, presence, p.returncode, p.stderr[-3000:]))
    violations = parse_consistent(p.stdout)
    by_name = {names[G.identity(e)]: e for e in m['edges']}
    docs = Docs(presence, bom)
    idx = {s: N.doc_index(presence, s, pins()[bom][s]) for s in SERVICES}
    rows = []
    for v in violations:
        e = by_name[v['edge']]
        ctx = enrich(v, e, docs, idx)
        category, basis = classify(v, ctx)
        rows.append({'bom': bom, 'presence': presence, 'edge': v['edge'], 'caller': e['caller'], 'provider': e['provider'],
                     'verb': e['verb'], 'path': e['path'], 'caller_path': e['caller_path'], 'caller_interface': e['caller_iface'],
                     'leg': v['leg'], 'component': ctx['component'], 'severity': v['severity'], 'rule': v['rule'],
                     'violation_path': v['path'], 'old': v['old'], 'new': v['new'], 'category': category, 'basis': basis,
                     'excluded': 'yes' if v['severity'] == 'BREAK' else 'no'})
    out_dir = os.path.join(HERE, 'triage', presence)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, '%s.tsv' % bom), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=TRIAGE_COLUMNS, delimiter='\t', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    excluded = sorted({r['edge'] for r in rows if r['excluded'] == 'yes'}, key=G._name_order)
    return {'bom': bom, 'presence': presence, 'edges': len(m['edges']), 'consistent': p.returncode == 0,
            'inconsistent_edges': len({r['edge'] for r in rows}), 'excluded_edges': excluded,
            'findings': len(rows), 'by_category': dict(collections.Counter(r['category'] for r in rows)),
            'edges_by_category': {k: len({r['edge'] for r in rows if r['category'] == k}) for k in {r['category'] for r in rows}},
            'd6_expect_any': len(d6), 'aligned_edges': sum(1 for e in m['edges'] if e.get('aligned')),
            'seconds': round(time.time() - t0, 2)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--presence', choices=PROFILES)
    ap.add_argument('--boms')
    ap.add_argument('--provisional', action='store_true', help='name edges over the BOMs whose documents exist')
    a = ap.parse_args(argv)
    selected = a.boms.split(',') if a.boms else list(boms())
    gus = gus_bin()
    summary_path = os.path.join(HERE, 'triage', 'gate-summary.json')
    summary = {}
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = json.load(f)
    for presence in ([a.presence] if a.presence else list(PROFILES)):
        available = None
        if a.provisional:
            available = [b for b in boms() if all(os.path.exists(pin_doc(r, s, pins()[b][s]))
                                                  for s in SERVICES for r in (presence, N.KEEP))]
        _, _, names = G.catalog(presence, available=available)
        for bom in selected:
            r = gate_bom(bom, presence, names, gus)
            summary.setdefault(presence, {})[bom] = r
            print('%-8s %-8s edges %3d  inconsistent %3d  excluded %3d  %s  (%.1fs)' % (
                presence, bom, r['edges'], r['inconsistent_edges'], len(r['excluded_edges']),
                json.dumps(r['edges_by_category'], sort_keys=True), r['seconds']), flush=True)
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=1, sort_keys=True)
        f.write('\n')
    untriaged = [(p, b) for p in summary for b in summary[p] if summary[p][b]['by_category'].get('untriaged')]
    if untriaged:
        print('!! untriaged findings at: %s' % untriaged)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
