#!/usr/bin/env python3
"""Census of the model types that endpoint signatures name directly.

For each service, collect the distinct named types appearing as a request body
or return type (after unwrapping containers), resolve each to its declaring
source file, and count how the model is written and annotated.
"""
import json, os, re, collections, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract as E

# The ten shallow clones (see memo CLAIM-S2-001 for the tags); override with
# SPINNAKER_CLONES.  Outputs (rows.json, diag.json, census.json, models.json)
# go to S2_OUT, which defaults to the clone root.
ROOT = os.environ.get('SPINNAKER_CLONES',
                      '/private/tmp/claude-501/-Users-pronei-work-faults-lab-service-beds-gus/01d8e507-e2b9-4543-baaa-b8859181517e/scratchpad/spinnaker/S2')
OUTDIR = os.environ.get('S2_OUT', ROOT)
ORDER = ['gate', 'orca', 'clouddriver', 'front50', 'echo', 'igor', 'fiat',
         'rosco', 'kayenta', 'keel']

E.build_type_index([s for s, _ in E.SERVICES] + ['kork'])
E.build_mixin_map([s for s, _ in E.SERVICES] + ['kork'])
rows = json.load(open(os.path.join(OUTDIR, 'rows.json')))


def named_types(t):
    """Named, non-container, non-primitive types inside a type expression."""
    if not t or t == '-':
        return []
    out = []
    for tok in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', t):
        if not tok[0].isupper():
            continue
        if tok in E.CONTAINERS or tok in E.UNTYPED_BASES or tok in E.PRIMITIVE_OK \
           or tok in E.NONE_TYPES or tok in ('RAW',):
            continue
        out.append(tok)
    return out


ANNPAT = {
    'validation_javax': re.compile(r'@(NotNull|NotEmpty|NotBlank|Size|Min|Max|Pattern|Valid)\b'),
    'jsonproperty_required': re.compile(r'@JsonProperty\s*\([^)]*required\s*=\s*true', re.S),
    'jsonproperty': re.compile(r'@JsonProperty\b'),
    'nullable_ann': re.compile(r'@(Nullable|CheckForNull)\b'),
    'nonnull_ann': re.compile(r'@(NonNull|Nonnull)\b'),
    'jsontypeinfo': re.compile(r'@JsonTypeInfo\b'),
    'jsoncreator': re.compile(r'@JsonCreator\b'),
    'jsonignoreprops': re.compile(r'@JsonIgnoreProperties\b'),
    'anysetter': re.compile(r'@Json(Any(Setter|Getter))\b'),
    'lombok': re.compile(r'@(Data|Value|Builder|Getter|Setter|AllArgsConstructor|NoArgsConstructor)\b'),
}

STYLE = {
    'kotlin_data_class': re.compile(r'\bdata class\b'),
    'kotlin_class': re.compile(r'\bclass\b'),
    'groovy_canonical': re.compile(r'@(Canonical|Immutable|ToString|TupleConstructor)\b'),
}

result = {}
examples = collections.defaultdict(list)

for svc in ORDER:
    E.CUR_SCOPE[0] = svc
    names = set()
    for r in rows:
        if r['service'] != svc:
            continue
        names.update(named_types(r['body_type']))
        names.update(named_types(r['return_unwrapped']))
    res = collections.Counter()
    langs = collections.Counter()
    resolved, unresolved = [], []
    kt_null_fields = kt_total_fields = 0
    java_fields = groovy_def_fields = 0
    for n in sorted(names):
        paths = E.lookup(n, svc)
        if not paths:
            unresolved.append(n)
            continue
        path = paths[0]
        resolved.append(n)
        lang = path.rsplit('.', 1)[1]
        langs[lang] += 1
        try:
            txt = open(path, errors='replace').read()
        except OSError:
            continue
        cb = E.class_body(txt, n)
        if cb is None:
            continue
        annstr, body = cb
        blob = annstr + '\n' + body
        for k, rx in ANNPAT.items():
            if rx.search(blob):
                res[k] += 1
                if len(examples[k]) < 4:
                    examples[k].append('%s %s %s' % (svc, n, os.path.relpath(path, ROOT)))
        if lang == 'kt':
            if STYLE['kotlin_data_class'].search(annstr + txt[:txt.find(n) + 200]) or \
               re.search(r'\bdata class\s+%s\b' % re.escape(n), txt):
                res['kotlin_data_class'] += 1
            for mm in re.finditer(r'\b(?:val|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Za-z_][A-Za-z0-9_.<>, \[\]]*\??)', body):
                kt_total_fields += 1
                if mm.group(1).rstrip().endswith('?'):
                    kt_null_fields += 1
        if lang == 'groovy':
            if STYLE['groovy_canonical'].search(annstr):
                res['groovy_canonical'] += 1
            groovy_def_fields += len(re.findall(r'^\s*(?:private |public |protected )?def\s+[a-z_]', body, re.M))
        if lang == 'java':
            java_fields += len(re.findall(r'^\s*(?:private|public|protected)\s+(?:final\s+)?[A-Z][\w.<>, \[\]]*\s+[a-z_]\w*\s*[;=]', body, re.M))
        if E.is_map_subclass(n):
            res['map_subclass'] += 1
            if len(examples['map_subclass']) < 6:
                examples['map_subclass'].append('%s %s %s' % (svc, n, os.path.relpath(path, ROOT)))
    result[svc] = {
        'named_types': len(names),
        'resolved': len(resolved),
        'unresolved': len(unresolved),
        'unresolved_names': sorted(unresolved)[:20],
        'langs': dict(langs),
        'ann': dict(res),
        'kt_fields': kt_total_fields,
        'kt_nullable_fields': kt_null_fields,
        'groovy_def_fields': groovy_def_fields,
        'java_fields': java_fields,
    }

json.dump({'per_service': result, 'examples': {k: v for k, v in examples.items()}},
          open(os.path.join(OUTDIR, 'models.json'), 'w'), indent=1)

for s in ORDER:
    r = result[s]
    print('%-12s types=%-4d resolved=%-4d langs=%-28s kt_fields=%d/%d null' %
          (s, r['named_types'], r['resolved'], str(r['langs']),
           r['kt_nullable_fields'], r['kt_fields']))
    print('             ', r['ann'])
