#!/usr/bin/env python3
"""Extract Retrofit method declarations from Java/Groovy/Kotlin interface files.

Emits TSV: file, lineno, http_method, path_template, interface, method_name,
           body_type, return_type
Deliberately conservative: anything it cannot parse is reported on stderr so it
can be hand-checked rather than silently dropped.
"""
import re
import sys
import os

HTTP_ANNOS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")

# annotations that may sit between the HTTP annotation and the method decl
SKIP_ANNO = re.compile(
    r"@(Headers|Multipart|Streaming|FormUrlEncoded|Deprecated|JvmSuppressWildcards|"
    r"Suppress|Nullable|NonNull|SuppressWarnings|Override|Timeout)\b"
)


def strip_comments(text):
    """Remove // and /* */ comments, preserving string literals and line count."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            # string literal (handles escapes); Kotlin triple-quote handled crudely
            if text.startswith('"""', i):
                j = text.find('"""', i + 3)
                j = n if j < 0 else j + 3
                out.append(text[i:j])
                i = j
                continue
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                if text[j] == "\n":
                    break
                j += 1
            out.append(text[i:j])
            i = j
        elif c == "'":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    j += 1
                    break
                if text[j] == "\n":
                    break
                j += 1
            out.append(text[i:j])
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            # keep newlines so line numbers stay right
            out.append("".join("\n" if ch == "\n" else " " for ch in text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def match_paren(text, start):
    """start is index of '('; return index just past matching ')'."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            q = c
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def split_top(params):
    """Split a parameter list on commas at angle/paren/bracket depth 0."""
    parts, buf, depth = [], [], 0
    i, n = 0, len(params)
    while i < n:
        c = params[i]
        if c == '"':
            j = i + 1
            while j < n and params[j] != '"':
                j += 2 if params[j] == "\\" else 1
            buf.append(params[i:j + 1])
            i = j + 1
            continue
        if c in "<([":
            depth += 1
        elif c in ">)]":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    if "".join(buf).strip():
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def body_type_of(params, kotlin):
    for p in split_top(params):
        if "@Body" not in p:
            continue
        rest = p.split("@Body", 1)[1].strip()
        if kotlin:
            # `name: Type = default`  -> Type
            if ":" in rest:
                t = rest.split(":", 1)[1].strip()
                t = t.split("=", 1)[0].strip()
                return re.sub(r"\s+", "", t)
            return re.sub(r"\s+", "", rest)
        # Java/Groovy: strip any further annotations, then "Type name"
        rest = re.sub(r"@\w+(\s*\([^)]*\))?", " ", rest).strip()
        toks = split_type_name(rest)
        return toks
    return "-"


def split_type_name(decl):
    """From 'List<Map<String,Object>> foo' return 'List<Map<String,Object>>'."""
    decl = decl.strip().rstrip(";")
    decl = re.sub(r"\bfinal\b", " ", decl).strip()
    # walk from the end: last identifier is the param name
    m = re.search(r"[\w$]+\s*$", decl)
    if not m:
        return decl
    head = decl[: m.start()].strip()
    if not head:
        # only one token -> Groovy `def`-less param, type unknown
        return decl
    return re.sub(r"\s+", "", head)


def parse_file(path, repo_root):
    rel = os.path.relpath(path, repo_root)
    kotlin = path.endswith(".kt")
    raw = open(path, encoding="utf-8", errors="replace").read()
    text = strip_comments(raw)
    lines_before = [0]
    for ch in text:
        pass
    rows, problems = [], []

    # index -> line number
    def lineno(idx):
        return text.count("\n", 0, idx) + 1

    # enclosing interface name at a given index
    iface_spans = []
    for m in re.finditer(r"\b(?:public\s+|private\s+|internal\s+|static\s+)*interface\s+([\w$]+)", text):
        iface_spans.append((m.start(), m.group(1)))

    def iface_at(idx):
        name = None
        for pos, nm in iface_spans:
            if pos < idx:
                name = nm
            else:
                break
        return name or "?"

    anno_re = re.compile(r"@(" + "|".join(HTTP_ANNOS) + r")\s*\(")
    for m in anno_re.finditer(text):
        verb = m.group(1)
        open_paren = m.end() - 1
        close = match_paren(text, open_paren)
        if close < 0:
            problems.append((rel, lineno(m.start()), "unbalanced annotation parens"))
            continue
        inner = text[open_paren + 1:close - 1].strip()
        pm = re.match(r"""^(["'])((?:[^"'\\]|\\.)*)\1\s*$""", inner)
        if not pm:
            # could be @GET(value = "...") or a Groovy GString
            pm2 = re.search(r"""(["'])((?:[^"'\\]|\\.)*)\1""", inner)
            if not pm2:
                problems.append((rel, lineno(m.start()), "no literal path: " + inner[:60]))
                continue
            path_t = pm2.group(2)
        else:
            path_t = pm.group(2)

        # walk forward past intervening annotations to the method declaration
        i = close
        n = len(text)
        guard = 0
        while i < n and guard < 40:
            guard += 1
            while i < n and text[i] in " \t\r\n":
                i += 1
            if i < n and text[i] == "@":
                am = re.match(r"@[\w.]+", text[i:])
                if not am:
                    break
                j = i + am.end()
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j < n and text[j] == "(":
                    j = match_paren(text, j)
                    if j < 0:
                        break
                i = j
                continue
            break

        decl_start = i
        # find the parameter-list '(' of the method
        # Kotlin: [modifiers] fun NAME(   ; Java/Groovy: TYPE NAME(
        seg = text[decl_start:decl_start + 4000]
        if kotlin:
            km = re.match(r"(?:[\w@\[\]]+\s+)*?fun\s+(?:<[^>]*>\s*)?([\w$`]+)\s*\(", seg)
            if not km:
                problems.append((rel, lineno(decl_start), "kotlin: no fun after " + verb + " " + path_t))
                continue
            name = km.group(1).strip("`")
            popen = decl_start + km.end() - 1
        else:
            jm = re.match(r"([\s\S]*?)\b([\w$]+)\s*\(", seg)
            if not jm:
                problems.append((rel, lineno(decl_start), "java: no method after " + verb + " " + path_t))
                continue
            name = jm.group(2)
            popen = decl_start + jm.end() - 1
        pclose = match_paren(text, popen)
        if pclose < 0:
            problems.append((rel, lineno(decl_start), "unbalanced param parens"))
            continue
        params = text[popen + 1:pclose - 1]

        if kotlin:
            tail = text[pclose:pclose + 400]
            tm = re.match(r"\s*:\s*([^\n{=]+)", tail)
            ret = re.sub(r"\s+", "", tm.group(1)).rstrip(",") if tm else "Unit"
            ret = ret.rstrip("{").strip()
        else:
            head = text[decl_start:popen].strip()
            head = re.sub(r"@\w+(\s*\([^)]*\))?", " ", head)
            head = re.sub(r"\b(public|abstract|default|static|final)\b", " ", head)
            head = head[: head.rfind(name)].strip() if name in head else head
            ret = re.sub(r"\s+", "", head) or "def"

        body = body_type_of(params, kotlin)
        rows.append(dict(
            file=rel, line=lineno(m.start()), verb=verb, path=path_t,
            iface=iface_at(m.start()), name=name, body=body, ret=ret,
        ))
    return rows, problems


if __name__ == "__main__":
    repo_root = sys.argv[1]
    out = []
    probs = []
    for f in sys.argv[2:]:
        r, p = parse_file(f, repo_root)
        out.extend(r)
        probs.extend(p)
    for r in out:
        print("\t".join([r["file"], str(r["line"]), r["verb"], r["path"],
                         r["iface"], r["name"], r["body"], r["ret"]]))
    for p in probs:
        print("PROBLEM\t%s\t%s\t%s" % p, file=sys.stderr)
