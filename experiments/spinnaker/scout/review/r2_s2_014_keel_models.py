#!/usr/bin/env python3
"""Re-derivation of CLAIM-S2-014: of the model types Keel's controller signatures name, how many are
Kotlin data classes and how many declared properties are nullable.  Independent of S2's models.json:
types are taken from endpoints.tsv (containers unwrapped), located by 'class <Name>' in keel's main
sources, and constructor properties counted from the primary constructor."""
import os, re, csv, json, collections
here = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(here, '..')
KEEL = os.environ.get('SPINNAKER_CLONES', '/private/tmp/claude-501/-Users-pronei-work-faults-lab-service-beds-gus/01d8e507-e2b9-4543-baaa-b8859181517e/scratchpad/spinnaker') + '/S2/keel'
eps = [e for e in csv.DictReader(open(os.path.join(S, 'S2', 'endpoints.tsv')), delimiter='\t') if e['service'] == 'keel']
SKIP = {'-', 'void', 'Unit', 'String', 'Boolean', 'Int', 'Long', 'Any', 'Any?', 'Map', 'List', 'Set', 'Collection', 'Object', 'ByteArray', 'Instant', 'UUID', 'ResponseEntity'}
def names(t):
    t = t.replace(' ', '')
    out = set()
    for tok in re.findall(r'[A-Za-z_][A-Za-z0-9_.]*', t):
        tok = tok.split('.')[-1].rstrip('?')
        if tok in SKIP or tok in ('Map', 'List', 'Set', 'Collection', 'Optional'): continue
        if tok[0].isupper(): out.add(tok)
    return out
types = set()
for e in eps:
    types |= names(e['body_type']); types |= names(e['return_type'])
files = {}
for dp, dn, fn in os.walk(KEEL):
    if '/src/test/' in dp + '/' or '/.git' in dp: continue
    for f in fn:
        if f.endswith('.kt'):
            p = os.path.join(dp, f); t = open(p, errors='replace').read()
            for name in types:
                if re.search(r'\b(data class|class|interface|object|sealed class|enum class)\s+' + re.escape(name) + r'\b', t): files.setdefault(name, []).append(p)
res = {'types_named': sorted(types), 'resolved': {}, 'unresolved': sorted(t for t in types if t not in files)}
props = nullable = data_classes = 0
for name, ps in sorted(files.items()):
    t = open(ps[0], errors='replace').read()
    m = re.search(r'\b(data class|class|interface|object|sealed class|enum class)\s+' + re.escape(name) + r'\b\s*(?:<[^>]*>)?\s*(?:@\w+\s*)*(\()?', t)
    kind = m.group(1); ctor = None
    if m.group(2):
        i = m.end(); depth = 1; j = i
        while depth and j < len(t):
            depth += {'(': 1, ')': -1}.get(t[j], 0); j += 1
        ctor = t[i:j - 1]
    n = nn = 0
    if ctor:
        for line in re.split(r',\s*\n', re.sub(r'/\*.*?\*/', '', ctor, flags=re.S)):
            line = re.sub(r'(?m)//.*$', '', line).strip()
            mm = re.match(r'(?:@\w+(?:\([^)]*\))?\s*)*(?:override\s+)?(?:val|var)\s+\w+\s*:\s*([^=]+?)(\s*=.*)?$', line, re.S)
            if mm:
                n += 1
                if mm.group(1).strip().endswith('?'): nn += 1
    if kind == 'data class': data_classes += 1
    props += n; nullable += nn
    res['resolved'][name] = {'kind': kind, 'file': os.path.relpath(ps[0], KEEL), 'ctor_props': n, 'nullable': nn, 'candidates': len(ps)}
res['summary'] = {'types_named': len(types), 'resolved': len(files), 'data_classes': data_classes, 'ctor_props_total': props, 'nullable_total': nullable}
json.dump(res, open(os.path.join(here, 'r2_s2_014_keel_models.json'), 'w'), indent=1)
print(json.dumps(res['summary'])); print('unresolved:', res['unresolved'])
for k, v in res['resolved'].items(): print(f"  {k:32s} {v['kind']:12s} props={v['ctor_props']:3d} nullable={v['nullable']:2d} {v['file']}" + (' [%d candidates]' % v['candidates'] if v['candidates'] > 1 else ''))
