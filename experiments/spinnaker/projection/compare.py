#!/usr/bin/env python3
"""What the checker saw, pair by pair, next to what S4 says.

    python3 compare.py [--provisional]   # results/compare.md, results/compare.json, results/findings.tsv, results/caller-drift.tsv

Inputs: results/<presence>/P<NN>/<batch>.{check.json,check.rc,check.err,mss.txt} (run.sh),
graph/<presence>/pairs.json and the pair graphs (graph.py), the extractor's documents through
normalize's index, scout/S4/ground-truth-candidates.md. `--provisional` reads only the pairs whose two
BOMs are extracted and whose results exist, with edge names over those BOMs (a dry run before the
extraction has finished).

How a finding is read.

* Conjunct and leg. `gus check` prefixes every violation's path with its
  conjunct (pkg/edge `tagViolations`): C1 and C2 are the request leg, C3 and C4
  the response leg. TGT carries both; a TGT path whose first step is `params`,
  `headers` or `body` belongs to the request leg unless that name is also a
  top-level field of either response schema, in which case the rule decides
  (REQ.*, *-request-*, a sender/receiver message).
* The pairing. Each conjunct compares one version of the caller with one of the
  provider: C1 (θ caller, θ' provider), C2 (θ', θ), C3 (θ, θ'), C4 (θ', θ), TGT
  (θ', θ'). Liveness is decided at that pairing, not at one BOM: a leg is live
  when neither declaration carries `x-untyped`, vacuous when exactly one does,
  untyped when both do, contentless when neither has content, and
  contentless-one-side when exactly one lacks it (D5; `r1b_legs.py`). Request
  findings are judged per component (`params`, `headers`, `body`), response
  findings on the response schema.
* Evidence. A finding is evidence when it is a BREAK, its component is live at
  its pairing, and its edge has no collision (a provider handler or a caller
  declaration that shares the edge's path and verb with another one — the
  handoff: a finding on a collided edge is not evidence).
* Every conjunct depends only on which of the edge's two services upgrade, and
  the `all` batch upgrades both ends of every edge, so a pair's distinct findings
  are the findings of its `all` batch; the other 45 batches are read for their
  verdicts and safe subsets.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graph as G
import normalize as N
from common import HERE, PROFILES, SERVICES, SPIN, boms, pairs, parse_version, pin_doc, pins

RESULTS = os.path.join(HERE, 'results')
CONJ = {'C1': ('from', 'to'), 'C2': ('to', 'from'), 'C3': ('from', 'to'), 'C4': ('to', 'from'), 'TGT': ('to', 'to')}
SEVERITY = {0: 'BREAK', 1: 'WARN', 2: 'INFO'}

# The two contract-visible breaking rows of S4 in range (review pass 1, R1(d)), traced to the edge they name.
LABEL_EDGES = {
    'CLAIM-S4-021': [('echo', 'front50', 'GET', '/pipelines/{}/get')],
    'CLAIM-S4-023': [('igor', 'echo', 'POST', '/')],
}


# --------------------------------------------------------------------------- documents

class Ops:
    """Operation summaries of the extractor's documents (normalize.doc_index), looked up by path and verb."""

    def __init__(self, presence):
        self.presence = presence
        self.cache = {}

    def _tables(self, svc, bom):
        k = (svc, bom)
        if k not in self.cache:
            idx = N.doc_index(self.presence, svc, pins()[bom][svc])
            self.cache[k] = ({(o['path'], o['verb']): o for o in idx['provider']},
                             {(o['path'], o['verb']): o for o in idx['client']}, idx)
        return self.cache[k]

    def provider(self, svc, bom, path, verb):
        return self._tables(svc, bom)[0].get((path, verb))

    def caller(self, svc, bom, path, verb):
        return self._tables(svc, bom)[1].get((path, verb))

    def index(self, svc, bom):
        return self._tables(svc, bom)[2]

    def collided(self, e, bom):
        """A duplicate-endpoint loss on the edge's provider handler or on its caller declaration."""
        prov = '%s %s' % (e['verb'], e['path'])
        call = '%s %s' % (e['verb'], e['caller_path'])
        return (any(d.split(' (')[0] == prov for d in self.index(e['provider'], bom)['duplicate_endpoints'])
                or any(d.split(' (')[0] == call for d in self.index(e['caller'], bom)['duplicate_endpoints'])
                or bool(e.get('collision')))


