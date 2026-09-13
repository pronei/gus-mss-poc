package com.netflix.spinnaker.gusx;

/**
 * Path assembly and the D3 normalization.
 *
 * <p>The normalization is fixed by R1(a) and is applied identically to both
 * sides, because the checker keys an endpoint on the literal
 * {@code {Path, Method}} pair (loader.go:56-59) and never normalizes anything
 * itself (CLAIM-S5-053).
 */
public final class Paths {

  /** Class-level prefix + method-level path, leading slash forced. */
  public static String join(String classPath, String methodPath) {
    String a = classPath == null ? "" : classPath.trim();
    String b = methodPath == null ? "" : methodPath.trim();
    String s = a + (a.isEmpty() || b.isEmpty() || b.startsWith("/") || a.endsWith("/") ? "" : "/") + b;
    return normalize(s);
  }

  /**
   * D3: strip a baked-in query string, force a leading slash, erase variable
   * names and regexes, collapse doubled slashes, strip a trailing one.
   * {@code "."} is Retrofit 2's spelling of the base URL.
   */
  public static String normalize(String raw) {
    String s = raw == null ? "" : raw.trim();
    int q = s.indexOf('?');
    if (q >= 0) {
      s = s.substring(0, q);
    }
    if (s.isEmpty() || s.equals(".") || s.equals("./")) {
      s = "/";
    }
    if (!s.startsWith("/")) {
      s = "/" + s;
    }
    // CLAIM-S5-020: a path variable may carry a regex ({id:.+}, 79 sites).
    // The regex goes; the NAME stays, because D6 needs it to key params and a
    // reader needs it to recognise the endpoint. The fully erased form is the
    // match key below, which G3 pairs on.
    s = stripRegexes(s);
    s = s.replaceAll("/{2,}", "/");
    if (s.length() > 1 && s.endsWith("/")) {
      s = s.substring(0, s.length() - 1);
    }
    return s;
  }

  /** {name:regex} -> {name}, balanced-brace aware. */
  static String stripRegexes(String s) {
    StringBuilder b = new StringBuilder();
    int i = 0;
    while (i < s.length()) {
      char c = s.charAt(i);
      if (c != '{') {
        b.append(c);
        i++;
        continue;
      }
      int depth = 0;
      int j = i;
      while (j < s.length()) {
        if (s.charAt(j) == '{') {
          depth++;
        } else if (s.charAt(j) == '}') {
          depth--;
          if (depth == 0) {
            break;
          }
        }
        j++;
      }
      if (j >= s.length()) {
        b.append(s.substring(i));
        break;
      }
      String inner = s.substring(i + 1, j);
      int colon = inner.indexOf(':');
      b.append('{').append(colon < 0 ? inner : inner.substring(0, colon)).append('}');
      i = j + 1;
    }
    return b.toString();
  }

  /**
   * The comparison key R1(a) uses: variable names and regexes erased. Kept
   * separate from the emitted path so that the document stays readable and
   * G3 can apply the same key to both sides.
   */
  public static String matchKey(String path) {
    return normalize(path).replaceAll("\\{[^}]*\\}", "{}");
  }

  /** The query string a Retrofit template bakes in, as name=value pairs. */
  public static java.util.List<String[]> bakedQuery(String raw) {
    java.util.List<String[]> out = new java.util.ArrayList<>();
    if (raw == null) {
      return out;
    }
    int q = raw.indexOf('?');
    if (q < 0) {
      return out;
    }
    for (String pair : raw.substring(q + 1).split("&")) {
      if (pair.isEmpty()) {
        continue;
      }
      int eq = pair.indexOf('=');
      if (eq < 0) {
        out.add(new String[] {pair, ""});
      } else {
        out.add(new String[] {pair.substring(0, eq), pair.substring(eq + 1)});
      }
    }
    return out;
  }

  private Paths() {}
}
