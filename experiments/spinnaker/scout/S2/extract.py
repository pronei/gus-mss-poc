#!/usr/bin/env python3
"""Extract Spring MVC/WebFlux endpoints from Spinnaker service source trees."""
import os, re, sys, json, collections

# The ten shallow clones (see memo CLAIM-S2-001 for the tags); override with
# SPINNAKER_CLONES.  Outputs (rows.json, diag.json, census.json, models.json)
# go to S2_OUT, which defaults to the clone root.
ROOT = os.environ.get('SPINNAKER_CLONES',
                      '/private/tmp/claude-501/-Users-pronei-work-faults-lab-service-beds-gus/01d8e507-e2b9-4543-baaa-b8859181517e/scratchpad/spinnaker/S2')
OUTDIR = os.environ.get('S2_OUT', ROOT)

SERVICES = [
    ("gate", "v6.69.0"), ("orca", "v8.64.0"), ("clouddriver", "v5.95.0"),
    ("front50", "v2.41.0"), ("echo", "v2.47.2"), ("igor", "v4.22.0"),
    ("fiat", "v1.57.0"), ("rosco", "v1.26.0"), ("kayenta", "v2.46.0"),
    ("keel", "v1.4.1"),
]

# ------------------------------------------------------- directory pruning ---
# Gradle writes its output to <module>/build, but `build` is also a source
# package name in this corpus (com.netflix.spinnaker.igor.build,
# com.netflix.spinnaker.echo.build), so no directory is pruned for its name
# alone: a directory is output only when it is named `build` AND holds one of
# Gradle's own output subdirectories.
GRADLE_OUTPUT_MARKERS = ('classes', 'libs', 'tmp', 'generated')
PRUNE_ALWAYS = ('.git', 'node_modules')

def is_gradle_output(path):
    return os.path.basename(path) == 'build' and any(
        os.path.isdir(os.path.join(path, m)) for m in GRADLE_OUTPUT_MARKERS)

def prune(dirpath, dirnames):
    """os.walk prune, in place: VCS, node_modules and Gradle output only."""
    dirnames[:] = [d for d in dirnames if d not in PRUNE_ALWAYS
                   and not is_gradle_output(os.path.join(dirpath, d))]

# A file is test source because of the Gradle source set it sits in, never
# because a package on its path is called `test`: the -tck and -test modules
# put main sources in com.netflix.spinnaker.<svc>.test.
TEST_SOURCE_SETS = ('test', 'integration', 'integTest', 'integrationTest',
                    'functionalTest', 'testFixtures', 'compatibility')
TEST_SRC_RX = re.compile(r'(?:^|/)src/(?:%s)(?:/|$)' % '|'.join(TEST_SOURCE_SETS))

def in_test_source_set(path):
    return bool(TEST_SRC_RX.search(path))

# ---------------------------------------------------------------- masking ----
def mask(text):
    """Return a copy with comments and string contents replaced by spaces.
    Length preserved so offsets stay valid against the original."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '/' and i + 1 < n and text[i+1] == '/':
            j = text.find('\n', i)
            j = n if j < 0 else j
            for k in range(i, j): out[k] = ' '
            i = j
        elif c == '/' and i + 1 < n and text[i+1] == '*':
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if text[k] != '\n': out[k] = ' '
            i = j
        elif text.startswith('"""', i) or text.startswith("'''", i):
            q = text[i:i+3]
            j = text.find(q, i + 3)
            j = n if j < 0 else j + 3
            for k in range(i + 3, min(j - 3, n)):
                if text[k] != '\n': out[k] = ' '
            i = j
        elif c == '"' or c == "'":
            j = i + 1
            while j < n:
                if text[j] == '\\': j += 2; continue
                if text[j] == c: j += 1; break
                if text[j] == '\n': break
                j += 1
            for k in range(i + 1, min(j - 1, n) + 1):
                if k < n and text[k] != c and text[k] != '\n': out[k] = ' '
            i = j
        else:
            i += 1
    return ''.join(out)


