#!/usr/bin/env python3
"""R1(c): longest runs of consecutive releases with retrievable=yes for every pinned service.
Reads ../S3/boms.tsv. Filters artifact_kind != not-pinned. Orders releases by version tuple
(1.x.y then CalVer) and, separately, by release_date. Also reports whether every service is
ever pinned, and runs restricted to container images only."""
import csv, json, sys, collections, os
here = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(here, '..', 'S3', 'boms.tsv')), delimiter='\t'))
def vt(v): return tuple(int(x) for x in v.split('.'))
releases = sorted(set(r['release'] for r in rows), key=vt)
dates = {r['release']: r['release_date'] for r in rows}
by_rel = collections.defaultdict(list)
for r in rows: by_rel[r['release']].append(r)
ever_pinned = collections.Counter(r['service'] for r in rows if r['artifact_kind'] != 'not-pinned')
never = sorted(set(r['service'] for r in rows) - set(ever_pinned))
def ok(rel, kinds):
    pinned = [r for r in by_rel[rel] if r['artifact_kind'] != 'not-pinned']
    return all(r['retrievable'] == 'yes' and r['artifact_kind'] in kinds for r in pinned)
def runs(order, kinds):
    out, cur = [], []
    for rel in order:
        if ok(rel, kinds): cur.append(rel)
        else:
            if cur: out.append(cur)
            cur = []
    if cur: out.append(cur)
    return sorted(out, key=len, reverse=True)
result = {'services_ever_pinned': dict(ever_pinned), 'services_never_pinned': never,
          'releases': len(releases), 'first': releases[0], 'last': releases[-1]}
for label, kinds in [('images-only', {'container-image'}), ('images+maven', {'container-image', 'maven-jar'})]:
    rs = runs(releases, kinds)
    result[label] = [{'from': r[0], 'to': r[-1], 'releases': len(r), 'pairs': len(r) - 1} for r in rs[:4]]
    bad = [rel for rel in releases if not ok(rel, kinds)]
    result[label + '-not-ok'] = {'count': len(bad), 'first': bad[0] if bad else None, 'last': bad[-1] if bad else None}
# by date order (ties broken by version)
date_order = sorted(releases, key=lambda r: (dates[r], vt(r)))
rs = runs(date_order, {'container-image', 'maven-jar'})
result['images+maven-by-date'] = [{'from': r[0], 'to': r[-1], 'releases': len(r), 'pairs': len(r) - 1} for r in rs[:3]]
# minor-line heads only
heads = [r for r in releases if vt(r)[2] == 0]
rs = runs(heads, {'container-image'})
result['images-only-minor-heads'] = [{'from': r[0], 'to': r[-1], 'releases': len(r), 'pairs': len(r) - 1} for r in rs[:3]]
# S3's recommended range 1.30.0..1.38.0
rec = [r for r in releases if vt('1.30.0') <= vt(r) <= vt('1.38.0')]
result['recommended-1.30.0..1.38.0'] = {'releases': len(rec), 'pairs': len(rec) - 1, 'all-images-ok': all(ok(r, {'container-image'}) for r in rec),
    'kayenta-pinned-throughout': all(any(x['service'] == 'kayenta' and x['artifact_kind'] != 'not-pinned' for x in by_rel[r]) for r in rec),
    'minor-heads': [r for r in rec if vt(r)[2] == 0]}
# kayenta first pin
kay = [r for r in releases if any(x['service']=='kayenta' and x['artifact_kind']!='not-pinned' for x in by_rel[r])]
result['kayenta_first_pinned'] = kay[0]; result['kayenta_absent_count'] = len(releases) - len(kay)
# per-row schema sanity
result['retrievable_values'] = dict(collections.Counter(r['retrievable'] for r in rows))
result['artifact_kind_values'] = dict(collections.Counter(r['artifact_kind'] for r in rows))
result['not_pinned_rows_with_retrievable_na'] = sum(1 for r in rows if r['artifact_kind']=='not-pinned' and r['retrievable']=='n/a')
json.dump(result, open(os.path.join(here, 'r1c_boms.json'), 'w'), indent=1)
print(json.dumps(result, indent=1))