def leg_state(caller, provider):
    """r1b_legs.leg_state, verbatim."""
    if caller == 'untyped' and provider == 'untyped':
        return 'untyped'
    if caller == 'none' and provider == 'none':
        return 'contentless'
    if 'untyped' in (caller, provider):
        return 'vacuous'
    if 'none' in (caller, provider):
        return 'contentless-one-side'
    return 'live'


def component_state(cop, pop, leg, component):
    if cop is None or pop is None:
        return 'missing'
    if leg == 'response':
        return leg_state(cop['resp'], pop['resp'])
    key = component if component in ('params', 'headers', 'body') else 'wrapper'
    return leg_state(cop['req'][key], pop['req'][key])


# --------------------------------------------------------------------------- checker output

def tokens(vpath):
    return re.findall(r'\[\*\]|[^.\[\]]+', vpath[1:])


def split_violation(v):
    m = re.match(r'^\[([A-Z0-9-]+)\](.*)$', v['Path'])
    return (m.group(1), m.group(2)) if m else ('', v['Path'])


def attribute(tag, vpath, v, cop, pop):
    """(leg, component) of one violation; cop/pop are the θ' operation summaries."""
    toks = tokens(vpath)
    first = toks[0] if toks else None
    if tag in ('C1', 'C2'):
        leg = 'request'
    elif tag in ('C3', 'C4'):
        leg = 'response'
    elif first in ('params', 'headers', 'body'):
        fields = set((cop or {}).get('resp_top_fields') or []) | set((pop or {}).get('resp_top_fields') or [])
        if first not in fields:
            leg = 'request'
        else:
            text = (v['Rule'] + ' ' + v['Message']).lower()
            leg = 'request' if (v['Rule'].startswith('REQ') or 'request' in v['Rule'] or 'sender' in text or 'receiver' in text) else 'response'
    else:
        leg = 'response'
    component = (first if first in ('params', 'headers', 'body') else 'wrapper') if leg == 'request' else 'response'
    return leg, component


def parse_mss(text):
    dec = re.search(r'^Decision: (YES|NO)', text, re.M)
    r = {'decision': dec.group(1) if dec else None, 'safe': None, 'order': [], 'excluded': {}, 'posthoc': None}
    if r['decision'] != 'NO':
        return r
    safe = re.search(r'^Safe subset: \{(.*)\}', text, re.M)
    r['safe'] = sorted(re.findall(r'([a-z0-9]+) [0-9.]+→[0-9.]+', safe.group(1))) if safe else []
    order = re.search(r'^Rollout order.*\n((?:  \d+\. .*\n)+)', text, re.M)
    if order:
        r['order'] = [ln.split('. ', 1)[1].split(', ') for ln in order.group(1).strip('\n').split('\n')]
    elif r['safe']:
        r['order'] = [r['safe']]
    for svc, why in re.findall(r'^  ([a-z0-9]+) [0-9.]+→[0-9.]+ — (.*)$', text, re.M):
        r['excluded'][svc] = why
    ph = re.search(r'^Post-hoc verification of the safe subset: (PASS|FAIL)', text, re.M)
    r['posthoc'] = ph.group(1) if ph else None
    return r


# --------------------------------------------------------------------------- S4 labels

def s4_rows():
    rows = []
    with open(os.path.join(SPIN, 'scout', 'S4', 'ground-truth-candidates.md')) as f:
        for ln in f:
            if not ln.startswith('| ') or ln.startswith('| pair') or ln.startswith('|---'):
                continue
            cells = [c.strip() for c in ln.strip().strip('|').split(' | ')]
            rows.append({'pair': cells[0], 'services': cells[1], 'kind': cells[2], 'quote': ' | '.join(cells[3:-2]),
                         'url': cells[-2], 'claim': cells[-1]})
    return rows


