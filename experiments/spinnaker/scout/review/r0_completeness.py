#!/usr/bin/env python3
"""R0: completeness of the six scout reports against PLAN.md 'Output schemas'."""
import os, re, csv, json, collections
here = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(here, '..')
EXPECTED = {
 'S1': {'files': ['edges.tsv', 'clients.md', 'memo.md'], 'tsv': ('edges.tsv', 'caller\tprovider\tmethod\tpath_template\tinterface\tmethod_name\tbody_type\treturn_type\tresolved_by\tclaim')},
 'S2': {'files': ['endpoints.tsv', 'typing-census.md', 'memo.md'], 'tsv': ('endpoints.tsv', 'service\tversion\tcontroller\tmethod\tpath_template\tpath_params\tquery_params\theader_params\tbody_type\treturn_type\tresponse_codes\tcontent_types\ttyping\tclaim')},
 'S3': {'files': ['boms.tsv', 'artifacts.md', 'memo.md'], 'tsv': ('boms.tsv', 'release\trelease_date\tservice\tpinned_version\tartifact_kind\tartifact_ref\tretrievable\tjdk\tclaim')},
 'S4': {'files': ['ground-truth-candidates.md', 'memo.md'], 'md': ('ground-truth-candidates.md', ['pair', 'services', 'kind', 'quoted_sentence', 'source_url', 'claim'])},
 'S5': {'files': ['gaps.md', 'memo.md'], 'md': ('gaps.md', ['construct', 'count', 'loader_today', 'projection_convention', 'checker_change', 'cost', 'claim'])},
 'S6': {'files': ['chains.md', 'memo.md']},
}
TYPING = {'typed', 'untyped-body', 'untyped-return', 'untyped-both', 'polymorphic', 'raw-generic'}
KINDS = {'breaking', 'compat-note', 'upgrade-order', 'deprecation-removed'}
out = {}
for s, exp in EXPECTED.items():
    r = {'missing_files': [f for f in exp['files'] if not os.path.exists(os.path.join(S, s, f))], 'problems': [], 'notes': []}
    if 'tsv' in exp:
        fn, hdr = exp['tsv']; p = os.path.join(S, s, fn)
        if os.path.exists(p):
            first = open(p).readline().rstrip('\n')
            r['header_exact'] = (first == hdr)
            if not r['header_exact']: r['problems'].append(f'{fn} header differs: {first!r}')
            rows = list(csv.DictReader(open(p), delimiter='\t')); r['rows'] = len(rows)
            bad = [i for i, x in enumerate(rows) if any(v is None for v in x.values())]
            if bad: r['problems'].append(f'{fn}: {len(bad)} rows with wrong column count')
            if fn == 'endpoints.tsv':
                badt = collections.Counter(x['typing'] for x in rows if x['typing'] not in TYPING)
                if badt: r['problems'].append(f'typing values outside vocabulary: {dict(badt)}')
                r['rows_without_source'] = sum(1 for x in rows if 'source:' not in x['claim'])
            if fn == 'edges.tsv':
                r['rows_without_source'] = sum(1 for x in rows if '@' not in x['claim'])
                r['unresolved_rows'] = sum(1 for x in rows if x['provider'] == 'unresolved')
            if fn == 'boms.tsv':
                r['retrievable_values'] = dict(collections.Counter(x['retrievable'] for x in rows))
                r['artifact_kind_values'] = dict(collections.Counter(x['artifact_kind'] for x in rows))
                r['services'] = len(set(x['service'] for x in rows)); r['releases'] = len(set(x['release'] for x in rows))
                np_ = [x for x in rows if x['artifact_kind'] == 'not-pinned']
                r['deviation_not_pinned'] = {'rows': len(np_), 'all_retrievable_na': all(x['retrievable'] == 'n/a' for x in np_), 'all_version_dash': all(x['pinned_version'] == '-' for x in np_)}
                r['rows_without_claim'] = sum(1 for x in rows if 'CLAIM-S3-' not in x['claim'])
    if 'md' in exp:
        fn, cols = exp['md']; p = os.path.join(S, s, fn)
        if os.path.exists(p):
            lines = [l for l in open(p) if l.startswith('|')]
            hdr = [c.strip() for c in lines[0].strip().strip('|').split('|')] if lines else []
            r['header_exact'] = (hdr == cols)
            if not r['header_exact']: r['problems'].append(f'{fn} table header {hdr} != {cols}')
            rows = [dict(zip(hdr, [c.strip() for c in l.strip().strip('|').split('|')])) for l in lines[2:]]
            rows = [x for x in rows if len(x) == len(hdr)]
            r['rows'] = len(rows)
            if fn == 'ground-truth-candidates.md':
                r['kinds'] = dict(collections.Counter(x['kind'] for x in rows)); bad = [x['claim'] for x in rows if x['kind'] not in KINDS]
                if bad: r['problems'].append(f'kind outside vocabulary: {bad}')
                r['rows_without_claim'] = sum(1 for x in rows if not re.fullmatch(r'CLAIM-S4-\d{3}', x['claim']))
            if fn == 'gaps.md':
                r['rows_without_claim'] = sum(1 for x in rows if 'CLAIM-S5-' not in x['claim'])
    if s == 'S6':
        m = open(os.path.join(S, s, 'chains.md')).read()
        r['chains_md'] = {'claims_referenced': len(set(re.findall(r'CLAIM-S6-\d{3}', m))), 'ranked_chains': len(re.findall(r'(?m)^### \d\.', m)),
                          'has_mint_sink_hops': all(k in m for k in ['**Mint**', '**Sink**', '**Hops**'])}
    # memo checks
    mp = os.path.join(S, s, 'memo.md')
    if os.path.exists(mp):
        m = open(mp).read(); secs = [l.strip() for l in m.splitlines() if l.startswith('## ')]
        r['memo_last_section'] = secs[-1] if secs else None
        r['memo_ends_with_could_not_verify'] = bool(secs) and secs[-1] == '## What I could not verify'
        if not r['memo_ends_with_could_not_verify']: r['problems'].append('memo does not end with "## What I could not verify"')
        # claim definitions: CLAIM-Sx-NNN followed by ':' (possibly closing ** first)
        defs = sorted(set(int(n) for n in re.findall(r'CLAIM-' + s + r'-(\d{3})(?:\*\*)?(?:/\d{3})?:', m)))
        # S5 writes "CLAIM-S5-045/046:" for a pair
        defs += [int(n) for n in re.findall(r'CLAIM-' + s + r'-\d{3}/(\d{3}):', m)]
        defs = sorted(set(defs))
        r['memo_claims_defined'] = len(defs); r['memo_claim_max'] = max(defs) if defs else 0
        r['memo_claims_missing_numbers'] = [i for i in range(1, (max(defs) if defs else 0) + 1) if i not in defs]
        # which defined claims have no 'source' token before the next definition
        parts = re.split(r'(CLAIM-' + s + r'-\d{3}(?:\*\*)?(?:/\d{3})?:)', m)
        nosrc = []
        for i in range(1, len(parts) - 1, 2):
            body = parts[i + 1]
            num = int(re.search(r'\d{3}', parts[i]).group())
            if not re.search(r'\bsource\b', body, re.I) and not re.search(r'https?://|@v\d|\.(java|groovy|kt|go|yml|tsv|md):?\d*', body):
                nosrc.append(num)
        r['memo_claims_without_source_marker'] = sorted(set(nosrc))
        r['memo_claims_without_literal_source_label'] = sorted(set(int(re.search(r'\d{3}', parts[i]).group()) for i in range(1, len(parts) - 1, 2) if 'source' not in parts[i + 1].lower()))
    r['pass'] = not r['missing_files'] and not r['problems']
    out[s] = r
json.dump(out, open(os.path.join(here, 'r0_completeness.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
