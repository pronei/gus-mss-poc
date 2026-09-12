#!/usr/bin/env python3
"""R1(a): match every S1 edge with a resolved provider to an S2 endpoint of that provider on
method and normalized path (D3).  R1(b): untyped share over the reconciled edges under D5 as
written and under S5's refinement.  Writes r1a_matched.tsv, r1a_unmatched.tsv, r1ab.json."""
import csv, re, json, os, collections
here = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(here, '..')
edges = list(csv.DictReader(open(os.path.join(S, 'S1', 'edges.tsv')), delimiter='\t'))
eps = list(csv.DictReader(open(os.path.join(S, 'S2', 'endpoints.tsv')), delimiter='\t'))

# ---------------- D3 normalization ----------------
# Per-provider prefix rules, applied to both sides.  Empty at these tags: every provider's
# callers already declare the same version prefix the provider maps (/v2 on front50, /api/v1 on
# rosco); the table is kept so G3 has one place to put a rule if a BOM in range needs one.
PREFIX_RULES = {}
ACTUATOR = {'/health', '/installedPlugins'}   # Spring Boot actuator / kork endpoints, not MVC controllers (out of S2's scope)

def norm_path(p, provider):
    p = p.strip().split('?')[0]                    # baked-in query string
    if p in ('', '.', './'): p = '/'               # Retrofit 2 "." = the base URL
    if not p.startswith('/'): p = '/' + p          # Retrofit 2 relative path
    p = re.sub(r'\{[^}]*\}', '{}', p)              # erase variable names and regexes
    p = re.sub(r'/{2,}', '/', p)
    for rx, rep in PREFIX_RULES.get(provider, []): p = re.sub(rx, rep, p)
    if len(p) > 1: p = p.rstrip('/')               # trailing slash
    return p

def template_regex(p):
    parts = []
    for seg in p.split('/'):
        if seg == '{}': parts.append(r'[^/]+')       # a caller literal or a caller {} both fill a provider slot
        elif seg == '**': parts.append(r'.*')
        else: parts.append(re.escape(seg))
    return re.compile('^' + '/'.join(parts) + '$')

by_provider = collections.defaultdict(list)
for i, ep in enumerate(eps):
    n = norm_path(ep['path_template'], ep['service'])
    by_provider[ep['service']].append((i, ep, n, template_regex(n), sum(1 for s in n.split('/') if s and s not in ('{}', '**')), n.count('**')))

matched, unmatched, ambiguous = [], [], 0
for j, e in enumerate(edges):
    prov = e['provider']
    if prov == 'unresolved': continue
    n = norm_path(e['path_template'], prov)
    cands = [c for c in by_provider[prov] if (c[1]['method'] == e['method'] or c[1]['method'] == 'ANY') and c[3].match(n)]
    if not cands:
        unmatched.append((j, e, n, 'actuator' if n in ACTUATOR else 'no-provider-mapping'))
        continue
    cands.sort(key=lambda c: (-c[4], c[5], c[1]['method'] == 'ANY', c[0]))
    if len(cands) > 1 and (cands[0][4], cands[0][5]) == (cands[1][4], cands[1][5]): ambiguous += 1
    matched.append((j, e, n, cands[0][1], len(cands)))

# ---------------- D5 typing ----------------
OPAQUE = {'-', 'void', 'Void', 'Unit', 'ResponseBody', 'Response', 'retrofit.client.Response', 'StreamingResponseBody', 'byte[]', 'RequestBody', 'Resource'}  # no JSON shape on that side
# NB 'Resource' is ambiguous (Spring Resource vs Keel's Resource model); resolved below by side/service.
WRAPPERS = ['Call', 'ResponseEntity', 'HttpEntity', 'Optional', 'CompletableFuture', 'DeferredResult', 'Callable', 'Mono', 'Flux']
UNTYPED_BASES = {'Object', 'Any', 'Any?', '?', 'def', 'JsonNode', 'ObjectNode', 'ArrayNode', 'Serializable', '*'}
MAP_BASES = {'Map', 'HashMap', 'LinkedHashMap', 'MultiValueMap', 'TreeMap', 'SortedMap'}
LIST_BASES = {'List', 'Collection', 'Set', 'Iterable', 'ArrayList', 'LinkedList', 'HashSet', 'Sequence', 'Array'}
MAP_SUBCLASSES = {'front50': {'PipelineTemplate', 'Notification'}}   # CLAIM-S2-005/006: extend HashMap<String,Object>