def strip_comments(text):
    """Blank out // and /* */ comments, preserving length, newlines and strings."""
    out = list(text)
    i, n = 0, len(text)
    TQ1 = chr(34) * 3
    TQ2 = chr(39) * 3
    while i < n:
        c = text[i]
        if c == '/' and i + 1 < n and text[i+1] == '/':
            j = text.find(chr(10), i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = ' '
            i = j
        elif c == '/' and i + 1 < n and text[i+1] == '*':
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if text[k] != chr(10):
                    out[k] = ' '
            i = j
        elif text.startswith(TQ1, i) or text.startswith(TQ2, i):
            q = text[i:i+3]
            j = text.find(q, i + 3)
            i = n if j < 0 else j + 3
        elif c == chr(34) or c == chr(39):
            j = i + 1
            while j < n:
                if text[j] == chr(92):
                    j += 2
                    continue
                if text[j] == c:
                    j += 1
                    break
                if text[j] == chr(10):
                    break
                j += 1
            i = j
        else:
            i += 1
    return ''.join(out)

CLOSER = {'(': ')', '[': ']', '{': '}', '<': '>'}

def match_paren(m, start, open_ch='('):
    """m is masked text, m[start]==open_ch. Return index just past the match."""
    close = CLOSER[open_ch]
    depth = 0
    i = start
    while i < len(m):
        if m[i] == open_ch: depth += 1
        elif m[i] == close:
            depth -= 1
            if depth == 0: return i + 1
        i += 1
    return -1

def split_top(s, seps=(',',)):
    """Split on separators at nesting depth 0 for () [] <> {}."""
    parts, buf = [], []
    dp = dbr = dan = dbc = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == '(': dp += 1
        elif c == ')': dp -= 1
        elif c == '[': dbr += 1
        elif c == ']': dbr -= 1
        elif c == '{': dbc += 1
        elif c == '}': dbc -= 1
        elif c == '<': dan += 1
        elif c == '>':
            if dan > 0: dan -= 1
        if c in seps and dp == dbr == dan == dbc == 0:
            parts.append(''.join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    parts.append(''.join(buf))
    return [p.strip() for p in parts if p.strip()]

# ------------------------------------------------------------ annotations ----
def parse_ann_args(raw):
    """raw = the text inside the annotation parens (original, not masked).
    Returns dict of key -> raw value string; positional value under '_0'."""
    d = {}
    for idx, part in enumerate(split_top(raw)):
        mm = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', part, re.S)
        if mm and not part.startswith('"'):
            d[mm.group(1)] = mm.group(2).strip()
        else:
            d['_%d' % idx] = part
    return d

STRLIT_RE = re.compile(r'"((?:[^"\\]|\\.)*)"' + r"|'((?:[^'\\]|\\.)*)'")

def str_list(v):
    """String literals from an annotation value: '"/a"', '["/a","/b"]', '{"/a"}',
    and Groovy single-quoted literals such as \'/webhooks/{type}\'."""
    if v is None: return []
    out = []
    for mm in STRLIT_RE.finditer(v):
        out.append(mm.group(1) if mm.group(1) is not None else mm.group(2))
    return out

def const_list(v):
    """Extract enum-ish constants: RequestMethod.GET, HttpStatus.OK, MediaType.X, bare ids."""
    if v is None: return []
    return re.findall(r'([A-Za-z_][A-Za-z0-9_.]*)', v)

# --------------------------------------------------------- file scanning -----
MAPPING_ANN = ('RequestMapping', 'GetMapping', 'PostMapping', 'PutMapping',
               'DeleteMapping', 'PatchMapping')
METHOD_OF = {'GetMapping': 'GET', 'PostMapping': 'POST', 'PutMapping': 'PUT',
             'DeleteMapping': 'DELETE', 'PatchMapping': 'PATCH'}

ANN_RE = re.compile(r'@([A-Za-z_][A-Za-z0-9_.]*)')

def annotations_at(text, m, pos):
    """Parse the annotation starting at pos (m[pos]=='@'). Returns (name, args_raw, end)."""
    mm = re.match(r'@([A-Za-z_][A-Za-z0-9_.]*)', m[pos:])
    if not mm: return None
    name = mm.group(1).split('.')[-1]
    end = pos + mm.end()
    j = end
    while j < len(m) and m[j] in ' \t\r\n': j += 1
    args = None
    if j < len(m) and m[j] == '(':
        e = match_paren(m, j, '(')
        if e < 0: return (name, None, end)
        args = text[j+1:e-1]
        end = e
    return (name, args, end)

def preceding_annotations(text, m, pos, limit=4000):
    """Collect annotations immediately before pos (walking backwards over
    whitespace and complete annotations)."""
    res = []
    i = pos
    start_search = max(0, pos - limit)
    while True:
        j = i - 1
        while j >= start_search and m[j] in ' \t\r\n': j -= 1
        if j < start_search: break
        if m[j] == ')':
            # find matching '('
            depth = 0; k = j
            while k >= start_search:
                if m[k] == ')': depth += 1
                elif m[k] == '(':
                    depth -= 1
                    if depth == 0: break
                k -= 1
            if k < start_search: break
            # identifier before '('
            e = k
            while e - 1 >= start_search and m[e-1] in ' \t\r\n': e -= 1
            mm = re.search(r'@([A-Za-z_][A-Za-z0-9_.]*)\s*$', m[start_search:e])
            if not mm: break
            s = start_search + mm.start()
            res.append((mm.group(1).split('.')[-1], text[k+1:j], s))
            i = s
        else:
            mm = re.search(r'@([A-Za-z_][A-Za-z0-9_.]*)\s*$', m[start_search:j+1])
            if not mm: break
            s = start_search + mm.start()
            res.append((mm.group(1).split('.')[-1], None, s))
            i = s
    return list(reversed(res))

CLASS_RE = re.compile(r'\b(?:class|interface)\s+([A-Za-z_][A-Za-z0-9_]*)')
MODIFIERS = ('public', 'private', 'protected', 'static', 'final', 'abstract',
             'open', 'data', 'sealed', 'internal', 'inner', 'strictfp', 'enum')

def back_over_modifiers(m, pos):
    """Walk backwards from pos over whitespace and class modifier keywords."""
    i = pos
    while True:
        j = i
        while j > 0 and m[j-1] in ' \t\r\n': j -= 1
        mm = re.search(r'([A-Za-z_][A-Za-z0-9_]*)$', m[max(0, j-40):j])
        if mm and mm.group(1) in MODIFIERS:
            i = j - len(mm.group(1))
        else:
            return i


def media(v):
    """Media types from a consumes=/produces= annotation value."""
    if v is None: return []
    lits = str_list(v)
    if lits: return lits
    out = []
    for c in const_list(v):
        b = c.split('.')[-1]
        if b.isupper() and b not in ('MediaType',):
            out.append(b)
    return out

def find_classes(text, m):
    """Return list of (name, decl_start, body_start, body_end)."""
    out = []
    for mm in CLASS_RE.finditer(m):
        # skip 'class' inside a word or after '.', or e.g. `::class`
        pre = m[max(0, mm.start()-2):mm.start()]
        if pre.endswith('.') or pre.endswith(':'): continue
        name = mm.group(1)
        # find opening brace of the body
        i = mm.end()
        depth_p = depth_b = depth_a = 0
        body = -1
        while i < len(m):
            c = m[i]
            if c == '(': depth_p += 1
            elif c == ')': depth_p -= 1
            elif c == '[': depth_b += 1
            elif c == ']': depth_b -= 1
            elif c == '<': depth_a += 1
            elif c == '>' and depth_a > 0: depth_a -= 1
            elif c == '{' and depth_p == depth_b == 0:
                body = i; break
            elif c == ';' and depth_p == depth_b == 0:
                break
            i += 1
        if body < 0: continue
        end = match_paren(m, body, '{')
        if end < 0: end = len(m)
        out.append((name, mm.start(), body, end))
    return out

# ------------------------------------------------------------- type utils ----
WRAPPERS = ('ResponseEntity', 'Mono', 'Flux', 'DeferredResult', 'Callable',
            'CompletableFuture', 'ListenableFuture', 'HttpEntity')

def strip_generics_name(t):
    t = t.strip()
    i = t.find('<')
    return (t[:i].strip() if i >= 0 else t)

def inner_generic(t):
    t = t.strip()
    i = t.find('<')
    if i < 0: return None
    j = t.rfind('>')
    if j < i: return None
    return t[i+1:j].strip()

def unwrap(t):
    """Unwrap reactive/servlet wrappers. Returns (unwrapped, wrappers_used)."""
    used = []
    t = t.strip()
    for _ in range(6):
        base = strip_generics_name(t).split('.')[-1]
        if base in WRAPPERS:
            used.append(base)
            inner = inner_generic(t)
            if inner is None:
                t = 'RAW_' + base
                break
            parts = split_top(inner)
            t = parts[0].strip() if parts else 'Object'
        else:
            break
    return t.strip(), used

UNTYPED_BASES = {'Map', 'HashMap', 'LinkedHashMap', 'TreeMap', 'SortedMap',
                 'Object', 'Any', 'JsonNode', 'ObjectNode', 'ArrayNode',
                 'def', 'Properties', 'MultiValueMap', 'LinkedMultiValueMap',
                 'Serializable', 'RAW_ResponseEntity', 'RAW_Mono', 'RAW_Flux',
                 'RAW_DeferredResult', 'RAW_Callable', 'RAW_CompletableFuture',
                 'RAW_HttpEntity'}
CONTAINERS = {'List', 'Collection', 'Set', 'Iterable', 'ArrayList', 'HashSet',
              'LinkedHashSet', 'SortedSet', 'TreeSet', 'Optional', 'Stream',
              'Page', 'Array', 'MutableList', 'MutableSet', 'MutableCollection'}
NONE_TYPES = {'void', 'Unit', 'Void', 'null'}
PRIMITIVE_OK = {'String', 'Integer', 'int', 'Long', 'long', 'Boolean', 'boolean',
                'Double', 'double', 'Float', 'float', 'Number', 'BigDecimal',
                'BigInteger', 'byte', 'byte[]', 'Date', 'Instant', 'UUID',
                'CharSequence', 'Resource', 'InputStreamResource', 'Short'}


MAPSUB_CACHE = {}
CUR_SCOPE = ['']          # service being processed; set in process_file

def lookup(name, scope=None):
    """Resolve a simple type name to source files, preferring the current
    service, then kork. Returns [] when the name is not defined in either."""
    scope = scope or CUR_SCOPE[0]
    out = TYPE_INDEX.get((scope, name), [])
    if not out:
        out = TYPE_INDEX.get(('kork', name), [])
    return out[:3]

def class_header(txt, name):
    """Return the text of the class declaration header for `name`, or None."""
    mm = re.search(r'\b(?:class|interface|object)\s+%s\b' % re.escape(name), txt)
    if not mm: return None
    i = mm.end(); dp = db = da = 0
    while i < len(txt):
        c = txt[i]
        if c == '(': dp += 1
        elif c == ')': dp -= 1
        elif c == '[': db += 1
        elif c == ']': db -= 1
        elif c == '<': da += 1
        elif c == '>' and da > 0: da -= 1
        elif c in '{;' and dp == db == da == 0: break
        i += 1
    return txt[mm.end():i]

MAP_IMPLS = ('Map', 'HashMap', 'LinkedHashMap', 'TreeMap', 'AbstractMap',
             'ConcurrentHashMap', 'ConcurrentSkipListMap', 'EnumMap')

def supertypes(txt, name):
    hdr = class_header(txt, name)
    if hdr is None: return []
    out = []
    mm = re.search(r'\bextends\s+([A-Za-z0-9_.]+)', hdr)
    if mm: out.append(mm.group(1).split('.')[-1])
    mm = re.search(r'\bimplements\s+([A-Za-z0-9_.<>,\s]+)$', hdr)
    if mm:
        for t in split_top(mm.group(1)):
            out.append(strip_generics_name(t).split('.')[-1])
    # Kotlin: supertype list after the ':' that follows the primary constructor
    kt = re.search(r'(?:\)|>)\s*:\s*([A-Za-z0-9_.<>,\s()]+)$', hdr) or \
         re.search(r'^\s*:\s*([A-Za-z0-9_.<>,\s()]+)$', hdr)
    if kt:
        for t in split_top(kt.group(1)):
            out.append(strip_generics_name(t.split('(')[0]).split('.')[-1])
    return [o for o in out if o]

def is_map_subclass(name, depth=0, scope=None):
    """True if the named type transitively extends a java.util.Map implementation."""
    if not name: return False
    base = strip_generics_name(name).split('.')[-1]
    if base in MAP_IMPLS: return True
    if depth > 4: return False
    scope = scope or CUR_SCOPE[0]
    key = (scope, base)
    if key in MAPSUB_CACHE: return MAPSUB_CACHE[key]
    MAPSUB_CACHE[key] = False
    for path in lookup(base, scope):
        try:
            with open(path, 'r', errors='replace') as f: txt = f.read()
        except OSError: continue
        for sup in supertypes(txt, base):
            if sup in MAP_IMPLS or is_map_subclass(sup, depth + 1, scope):
                MAPSUB_CACHE[key] = True
                return True
    return MAPSUB_CACHE[key]

def classify_type(t):
    """Return one of none / untyped / raw / typed, plus the base name."""
    if t is None: return ('none', None)
    t = t.strip()
    if t == '' or t in NONE_TYPES: return ('none', t)
    base = strip_generics_name(t).split('.')[-1]
    if base in NONE_TYPES: return ('none', base)
    if base in UNTYPED_BASES: return ('untyped', base)
    if base in CONTAINERS:
        inner = inner_generic(t)
        if inner is None:
            return ('raw', base)
        parts = split_top(inner)
        sub = classify_type(parts[-1] if parts else 'Object')
        if sub[0] == 'none': return ('typed', base)
        return (sub[0], base + '<' + sub[1] + '>' if sub[1] else base)
    if base in ('?', '*'): return ('untyped', base)
    if base not in PRIMITIVE_OK and is_map_subclass(base): return ('untyped', base + '(Map subclass)')
    return ('typed', base)

# ------------------------------------------ type index for @JsonTypeInfo -----
TYPE_INDEX = {}      # simple name -> list of file paths
POLY_CACHE = {}

def build_type_index(repos):
    for repo in repos:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, repo)):
            prune(dirpath, dirnames)
            if in_test_source_set(dirpath): continue
            for fn in filenames:
                if not fn.endswith(('.java', '.groovy', '.kt')): continue
                name = fn.rsplit('.', 1)[0]
                TYPE_INDEX.setdefault((repo, name), []).append(os.path.join(dirpath, fn))
                # nested/companion classes declared inside the file
                try:
                    with open(os.path.join(dirpath, fn), 'r', errors='replace') as f:
                        txt = f.read()
                except OSError:
                    continue
                for mm in re.finditer(r'\b(?:class|interface)\s+([A-Z][A-Za-z0-9_]*)', txt):
                    TYPE_INDEX.setdefault((repo, mm.group(1)), []).append(os.path.join(dirpath, fn))


