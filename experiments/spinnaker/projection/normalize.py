#!/usr/bin/env python3
"""D3 on the extractor's documents: pair every caller declaration with the provider operation it calls.

A library for graph.py, gate.py and compare.py, and a report when run:

    python3 normalize.py --bom 1.38.0 [--presence none]     # one BOM: matched share, categories, ties, collisions
    python3 normalize.py --all                              # every BOM; writes unmatched.tsv and match-summary.json

The rules are R1(a) of review pass 1 (`scout/review/r1ab_reconcile.py`),
applied to G1's documents instead of the scout tables:

* both sides are compared on `x-match-key`, which the extractor normalised as
  `norm_path` does: query string stripped, `.` read as `/`, leading slash,
  variable names and regexes erased to `{}`, `//` collapsed, trailing `/`
  stripped (`Paths.matchKey`);
* a provider template matches a caller path segment by segment
  (`template_regex`, verbatim): a provider `{}` is filled by a caller literal or
  a caller `{}`, a provider `**` matches any suffix, any other segment matches
  only literally;
* verbs are compared exactly, because the extractor already wrote an `ANY`
  mapping once per verb (`x-method-any`) — R1(a)'s "ANY matches every method";
* several matching templates: the most specific wins (most literal segments,
  fewest `**`, an explicit verb before an `ANY` copy), as in R1(a); a remaining
  tie is counted and the first by path is taken;
* a caller variable over a provider literal slot (R1(a)'s dispatch class) is
  expanded by the hand table `DISPATCH` into one edge per concrete provider
  controller, and only when ordinary matching found nothing.

A caller operation that yields no edge gets exactly one category, in this
order: out-of-mesh (the provider is not one of the nine; Keel, D2), self-edge
(caller = provider, D3 as revised 2026-09-12), actuator (`/health`,
`/installedPlugins`), framework (a route the provider's extraction excluded
by provenance, CLAIM-G1-007), dispatch-slot (a table row with no controller at
that BOM, or a caller variable over a provider literal the table does not yet
list — the second is a normalization defect and is triaged as one), stale (the
residue: the caller declares an endpoint the provider does not expose). The
owner's two dropped client families never reach the profile documents; they
are listed from the client-only listing run as kork and indirect-fiat.
"""
import argparse
import collections
import csv
import functools
import hashlib
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE, KEEP, PROFILES, SERVICES, WORK, bom_doc, boms, pin_doc, pins, sha256_file

VERBS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch')
ACTUATOR = {'/health', '/installedPlugins'}
KORK_IFACE = 'com.netflix.spinnaker.kork.plugins.update.internal.Front50Service'
FIAT_IFACE = 'com.netflix.spinnaker.fiat.shared.FiatService'
INDIRECT_FIAT_CALLERS = {'clouddriver', 'echo', 'igor', 'keel'}          # CLAIM-S1-009; owner's ruling (ii)
LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)

# The provider-dispatch table (R1(a), class "provider dispatch slot"), keyed on
# (caller, provider, VERB, caller match path). The seven rows of 1.38.0 are
# scout/review/r1a_unmatched.tsv's; any row added for another BOM names it.
DISPATCH = {
    ('gate', 'clouddriver', 'GET', '/applications/{}/clusters/{}/{}/{}/serverGroups/{}/scalingActivities'):
        'r1a_unmatched.tsv (ClouddriverService.getScalingActivities)',
    ('gate', 'clouddriver', 'GET', '/{}/images/{}/{}/{}'): 'r1a_unmatched.tsv (ClouddriverService.getImageDetails)',
    ('gate', 'clouddriver', 'GET', '/{}/images/find'): 'r1a_unmatched.tsv (ClouddriverService.findImages)',
    ('gate', 'clouddriver', 'GET', '/{}/images/tags'): 'r1a_unmatched.tsv (ClouddriverService.findTags)',
    ('orca', 'clouddriver', 'GET', '/{}/images/{}/{}/{}'): 'r1a_unmatched.tsv (OortService.getByAmiId)',
    ('orca', 'clouddriver', 'GET', '/{}/images/find'): 'r1a_unmatched.tsv (OortService.findImage)',
    ('orca', 'igor', 'GET', '/{}/{}/{}/compareCommits'): 'r1a_unmatched.tsv (IgorService.compareCommits)',
}


# --------------------------------------------------------------------------- paths

def strip_regexes(s):
    """{name:regex} -> {name}, brace-balanced, as Paths.stripRegexes."""
    out, i = [], 0
    while i < len(s):
        if s[i] != '{':
            out.append(s[i])
            i += 1
            continue
        depth, j = 0, i
        while j < len(s):
            if s[j] == '{':
                depth += 1
            elif s[j] == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= len(s):
            out.append(s[i:])
            break
        inner = s[i + 1:j]
        out.append('{' + inner.split(':', 1)[0] + '}')
        i = j + 1
    return ''.join(out)


