#!/usr/bin/env python3
"""Audit of every directory name the extractor prunes or skips, and of the names the
review's redo asked about (build, out, target, generated, test, bin), over the ten
clones of CLAIM-S2-001.  Backs CLAIM-S2-028.  Reports, per name: how many such
directories exist, whether each is Gradle output (named `build` and holding
classes/ libs/ tmp/ generated/), how many source files each rule touches, how many
of those are under src/main, and how many are controllers with a method-level
mapping (i.e. endpoint rows at risk)."""
import os, re, json, collections, sys
CLONES = os.environ.get('SPINNAKER_CLONES',
                        '/private/tmp/claude-501/-Users-pronei-work-faults-lab-service-beds-gus/01d8e507-e2b9-4543-baaa-b8859181517e/scratchpad/spinnaker/S2')
SERVICES = ['gate','orca','clouddriver','front50','echo','igor','fiat','rosco','kayenta','keel']
NAMES = ['build','out','target','generated','test','bin','node_modules']
MARKERS = ('classes','libs','tmp','generated')
CTRL = re.compile(r'@(RestController|Controller)\b')
MAP = re.compile(r'@(RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\b')

def strip_comments(t):
    t = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', t); t = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", t)
    t = re.sub(r'/\*.*?\*/', '', t, flags=re.S); return re.sub(r'(?m)//.*$', '', t)

dirs_by_name = collections.defaultdict(list)
srcfiles = collections.defaultdict(list)   # (svc) -> [relpath]
for svc in SERVICES:
    root = os.path.join(CLONES, svc)
    for dp, dn, fn in os.walk(root):
        if '/.git' in dp: dn[:] = []; continue
        dn[:] = [d for d in dn if d != '.git']
        for d in dn:
            if d in NAMES:
                full = os.path.join(dp, d)
                dirs_by_name[d].append({
                    'svc': svc, 'rel': os.path.relpath(full, root),
                    'markers': [m for m in MARKERS if os.path.isdir(os.path.join(full, m))],
                    'parent_has_gradle': any(os.path.exists(os.path.join(dp, g)) for g in ('build.gradle','build.gradle.kts','settings.gradle','settings.gradle.kts')),
                })
        for f in fn:
            if f.endswith(('.java','.groovy','.kt')):
                srcfiles[svc].append(os.path.relpath(os.path.join(dp, f), root))

# how each rule in extract.py touches the source files
def is_output(svc, rel):
    """content test: some ancestor dir named build holds a gradle output marker"""
    parts = rel.split('/'); root = os.path.join(CLONES, svc)
    for i, p in enumerate(parts[:-1]):
        if p == 'build':
            full = os.path.join(root, *parts[:i+1])
            if any(os.path.isdir(os.path.join(full, m)) for m in MARKERS): return True
    return False

rules = collections.defaultdict(lambda: {'files': 0, 'controllers': [], 'under_src_main': 0})
for svc in SERVICES:
    root = os.path.join(CLONES, svc)
    for rel in srcfiles[svc]:
        parts = rel.split('/')[:-1]
        dp = '/'.join(parts)
        hits = []
        if 'build' in parts: hits.append('name:build')
        if 'test' in parts: hits.append('name:test')
        if any(p in ('out','target','generated','bin','node_modules') for p in parts): hits.append('name:other')
        if '/test/' in '/' + dp + '/': hits.append('substr:/test/')
        if dp.endswith('/test') or dp == 'test': hits.append('endswith:/test')
        if is_output(svc, rel): hits.append('gradle-output')
        if not hits: continue
        try: t = strip_comments(open(os.path.join(root, rel), errors='replace').read())
        except OSError: continue
        is_ctrl = bool(CTRL.search(t)) and bool(MAP.search(t))
        for h in hits:
            r = rules[h]; r['files'] += 1
            if '/src/main/' in '/' + rel: r['under_src_main'] += 1
            if is_ctrl: r['controllers'].append(svc + ' ' + rel)

print('=== directories by name (ten clones, .git excluded) ===')
for n in NAMES:
    lst = dirs_by_name.get(n, [])
    print('%-12s %d dirs' % (n, len(lst)))
    if n != 'test':
        for d in lst: print('     ', d['svc'], d['rel'], 'markers=', d['markers'], 'parent_gradle=', d['parent_has_gradle'])
    else:
        main = [d for d in lst if '/src/main/' in '/' + d['rel']]
        print('      under src/main:', len(main))
        for d in main: print('       ', d['svc'], d['rel'])
print()
print('=== source files touched by each rule ===')
for k, v in sorted(rules.items()):
    print('%-16s files=%-5d under_src_main=%-4d controller_files_with_method_mapping=%d' % (k, v['files'], v['under_src_main'], len(v['controllers'])))
    for c in v['controllers'][:40]: print('      ', c)