def class_body(txt, name):
    """Return (annotations_text_before_decl, body_text) for class `name`, or None."""
    m2 = mask(txt)
    for mm in re.finditer(r'\b(?:class|interface|object|enum)\s+%s\b' % re.escape(name), m2):
        i = mm.end(); dp = db = da = 0; body = -1
        while i < len(m2):
            c = m2[i]
            if c == '(': dp += 1
            elif c == ')': dp -= 1
            elif c == '[': db += 1
            elif c == ']': db -= 1
            elif c == '<': da += 1
            elif c == '>' and da > 0: da -= 1
            elif c == '{' and dp == db == da == 0: body = i; break
            elif c == ';' and dp == db == da == 0: break
            i += 1
        if body < 0: continue
        e = match_paren(m2, body, '{')
        if e < 0: e = len(txt)
        ds = back_over_modifiers(m2, mm.start())
        anns = [a for a in preceding_annotations(txt, m2, ds)]
        annstr = ' '.join('@' + a[0] + '(' + (a[1] or '') + ')' for a in anns)
        # primary-constructor parameters count as fields in Kotlin
        ctor = txt[mm.end():body]
        return (annstr, ctor + txt[body:e])
    return None

FIELD_RE = [
    re.compile(r'\b(?:val|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Za-z_][A-Za-z0-9_.<>, \?\[\]]*)'),
    re.compile(r'^[ \t]*(?:@\w+(?:\([^)]*\))?[ \t\r\n]*)*(?:public|private|protected)?[ \t]*(?:static[ \t]+)?(?:final[ \t]+)?([A-Z][A-Za-z0-9_.]*(?:<[^;=\n]*>)?)[ \t]+[a-z_][A-Za-z0-9_]*[ \t]*[;=]', re.M),
]

