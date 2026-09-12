#!/usr/bin/env python3
"""Emit endpoints.tsv from rows.json.

A row claim id is a citation, so it names one endpoint for good: with
--stable-from <previous endpoints.tsv> every row already in that table keeps the
id it was delivered under, and rows that are new take fresh ids continuing from
the previous maximum.  Without the flag the ids are assigned in row order.
"""
import csv, json, os, re, sys

ROOT = os.environ.get('SPINNAKER_CLONES', os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.environ.get('S2_OUT', ROOT)
REPO = {'gate': 'gate', 'orca': 'orca', 'clouddriver': 'clouddriver',
        'front50': 'front50', 'echo': 'echo', 'igor': 'igor', 'fiat': 'fiat',
        'rosco': 'rosco', 'kayenta': 'kayenta', 'keel': 'keel'}

HEADER = ('service\tversion\tcontroller\tmethod\tpath_template\tpath_params\t'
          'query_params\theader_params\tbody_type\treturn_type\tresponse_codes\t'
          'content_types\ttyping\tclaim')

ORDER = ['gate', 'orca', 'clouddriver', 'front50', 'echo', 'igor', 'fiat',
         'rosco', 'kayenta', 'keel']


def clean(x):
    return (x or '-').replace('\t', ' ').replace('\n', ' ').strip() or '-'


def key(service, file, line, method, path_template):
    return (service, file, int(line), method, path_template)


def previous_ids(path):
    """{row key: claim number} read back from a delivered endpoints.tsv."""
    out = {}
    for r in csv.DictReader(open(path), delimiter='\t'):
        m = re.match(r'CLAIM-S2-R(\d+) source:spinnaker/\S+ (\S+):(\d+)', r['claim'])
        if not m:
            continue
        out[key(r['service'], m.group(2), m.group(3), r['method'],
                r['path_template'])] = int(m.group(1))
    return out


def main():
    args = sys.argv[1:]
    prev = {}
    if '--stable-from' in args:
        i = args.index('--stable-from')
        prev = previous_ids(args[i + 1])
        del args[i:i + 2]
    out_path = args[0] if args else os.path.join(OUTDIR, 'endpoints.tsv')

    rows = json.load(open(os.path.join(OUTDIR, 'rows.json')))
    rows.sort(key=lambda r: (ORDER.index(r['service']), r['file'], r['line'],
                             r['path_template'], r['method']))
    nxt = max(prev.values(), default=0) + 1
    n, kept, fresh = 0, 0, 0
    with open(out_path, 'w') as f:
        f.write(HEADER + '\n')
        for r in rows:
            n += 1
            k = key(r['service'], r['file'], r['line'], r['method'], r['path_template'])
            if prev:
                if k in prev:
                    num, kept = prev[k], kept + 1
                else:
                    num, nxt, fresh = nxt, nxt + 1, fresh + 1
            else:
                num = n
            claim = 'CLAIM-S2-R%04d source:spinnaker/%s@%s %s:%d' % (
                num, REPO[r['service']], r['version'], r['file'], r['line'])
            rt = r['return_unwrapped']
            if rt in ('void', 'Unit', 'Void'):
                rt = 'void'
            if rt.startswith('RAW_'):
                rt = rt[4:] + '<?>(raw)'
            dep = ' [deprecated]' if r['deprecated'] == 'yes' else ''
            f.write('\t'.join([
                r['service'], r['version'], clean(r['controller']) + dep,
                r['method'], clean(r['path_template']),
                clean(r['path_params']), clean(r['query_params']),
                clean(r['header_params']), clean(r['body_type']),
                clean(rt), clean(r['response_codes']),
                clean(r['content_types']), r['typing'], claim,
            ]) + '\n')
    print('wrote', n, 'rows to', out_path,
          ('(%d ids kept, %d fresh)' % (kept, fresh)) if prev else '')


if __name__ == '__main__':
    main()
