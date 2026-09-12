#!/usr/bin/env python3
"""Re-derivation of CLAIM-S2-003 (coverage complete): every main-source file in the ten clones that
carries @RestController/@Controller and at least one method-level mapping annotation must appear as a
source file in S2's endpoints.tsv.  Lists the files S2 missed and their mapping counts."""
import os, re, csv, json, collections
here = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(here, '..')
CLONES = os.environ.get('SPINNAKER_CLONES', '/private/tmp/claude-501/-Users-pronei-work-faults-lab-service-beds-gus/01d8e507-e2b9-4543-baaa-b8859181517e/scratchpad/spinnaker') + '/S2'
eps = list(csv.DictReader(open(os.path.join(S, 'S2', 'endpoints.tsv')), delimiter='\t'))
s2_files = collections.defaultdict(set)
for e in eps:
    m = re.search(r'source:spinnaker/(\w+)@\S+ (\S+):\d+', e['claim'])
    s2_files[m.group(1)].add(m.group(2))
MAP = re.compile(r'@(RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\b')
def strip_comments(t):
    # blank string literals first so that a '/**' Ant wildcard inside a path is not read as a comment
    t = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', t); t = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", t)
    t = re.sub(r'/\*.*?\*/', '', t, flags=re.S); return re.sub(r'(?m)//.*$', '', t)
out = {}; total_missing_mappings = 0
for svc in ['gate', 'orca', 'clouddriver', 'front50', 'echo', 'igor', 'fiat', 'rosco', 'kayenta', 'keel']:
    root = os.path.join(CLONES, svc); missing = []; ctrl_files = 0
    for dp, dn, fn in os.walk(root):
        if '/src/test/' in dp + '/' or '/.git' in dp: continue
        for f in fn:
            if not f.endswith(('.java', '.groovy', '.kt')): continue
            p = os.path.join(dp, f); rel = os.path.relpath(p, root)
            try: t = strip_comments(open(p, errors='replace').read())
            except OSError: continue
            if not re.search(r'@(RestController|Controller)\b', t): continue
            ctrl_files += 1
            # method-level mappings = all mapping annotations minus the class-level one(s) that precede 'class'
            n_all = len(MAP.findall(t))
            cls = re.search(r'\b(class|object)\s+\w+', t)
            n_class_level = len(MAP.findall(t[:cls.start()])) if cls else 0
            n_method = n_all - n_class_level
            if n_method > 0 and rel not in s2_files[svc]:
                # where is the @RestController annotation?
                pos = re.search(r'@(RestController|Controller)\b', open(p, errors='replace').read()).start()
                missing.append({'file': rel, 'method_mappings': n_method, 'controller_annotation_at_char': pos, 'line': open(p, errors='replace').read()[:pos].count('\n') + 1})
    total_missing_mappings += sum(m['method_mappings'] for m in missing)
    out[svc] = {'controller_files_in_source': ctrl_files, 'files_in_s2': len(s2_files[svc]), 'missing_files': missing}
out['_total_missing_method_mappings'] = total_missing_mappings
json.dump(out, open(os.path.join(here, 'r2_s2_coverage.json'), 'w'), indent=1)
for svc, v in out.items():
    if svc.startswith('_'): print(svc, v); continue
    print(svc, 'source controller files:', v['controller_files_in_source'], '| files in S2:', v['files_in_s2'], '| missing:', len(v['missing_files']))
    for m in v['missing_files']: print('    ', m)