def match_path(raw):
    """Paths.matchKey: the D3-normalised, fully erased form of a path."""
    s = raw.strip().split('?', 1)[0]
    if s in ('', '.', './'):
        s = '/'
    if not s.startswith('/'):
        s = '/' + s
    s = re.sub(r'/{2,}', '/', strip_regexes(s))
    if len(s) > 1 and s.endswith('/'):
        s = s[:-1]
    return re.sub(r'\{[^}]*\}', '{}', s)


@functools.lru_cache(maxsize=None)
def template_regex(p):
    """r1ab_reconcile.template_regex, verbatim."""
    parts = []
    for seg in p.split('/'):
        if seg == '{}':
            parts.append(r'[^/]+')
        elif seg == '**':
            parts.append(r'.*')
        else:
            parts.append(re.escape(seg))
    return re.compile('^' + '/'.join(parts) + '$')


def literal_segments(p):
    return sum(1 for s in p.split('/') if s and s not in ('{}', '**'))


def calls_key(provider, path):
    """The key the checker looks a caller declaration up under: Go's
    filepath.Join("/_calls", provider, path), which cleans the result
    (main.go:1121). `/_calls/echo/` is never found; `/_calls/echo` is."""
    parts = ['_calls', provider] + [seg for seg in path.split('/') if seg not in ('', '.')]
    return '/' + '/'.join(parts)


# --------------------------------------------------------------------------- document index

def _hash(obj):
    if obj is None:
        return None
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _state(schema):
    if schema is None:
        return 'none'
    return 'untyped' if schema.get('x-untyped') else 'typed'


def _op_summary(path, verb, op):
    key = op.get('x-match-key', '')
    wrapper = (((op.get('requestBody') or {}).get('content') or {}).get('application/json') or {}).get('schema')
    props = (wrapper or {}).get('properties') or {}
    ok = (op.get('responses') or {}).get('200') or {}
    resp = ((ok.get('content') or {}).get('application/json') or {}).get('schema')
    return {
        'path': path, 'verb': verb.upper(), 'key': key, 'mpath': key.split(' ', 1)[1] if ' ' in key else '',
        'any': bool(op.get('x-method-any')), 'validated': bool(op.get('x-validated')),
        'req': {'wrapper': ('none' if wrapper is None or not props else _state(wrapper)),
                'params': _state(props.get('params')), 'headers': _state(props.get('headers')),
                'body': _state(props.get('body'))},
        'resp': _state(resp),
        'hash': {'params': _hash(props.get('params')), 'headers': _hash(props.get('headers')),
                 'body': _hash(props.get('body')), 'resp': _hash(resp)},
        'resp_top_fields': sorted((resp or {}).get('properties') or {}) if isinstance(resp, dict) else [],
    }


def _framework_routes(diag):
    out = []
    for entry in (diag.get('losses') or {}).get('framework-route-excluded') or []:
        head = entry.split('  (', 1)[0]
        if ' ' in head:
            verb, path = head.split(' ', 1)
            out.append((verb.upper(), match_path(path)))
    return sorted(set(out))


def build_index(yaml_path, diag_path):
    with open(yaml_path) as f:
        doc = yaml.load(f, Loader=LOADER)
    with open(diag_path) as f:
        diag = json.load(f)
    provider, client = [], []
    for path, item in sorted((doc.get('paths') or {}).items()):
        for verb in VERBS:
            op = (item or {}).get(verb)
            if op is None:
                continue
            s = _op_summary(path, verb, op)
            if op.get('x-role') == 'client':
                s.update(provider=op.get('x-provider', ''), iface=op.get('x-interface', ''),
                         opaque=bool(op.get('x-response-opaque')))
                client.append(s)
            else:
                provider.append(s)
    return {'provider': provider, 'client': client, 'framework_routes': _framework_routes(diag),
            'diag_counts': diag.get('counts') or {},
            'diag_losses': {k: len(v) for k, v in (diag.get('losses') or {}).items()},
            'duplicate_endpoints': sorted((diag.get('losses') or {}).get('duplicate-endpoint') or []),
            'recursive_losses': sorted((diag.get('losses') or {}).get('recursive-type-side-neutral') or []),
            'components': sorted(((doc.get('components') or {}).get('schemas') or {}).keys())}


_memo = {}