def field_types(body):
    refs = set()
    for rx in FIELD_RE:
        for mm in rx.finditer(body):
            for tok in re.findall(r'[A-Z][A-Za-z0-9_]*', mm.group(1)):
                refs.add(tok)
    return refs

SKIP_TYPES = set(list(UNTYPED_BASES) + list(CONTAINERS) + list(PRIMITIVE_OK) +
                 list(NONE_TYPES) + ['Logger', 'ObjectMapper', 'Clock', 'Class',
                 'Exception', 'RuntimeException', 'Registry', 'Id', 'Counter',
                 'Duration', 'Pattern', 'URI', 'URL', 'Charset', 'File'])


MIXIN_MAP = {}          # (service, target simple name) -> mixin simple name
MIXIN_SRC = {}

def build_mixin_map(repos):
    rx1 = re.compile(r'(?:addMixIn|setMixInAnnotations?)\s*\(\s*([A-Za-z0-9_.]+)\.class\s*,\s*([A-Za-z0-9_.]+)\.class', re.S)
    rx2 = re.compile(r'setMixInAnnotations?\s*<\s*([A-Za-z0-9_.]+)[^,>]*,\s*([A-Za-z0-9_.]+)')
    for repo in repos:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, repo)):
            prune(dirpath, dirnames)
            if in_test_source_set(dirpath): continue
            for fn in filenames:
                if not fn.endswith(('.java', '.groovy', '.kt')): continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, 'r', errors='replace') as f: txt = f.read()
                except OSError: continue
                if 'MixIn' not in txt: continue
                for rx in (rx1, rx2):
                    for mm in rx.finditer(txt):
                        tgt = mm.group(1).split('.')[-1]
                        mix = mm.group(2).split('.')[-1]
                        MIXIN_MAP[(repo, tgt)] = mix
                        MIXIN_SRC[(repo, tgt)] = os.path.relpath(fp, ROOT)