def label_to_pairs(label_pair, services_text):
    """D10: `1.N.x -> 1.M.0` is the pair (last 1.N patch, 1.M.0); two explicit BOM versions that are not
    consecutive map to the consecutive pairs between them at which a named service's pin changes."""
    m = re.match(r'^(\S+) -> (\S+)$', label_pair)
    if not m:
        return [], 'unparsed'
    a, b = m.groups()
    bs = list(boms())
    if a.endswith('.x'):
        patches = [v for v in bs if v.startswith(a[:-1])]
        if not patches:
            return [], 'outside the range (%s is not in 1.30.0…1.38.0)' % a
        a = max(patches, key=parse_version)
    if a not in bs or b not in bs:
        return [], 'outside the range'
    ia, ib = bs.index(a), bs.index(b)
    if ib <= ia:
        return [], 'not in version order'
    span = [('P%02d' % (i + 1), bs[i], bs[i + 1]) for i in range(ia, ib)]
    if len(span) == 1:
        return [span[0][0]], 'consecutive pair'
    named = [s for s in SERVICES if re.search(r'\b%s\b' % s, services_text)]
    crossing = [p for p, x, y in span if any(pins()[x][s] != pins()[y][s] for s in named)]
    return crossing, 'span %s..%s, pairs where %s change pin' % (span[0][0], span[-1][0], '/'.join(named) or 'a named service')


# --------------------------------------------------------------------------- one pair

def read_batches(presence, pair):
    out_dir = os.path.join(RESULTS, presence, pair)
    batches = {}
    for rc_path in sorted(glob.glob(os.path.join(out_dir, '*.check.rc'))):
        batch = os.path.basename(rc_path)[:-len('.check.rc')]
        with open(rc_path) as f:
            text = f.read().strip()
        entry = {'rc': int(text) if text else 2}
        if entry['rc'] not in (0, 1):
            with open(os.path.join(out_dir, batch + '.check.err')) as f:
                entry['error'] = f.read().strip()[-1500:]
        else:
            with open(os.path.join(out_dir, batch + '.check.json')) as f:
                entry['check'] = json.load(f)
            mss_path = os.path.join(out_dir, batch + '.mss.txt')
            if os.path.exists(mss_path):
                with open(mss_path) as f:
                    entry['mss'] = parse_mss(f.read())
        batches[batch] = entry
    return batches


def read_findings(presence, pair, a, b, batches, ops, names, per_bom):
    A = {G.identity(e): e for e in per_bom[a]['edges']}
    B = {G.identity(e): e for e in per_bom[b]['edges']}
    by_name = {names[i]: i for i in set(A) & set(B)}
    findings, tier3 = [], []
    for er in ((batches.get('all') or {}).get('check') or {}).get('Edges') or []:
        name = er['Edge']['Name']
        if not er.get('CallerSpecUsed'):
            tier3.append(name)
        ident = by_name[name]
        ea, eb = A[ident], B[ident]
        cop = {'from': ops.caller(ea['caller'], a, ea['caller_path'], ea['verb']),
               'to': ops.caller(eb['caller'], b, eb['caller_path'], eb['verb'])}
        pop = {'from': ops.provider(ea['provider'], a, ea['path'], ea['verb']),
               'to': ops.provider(eb['provider'], b, eb['path'], eb['verb'])}
        collided = ops.collided(ea, a) or ops.collided(eb, b)
        for v in er.get('Violations') or []:
            tag, vpath = split_violation(v)
            leg, component = attribute(tag, vpath, v, cop['to'], pop['to'])
            cside, pside = CONJ.get(tag, ('to', 'to'))
            state = component_state(cop[cside], pop[pside], leg, component)
            severity = SEVERITY.get(v['Severity'], str(v['Severity']))
            findings.append({
                'presence': presence, 'pair': pair, 'from': a, 'to': b, 'edge': name, 'caller': ea['caller'],
                'provider': ea['provider'], 'verb': ea['verb'], 'path': eb['path'], 'conjunct': tag, 'leg': leg,
                'component': component, 'severity': severity, 'rule': v['Rule'], 'violation_path': vpath,
                'old': v['OldType'], 'new': v['NewType'], 'state': state, 'collided': 'yes' if collided else 'no',
                'evidence': 'yes' if (severity == 'BREAK' and state == 'live' and not collided) else 'no',
                'caller_changed': 'yes' if pins()[a][ea['caller']] != pins()[b][ea['caller']] else 'no',
                'provider_changed': 'yes' if pins()[a][ea['provider']] != pins()[b][ea['provider']] else 'no'})
    return findings, tier3


