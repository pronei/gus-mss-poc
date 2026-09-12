#!/usr/bin/env python3
"""Compute the typing census from rows.json plus repo-wide annotation counts."""
import json, os, re, collections, subprocess, sys

# The ten shallow clones (see memo CLAIM-S2-001 for the tags); override with
# SPINNAKER_CLONES.  Outputs (rows.json, diag.json, census.json, models.json)
# go to S2_OUT, which defaults to the clone root.
ROOT = os.environ.get('SPINNAKER_CLONES',
                      '/private/tmp/claude-501/-Users-pronei-work-faults-lab-service-beds-gus/01d8e507-e2b9-4543-baaa-b8859181517e/scratchpad/spinnaker/S2')
OUTDIR = os.environ.get('S2_OUT', ROOT)
ORDER = ['gate', 'orca', 'clouddriver', 'front50', 'echo', 'igor', 'fiat',
         'rosco', 'kayenta', 'keel']
VERSION = {'gate': 'v6.69.0', 'orca': 'v8.64.0', 'clouddriver': 'v5.95.0',
           'front50': 'v2.41.0', 'echo': 'v2.47.2', 'igor': 'v4.22.0',
           'fiat': 'v1.57.0', 'rosco': 'v1.26.0', 'kayenta': 'v2.46.0',
           'keel': 'v1.4.1'}

rows = json.load(open(os.path.join(OUTDIR, 'rows.json')))

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          cwd=ROOT).stdout.strip()

def count_files(repo, pattern, globs='-g "*.java" -g "*.groovy" -g "*.kt"'):
    out = sh('rg -l --no-messages %s %s -g "!**/test/**" -g "!**/*Test*" -g "!**/*Spec*" | wc -l'
             % (pattern, repo + ' ' + globs))
    return int(out or 0)

def count_hits(repo, pattern, globs='-g "*.java" -g "*.groovy" -g "*.kt"'):
    out = sh('rg -c --no-messages %s %s -g "!**/test/**" -g "!**/*Test*" -g "!**/*Spec*" | '
             'awk -F: \'{s+=$2} END{print s+0}\'' % (pattern, repo + ' ' + globs))
    return int(out or 0)

stats = {}
for svc in ORDER:
    rs = [r for r in rows if r['service'] == svc]
    typing = collections.Counter(r['typing'] for r in rs)
    langs = collections.Counter(r['lang'] for r in rs)
    ctrl_langs = {}
    for r in rs:
        ctrl_langs[r['file']] = r['lang']
    ctrl_lang_count = collections.Counter(ctrl_langs.values())
    untyped = sum(typing[k] for k in ('untyped-body', 'untyped-return',
                                      'untyped-both', 'raw-generic'))
    stats[svc] = {
        'endpoints': len(rs),
        'controllers': len(set(r['controller'].split('.')[0] for r in rs)),
        'controller_files': len(ctrl_langs),
        'typing': dict(typing),
        'untyped': untyped,
        'untyped_share': (untyped / len(rs)) if rs else 0.0,
        'endpoint_langs': dict(langs),
        'controller_file_langs': dict(ctrl_lang_count),
        'deprecated': sum(1 for r in rs if r['deprecated'] == 'yes'),
        'versioned_paths': sum(1 for r in rs if re.search(r'/v\d+(/|$)', r['path_template'])),
        'void_return': sum(1 for r in rs if r['return_unwrapped'] in ('void', 'Unit', 'Void')),
        'no_body': sum(1 for r in rs if r['body_type'] == '-'),
        'poly_touch': sum(1 for r in rs if r['poly']),
        'with_query': sum(1 for r in rs if r['query_params'] != '-'),
        'with_header': sum(1 for r in rs if r['header_params'] != '-'),
        'with_codes': sum(1 for r in rs if r['response_codes'] != '-'),
        'with_ct': sum(1 for r in rs if r['content_types'] != '-'),
    }
    # annotation presence across the whole (non-test) source tree
    stats[svc]['ann'] = {
        'javax_validation': count_hits(svc, "-e 'import javax\\.validation'"),
        'jakarta_validation': count_hits(svc, "-e 'import jakarta\\.validation'"),
        'valid_ann': count_hits(svc, "-e '@Valid\\b' -e '@Validated\\b'"),
        'notnull': count_hits(svc, "-e '@NotNull\\b' -e '@NotEmpty\\b' -e '@NotBlank\\b'"),
        'size_min_max': count_hits(svc, "-e '@Size\\(' -e '@Min\\(' -e '@Max\\(' -e '@Pattern\\('"),
        'jsonproperty_required': count_hits(svc, "-e 'JsonProperty\\([^)]*required *= *true'"),
        'jsonproperty': count_hits(svc, "-e '@JsonProperty'"),
        'nullable': count_hits(svc, "-e '@Nullable\\b'"),
        'nonnull': count_hits(svc, "-e '@NonNull\\b' -e '@Nonnull\\b'"),
        'jsontypeinfo_files': count_files(svc, "-e '@JsonTypeInfo'"),
        'jsonsubtypes_files': count_files(svc, "-e '@JsonSubTypes'"),
        'mixins': count_hits(svc, "-e 'addMixIn' -e 'setMixInAnnotations'"),
        'anysetter': count_hits(svc, "-e '@JsonAnySetter' -e '@JsonAnyGetter'"),
        'lombok_data': count_hits(svc, "-e '@Data\\b' -e '@Value\\b' -e '@Builder\\b'"),
        'kotlin_data_class': count_hits(svc, "-e '\\bdata class\\b' -g '*.kt'"),
        'groovy_def_field': count_hits(svc, "-e '^\\s*def [a-z]' -g '*.groovy'"),
        'canonical_groovy': count_hits(svc, "-e '@Canonical' -e '@CompileStatic' -g '*.groovy'"),
    }

json.dump(stats, open(os.path.join(OUTDIR, 'census.json'), 'w'), indent=1)
for s in ORDER:
    st = stats[s]
    print('%-12s ep=%-4d ctrl=%-3d untyped=%-4d (%.0f%%) %s' %
          (s, st['endpoints'], st['controllers'], st['untyped'],
           100 * st['untyped_share'], st['typing']))
tot = sum(stats[s]['endpoints'] for s in ORDER)
untot = sum(stats[s]['untyped'] for s in ORDER)
print('TOTAL endpoints=%d untyped=%d (%.1f%%)' % (tot, untot, 100.0 * untot / tot))