# keel declares polymorphism for these six types with no annotation at all, via
# KeelApiAnnotationIntrospector.findTypeResolver
# (keel-core/src/main/kotlin/com/netflix/spinnaker/keel/jackson/KeelApiModule.kt:104-125)
INTROSPECTOR_POLY = {
 ('keel', 'Constraint'), ('keel', 'ConstraintStateAttributes'),
 ('keel', 'DeliveryArtifact'), ('keel', 'SortingStrategy'),
 ('keel', 'Verification'), ('keel', 'PostDeployAction'),
}

POLY_WITNESS = {}

def is_polymorphic(type_name, depth=5, budget=400):
    """True if the named type, a supertype, or a transitively declared field type
    carries @JsonTypeInfo. Class-scoped: only the named class's own annotations
    and body are inspected, never the rest of its file."""
    if not type_name: return False
    scope = CUR_SCOPE[0]
    roots = [t for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', type_name)
             if t and t[0].isupper() and t not in SKIP_TYPES]
    if not roots: return False
    key = (scope, type_name)
    if key in POLY_CACHE: return POLY_CACHE[key]
    POLY_CACHE[key] = False
    seen, frontier, n = set(), list(roots), 0
    trail = {r: r for r in roots}
    for _ in range(depth):
        nxt = []
        for name in frontier:
            if name in seen or name in SKIP_TYPES: continue
            seen.add(name); n += 1
            if n > budget: break
            if (scope, name) in INTROSPECTOR_POLY:
                POLY_CACHE[key] = True
                POLY_WITNESS[key] = trail.get(name, name) + '(introspector)'
                return True
            targets = [name]
            mix = MIXIN_MAP.get((scope, name))
            if mix: targets.append(mix)
            for tname in targets:
                for path in lookup(tname, scope):
                    try:
                        with open(path, 'r', errors='replace') as f: txt = f.read()
                    except OSError: continue
                    cb = class_body(txt, tname)
                    if cb is None: continue
                    annstr, body = cb
                    if '@JsonTypeInfo' in annstr or '@JsonSubTypes' in annstr:
                        POLY_CACHE[key] = True
                        POLY_WITNESS[key] = trail.get(name, name) + ('(mixin ' + tname + ')' if tname != name else '')
                        return True
                    for sup in supertypes(txt, tname):
                        if sup not in trail: trail[sup] = trail.get(name, name) + '>' + sup
                        nxt.append(sup)
                    for ft in field_types(body):
                        if ft not in trail: trail[ft] = trail.get(name, name) + '>' + ft
                        nxt.append(ft)
        if n > budget: break
        frontier = nxt
    return False


STATUS_CODE = {
 'OK':'200','CREATED':'201','ACCEPTED':'202','NO_CONTENT':'204','RESET_CONTENT':'205',
 'PARTIAL_CONTENT':'206','MULTI_STATUS':'207','MOVED_PERMANENTLY':'301','FOUND':'302',
 'SEE_OTHER':'303','NOT_MODIFIED':'304','TEMPORARY_REDIRECT':'307','PERMANENT_REDIRECT':'308',
 'BAD_REQUEST':'400','UNAUTHORIZED':'401','PAYMENT_REQUIRED':'402','FORBIDDEN':'403',
 'NOT_FOUND':'404','METHOD_NOT_ALLOWED':'405','NOT_ACCEPTABLE':'406','CONFLICT':'409',
 'GONE':'410','PRECONDITION_FAILED':'412','PAYLOAD_TOO_LARGE':'413','UNSUPPORTED_MEDIA_TYPE':'415',
 'UNPROCESSABLE_ENTITY':'422','TOO_MANY_REQUESTS':'429','INTERNAL_SERVER_ERROR':'500',
 'NOT_IMPLEMENTED':'501','BAD_GATEWAY':'502','SERVICE_UNAVAILABLE':'503','GATEWAY_TIMEOUT':'504',
}
MIME = {
 'APPLICATION_JSON_VALUE':'application/json','APPLICATION_JSON_UTF8_VALUE':'application/json;charset=UTF-8',
 'APPLICATION_YAML_VALUE':'application/x-yaml','TEXT_PLAIN_VALUE':'text/plain',
 'TEXT_HTML_VALUE':'text/html','TEXT_EVENT_STREAM_VALUE':'text/event-stream',
 'APPLICATION_OCTET_STREAM_VALUE':'application/octet-stream','ALL_VALUE':'*/*',
 'MULTIPART_FORM_DATA_VALUE':'multipart/form-data','APPLICATION_FORM_URLENCODED_VALUE':'application/x-www-form-urlencoded',
 'APPLICATION_XML_VALUE':'application/xml','IMAGE_PNG_VALUE':'image/png','APPLICATION_PDF_VALUE':'application/pdf',
 'APPLICATION_NDJSON_VALUE':'application/x-ndjson','APPLICATION_STREAM_JSON_VALUE':'application/stream+json',
}
def mime(x): return MIME.get(x, x)
def statuscode(x): return STATUS_CODE.get(x, x)