def caller_drift(presence, pair, a, b, ops, names, per_bom, findings, in_graph):
    """Edges of the pair graph whose caller declaration differs between the two BOMs, per component."""
    A = {G.identity(e): e for e in per_bom[a]['edges']}
    B = {G.identity(e): e for e in per_bom[b]['edges']}
    rows = []
    for ident in sorted(set(A) & set(B), key=lambda i: G._name_order(names[i])):
        name = names[ident]
        if name not in in_graph:
            continue
        ea, eb = A[ident], B[ident]
        ca = ops.caller(ea['caller'], a, ea['caller_path'], ea['verb'])
        cb = ops.caller(eb['caller'], b, eb['caller_path'], eb['verb'])
        changed = [k for k in ('params', 'headers', 'body', 'resp') if ca['hash'][k] != cb['hash'][k]]
        if not changed and ea['opaque'] == eb['opaque']:
            continue
        pb = ops.provider(eb['provider'], b, eb['path'], eb['verb'])
        fs = [f for f in findings if f['edge'] == name and f['conjunct'] in ('C2', 'C4', 'TGT') and f['severity'] == 'BREAK']
        rows.append({
            'presence': presence, 'pair': pair, 'from': a, 'to': b, 'edge': name, 'caller': ea['caller'],
            'provider': ea['provider'], 'verb': ea['verb'], 'path': eb['path'],
            'caller_pin': '%s -> %s' % (pins()[a][ea['caller']], pins()[b][ea['caller']]),
            'changed': ','.join(changed) + ('' if ea['caller_path'] == eb['caller_path'] else ' (caller path %s -> %s)' % (ea['caller_path'], eb['caller_path'])),
            'opacity': ('opaque' if ea['opaque'] else 'typed') + ' -> ' + ('opaque' if eb['opaque'] else 'typed'),
            'states_to': 'params %s, body %s, response %s' % (leg_state(cb['req']['params'], pb['req']['params']),
                                                              leg_state(cb['req']['body'], pb['req']['body']),
                                                              leg_state(cb['resp'], pb['resp'])),
            'caller_conjunct_breaks': ','.join(sorted({'%s:%s:%s' % (f['conjunct'], f['component'], f['rule']) for f in fs})),
            'evidence_breaks': sum(1 for f in fs if f['evidence'] == 'yes')})
    return rows


