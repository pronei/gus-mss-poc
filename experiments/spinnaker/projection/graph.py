#!/usr/bin/env python3
"""The checker's inputs: loaded copies of the documents, a graph per BOM (the gate) and a graph per pair.

    python3 graph.py catalog [--presence none]        # graph/edges.tsv: every edge of every BOM, globally named
    python3 graph.py bom <bom> [--presence none]      # loaded copies + graph/<presence>/bom-<bom>.yaml
    python3 graph.py pairs [--presence none]          # graph/<presence>/P<NN>.yaml (reads triage/ from the gate)

Why more than one graph. `gus` reads edges globally and every command visits
every edge: `consistent` and the baseline gate inside `check`/`mss` look each
edge up in the provider document at the baseline (a missing endpoint is a hard
error, main.go:1097), and a caller declaration missing at either version
silently degrades the edge to the provider self-diff (Tier 3, main.go:1145).
The edge set is not constant over 50 releases, so one graph cannot serve every
BOM: each BOM gets the graph of its own matched edges, and each pair the edges
matched at both of its BOMs. Everything lives under graph/<presence>/ because a
graph may only name documents below its own directory (graph.go:108-112).

Loaded copies (graph/<presence>/loaded/<bom>/<svc>.yaml) are the extractor's
document with two changes, made on the YAML text so that every other byte is
the extractor's:

1. D3 — each `/_calls` operation that yields an edge is re-keyed to the key the
   checker looks it up under, `filepath.Join("/_calls", provider, <provider
   spelling>)` (main.go:1121; the join cleans, so the extractor's
   `/_calls/echo/` would never be found), marked `x-g3-calls-key-from` with the
   caller's own key. A dispatch row is copied once per concrete controller.
   Caller operations that yield no edge are left out: no edge reaches them, and
   the raw document under docs/ keeps them.
2. D6 — a caller operation marked `x-response-opaque` whose provider returns a
   body at that BOM expects `{}` (the loader's Any, loader.go:462) instead of
   nothing, marked `x-g3-expect-any`. decisions.md records why the caller's side
   is the one changed.
"""
import argparse
import collections
import csv
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import normalize
from common import HERE, PROFILES, SERVICES, WORK, boms, pairs, pin_doc, pins

VERB_ORDER = ['delete', 'get', 'head', 'options', 'patch', 'post', 'put']   # the writer's TreeMap order


# --------------------------------------------------------------------------- YAML text

def _needs_quote(s):
    """Yaml.needsQuote, ported, so re-keyed paths are written the way the extractor writes keys."""
    if s == '' or s in ('true', 'false', 'null', 'yes', 'no', 'on', 'off', '~'):
        return True
    import re
    if re.fullmatch(r'[-+]?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?', s):
        return True
    for c in s:
        if c in ':#{}[],&*!|>\'"%@`\n\t' or ord(c) < 0x20:
            return True
    return s[0] in '-? ' or s[-1] == ' '


def yaml_str(s):
    return json.dumps(s, ensure_ascii=False) if _needs_quote(s) else s


def parse_document(text):
    """(head lines up to and including `paths:`, [[key, [(verb, body lines)]]], tail lines)."""
    lines = text.split('\n')
    if 'paths:' not in lines:
        if 'paths: {}' in lines:
            i = lines.index('paths: {}')
            return lines[:i] + ['paths:'], [], lines[i + 1:]
        raise ValueError('no paths section')
    i = lines.index('paths:')
    j = i + 1
    while j < len(lines) and lines[j].startswith(' '):
        j += 1
    blocks = []
    for ln in lines[i + 1:j]:
        indent = len(ln) - len(ln.lstrip(' '))
        if indent == 2:
            if not ln.endswith(':'):
                raise ValueError('path key line not understood: %r' % ln)
            raw = ln[2:-1]
            blocks.append([json.loads(raw) if raw.startswith('"') else raw, []])
        elif indent == 4:
            if not ln.endswith(':') or not blocks:
                raise ValueError('verb line not understood: %r' % ln)
            blocks[-1][1].append((ln[4:-1], []))
        elif indent >= 6 and blocks and blocks[-1][1]:
            blocks[-1][1][-1][1].append(ln)
        else:
            raise ValueError('line outside an operation: %r' % ln)
    return lines[:i + 1], blocks, lines[j:]