# Hand-resolved Kotlin expression-body return types (INFERRED -> declared type of
# the delegate). Keyed by (service, file basename, method name[@line]).
INFERRED_OVERRIDE = {
 ('keel','AdminController.kt','getPausedApplications'): 'List<String>',
 ('keel','AdminController.kt','getManagedApplications@45'): 'Collection<ApplicationSummary>',
 ('keel','AdminController.kt','getManagedApplications@157'): 'ExecutionSummary',
 ('keel','EnvironmentController.kt','list'): 'List<EnvironmentView>',
}

# ------------------------------------------------------------ param parse ----
PARAM_ANNS = ('RequestParam', 'PathVariable', 'RequestHeader', 'RequestBody',
              'RequestPart', 'ModelAttribute', 'RequestAttribute', 'CookieValue',
              'MatrixVariable')

def parse_params(raw, lang):
    """Return list of dicts describing each parameter."""
    out = []
    for p in split_top(raw):
        anns = []
        rest = p
        while True:
            rest = rest.lstrip()
            if not rest.startswith('@'): break
            mm = re.match(r'@([A-Za-z_][A-Za-z0-9_.]*)', rest)
            name = mm.group(1).split('.')[-1]
            k = mm.end()
            while k < len(rest) and rest[k] in ' \t\r\n': k += 1
            args = None
            if k < len(rest) and rest[k] == '(':
                e = match_paren(rest, k, '(')
                if e < 0: e = len(rest)
                args = rest[k+1:e-1]
                k = e
            anns.append((name, args))
            rest = rest[k:]
        rest = rest.strip()
        rest = re.sub(r'^(final|vararg)\s+', '', rest)
        pname, ptype = None, None
        if lang == 'kt':
            mm = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)(?:\s*=\s*.*)?$', rest, re.S)
            if mm:
                pname, ptype = mm.group(1), mm.group(2).strip()
        if ptype is None:
            # Java/Groovy:  Type name [= default]
            body = split_top(rest, seps=('=',))[0].strip() if '=' in rest else rest
            mm = re.match(r'^(.*[\s>\]])([A-Za-z_][A-Za-z0-9_]*)$', body, re.S)
            if mm:
                ptype, pname = mm.group(1).strip(), mm.group(2)
            else:
                mm2 = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)$', body)
                if mm2:
                    ptype, pname = 'def', mm2.group(1)
                else:
                    ptype, pname = body, ''
        out.append({'anns': anns, 'name': pname or '', 'type': (ptype or '').strip(), 'raw': p})
    return out

def ann_get(args, keys, positional=True):
    if args is None: return None
    d = parse_ann_args(args)
    for k in keys:
        if k in d: return d[k]
    if positional and '_0' in d: return d['_0']
    return None

def is_required(args, lang, ptype):
    if args is not None:
        d = parse_ann_args(args)
        if 'required' in d:
            return 'false' not in d['required']
        if 'defaultValue' in d:
            return False
    if lang == 'kt' and ptype.rstrip().endswith('?'):
        return False
    return True

# ------------------------------------------------------------------ main ----
def norm_path(prefix, sub):
    parts = []
    for x in (prefix, sub):
        if x is None: continue
        x = x.strip()
        if x in ('', '/'): continue
        parts.append(x.strip('/'))
    p = '/' + '/'.join([x for x in parts if x])
    return p if p != '' else '/'

PATHVAR_RE = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)')