def static_legs(bom, ops, per_bom):
    """Review pass 2's accounting on G1's documents at one BOM: every matched edge, both declarations at that BOM."""
    legs, comps, edges, body = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for e in per_bom[bom]['edges']:
        c = ops.caller(e['caller'], bom, e['caller_path'], e['verb'])
        p = ops.provider(e['provider'], bom, e['path'], e['verb'])
        req = leg_state(c['req']['wrapper'], p['req']['wrapper'])
        res = leg_state(c['resp'], p['resp'])
        breq = leg_state(c['req']['body'], p['req']['body'])
        legs['request:' + req] += 1
        legs['response:' + res] += 1
        body['request:' + breq] += 1
        body['response:' + res] += 1
        for k in ('params', 'headers', 'body'):
            comps['%s:%s' % (k, leg_state(c['req'][k], p['req'][k]))] += 1
        comps['response:' + res] += 1
        edges['edges'] += 1
        edges['untyped'] += (req == 'untyped' and res == 'untyped')
        edges['no live leg'] += (req != 'live' and res != 'live')
        edges['both legs live'] += (req == 'live' and res == 'live')
        edges['body reading: untyped'] += (breq == 'untyped' and res == 'untyped')
        edges['body reading: no live leg'] += (breq != 'live' and res != 'live')
    n = edges['edges']
    share = lambda c, k: round((c['request:' + k] + c['response:' + k]) / (2 * n), 4)
    return {
        'bom': bom, 'edges': n, 'edge_counts': dict(edges), 'legs': dict(sorted(legs.items())), 'components': dict(sorted(comps.items())),
        'wrapper_reading': {'untyped_edge_share': round(edges['untyped'] / n, 4), 'live_leg_share': share(legs, 'live'),
                            'vacuous_leg_share': share(legs, 'vacuous')},
        'body_reading': {'untyped_edge_share': round(edges['body reading: untyped'] / n, 4), 'live_leg_share': share(body, 'live'),
                         'vacuous_leg_share': share(body, 'vacuous'), 'legs': dict(sorted(body.items()))},
        'component_live_share': {k: round(comps['%s:live' % k] / n, 4) for k in ('params', 'headers', 'body', 'response')},
        'component_vacuous_share': {k: round(comps['%s:vacuous' % k] / n, 4) for k in ('params', 'headers', 'body', 'response')},
    }


# --------------------------------------------------------------------------- one profile

def available_boms(presence):
    return [b for b in boms() if all(os.path.exists(pin_doc(r, s, pins()[b][s], 'diag.json'))
                                     for s in SERVICES for r in (presence, N.KEEP))]