def render_document(head, blocks, tail):
    out = list(head)
    for key, verbs in sorted(blocks, key=lambda b: b[0]):
        out.append('  %s:' % yaml_str(key))
        for verb, body in sorted(verbs, key=lambda v: VERB_ORDER.index(v[0])):
            out.append('    %s:' % verb)
            out.extend(body)
    out.extend(tail)
    return '\n'.join(out)


def expect_any(body):
    """Give an opaque caller operation's 200 the empty schema (Any)."""
    try:
        k = body.index('      responses:')
        k2 = body.index('        "200":', k)
    except ValueError:
        raise ValueError('no responses/"200" in an opaque caller operation')
    n = 0
    while k2 + 1 + n < len(body) and body[k2 + 1 + n].startswith(' ' * 10):
        n += 1
    children = body[k2 + 1:k2 + 1 + n]
    if children != ['          description: ""']:
        raise ValueError('an x-response-opaque operation carries response content: %r' % children[:3])
    return body[:k2 + 1] + ['          description: ""', '          content:', '            application/json:',
                            '              schema: {}'] + body[k2 + 1 + n:]


def _indent(line):
    return len(line) - len(line.lstrip(' '))


def _children(lines, i):
    """(first, end) of the lines nested under lines[i]."""
    j = i + 1
    while j < len(lines) and _indent(lines[j]) > _indent(lines[i]):
        j += 1
    return i + 1, j


def _find(lines, lo, hi, indent, key):
    """Index of the mapping key `key` written at `indent` within [lo, hi), or None."""
    for i in range(lo, hi):
        ln = lines[i]
        if _indent(ln) == indent and (ln[indent:] == key + ':' or ln[indent:].startswith(key + ': ')):
            return i
    return None


def _scalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    return yaml_str(v)


def _literal_schema(value):
    """CallerScan.literal: what a fixed path literal declares about its own type."""
    if value.lower() in ('true', 'false'):
        return ['type: boolean', 'default: %s' % _scalar(value.lower() == 'true')]
    try:
        return ['type: integer', 'format: int64', 'default: %s' % _scalar(int(value))]
    except ValueError:
        return ['type: string', 'default: %s' % _scalar(value)]


def _path_vars(path):
    """[(segment index, segment, [variable names])] for every segment; stops at the first `**`."""
    out = []
    for i, seg in enumerate(path.split('/')):
        if seg == '**':
            break
        out.append((i, seg, re.findall(r'\{([^}:]*)(?::[^}]*)?\}', seg)))
    return out


def path_param_plan(caller_rel, provider_path):
    """D3 on parameters: a path variable is positional on the wire, so the caller's variable at a
    provider variable's position is that variable, whatever the caller calls it; a caller literal
    there is a fixed value. Returns ([(caller name, provider name)], [(provider name, literal)])."""
    renames, fills = [], []
    csegs = {i: (seg, names) for i, seg, names in _path_vars(caller_rel)}
    for i, pseg, pnames in _path_vars(provider_path):
        if not pnames or i not in csegs:
            continue
        cseg, cnames = csegs[i]
        if cnames:
            if len(cnames) == len(pnames):
                renames.extend((c, p) for c, p in zip(cnames, pnames) if c != p)
            continue
        # a literal fills the slot: read each value off the provider's segment template
        rx = '^' + ''.join('(.+?)' if part.startswith('{') else re.escape(part)
                           for part in re.split(r'(\{[^}]*\})', pseg) if part) + '$'
        m = re.match(rx, cseg)
        if m:
            fills.extend(zip(pnames, m.groups()))
    return renames, fills