def process_file(service, version, path, rows, diag):
    with open(path, 'r', errors='replace') as f:
        text = strip_comments(f.read())
    lang = path.rsplit('.', 1)[1]
    CUR_SCOPE[0] = service
    m = mask(text)
    line_of = [0]
    for i, ch in enumerate(text):
        pass
    # cheap line lookup
    nl = [i for i, c in enumerate(text) if c == '\n']
    import bisect
    def lineno(off): return bisect.bisect_right(nl, off) + 1

    classes = find_classes(text, m)
    # controller classes: those with @RestController / @Controller
    ctrl = []
    for (name, ds, bs, be) in classes:
        anns = preceding_annotations(text, m, back_over_modifiers(m, ds))
        annnames = [a[0] for a in anns]
        if 'RestController' in annnames or 'Controller' in annnames:
            prefixes = []
            ccons, cprod = [], []
            for (an, ar, _) in anns:
                if an == 'RequestMapping':
                    v = ann_get(ar, ['value', 'path'])
                    prefixes = str_list(v) or ['']
                    ccons = media(ann_get(ar, ['consumes'], positional=False))
                    cprod = media(ann_get(ar, ['produces'], positional=False))
            if not prefixes: prefixes = ['']
            cdep = 'Deprecated' in annnames
            ctrl.append({'name': name, 'bs': bs, 'be': be, 'prefixes': prefixes,
                         'deprecated': cdep, 'consumes': ccons, 'produces': cprod})
    if not ctrl: return

    rel = os.path.relpath(path, ROOT)
    rel = rel.split('/', 1)[1] if '/' in rel else rel

    # find all method-level mapping annotations
    for mm in re.finditer(r'@(RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\b', m):
        pos = mm.start()
        owner = None
        for c in ctrl:
            if c['bs'] < pos < c['be']:
                if owner is None or c['bs'] > owner['bs']: owner = c
        if owner is None: continue   # class-level annotation, already consumed
        parsed = annotations_at(text, m, pos)
        if not parsed: continue
        annname, annargs, aend = parsed
        # gather all annotations in this block (from first '@' of the run to signature)
        blk = []
        i = aend
        while True:
            j = i
            while j < len(m) and m[j] in ' \t\r\n': j += 1
            if j < len(m) and m[j] == '@':
                pa = annotations_at(text, m, j)
                if not pa: break
                blk.append(pa)
                i = pa[2]
            else:
                break
        pre = preceding_annotations(text, m, pos)
        allanns = [(a, b) for (a, b, _) in pre] + [(annname, annargs)] + [(a, b) for (a, b, _) in blk]

        sig_start = i
        # find the parameter-list '('
        k = sig_start
        depth_a = 0
        while k < len(m):
            c = m[k]
            if c == '<': depth_a += 1
            elif c == '>' and depth_a > 0: depth_a -= 1
            elif c == '(' and depth_a == 0: break
            elif c in '{};' and depth_a == 0:
                k = -1; break
            k += 1
        if k < 0 or k >= len(m):
            diag.append(('nosig', service, rel, lineno(pos))); continue
        pend = match_paren(m, k, '(')
        if pend < 0:
            diag.append(('noparen', service, rel, lineno(pos))); continue
        head = text[sig_start:k]
        params_raw = text[k+1:pend-1]
        tail = text[pend:pend + 400]
        mtail = m[pend:pend + 400]

        # method name + return type
        head_clean = head
        head_clean = re.sub(r'@[A-Za-z_][A-Za-z0-9_.]*(\([^)]*\))?', ' ', head_clean)
        head_clean = re.sub(r'\b(public|private|protected|static|final|synchronized|abstract|default|open|override|suspend|inline|operator|native|strictfp)\b', ' ', head_clean)
        head_clean = head_clean.strip()
        mname = ''
        rtype = ''
        if lang == 'kt':
            mmk = re.search(r'\bfun\s+(?:<[^>]*>\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*$', head_clean)
            if mmk: mname = mmk.group(1)
            t2 = mtail.lstrip()
            if t2.startswith(':'):
                mr = re.match(r'^\s*:\s*(.+?)\s*(?:\{|=[^=]|$)', mtail, re.S)
                rtype = mr.group(1).strip() if mr else 'INFERRED'
                rtype = re.sub(r'\s+', ' ', rtype)
            elif t2.startswith('{'):
                rtype = 'Unit'
            elif t2.startswith('='):
                rtype = 'INFERRED'
            else:
                rtype = 'INFERRED'
        else:
            mmj = re.search(r'([A-Za-z_][A-Za-z0-9_]*)\s*$', head_clean)
            if mmj:
                mname = mmj.group(1)
                rt = head_clean[:mmj.start()].strip()
                rt = re.sub(r'^<[^>]*>', '', rt).strip()
                rtype = rt if rt else 'def'
        if not mname:
            diag.append(('noname', service, rel, lineno(pos), head_clean[:60])); continue

        # HTTP methods
        if annname in METHOD_OF:
            methods = [METHOD_OF[annname]]
        else:
            mv = ann_get(annargs, ['method'], positional=False)
            methods = []
            for cst in const_list(mv):
                b = cst.split('.')[-1]
                if b in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS', 'TRACE'):
                    methods.append(b)
            if not methods: methods = ['ANY']
        # paths
        pv = ann_get(annargs, ['value', 'path'])
        subs = str_list(pv)
        if not subs: subs = ['']
        # content types
        cons = media(ann_get(annargs, ['consumes'], positional=False)) or owner['consumes']
        prod = media(ann_get(annargs, ['produces'], positional=False)) or owner['produces']

        # params
        plist = parse_params(params_raw, lang)
        path_params, query_params, header_params = [], [], []
        body_type = None
        for p in plist:
            annd = {a[0]: a[1] for a in p['anns']}
            if 'PathVariable' in annd:
                nm = None
                v = ann_get(annd['PathVariable'], ['value', 'name'])
                nm = (str_list(v) or [None])[0] or p['name']
                path_params.append(nm)
            elif 'RequestParam' in annd:
                v = ann_get(annd['RequestParam'], ['value', 'name'])
                nm = (str_list(v) or [None])[0] or p['name']
                req = is_required(annd['RequestParam'], lang, p['type'])
                dv = ann_get(annd['RequestParam'], ['defaultValue'], positional=False)
                tag = 'required' if req else 'optional'
                if dv is not None:
                    tag = 'optional'
                query_params.append('%s:%s' % (nm, tag))
            elif 'RequestHeader' in annd:
                v = ann_get(annd['RequestHeader'], ['value', 'name'])
                nm = (str_list(v) or [None])[0] or p['name']
                req = is_required(annd['RequestHeader'], lang, p['type'])
                header_params.append('%s:%s' % (nm, 'required' if req else 'optional'))
            elif 'RequestBody' in annd:
                body_type = p['type']
            elif 'RequestPart' in annd:
                body_type = (body_type or '') + ('+' if body_type else '') + 'multipart:' + p['type']
            elif 'ModelAttribute' in annd:
                body_type = p['type']
            elif strip_generics_name(p['type']).split('.')[-1] in ('MultipartFile',):
                body_type = 'multipart:MultipartFile'

        # response status
        codes = []
        for (an, ar) in allanns:
            if an == 'ResponseStatus':
                for cst in const_list(ar or ''):
                    b = cst.split('.')[-1]
                    if b not in ('HttpStatus', 'value', 'code', 'reason') and b.isupper():
                        codes.append(b)
        deprecated = any(a[0] == 'Deprecated' for a in allanns) or owner['deprecated']
        ln0 = lineno(pos)

        # body statuses (ResponseEntity built inline)
        body_start = -1
        bb = m.find('{', pend)
        if bb >= 0 and bb - pend < 300:
            be2 = match_paren(m, bb, '{')
            if be2 > 0:
                mbody = text[bb:be2]
                for cst in set(re.findall(r'HttpStatus\.([A-Z_0-9]+)', mbody)):
                    codes.append(cst)
                for pat, code in (('ResponseEntity.ok', 'OK'), ('.noContent()', 'NO_CONTENT'),
                                  ('.notFound()', 'NOT_FOUND'), ('.badRequest()', 'BAD_REQUEST'),
                                  ('.created(', 'CREATED'), ('.accepted()', 'ACCEPTED')):
                    if pat in mbody: codes.append(code)
        codes = sorted(set(statuscode(c) for c in codes))

        if rtype == 'INFERRED':
            bn = os.path.basename(rel)
            for key in ('%s@%d' % (mname, ln0), mname):
                if (service, bn, key) in INFERRED_OVERRIDE:
                    rtype = INFERRED_OVERRIDE[(service, bn, key)]; break
        # return type
        rt_un, wrappers = unwrap(rtype) if rtype != 'INFERRED' else ('INFERRED', [])
        bt_un, bwrap = (unwrap(body_type) if body_type else (None, []))

        rk, rbase = classify_type(rt_un if rt_un != 'INFERRED' else None)
        if rt_un == 'INFERRED': rk, rbase = 'inferred', 'INFERRED'
        bk, bbase = classify_type(bt_un)
        if body_type and body_type.startswith('multipart:'):
            bk, bbase = 'typed', 'multipart'

        poly = False
        if rk == 'typed' and rbase: poly = poly or is_polymorphic(rt_un)
        if bk == 'typed' and bbase: poly = poly or is_polymorphic(bt_un)

        if bk == 'untyped' and rk == 'untyped': typing = 'untyped-both'
        elif bk == 'untyped': typing = 'untyped-body'
        elif rk == 'untyped': typing = 'untyped-return'
        elif poly: typing = 'polymorphic'
        elif bk == 'raw' or rk == 'raw': typing = 'raw-generic'
        elif rk == 'inferred': typing = 'unknown-return'
        else: typing = 'typed'

        ln = lineno(pos)
        for pfx in owner['prefixes']:
            for sub in subs:
                fp = norm_path(pfx, sub)
                pvars = PATHVAR_RE.findall(fp)
                for httpm in methods:
                    rows.append({
                        'service': service, 'version': version,
                        'controller': owner['name'] + '.' + mname,
                        'method': httpm, 'path_template': fp,
                        'path_params': ','.join(pvars) if pvars else '-',
                        'query_params': ','.join(query_params) if query_params else '-',
                        'header_params': ','.join(header_params) if header_params else '-',
                        'body_type': (body_type or '-'),
                        'return_type': (rtype or '-'),
                        'return_unwrapped': rt_un,
                        'response_codes': ','.join(codes) if codes else '-',
                        'content_types': (('consumes=' + '|'.join(mime(c) for c in cons)) if cons else '') +
                                         (';' if cons and prod else '') +
                                         (('produces=' + '|'.join(mime(c) for c in prod)) if prod else '') or '-',
                        'typing': typing,
                        'deprecated': 'yes' if deprecated else 'no',
                        'file': rel, 'line': ln,
                        'lang': lang,
                        'rk': rk, 'bk': bk, 'poly': poly,
                        'declared_pathvars': ','.join(path_params) if path_params else '-',
                    })