def profile(presence, provisional):
    if not os.path.isdir(os.path.join(RESULTS, presence)):
        return None
    ops = Ops(presence)
    per_bom, ids, names = G.catalog(presence, available=available_boms(presence) if provisional else None)
    with open(os.path.join(HERE, 'graph', presence, 'pairs.json')) as f:
        accounting = json.load(f)
    per_pair, all_findings, drift = {}, [], []
    for nn, a, b in pairs():
        pair = 'P' + nn
        graph_path = os.path.join(HERE, 'graph', presence, pair + '.yaml')
        if pair not in accounting or not os.path.exists(graph_path) or not os.path.isdir(os.path.join(RESULTS, presence, pair)):
            if provisional:
                continue
            raise SystemExit('%s %s: no graph or no results (run graph.py pairs and run.sh)' % (presence, pair))
        with open(graph_path) as f:
            in_graph = set(re.findall(r'^  - name: "([^"]+)"', f.read(), re.M))
        batches = read_batches(presence, pair)
        findings, tier3 = read_findings(presence, pair, a, b, batches, ops, names, per_bom)
        all_findings.extend(findings)
        drift.extend(caller_drift(presence, pair, a, b, ops, names, per_bom, findings, in_graph))
        acct = accounting[pair]
        mss_all = (batches.get('all') or {}).get('mss') or {}
        ev = [f for f in findings if f['evidence'] == 'yes']
        # legs of the pair graph's edges at θ' (both declarations at the later BOM)
        leg_counts = collections.Counter()
        for e in per_bom[b]['edges']:
            if names[G.identity(e)] not in in_graph:
                continue
            c = ops.caller(e['caller'], b, e['caller_path'], e['verb'])
            p = ops.provider(e['provider'], b, e['path'], e['verb'])
            for k in ('params', 'headers', 'body'):
                leg_counts['%s:%s' % (k, leg_state(c['req'][k], p['req'][k]))] += 1
            leg_counts['response:%s' % leg_state(c['resp'], p['resp'])] += 1
        per_pair[pair] = {
            'from': a, 'to': b, 'changed': [s for s in SERVICES if pins()[a][s] != pins()[b][s]],
            'edges_in_graph': len(in_graph), 'gate_excluded': len(acct['excluded_by_gate']),
            'added': acct['added'], 'removed': acct['removed'], 'batches': len(batches),
            'not_safe': sorted(k for k, v in batches.items() if v['rc'] == 1),
            'errors': {k: v['error'] for k, v in batches.items() if v['rc'] not in (0, 1)},
            'posthoc_fail': sorted(k for k, v in batches.items() if v['rc'] == 1 and (v.get('mss') or {}).get('posthoc') == 'FAIL'),
            'tier3_edges_in_all': tier3,
            'all_decision': {0: 'YES', 1: 'NO'}.get((batches.get('all') or {}).get('rc'), 'ERROR'),
            'all_safe_subset': mss_all.get('safe'), 'all_order': mss_all.get('order'), 'all_excluded': mss_all.get('excluded'),
            'findings': sum(1 for f in findings if f['severity'] == 'BREAK'),
            'warnings': sum(1 for f in findings if f['severity'] != 'BREAK'),
            'evidence': len(ev),
            'evidence_edges': sorted({f['edge'] for f in ev}, key=G._name_order),
            'legs_at_to': dict(sorted(leg_counts.items())),
            'live_share_at_to': {k: round(leg_counts['%s:live' % k] / max(1, len(in_graph)), 4) for k in ('params', 'headers', 'body', 'response')},
            'vacuous_share_at_to': {k: round(leg_counts['%s:vacuous' % k] / max(1, len(in_graph)), 4) for k in ('params', 'headers', 'body', 'response')},
            'evidence_by_conjunct': dict(collections.Counter(f['conjunct'] for f in ev)),
            'evidence_by_component': dict(collections.Counter(f['component'] for f in ev)),
            'evidence_by_rule': dict(collections.Counter(f['rule'] for f in ev)),
            'non_evidence_by_state': dict(collections.Counter(f['state'] for f in findings if f['severity'] == 'BREAK' and f['evidence'] == 'no')),
            'd6_residue_edges': acct['d6_opacity_changes'] + acct['d6_provider_body_changes'],
            'batch_verdicts': {k: {0: 'YES', 1: 'NO'}.get(v['rc'], 'ERROR') for k, v in batches.items()},
            'batch_safe': {k: (v.get('mss') or {}).get('safe') for k, v in batches.items() if v['rc'] == 1},
        }
    breaks = [f for f in all_findings if f['severity'] == 'BREAK']
    ev = [f for f in breaks if f['evidence'] == 'yes']
    totals = {
        'pairs': len(per_pair), 'findings': len(breaks), 'warnings': len(all_findings) - len(breaks), 'evidence': len(ev),
        'by_conjunct': {'all': dict(collections.Counter(f['conjunct'] for f in breaks)), 'evidence': dict(collections.Counter(f['conjunct'] for f in ev))},
        'by_component': {'all': dict(collections.Counter(f['component'] for f in breaks)), 'evidence': dict(collections.Counter(f['component'] for f in ev))},
        'by_rule': {'all': dict(collections.Counter(f['rule'] for f in breaks)), 'evidence': dict(collections.Counter(f['rule'] for f in ev))},
        'by_state': dict(collections.Counter(f['state'] for f in breaks)),
        'collided_findings': sum(1 for f in breaks if f['collided'] == 'yes'),
        'scenarios': sum(p['batches'] for p in per_pair.values()),
        'not_safe': sum(len(p['not_safe']) for p in per_pair.values()),
        'errors': sum(len(p['errors']) for p in per_pair.values()),
        'posthoc_fail': [(pair, x) for pair, p in sorted(per_pair.items()) for x in p['posthoc_fail']],
        'tier3_edges': sum(len(p['tier3_edges_in_all']) for p in per_pair.values()),
    }
    legs = {bom: static_legs(bom, ops, per_bom) for bom in ('1.30.0', '1.38.0') if bom in per_bom}
    return {'presence': presence, 'pairs': per_pair, 'totals': totals, 'static_legs': legs,
            'findings': all_findings, 'drift': drift, 'catalog': (per_bom, ids, names)}


