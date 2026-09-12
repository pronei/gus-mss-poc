#!/usr/bin/env python3
"""R1(d): every ground-truth row must have a URL and a quoted sentence; drop the rest;
report survivors per kind; flag rows whose source is a closed/unmerged PR (CLAIM-S4-019)."""
import re, json, os, collections
here = os.path.dirname(os.path.abspath(__file__))
lines = [l for l in open(os.path.join(here, '..', 'S4', 'ground-truth-candidates.md')) if l.startswith('|')]
hdr = [c.strip() for c in lines[0].strip().strip('|').split('|')]
rows = []
for l in lines[2:]:
    cells = [c.strip() for c in l.strip().strip('|').split('|')]
    if len(cells) == len(hdr): rows.append(dict(zip(hdr, cells)))
    else: print('UNPARSED', l[:100])
kinds = {'breaking', 'compat-note', 'upgrade-order', 'deprecation-removed'}
keep, drop = [], []
for r in rows:
    has_url = bool(re.match(r'https?://\S+$', r['source_url']))
    q = r['quoted_sentence']
    has_quote = len(q) >= 2 and q[0] == '"' and q[-1] == '"' and len(q.strip('"').strip()) > 0
    kind_ok = r['kind'] in kinds
    (keep if has_url and has_quote and kind_ok else drop).append((r, has_url, has_quote, kind_ok))
flag = [r for r, *_ in keep if 'spinnaker.io/pull/504' in r['source_url']]
res = {'rows': len(rows), 'kept': len(keep), 'dropped': [(r['claim'], u, q, k) for r, u, q, k in drop],
       'survivors_per_kind': dict(collections.Counter(r['kind'] for r, *_ in keep)),
       'flagged_closed_unmerged_pr': [r['claim'] for r in flag],
       'survivors_per_kind_excluding_flagged': dict(collections.Counter(r['kind'] for r, *_ in keep if r not in flag)),
       'sources': dict(collections.Counter(re.sub(r'^(https?://[^/]+/).*', r'\1', r['source_url']) for r, *_ in keep)),
       'breaking_rows': [(r['claim'], r['pair'], r['source_url']) for r, *_ in keep if r['kind'] == 'breaking'],
       'pairs_in_1.30.0..1.38.0': [(r['claim'], r['pair'], r['kind']) for r, *_ in keep if re.match(r'1\.3[0-8]', r['pair'].split('->')[-1].strip())]}
json.dump(res, open(os.path.join(here, 'r1d_groundtruth.json'), 'w'), indent=1)
print(json.dumps(res, indent=1))