def doc_index(run, svc, ver):
    """The index of one pin's document, cached in memory and under .work/index keyed by the document's sha256."""
    k = (run, svc, ver)
    if k in _memo:
        return _memo[k]
    y, d = pin_doc(run, svc, ver), pin_doc(run, svc, ver, 'diag.json')
    digest = sha256_file(y)[:20]
    cache = os.path.join(WORK, 'index', run, svc, '%s-%s.json' % (ver, digest))
    if os.path.exists(cache):
        with open(cache) as f:
            idx = json.load(f)
    else:
        idx = build_index(y, d)
        idx['sha256'] = digest
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache + '.tmp', 'w') as f:
            json.dump(idx, f)
        os.replace(cache + '.tmp', cache)
    _memo[k] = idx
    return idx


# --------------------------------------------------------------------------- matching

def _provider_table(idx):
    return [dict(op, lit=literal_segments(op['mpath']), ss=op['mpath'].count('**')) for op in idx['provider']]


def match_bom(bom, run='none'):
    """Edges and unmatched caller operations at one BOM for one profile."""
    idx = {s: doc_index(run, s, pins()[bom][s]) for s in SERVICES}
    table = {s: _provider_table(idx[s]) for s in SERVICES}
    edges, unmatched, ties = [], [], []
    stats = collections.Counter()

    def add_edge(caller, c, p, how, ncand):
        edges.append({
            'caller': caller, 'provider': c['provider'], 'verb': c['verb'], 'path': p['path'],
            'provider_mpath': p['mpath'], 'caller_path': c['path'], 'caller_mpath': c['mpath'],
            'caller_iface': c['iface'], 'how': how, 'candidates': ncand, 'provider_any': p['any'],
            'opaque': c['opaque'], 'provider_resp': p['resp'],
        })

    for caller in SERVICES:
        for c in idx[caller]['client']:
            prov = c['provider']
            base = {'bom': bom, 'caller': caller, 'provider': prov, 'verb': c['verb'], 'caller_path': c['path'],
                    'mpath': c['mpath'], 'interface': c['iface'], 'note': ''}
            stats['caller operations'] += 1
            if prov not in SERVICES:
                unmatched.append(dict(base, category='out-of-mesh'))
                continue
            stats['resolved'] += 1
            if prov == caller:
                unmatched.append(dict(base, category='self-edge'))
                continue
            if c['mpath'] in ACTUATOR:
                unmatched.append(dict(base, category='actuator'))
                continue
            cands = [p for p in table[prov] if p['verb'] == c['verb'] and template_regex(p['mpath']).match(c['mpath'])]
            if cands:
                cands.sort(key=lambda p: (-p['lit'], p['ss'], p['any'], p['path']))
                if len(cands) > 1 and (cands[0]['lit'], cands[0]['ss'], cands[0]['any']) == \
                        (cands[1]['lit'], cands[1]['ss'], cands[1]['any']):
                    ties.append({'bom': bom, 'caller': caller, 'provider': prov, 'verb': c['verb'],
                                 'caller_path': c['path'], 'taken': cands[0]['path'],
                                 'tied_with': [p['path'] for p in cands[1:]
                                               if (p['lit'], p['ss'], p['any']) == (cands[0]['lit'], cands[0]['ss'], cands[0]['any'])]})
                add_edge(caller, c, cands[0], 'template' if c['mpath'] != cands[0]['mpath'] else 'exact', len(cands))
                stats['matched'] += 1
                continue
            crx = template_regex(c['mpath'])
            slot = sorted((p for p in table[prov] if p['verb'] == c['verb'] and crx.match(p['mpath'])),
                          key=lambda p: p['path'])
            row = DISPATCH.get((caller, prov, c['verb'], c['mpath']))
            if row is not None:
                if slot:
                    for p in slot:
                        add_edge(caller, c, p, 'dispatch', len(slot))
                    stats['matched'] += 1
                    stats['matched by dispatch'] += 1
                else:
                    unmatched.append(dict(base, category='dispatch-slot', note='table row; no controller for the slot at this BOM'))
                continue
            fw = [r for r in idx[prov]['framework_routes'] if r[0] == c['verb'] and template_regex(r[1]).match(c['mpath'])]
            if fw:
                unmatched.append(dict(base, category='framework', note='excluded by provenance: %s %s' % tuple(fw[0])))
                continue
            if slot:
                unmatched.append(dict(base, category='dispatch-slot',
                                      note='NOT IN TABLE: caller variable over %d provider literal(s): %s' % (
                                          len(slot), ', '.join(p['path'] for p in slot[:4]))))
                continue
            unmatched.append(dict(base, category='stale'))

    # The owner's dropped families, from the listing run.
    for caller in SERVICES:
        keep = doc_index(KEEP, caller, pins()[bom][caller])
        for c in keep['client']:
            cat = None
            if c['iface'] == KORK_IFACE:
                cat = 'kork'
            elif c['iface'] == FIAT_IFACE and caller in INDIRECT_FIAT_CALLERS:
                cat = 'indirect-fiat'
            if cat:
                unmatched.append({'bom': bom, 'caller': caller, 'provider': c['provider'], 'verb': c['verb'],
                                  'caller_path': c['path'], 'mpath': c['mpath'], 'interface': c['iface'],
                                  'category': cat, 'note': 'dropped family (owner ruling 2026-09-12)'})

    # Several caller declarations answering to one edge: one wins, the rest are recorded.
    by_key = collections.defaultdict(list)
    for e in edges:
        by_key[(e['caller'], e['provider'], e['verb'], e['path'])].append(e)
    kept, collisions = [], []
    for k in sorted(by_key):
        group = sorted(by_key[k], key=lambda e: (e['how'] == 'dispatch', e['caller_path']))
        winner = dict(group[0])
        winner['collision'] = [e['caller_path'] for e in group[1:]]
        if winner['collision']:
            collisions.append({'bom': bom, 'caller': k[0], 'provider': k[1], 'verb': k[2], 'path': k[3],
                               'kept': group[0]['caller_path'], 'dropped': winner['collision']})
        kept.append(winner)

    cat = collections.Counter(u['category'] for u in unmatched)
    resolved_ex_actuator = stats['resolved'] - cat['actuator']
    summary = {
        'bom': bom, 'run': run, 'caller_operations': stats['caller operations'], 'resolved': stats['resolved'],
        'matched_operations': stats['matched'], 'matched_by_dispatch': stats['matched by dispatch'],
        'edges': len(kept), 'dispatch_edges': sum(1 for e in kept if e['how'] == 'dispatch'),
        'matched_share_of_resolved': round(stats['matched'] / stats['resolved'], 4) if stats['resolved'] else None,
        'matched_share_excluding_actuator': round(stats['matched'] / resolved_ex_actuator, 4) if resolved_ex_actuator else None,
        'unmatched_by_category': dict(sorted(cat.items())), 'ties': len(ties), 'collisions': len(collisions),
    }
    return {'edges': kept, 'unmatched': unmatched, 'ties': ties, 'collisions': collisions, 'summary': summary}