# --------------------------------------------------------------------------- labels against the checker

def label_table(results):
    rows = []
    for r in s4_rows():
        if r['claim'] == 'CLAIM-S4-019':
            continue
        mapped, how = label_to_pairs(r['pair'], r['services'])
        for pair in mapped:
            entry = {'claim': r['claim'], 'label_pair': r['pair'], 'kind': r['kind'], 'services': r['services'],
                     'pair': pair, 'mapping': how, 'quote': r['quote'], 'url': r['url']}
            named = [s for s in SERVICES if re.search(r'\b%s\b' % s, r['services'])]
            present = False
            for presence, res in results.items():
                if pair not in res['pairs']:
                    continue
                present = True
                p = res['pairs'][pair]
                fs = [f for f in res['findings'] if f['pair'] == pair and f['severity'] == 'BREAK'
                      and (f['caller'] in named or f['provider'] in named)]
                entry[presence] = {
                    'all': p['all_decision'], 'safe_subset_all': p['all_safe_subset'], 'batches_not_safe': len(p['not_safe']),
                    'named_service_batches': {s: p['batch_verdicts'].get(s) for s in named},
                    'findings_on_named_edges': len(fs), 'evidence_on_named_edges': sum(1 for f in fs if f['evidence'] == 'yes'),
                    'states': dict(collections.Counter(f['state'] for f in fs)),
                }
            if not present:
                continue
            if r['claim'] in LABEL_EDGES:
                entry['trace'] = trace_label(r['claim'], pair, results)
            rows.append(entry)
    return rows


def trace_label(claim, pair, results):
    out = []
    a, b = [(x, y) for n, x, y in pairs() if 'P' + n == pair][0]
    for presence, res in results.items():
        if pair not in res['pairs']:
            continue
        ops = Ops(presence)
        per_bom, ids, names = res['catalog']
        with open(os.path.join(HERE, 'graph', presence, 'pairs.json')) as f:
            acct = json.load(f)[pair]
        for ident in LABEL_EDGES[claim]:
            at = ids.get(ident, {})
            name = names.get(ident)
            row = {'presence': presence, 'edge': name, 'identity': '%s -> %s %s %s' % ident,
                   'exists_at_from': a in at, 'exists_at_to': b in at}
            if a in at and b in at:
                for side, bom in (('from', a), ('to', b)):
                    e = at[bom]
                    c = ops.caller(e['caller'], bom, e['caller_path'], e['verb'])
                    p = ops.provider(e['provider'], bom, e['path'], e['verb'])
                    row['legs_' + side] = {'params': leg_state(c['req']['params'], p['req']['params']),
                                           'body': leg_state(c['req']['body'], p['req']['body']),
                                           'response': leg_state(c['resp'], p['resp'])}
                    row['caller_hash_' + side], row['provider_hash_' + side] = c['hash'], p['hash']
                    row['caller_path_' + side] = e['caller_path']
                row['caller_declaration_changed'] = [k for k in ('params', 'headers', 'body', 'resp')
                                                     if row['caller_hash_from'][k] != row['caller_hash_to'][k]]
                row['provider_declaration_changed'] = [k for k in ('params', 'headers', 'body', 'resp')
                                                       if row['provider_hash_from'][k] != row['provider_hash_to'][k]]
                row['gate_excluded_at_from'] = acct['excluded_by_gate'].get(name)
                row['findings_all_batch'] = [{k: f[k] for k in ('conjunct', 'leg', 'component', 'severity', 'rule', 'violation_path', 'state', 'evidence')}
                                             for f in res['findings'] if f['pair'] == pair and f['edge'] == name]
                caller, provider = ident[0], ident[1]
                v = res['pairs'][pair]['batch_verdicts']
                row['verdicts'] = {k: v.get(k) for k in ('all', caller, provider, '+'.join(sorted([caller, provider])))}
            out.append(row)
    return out