def split_top(s):
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch == '<': depth += 1
        elif ch == '>': depth -= 1
        if ch == ',' and depth == 0: out.append(cur); cur = ''
        else: cur += ch
    if cur: out.append(cur)
    return out

def parse(t):
    m = re.fullmatch(r'([^<]+)<(.*)>', t)
    if m: return m.group(1), split_top(m.group(2))
    return t, []

def unwrap(t):
    t = t.replace(' ', '')
    if t.endswith('(raw)'): return 'RAW'
    changed = True
    while changed:
        changed = False
        for w in WRAPPERS:
            m = re.fullmatch(re.escape(w) + r'<(.*)>', t)
            if m: t, changed = m.group(1), True
    return t

def classify(t, strict, service=None):
    """'none' (no JSON shape) | 'untyped' | 'typed'.  strict=True is D5 as written (every Map,
    Object, List<Map>, JsonNode, raw type); strict=False is S5's refinement (Map<String,X> with a
    concrete X is typed)."""
    t = unwrap(t)
    if t.startswith('multipart:'): return 'none'
    if t in OPAQUE and not (t == 'Resource' and service == 'keel'): return 'none'
    if t == 'RAW': return 'untyped'
    if t.startswith('?extends'): return classify(t[len('?extends'):], strict, service)
    base, args = parse(t)
    base = base.split('.')[-1] if base.split('.')[-1] in MAP_BASES | LIST_BASES else base
    if base in UNTYPED_BASES: return 'untyped'
    if service and base in MAP_SUBCLASSES.get(service, set()): return 'untyped'
    if base in MAP_BASES:
        if not args or strict: return 'untyped'
        return 'untyped' if classify(args[-1], strict, service) == 'untyped' else 'typed'
    if base in LIST_BASES:
        if not args: return 'untyped'
        return classify(args[0], strict, service)
    return 'typed'

def edge_typing(e, ep, strict):
    sides = {'caller_body': classify(e['body_type'], strict), 'caller_return': classify(e['return_type'], strict),
             'provider_body': classify(ep['body_type'], strict, ep['service']), 'provider_return': classify(ep['return_type'], strict, ep['service'])}
    req_untyped = 'untyped' in (sides['caller_body'], sides['provider_body'])
    resp_untyped = 'untyped' in (sides['caller_return'], sides['provider_return'])
    return sides, req_untyped or resp_untyped, req_untyped and resp_untyped

# cross-check my strict classifier against S2's typing column
s2_untyped_col = {'untyped-body', 'untyped-return', 'untyped-both', 'raw-generic'}
xcheck = []
for ep in eps:
    mine = 'untyped' in (classify(ep['body_type'], True, ep['service']), classify(ep['return_type'], True, ep['service']))
    theirs = ep['typing'] in s2_untyped_col
    if mine != theirs: xcheck.append((ep['service'], ep['method'], ep['path_template'], ep['body_type'], ep['return_type'], ep['typing']))

rows_out = []
stats = {'strict': collections.Counter(), 'refined': collections.Counter()}
per_prov = collections.defaultdict(lambda: {'resolved': 0, 'matched': 0, 'untyped_strict': 0, 'untyped_refined': 0, 'both_sides_strict': 0})
for e in edges:
    if e['provider'] != 'unresolved': per_prov[e['provider']]['resolved'] += 1