def align_path_params(body, renames, fills):
    """Apply path_param_plan to one caller operation's lines (indent 6 = the operation's keys)."""
    if not renames and not fills:
        return body
    lines = list(body)
    rb = _find(lines, 0, len(lines), 6, 'requestBody')
    ct = _find(lines, *_children(lines, rb), 8, 'content')
    aj = _find(lines, *_children(lines, ct), 10, 'application/json')
    sc = _find(lines, *_children(lines, aj), 12, 'schema')
    wlo, whi = _children(lines, sc)
    wprops = _find(lines, wlo, whi, 14, 'properties')
    if wprops is None:
        raise ValueError('request wrapper without properties')
    if lines[wprops].endswith('{}'):
        lines[wprops] = ' ' * 14 + 'properties:'
    params = _find(lines, *_children(lines, wprops), 16, 'params')
    if params is None:
        if renames:
            raise ValueError('path variables to rename but no params object')
        insert = _children(lines, wprops)[1]
        lines[insert:insert] = [' ' * 16 + 'params:', ' ' * 18 + 'type: object', ' ' * 18 + 'properties: {}',
                                ' ' * 18 + 'additionalProperties: true']
        params = insert
    plo, phi = _children(lines, params)
    pprops = _find(lines, plo, phi, 18, 'properties')
    names_lo, names_hi = _children(lines, pprops)
    declared = [lines[k][20:-1] for k in range(names_lo, names_hi) if _indent(lines[k]) == 20]
    # All renames at once: {name}->{application} together with {cluster}->{name} is a permutation, not a clash.
    mapping = {}
    for c, p in renames:
        if mapping.get(yaml_str(c), yaml_str(p)) != yaml_str(p):
            raise ValueError('caller path variable %s fills two differently named provider variables' % c)
        mapping[yaml_str(c)] = yaml_str(p)
    missing = [c for c in mapping if c not in declared]
    if missing:
        raise ValueError('caller path variables %s not among its params' % missing)
    final = [mapping.get(n, n) for n in declared]
    if len(set(final)) != len(final):
        raise ValueError('aligning %s collides with a declared parameter (%s)' % (mapping, declared))
    for k in range(names_lo, names_hi):
        if _indent(lines[k]) == 20 and lines[k][20:-1] in mapping:
            lines[k] = ' ' * 20 + mapping[lines[k][20:-1]] + ':'
    preq = _find(lines, *_children(lines, params), 18, 'required')
    if preq is not None:
        rlo, rhi = _children(lines, preq)
        for r in range(rlo, rhi):
            item = lines[r][22:] if lines[r].startswith(' ' * 20 + '- ') else None
            if item in mapping:
                lines[r] = ' ' * 20 + '- ' + mapping[item]
    declared = final
    for p, value in fills:
        if yaml_str(p) in declared:
            continue
        plo, phi = _children(lines, params)
        pprops = _find(lines, plo, phi, 18, 'properties')
        if lines[pprops].endswith('{}'):
            lines[pprops] = ' ' * 18 + 'properties:'
        at = _children(lines, pprops)[1]
        lines[at:at] = [' ' * 20 + yaml_str(p) + ':'] + [' ' * 22 + s for s in _literal_schema(value)]
        plo, phi = _children(lines, params)
        preq = _find(lines, plo, phi, 18, 'required')
        if preq is None:
            ap = _find(lines, plo, phi, 18, 'additionalProperties')
            lines[ap:ap] = [' ' * 18 + 'required:', ' ' * 20 + '- ' + yaml_str(p)]
        else:
            at = _children(lines, preq)[1]
            lines[at:at] = [' ' * 20 + '- ' + yaml_str(p)]
        wlo, whi = _children(lines, sc)
        wreq = _find(lines, wlo, whi, 14, 'required')
        if wreq is None:
            ap = _find(lines, wlo, whi, 14, 'additionalProperties')
            lines[ap:ap] = [' ' * 14 + 'required:', ' ' * 16 + '- params']
        elif ' ' * 16 + '- params' not in lines[slice(*_children(lines, wreq))]:
            at = _children(lines, wreq)[1]
            lines[at:at] = [' ' * 16 + '- params']
    return lines


