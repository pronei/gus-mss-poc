#!/usr/bin/env python3
"""Pass 2 (2026-09-12): untypedness per leg under the owner's D5 ruling.

A leg (request: caller Send vs provider Accept; response: provider Return vs
caller Expect) is untyped only when BOTH sides are untyped; an edge only when
both legs are.  A leg with exactly one untyped side is vacuous (it can only
pass); a leg typed on both sides is live; 'none' on both sides is contentless.
Reuses r1ab_reconcile.py's matching and classifier (typed maps typed = D5 as in
force; strict = as originally written) by executing it in place.
"""
import collections, json, os
here = os.path.dirname(os.path.abspath(__file__))
ns = {'__file__': os.path.join(here, 'r1ab_reconcile.py'), '__name__': 'r1ab'}
exec(open(ns['__file__']).read(), ns)
matched, edge_typing = ns['matched'], ns['edge_typing']

def leg_state(a, b):
    if a == 'untyped' and b == 'untyped': return 'untyped'
    if a == 'none' and b == 'none': return 'contentless'
    if 'untyped' in (a, b): return 'vacuous'
    if 'none' in (a, b): return 'contentless-one-side'
    return 'live'

out = {}
for label, strict in (('as_written', True), ('in_force_typed_maps_typed', False)):
    legs = collections.Counter(); edges = collections.Counter(); per_prov = collections.defaultdict(collections.Counter)
    for j, e, n, ep, nc in matched:
        sides, _, _ = edge_typing(e, ep, strict)
        req = leg_state(sides['caller_body'], sides['provider_body'])
        resp = leg_state(sides['caller_return'], sides['provider_return'])
        legs['request:' + req] += 1; legs['response:' + resp] += 1
        edge_untyped = (req == 'untyped' and resp == 'untyped')
        edges['untyped_both_legs_both_sides'] += edge_untyped
        edges['no_live_leg'] += (req != 'live' and resp != 'live')
        edges['at_least_one_live_leg'] += (req == 'live' or resp == 'live')
        edges['both_legs_live'] += (req == 'live' and resp == 'live')
        per_prov[e['provider']]['edges'] += 1
        per_prov[e['provider']]['untyped'] += edge_untyped
        per_prov[e['provider']]['live_legs'] += (req == 'live') + (resp == 'live')
    n = len(matched)
    out[label] = {
        'edges': n,
        'edge_untyped_share_owner_ruling': round(edges['untyped_both_legs_both_sides'] / n, 4),
        'edges_untyped': edges['untyped_both_legs_both_sides'],
        'edges_with_no_live_leg': edges['no_live_leg'],
        'edges_with_at_least_one_live_leg': edges['at_least_one_live_leg'],
        'edges_with_both_legs_live': edges['both_legs_live'],
        'legs': dict(legs),
        'live_leg_share_of_all_legs': round((legs['request:live'] + legs['response:live']) / (2 * n), 4),
        'vacuous_leg_share_of_all_legs': round((legs['request:vacuous'] + legs['response:vacuous']) / (2 * n), 4),
        'per_provider': {p: {'edges': c['edges'], 'untyped_edges': c['untyped'], 'live_leg_share': round(c['live_legs'] / (2 * c['edges']), 3)} for p, c in sorted(per_prov.items())},
    }
json.dump(out, open(os.path.join(here, 'r1b_legs.json'), 'w'), indent=1)
for label, r in out.items():
    print(label, '| edges', r['edges'], '| untyped (owner ruling)', r['edges_untyped'], r['edge_untyped_share_owner_ruling'],
          '| no live leg', r['edges_with_no_live_leg'], '| live legs', r['live_leg_share_of_all_legs'], '| vacuous legs', r['vacuous_leg_share_of_all_legs'])
    print('   legs:', r['legs'])