# --------------------------------------------------------------------------- main

FINDING_COLUMNS = ['presence', 'pair', 'from', 'to', 'edge', 'caller', 'provider', 'verb', 'path', 'conjunct', 'leg', 'component',
                   'severity', 'rule', 'violation_path', 'old', 'new', 'state', 'collided', 'evidence', 'caller_changed', 'provider_changed']
DRIFT_COLUMNS = ['presence', 'pair', 'from', 'to', 'edge', 'caller', 'provider', 'verb', 'path', 'caller_pin', 'changed', 'opacity',
                 'states_to', 'caller_conjunct_breaks', 'evidence_breaks']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--provisional', action='store_true')
    a = ap.parse_args(argv)
    results = {}
    for presence in PROFILES:
        r = profile(presence, a.provisional)
        if r:
            results[presence] = r
    if not results:
        raise SystemExit('no results under %s: run run.sh first' % RESULTS)
    labels = label_table(results)
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, 'findings.tsv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FINDING_COLUMNS, delimiter='\t', lineterminator='\n')
        w.writeheader()
        for presence in results:
            w.writerows(results[presence]['findings'])
    with open(os.path.join(RESULTS, 'caller-drift.tsv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=DRIFT_COLUMNS, delimiter='\t', lineterminator='\n')
        w.writeheader()
        for presence in results:
            w.writerows(results[presence]['drift'])
    summary = {p: {k: v for k, v in r.items() if k not in ('findings', 'drift', 'catalog')} for p, r in results.items()}
    summary['labels'] = labels
    if all(p in results for p in PROFILES):
        key = lambda f: (f['pair'], f['edge'], f['conjunct'], f['violation_path'], f['rule'])
        sets = {p: {key(f): f for f in results[p]['findings'] if f['severity'] == 'BREAK'} for p in PROFILES}
        only = {p: sorted(set(sets[p]) - set(sets[q])) for p, q in (('declared', 'none'), ('none', 'declared'))}
        verdicts = []
        for pair in sorted(set(results['none']['pairs']) & set(results['declared']['pairs'])):
            vn, vd = results['none']['pairs'][pair], results['declared']['pairs'][pair]
            for batch in sorted(vn['batch_verdicts']):
                if vn['batch_verdicts'][batch] != vd['batch_verdicts'].get(batch) or \
                        vn['batch_safe'].get(batch) != vd['batch_safe'].get(batch):
                    verdicts.append({'pair': pair, 'batch': batch,
                                     'none': [vn['batch_verdicts'][batch], vn['batch_safe'].get(batch)],
                                     'declared': [vd['batch_verdicts'].get(batch), vd['batch_safe'].get(batch)]})
        summary['profiles'] = {
            'breaks_only_in': {p: [dict(zip(('pair', 'edge', 'conjunct', 'violation_path', 'rule'), k),
                                        state=sets[p][k]['state'], evidence=sets[p][k]['evidence']) for k in only[p]]
                               for p in only},
            'breaks_in_both': len(set(sets['none']) & set(sets['declared'])),
            'batches_with_different_verdict_or_subset': verdicts,
        }
    summary['provisional'] = a.provisional
    with open(os.path.join(RESULTS, 'compare.json'), 'w') as f:
        json.dump(summary, f, indent=1, sort_keys=True, default=str)
        f.write('\n')
    import report
    report.write(summary, results)
    for p in results:
        t = summary[p]['totals']
        print('%s: %d pairs, %d scenarios, %d not safe, %d errors, %d post-hoc FAIL; breaks %d (live %d); by conjunct %s; live by conjunct %s' % (
            p, t['pairs'], t['scenarios'], t['not_safe'], t['errors'], len(t['posthoc_fail']), t['findings'], t['evidence'],
            t['by_conjunct']['all'], t['by_conjunct']['evidence']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