def loaded_copy(text, edges_from_caller):
    """The document the checker reads for one service at one BOM (see the module docstring)."""
    head, blocks, tail = parse_document(text)
    calls = {}
    kept = []
    for key, verbs in blocks:
        if key.startswith('/_calls/'):
            for verb, body in verbs:
                calls[(key, verb)] = body
        else:
            kept.append([key, list(verbs)])
    new = collections.OrderedDict()
    any_edges = []
    for e in edges_from_caller:
        verb = e['verb'].lower()
        body = calls[(e['caller_path'], verb)]
        marks = ['      x-g3-calls-key-from: %s' % json.dumps(e['caller_path'])]
        caller_rel = e['caller_path'][len('/_calls/' + e['provider']):] or '/'
        renames, fills = path_param_plan(caller_rel, e['path'])
        if renames or fills:
            body = align_path_params(body, renames, fills)
            marks.append('      x-g3-path-params: %s' % json.dumps(
                '; '.join(['{%s} -> {%s}' % rf for rf in renames] + ['%r fills {%s}' % (v, p) for p, v in fills])))
            e.setdefault('aligned', []).extend(['%s->%s' % rf for rf in renames] + ['literal->%s' % p for p, _ in fills])
        if e['opaque'] and e['provider_resp'] != 'none':
            body = expect_any(body)
            marks.append('      x-g3-expect-any: true')
            any_edges.append(e)
        key = normalize.calls_key(e['provider'], e['path'])
        slot = new.setdefault(key, {})
        if verb in slot:
            raise ValueError('two edges re-key onto %s %s' % (verb.upper(), key))
        slot[verb] = marks + body
    blocks_out = kept + [[k, sorted(v.items())] for k, v in new.items()]
    return render_document(head, blocks_out, tail), any_edges


# --------------------------------------------------------------------------- matching, cached

def _match_cache_key(bom, presence):
    h = hashlib.sha256()
    for f in ('normalize.py', 'common.py'):
        with open(os.path.join(HERE, f), 'rb') as fh:
            h.update(fh.read())
    for run in (presence, normalize.KEEP):
        for s in SERVICES:
            h.update(normalize.doc_index(run, s, pins()[bom][s])['sha256'].encode())
    return h.hexdigest()[:24]


def match(bom, presence):
    key = _match_cache_key(bom, presence)
    path = os.path.join(WORK, 'match', presence, '%s-%s.json' % (bom, key))
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    r = normalize.match_bom(bom, presence)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w') as f:
        json.dump(r, f)
    os.replace(path + '.tmp', path)
    return r


def identity(e):
    """An edge across releases: caller, provider, verb and the provider's erased path."""
    return (e['caller'], e['provider'], e['verb'], e['provider_mpath'])


# --------------------------------------------------------------------------- catalog

CATALOG_COLUMNS = ['name', 'caller', 'provider', 'verb', 'provider_mpath', 'boms', 'first', 'last', 'membership',
                   'spellings', 'how', 'caller_opaque', 'collision_boms']


def catalog(presence='none', available=None):
    """{bom: match}, {identity: {bom: edge}}, {identity: name}. Names are global and stable: numbered per
    (caller, provider) in order of the provider's erased path and verb over every BOM."""
    per_bom, ids = {}, collections.defaultdict(dict)
    for b in (available or boms()):
        per_bom[b] = match(b, presence)
        for e in per_bom[b]['edges']:
            ids[identity(e)][b] = e
    names, counter = {}, collections.Counter()
    for i in sorted(ids, key=lambda i: (i[0], i[1], i[3], VERB_ORDER.index(i[2].lower()))):
        counter[(i[0], i[1])] += 1
        names[i] = '%s-%s/%d' % (i[0], i[1], counter[(i[0], i[1])])
    return per_bom, ids, names


