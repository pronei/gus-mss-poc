#!/usr/bin/env python3
"""Scenarios per consecutive BOM pair, and the rollout steps for `gus evolve`.

    python3 scenarios.py      # scenarios/pairs/P<NN>/<batch>.yaml, scenarios/steps/P<NN>/P<NN>-all.yaml, scenarios/pairs.tsv

For each pair (b, b') in version order (D2) there are 46 batches: `all` (the
nine services move to b'), one batch per service, and the 36 pairs of
services; the rest of the mesh stays at b. Ids are `P<NN>-<batch>`, batch names
`all`, `<svc>` and `<svc>+<svc>`.

A service is versioned by BOM in every graph (graph.py), so a batch that names a
service whose pin did not change moves it between two documents of the same
release; `pairs.tsv` records which services change pin at each pair. Scenario
files do not depend on the presence profile — the graph does — and each pair is
judged against its own graph, so the steps for `gus evolve` are one directory
per pair holding that pair's `all` batch; run.sh replays them in version order
through one ledger.
"""
import csv
import itertools
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE, SERVICES, pairs, pins

BATCHES = [('all', list(SERVICES))] + [(s, [s]) for s in SERVICES] + \
          [('%s+%s' % (a, b), [a, b]) for a, b in itertools.combinations(SERVICES, 2)]


def scenario_text(sid, name, base, target, upgraded):
    lines = ['id: %s' % json.dumps(sid), 'name: %s' % json.dumps(name), 'baseline:']
    lines += ['  %s: %s' % (s, json.dumps(base)) for s in SERVICES]
    lines += ['upgrades:'] + ['  %s: %s' % (s, json.dumps(target)) for s in upgraded]
    return '\n'.join(lines) + '\n'


def main():
    root = os.path.join(HERE, 'scenarios')
    for d in ('pairs', 'steps'):
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    rows = []
    for nn, a, b in pairs():
        pdir = os.path.join(root, 'pairs', 'P' + nn)
        os.makedirs(pdir)
        for batch, svcs in BATCHES:
            sid = 'P%s-%s' % (nn, batch)
            with open(os.path.join(pdir, batch + '.yaml'), 'w') as f:
                f.write(scenario_text(sid, '%s -> %s: %s' % (a, b, batch), a, b, svcs))
        sdir = os.path.join(root, 'steps', 'P' + nn)
        os.makedirs(sdir)
        with open(os.path.join(sdir, 'P%s-all.yaml' % nn), 'w') as f:
            f.write(scenario_text('P%s-all' % nn, 'rollout step %s -> %s: every service' % (a, b), a, b, list(SERVICES)))
        changed = [s for s in SERVICES if pins()[a][s] != pins()[b][s]]
        rows.append({'pair': 'P' + nn, 'from': a, 'to': b, 'changed': ','.join(changed), 'changed_count': len(changed),
                     **{s: pins()[a][s] + ('' if pins()[a][s] == pins()[b][s] else ' -> ' + pins()[b][s]) for s in SERVICES}})
    with open(os.path.join(root, 'pairs.tsv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['pair', 'from', 'to', 'changed_count', 'changed'] + list(SERVICES),
                           delimiter='\t', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    print('%d pairs x %d batches = %d scenarios; %d steps' % (len(rows), len(BATCHES), len(rows) * len(BATCHES), len(rows)))


if __name__ == '__main__':
    main()
