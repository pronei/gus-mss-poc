#!/usr/bin/env python3
"""R1(f): no gaps.md row with checker_change=yes and an empty projection_convention unless it has a cost."""
import json, os, re
here = os.path.dirname(os.path.abspath(__file__))
lines = [l for l in open(os.path.join(here, '..', 'S5', 'gaps.md')) if l.startswith('|')]
hdr = [c.strip() for c in lines[0].strip().strip('|').split('|')]
rows = [dict(zip(hdr, [c.strip() for c in l.strip().strip('|').split('|')])) for l in lines[2:]]
rows = [r for r in rows if len(r) == len(hdr) and r.get('construct') and not set(r['construct']) <= set('-')]
def is_yes(s): return bool(re.match(r'\s*yes\b', s, re.I)) or bool(re.search(r'\byes\b', s, re.I))
def has_cost(s): return bool(re.search(r'\d+\s*(–|-)?\s*\d*\s*h', s))
viol, yes_rows = [], []
for r in rows:
    if is_yes(r['checker_change']):
        yes_rows.append({'construct': r['construct'], 'projection_empty': r['projection_convention'] in ('', '-', '—'), 'cost': r['cost'], 'has_cost': has_cost(r['cost']), 'claim': r['claim']})
        if r['projection_convention'] in ('', '-', '—') and not has_cost(r['cost']): viol.append(r['construct'])
res = {'rows': len(rows), 'checker_change_rows': yes_rows, 'violations': viol,
       'rows_missing_cost_any': [r['construct'] for r in rows if not has_cost(r['cost']) and not re.search(r'0h', r['cost'])],
       'rows_missing_claim': [r['construct'] for r in rows if 'CLAIM-S5-' not in r['claim']]}
json.dump(res, open(os.path.join(here, 'r1f_gaps.json'), 'w'), indent=1)
print(json.dumps(res, indent=1))