def main():
    build_type_index([s for s, _ in SERVICES] + ['kork'])
    build_mixin_map([s for s, _ in SERVICES] + ['kork'])
    rows, diag = [], []
    for service, version in SERVICES:
        base = os.path.join(ROOT, service)
        for dirpath, dirnames, filenames in os.walk(base):
            prune(dirpath, dirnames)
            if in_test_source_set(dirpath): continue
            for fn in filenames:
                if not fn.endswith(('.java', '.groovy', '.kt')): continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, 'r', errors='replace') as f:
                        head = f.read()
                except OSError: continue
                if '@RestController' not in head and '@Controller' not in head: continue
                process_file(service, version, p, rows, diag)
    with open(os.path.join(OUTDIR, 'rows.json'), 'w') as f:
        json.dump(rows, f, indent=1)
    with open(os.path.join(OUTDIR, 'diag.json'), 'w') as f:
        json.dump(diag, f, indent=1)
    print('rows', len(rows), 'diag', len(diag))
    c = collections.Counter((r['service'], r['typing']) for r in rows)
    for s, _ in SERVICES:
        tot = sum(v for (sv, t), v in c.items() if sv == s)
        print(s, tot, {t: v for (sv, t), v in sorted(c.items()) if sv == s})

if __name__ == '__main__':
    main()