opaque_caller_return = 0
for j, e, n, ep, nc in matched:
    ss, us, bs = edge_typing(e, ep, True)
    sr, ur, br = edge_typing(e, ep, False)
    p = per_prov[e['provider']]; p['matched'] += 1
    if us: p['untyped_strict'] += 1; stats['strict']['untyped'] += 1
    if ur: p['untyped_refined'] += 1; stats['refined']['untyped'] += 1
    if bs: p['both_sides_strict'] += 1; stats['strict']['both_sides'] += 1
    if br: stats['refined']['both_sides'] += 1
    if ss['caller_return'] == 'none' and e['return_type'] != '-': opaque_caller_return += 1
    rows_out.append({'caller': e['caller'], 'provider': e['provider'], 'method': e['method'], 'caller_path': e['path_template'], 'norm_path': n,
                     'provider_path': ep['path_template'], 'provider_claim': ep['claim'].split(' ')[0], 'candidates': nc,
                     'caller_body': e['body_type'], 'caller_return': e['return_type'], 'provider_body': ep['body_type'], 'provider_return': ep['return_type'], 's2_typing': ep['typing'],
                     'untyped_as_written': int(us), 'untyped_refined': int(ur), 'both_sides_untyped_as_written': int(bs), 'edge_claim': e['claim']})
# sensitivity: as written, but counting an opaque caller return (Call<ResponseBody>/Response/Call<Void>) as untyped, as S1's 65% did
sens = 0
for j, e, n, ep, nc in matched:
    ss, us, bs = edge_typing(e, ep, True)
    if us or (ss['caller_return'] == 'none' and e['return_type'] != '-'): sens += 1

resolved = sum(1 for e in edges if e['provider'] != 'unresolved')
res = {'edges': len(edges), 'resolved': resolved, 'unresolved': len(edges) - resolved, 'matched': len(matched), 'unmatched': len(unmatched),
       'matched_share_of_resolved': round(len(matched) / resolved, 4), 'ambiguous_matches': ambiguous,
       'unmatched_by_category': dict(collections.Counter(c for *_, c in unmatched)),
       'matched_share_excluding_actuator': round(len(matched) / (resolved - sum(1 for *_, c in unmatched if c == 'actuator')), 4),
       'per_provider': {k: dict(v, matched_share=round(v['matched'] / v['resolved'], 3), untyped_share_as_written=round(v['untyped_strict'] / v['matched'], 3) if v['matched'] else None,
                                untyped_share_refined=round(v['untyped_refined'] / v['matched'], 3) if v['matched'] else None) for k, v in sorted(per_prov.items())},
       'untyped_share_as_written': {'untyped': stats['strict']['untyped'], 'of': len(matched), 'share': round(stats['strict']['untyped'] / len(matched), 4), 'both_sides_untyped': stats['strict']['both_sides']},
       'untyped_share_s5_refined': {'untyped': stats['refined']['untyped'], 'of': len(matched), 'share': round(stats['refined']['untyped'] / len(matched), 4), 'both_sides_untyped': stats['refined']['both_sides']},
       'sensitivity_as_written_plus_opaque_caller_return_counted_untyped': {'untyped': sens, 'share': round(sens / len(matched), 4), 'edges_with_opaque_caller_return': opaque_caller_return},
       's2_typing_column_crosscheck_mismatches': len(xcheck), 's2_typing_column_crosscheck_examples': xcheck[:20],
       'normalization': {'prefix_rules': PREFIX_RULES, 'rules': ['strip ?query', '"."/"" -> /', 'add leading /', '{name[:regex]} -> {}', 'collapse //', 'strip trailing /', 'provider ** matches any suffix', 'provider {} matches a caller literal or {}', 'provider ANY matches every method']}}
with open(os.path.join(here, 'r1a_matched.tsv'), 'w') as f:
    w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()), delimiter='\t'); w.writeheader(); w.writerows(rows_out)
with open(os.path.join(here, 'r1a_unmatched.tsv'), 'w') as f:
    w = csv.writer(f, delimiter='\t'); w.writerow(['caller', 'provider', 'method', 'caller_path', 'normalized_path', 'category', 'interface', 'method_name', 'edge_claim'])
    for j, e, n, c in unmatched: w.writerow([e['caller'], e['provider'], e['method'], e['path_template'], n, c, e['interface'], e['method_name'], e['claim']])
json.dump(res, open(os.path.join(here, 'r1ab.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ('s2_typing_column_crosscheck_examples',)}, indent=1))
print('\nxcheck examples:'); [print(' ', x) for x in xcheck[:20]]
print('\nUNMATCHED:'); [print(' ', e['caller'], '->', e['provider'], e['method'], e['path_template'], '=>', n, '[', c, ']') for j, e, n, c in unmatched]