# --------------------------------------------------------------------------- CLI

UNMATCHED_COLUMNS = ['bom', 'caller', 'provider', 'verb', 'caller_path', 'mpath', 'category', 'interface', 'note']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--bom')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--presence', choices=PROFILES, default='none')
    a = ap.parse_args(argv)
    if a.bom:
        r = match_bom(a.bom, a.presence)
        print(json.dumps(r['summary'], indent=1))
        for u in sorted(r['unmatched'], key=lambda u: (u['category'], u['caller'], u['provider'], u['caller_path'])):
            if u['category'] not in ('kork', 'indirect-fiat', 'out-of-mesh'):
                print('  %-13s %-11s -> %-11s %-6s %s  %s' % (u['category'], u['caller'], u['provider'], u['verb'], u['caller_path'], u['note']))
        for t in r['ties']:
            print('  tie        ', t)
        for c in r['collisions']:
            print('  collision  ', c)
        return 0
    if a.all:
        rows, summaries = [], []
        for bom in boms():
            r = match_bom(bom, a.presence)
            other = match_bom(bom, [p for p in PROFILES if p != a.presence][0])
            same = [(e['caller'], e['provider'], e['verb'], e['path']) for e in r['edges']] == \
                   [(e['caller'], e['provider'], e['verb'], e['path']) for e in other['edges']]
            r['summary']['edges_equal_across_profiles'] = same
            rows.extend(r['unmatched'])
            summaries.append(dict(r['summary'], ties=r['ties'], collisions=r['collisions']))
            print('%-8s edges %4d  matched %.1f%% (%.1f%% excl. actuator)  %s' % (
                bom, r['summary']['edges'], 100 * r['summary']['matched_share_of_resolved'],
                100 * r['summary']['matched_share_excluding_actuator'], r['summary']['unmatched_by_category']))
        with open(os.path.join(HERE, 'unmatched.tsv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=UNMATCHED_COLUMNS, delimiter='\t', extrasaction='ignore', lineterminator='\n')
            w.writeheader()
            for u in sorted(rows, key=lambda u: (tuple(map(int, u['bom'].split('.'))), u['category'], u['caller'],
                                                 u['provider'], u['verb'], u['caller_path'])):
                w.writerow(u)
        with open(os.path.join(HERE, 'match-summary.json'), 'w') as f:
            json.dump(summaries, f, indent=1)
            f.write('\n')
        return 0
    ap.error('give --bom or --all')


if __name__ == '__main__':
    sys.exit(main())
