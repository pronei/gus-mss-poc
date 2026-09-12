#!/usr/bin/env python3
"""R1 figures restricted to the nine BOM-pinned services (Keel dropped under the revised D2):
matched share and untyped share (as written / refined) over the reconciled non-Keel edges, with the
actuator rows shown separately.  Also the same figures with the hand-read Igor rows (estimate)."""
import csv, json, os
here = os.path.dirname(os.path.abspath(__file__))
m = [r for r in csv.DictReader(open(os.path.join(here, 'r1a_matched.tsv')), delimiter='\t')]
u = [r for r in csv.DictReader(open(os.path.join(here, 'r1a_unmatched.tsv')), delimiter='\t')]
e = [r for r in csv.DictReader(open(os.path.join(here, '..', 'S1', 'edges.tsv')), delimiter='\t')]
nk = lambda r: r['caller'] != 'keel' and r['provider'] != 'keel'
m9, u9 = [r for r in m if nk(r)], [r for r in u if nk(r)]
res9 = sum(1 for r in e if nk(r) and r['provider'] != 'unresolved')
act9 = sum(1 for r in u9 if r['category'] == 'actuator')
us = sum(int(r['untyped_as_written']) for r in m9); ur = sum(int(r['untyped_refined']) for r in m9); bs = sum(int(r['both_sides_untyped_as_written']) for r in m9)
out = {'nine_service_mesh': {'edges': sum(1 for r in e if nk(r)), 'resolved': res9, 'matched': len(m9), 'unmatched': len(u9), 'unmatched_actuator': act9,
       'matched_share': round(len(m9) / res9, 4), 'matched_share_excluding_actuator': round(len(m9) / (res9 - act9), 4),
       'untyped_share_as_written': round(us / len(m9), 4), 'untyped_share_refined': round(ur / len(m9), 4), 'both_sides_untyped': bs, 'both_sides_share': round(bs / len(m9), 4)}}
try:
    s = json.load(open(os.path.join(here, 'r1b_sensitivity_igor_gap.json')))
    newly = [x for x in s['newly_matched'] if x['caller'] != 'keel']
    m1 = len(m9) + len(newly); us1 = us + sum(x['untyped_as_written'] for x in newly); ur1 = ur + sum(x['untyped_refined'] for x in newly)
    out['nine_service_mesh_with_igor_gap_estimate'] = {'matched': m1, 'matched_share': round(m1 / res9, 4), 'matched_share_excluding_actuator': round(m1 / (res9 - act9), 4),
        'untyped_share_as_written': round(us1 / m1, 4), 'untyped_share_refined': round(ur1 / m1, 4)}
except FileNotFoundError: pass
out['keel_rows_dropped'] = {'as_caller': sum(1 for r in e if r['caller'] == 'keel'), 'as_provider': sum(1 for r in e if r['provider'] == 'keel')}
json.dump(out, open(os.path.join(here, 'r1_nine_service_mesh.json'), 'w'), indent=1); print(json.dumps(out, indent=1))