def write_catalog(presence='none'):
    per_bom, ids, names = catalog(presence)
    bs = boms()
    rows = []
    for i, name in sorted(names.items(), key=lambda kv: kv[1].split('/')[0] + '/%06d' % int(kv[1].split('/')[1])):
        at = ids[i]
        spell = collections.OrderedDict()
        for b in bs:
            if b in at:
                spell.setdefault(at[b]['path'], []).append(b)
        rows.append({
            'name': name, 'caller': i[0], 'provider': i[1], 'verb': i[2], 'provider_mpath': i[3], 'boms': len(at),
            'first': min(at, key=lambda b: bs.index(b)), 'last': max(at, key=lambda b: bs.index(b)),
            'membership': ''.join('x' if b in at else '.' for b in bs),
            'spellings': ' | '.join('%s @%s..%s' % (p, v[0], v[-1]) if len(v) > 1 else '%s @%s' % (p, v[0]) for p, v in spell.items()),
            'how': ','.join(sorted({at[b]['how'] for b in at})),
            'caller_opaque': ''.join(('o' if at[b]['opaque'] else 't') if b in at else '.' for b in bs),
            'collision_boms': ','.join(b for b in bs if b in at and at[b].get('collision')),
        })
    os.makedirs(os.path.join(HERE, 'graph'), exist_ok=True)
    with open(os.path.join(HERE, 'graph', 'edges.tsv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_COLUMNS, delimiter='\t', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    return per_bom, ids, names


# --------------------------------------------------------------------------- graphs

def render_graph(versions, edges, comment):
    out = ['# %s' % comment, '# generated by experiments/spinnaker/projection/graph.py — do not edit', 'services:']
    for svc in SERVICES:
        out.append('  %s:' % svc)
        for ver, path in versions[svc]:
            out.append('    %s: %s' % (json.dumps(ver), json.dumps(path)))
    out.append('edges:' if edges else 'edges: []')
    for name, e in edges:
        out += ['  - name: %s' % json.dumps(name), '    from: %s' % e['caller'], '    to: %s' % e['provider'],
                '    method: %s' % e['verb'], '    path: %s' % json.dumps(e['path'])]
    return '\n'.join(out) + '\n'


def write_loaded(bom, presence, m):
    """Loaded copies of the nine documents at one BOM; returns the D6 edges."""
    out_dir = os.path.join(HERE, 'graph', presence, 'loaded', bom)
    os.makedirs(out_dir, exist_ok=True)
    by_caller = collections.defaultdict(list)
    for e in m['edges']:
        by_caller[e['caller']].append(e)
    d6 = []
    for svc in SERVICES:
        with open(pin_doc(presence, svc, pins()[bom][svc])) as f:
            text = f.read()
        doc, any_edges = loaded_copy(text, sorted(by_caller[svc], key=lambda e: (e['provider'], e['path'], e['verb'])))
        d6.extend(any_edges)
        target = os.path.join(out_dir, svc + '.yaml')
        with open(target + '.tmp', 'w') as f:
            f.write(doc)
        os.replace(target + '.tmp', target)
    return d6


def write_bom_graph(bom, presence, m, names):
    d6 = write_loaded(bom, presence, m)
    versions = {s: [(bom, 'loaded/%s/%s.yaml' % (bom, s))] for s in SERVICES}
    edges = sorted(((names[identity(e)], e) for e in m['edges']), key=lambda ne: _name_order(ne[0]))
    path = os.path.join(HERE, 'graph', presence, 'bom-%s.yaml' % bom)
    with open(path, 'w') as f:
        f.write(render_graph(versions, edges, 'the consistency gate at BOM %s (%s presence profile): every edge matched at that BOM' % (bom, presence)))
    return path, d6


def _name_order(name):
    head, n = name.rsplit('/', 1)
    return head, int(n)


def baseline_scenario(bom):
    d = os.path.join(HERE, 'scenarios', 'baselines')
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, '%s.yaml' % bom)
    body = ['id: %s' % json.dumps('G-' + bom), 'name: %s' % json.dumps('consistency gate at BOM %s' % bom), 'baseline:']
    body += ['  %s: %s' % (s, json.dumps(bom)) for s in SERVICES]
    body += ['upgrades: {}']
    with open(path, 'w') as f:
        f.write('\n'.join(body) + '\n')
    return path


def gate_exclusions(presence, bom):
    """Edge names with a BREAK at the BOM's consistency gate (triage/<presence>/<bom>.tsv)."""
    path = os.path.join(HERE, 'triage', presence, '%s.tsv' % bom)
    if not os.path.exists(path):
        raise SystemExit('no triage for %s at %s: run gate.py first' % (presence, bom))
    with open(path) as f:
        return {r['edge']: r['category'] for r in csv.DictReader(f, delimiter='\t') if r['excluded'] == 'yes'}


DELTA_COLUMNS = ['pair', 'from', 'to', 'change', 'edge', 'caller', 'provider', 'verb', 'provider_mpath', 'caller_mpath',
                 'provider_has_endpoint_at_other', 'caller_declares_at_other', 'reading']


def _delta_row(nn, a, b, change, i, e, names, idx_other, other_match):
    caller, provider, verb, mpath = i
    has_endpoint = any(op['verb'] == verb and op['mpath'] == mpath for op in idx_other[provider]['provider'])
    declares = any(c['provider'] == provider and c['verb'] == verb and c['mpath'] == e['caller_mpath']
                   for c in idx_other[caller]['client'])
    unmatched = [u['category'] for u in other_match['unmatched'] if u['caller'] == caller and u['provider'] == provider
                 and u['verb'] == verb and u['mpath'] == e['caller_mpath']]
    if change == 'removed':
        if not has_endpoint and not declares:
            reading = 'the endpoint and the call leave together; old callers still call it during the roll (callers first)'
        elif not has_endpoint:
            reading = 'the endpoint leaves while the new caller still declares it (%s at %s)' % (','.join(unmatched) or 'rematched', b)
        elif not declares:
            reading = 'the caller drops the call; the endpoint stays'
        else:
            reading = 'the declaration is paired differently at %s' % b
    else:
        if not has_endpoint and not declares:
            reading = 'a new call to a new endpoint; the new caller against the old provider finds no endpoint (providers first)'
        elif not has_endpoint:
            reading = 'the endpoint arrives for a call the old caller already declared (%s at %s)' % (','.join(unmatched) or 'rematched', a)
        elif not declares:
            reading = 'a new call to an endpoint the old provider already exposes'
        else:
            reading = 'the declaration is paired differently at %s' % a
    return {'pair': 'P' + nn, 'from': a, 'to': b, 'change': change, 'edge': names[i], 'caller': caller, 'provider': provider,
            'verb': verb, 'provider_mpath': mpath, 'caller_mpath': e['caller_mpath'],
            'provider_has_endpoint_at_other': 'yes' if has_endpoint else 'no', 'caller_declares_at_other': 'yes' if declares else 'no',
            'reading': reading}


def write_pair_graphs(presence, provisional=False):
    """graph/<presence>/P<NN>.yaml for every pair, graph/<presence>/pairs.json, and graph/deltas.tsv.
    `provisional`: only the pairs whose two BOMs are extracted, with names over those BOMs (a dry run)."""
    available = None
    if provisional:
        available = [b for b in boms() if all(os.path.exists(pin_doc(r, s, pins()[b][s], 'diag.json'))
                                              for s in SERVICES for r in (presence, normalize.KEEP))]
    per_bom, ids, names = catalog(presence, available=available)
    out_dir = os.path.join(HERE, 'graph', presence)
    accounting, deltas = {}, []
    for nn, a, b in pairs():
        if a not in per_bom or b not in per_bom:
            continue
        A = {identity(e): e for e in per_bom[a]['edges']}
        B = {identity(e): e for e in per_bom[b]['edges']}
        excluded = gate_exclusions(presence, a)
        common = sorted(set(A) & set(B), key=lambda i: _name_order(names[i]))
        respelled = [names[i] for i in common if A[i]['path'] != B[i]['path']]
        gate_out = {names[i]: excluded[names[i]] for i in common if names[i] in excluded}
        in_graph = [i for i in common if names[i] not in gate_out and A[i]['path'] == B[i]['path']]
        versions = {s: [(a, 'loaded/%s/%s.yaml' % (a, s)), (b, 'loaded/%s/%s.yaml' % (b, s))] for s in SERVICES}
        with open(os.path.join(out_dir, 'P%s.yaml' % nn), 'w') as f:
            f.write(render_graph(versions, [(names[i], B[i]) for i in in_graph],
                                 'pair P%s: %s -> %s (%s presence profile): edges matched at both BOMs, less the baseline gate\'s exclusions'
                                 % (nn, a, b, presence)))
        opacity_changes = [names[i] for i in in_graph if A[i]['opaque'] != B[i]['opaque']]
        body_changes = [names[i] for i in in_graph if (A[i]['opaque'] or B[i]['opaque'])
                        and (A[i]['provider_resp'] == 'none') != (B[i]['provider_resp'] == 'none')]
        accounting['P' + nn] = {
            'from': a, 'to': b, 'edges_at_from': len(A), 'edges_at_to': len(B), 'common': len(common),
            'in_graph': len(in_graph), 'excluded_by_gate': gate_out, 'respelled': respelled,
            'added': len(set(B) - set(A)), 'removed': len(set(A) - set(B)),
            'd6_opacity_changes': opacity_changes, 'd6_provider_body_changes': body_changes,
        }
        if presence == 'none':
            idx = {bom: {s: normalize.doc_index(presence, s, pins()[bom][s]) for s in SERVICES} for bom in (a, b)}
            for i in sorted(set(A) - set(B), key=lambda i: _name_order(names[i])):
                deltas.append(_delta_row(nn, a, b, 'removed', i, A[i], names, idx[b], per_bom[b]))
            for i in sorted(set(B) - set(A), key=lambda i: _name_order(names[i])):
                deltas.append(_delta_row(nn, a, b, 'added', i, B[i], names, idx[a], per_bom[a]))
    with open(os.path.join(out_dir, 'pairs.json'), 'w') as f:
        json.dump(accounting, f, indent=1, sort_keys=True)
        f.write('\n')
    if presence == 'none':
        with open(os.path.join(HERE, 'graph', 'deltas.tsv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=DELTA_COLUMNS, delimiter='\t', lineterminator='\n')
            w.writeheader()
            w.writerows(deltas)
    return accounting, deltas


def replay_caller_op(raw_op, e):
    """The loaded copy's caller operation for edge `e`, rebuilt on the parsed form of the extractor's
    operation: path parameters aligned (path_param_plan) and the D6 expect applied. The text edits of
    loaded_copy and this replay must agree; `graph.py verify` checks that they do."""
    import copy
    op = copy.deepcopy(raw_op)
    caller_rel = e['caller_path'][len('/_calls/' + e['provider']):] or '/'
    renames, fills = path_param_plan(caller_rel, e['path'])
    if renames or fills:
        wrapper = op['requestBody']['content']['application/json']['schema']
        props = wrapper.get('properties')
        if not isinstance(props, dict):
            props = wrapper['properties'] = {}
        params = props.setdefault('params', {'type': 'object', 'properties': {}, 'additionalProperties': True})
        mapping = dict(renames)
        params['properties'] = {mapping.get(n, n): s for n, s in (params.get('properties') or {}).items()}
        if 'required' in params:
            params['required'] = [mapping.get(n, n) for n in params['required']]
        for p, value in fills:
            if p in params['properties']:
                continue
            sch = {}
            for line in _literal_schema(value):
                k, v = line.split(': ', 1)
                if v in ('true', 'false'):
                    sch[k] = v == 'true'
                elif re.fullmatch(r'-?[0-9]+', v):
                    sch[k] = int(v)
                elif v.startswith('"'):
                    sch[k] = json.loads(v)
                else:
                    sch[k] = v
            params['properties'][p] = sch
            params.setdefault('required', []).append(p)
            if 'params' not in wrapper.setdefault('required', []):
                wrapper['required'].append('params')
    if e['opaque'] and e['provider_resp'] != 'none':
        op['responses']['200']['content'] = {'application/json': {'schema': {}}}
    return op


def verify_loaded(bom, presence, m):
    """The loaded copies differ from the extractor's documents only as the module docstring says.

    Both files are parsed with the same loader; every provider operation must be equal, and every
    caller operation of an edge must equal the extractor's once the x-g3 marks are dropped and the
    three edits are replayed on the parsed form: the re-key, the path-parameter alignment and the
    D6 expect. Returns a list of problems (empty when faithful)."""
    import copy
    import yaml
    loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
    problems = []
    by_caller = collections.defaultdict(list)
    for e in m['edges']:
        by_caller[e['caller']].append(e)
    for svc in SERVICES:
        with open(pin_doc(presence, svc, pins()[bom][svc])) as f:
            raw = yaml.load(f, Loader=loader)
        with open(os.path.join(HERE, 'graph', presence, 'loaded', bom, svc + '.yaml')) as f:
            loaded = yaml.load(f, Loader=loader)
        for k in raw:
            if k != 'paths' and raw[k] != loaded.get(k):
                problems.append('%s: top-level %s differs' % (svc, k))
        raw_provider = {p: v for p, v in raw['paths'].items() if not p.startswith('/_calls/')}
        loaded_provider = {p: v for p, v in loaded['paths'].items() if not p.startswith('/_calls/')}
        if raw_provider != loaded_provider:
            problems.append('%s: provider operations differ (%d vs %d paths)' % (svc, len(raw_provider), len(loaded_provider)))
        expected_calls = collections.defaultdict(dict)
        for e in by_caller[svc]:
            op = replay_caller_op(raw['paths'][e['caller_path']][e['verb'].lower()], e)
            expected_calls[normalize.calls_key(e['provider'], e['path'])][e['verb'].lower()] = op
        loaded_calls = {}
        for p, item in loaded['paths'].items():
            if p.startswith('/_calls/'):
                loaded_calls[p] = {v: {k: x for k, x in op.items() if not k.startswith('x-g3-')} for v, op in item.items()}
        if set(loaded_calls) != set(expected_calls):
            problems.append('%s: /_calls keys differ: extra %s missing %s' % (
                svc, sorted(set(loaded_calls) - set(expected_calls))[:3], sorted(set(expected_calls) - set(loaded_calls))[:3]))
        for p in set(loaded_calls) & set(expected_calls):
            if loaded_calls[p] != expected_calls[p]:
                problems.append('%s: caller operation %s differs from the replayed edit' % (svc, p))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('catalog')
    p.add_argument('--presence', choices=PROFILES, default='none')
    p = sub.add_parser('bom')
    p.add_argument('bom')
    p.add_argument('--presence', choices=PROFILES, default='none')
    p = sub.add_parser('verify')
    p.add_argument('bom')
    p.add_argument('--presence', choices=PROFILES, default='none')
    p = sub.add_parser('pairs')
    p.add_argument('--presence', choices=PROFILES, default='none')
    p.add_argument('--provisional', action='store_true')
    a = ap.parse_args(argv)
    if a.cmd == 'pairs':
        accounting, deltas = write_pair_graphs(a.presence, a.provisional)
        for pair, r in sorted(accounting.items()):
            print('%s %s->%s: in graph %d (common %d, gate-excluded %d, respelled %d); added %d, removed %d; '
                  'D6 opacity changes %d, provider body changes %d' % (
                      pair, r['from'], r['to'], r['in_graph'], r['common'], len(r['excluded_by_gate']), len(r['respelled']),
                      r['added'], r['removed'], len(r['d6_opacity_changes']), len(r['d6_provider_body_changes'])))
        return 0
    if a.cmd == 'verify':
        problems = verify_loaded(a.bom, a.presence, match(a.bom, a.presence))
        for x in problems:
            print('!!', x)
        print('%s %s: loaded copies %s' % (a.bom, a.presence, 'faithful' if not problems else '%d problems' % len(problems)))
        return 1 if problems else 0
    if a.cmd == 'catalog':
        _, ids, names = write_catalog(a.presence)
        print('%d edge identities over %d BOMs -> graph/edges.tsv' % (len(ids), len(boms())))
        return 0
    if a.cmd == 'bom':
        per_bom, ids, names = catalog(a.presence, available=[a.bom])
        path, d6 = write_bom_graph(a.bom, a.presence, per_bom[a.bom], names)
        baseline_scenario(a.bom)
        print('%s: %d edges, %d opaque caller operations given Any' % (path, len(per_bom[a.bom]['edges']), len(d6)))
        return 0


if __name__ == '__main__':
    sys.exit(main())
