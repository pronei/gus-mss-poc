package com.netflix.spinnaker.gusx;

import java.util.List;
import java.util.Map;

/**
 * A deterministic YAML writer for the subset the documents use: ordered
 * mappings, lists, strings, booleans and integers.
 *
 * <p>Written by hand rather than taken from snakeyaml so that the tool keeps
 * its promise of no runtime dependency of its own: it runs inside the
 * service's class loader (Main), where a second snakeyaml would be one more
 * version to reconcile with Spring Boot's.
 */
public final class Yaml {

  private final StringBuilder sb = new StringBuilder();

  public static String write(Map<String, Object> doc) {
    Yaml y = new Yaml();
    y.mapping(doc, 0);
    return y.sb.toString();
  }

  @SuppressWarnings("unchecked")
  private void mapping(Map<String, Object> m, int indent) {
    for (Map.Entry<String, Object> e : m.entrySet()) {
      Object v = e.getValue();
      String k = key(e.getKey());
      if (v instanceof Map) {
        Map<String, Object> mm = (Map<String, Object>) v;
        if (mm.isEmpty()) {
          line(indent, k + ": {}");
        } else {
          line(indent, k + ":");
          mapping(mm, indent + 1);
        }
      } else if (v instanceof Schema) {
        Map<String, Object> mm = ordered((Schema) v);
        if (mm.isEmpty()) {
          line(indent, k + ": {}");
        } else {
          line(indent, k + ":");
          mapping(mm, indent + 1);
        }
      } else if (v instanceof List) {
        List<Object> l = (List<Object>) v;
        if (l.isEmpty()) {
          line(indent, k + ": []");
        } else {
          line(indent, k + ":");
          for (Object o : l) {
            item(o, indent + 1);
          }
        }
      } else {
        line(indent, k + ": " + scalar(v));
      }
    }
  }

  private void item(Object o, int indent) {
    if (o instanceof Schema) {
      o = ordered((Schema) o);
    }
    if (o instanceof Map) {
      @SuppressWarnings("unchecked")
      Map<String, Object> mm = (Map<String, Object>) o;
      if (mm.isEmpty()) {
        line(indent, "- {}");
        return;
      }
      // A dash alone, then the mapping one level in: valid YAML for a
      // sequence entry that is a mapping, and free of the alignment
      // bookkeeping that inlining the first key would need.
      line(indent, "-");
      mapping(mm, indent + 1);
    } else {
      line(indent, "- " + scalar(o));
    }
  }

  /** Schema keys in the fixed order, unknown keys after, sorted. */
  static Map<String, Object> ordered(Schema s) {
    java.util.LinkedHashMap<String, Object> out = new java.util.LinkedHashMap<>();
    for (String k : Schema.KEY_ORDER) {
      if (s.keys.containsKey(k)) {
        out.put(k, s.keys.get(k));
      }
    }
    java.util.List<String> rest = new java.util.ArrayList<>();
    for (String k : s.keys.keySet()) {
      if (!Schema.KEY_ORDER.contains(k)) {
        rest.add(k);
      }
    }
    rest.sort(null);
    for (String k : rest) {
      out.put(k, s.keys.get(k));
    }
    return out;
  }

  private void line(int indent, String s) {
    sb.append("  ".repeat(indent)).append(s).append('\n');
  }

  private static String key(String k) {
    return needsQuote(k) ? quote(k) : k;
  }

  private static String scalar(Object v) {
    if (v == null) {
      return "null";
    }
    if (v instanceof Boolean || v instanceof Integer || v instanceof Long) {
      return String.valueOf(v);
    }
    String s = String.valueOf(v);
    return needsQuote(s) ? quote(s) : s;
  }

  private static boolean needsQuote(String s) {
    if (s.isEmpty()) {
      return true;
    }
    if (s.equals("true") || s.equals("false") || s.equals("null")
        || s.equals("yes") || s.equals("no") || s.equals("on") || s.equals("off")
        || s.equals("~")) {
      return true;
    }
    // A bare scalar that YAML would read as a number or that carries
    // structural punctuation.
    if (s.matches("[-+]?[0-9]+(\\.[0-9]+)?([eE][-+]?[0-9]+)?")) {
      return true;
    }
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c == ':' || c == '#' || c == '{' || c == '}' || c == '[' || c == ']'
          || c == ',' || c == '&' || c == '*' || c == '!' || c == '|' || c == '>'
          || c == '\'' || c == '"' || c == '%' || c == '@' || c == '`'
          || c == '\n' || c == '\t' || c < 0x20) {
        return true;
      }
    }
    char f = s.charAt(0);
    return f == '-' || f == '?' || f == ' ' || s.charAt(s.length() - 1) == ' ';
  }

  private static String quote(String s) {
    StringBuilder b = new StringBuilder("\"");
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      switch (c) {
        case '"': b.append("\\\""); break;
        case '\\': b.append("\\\\"); break;
        case '\n': b.append("\\n"); break;
        case '\t': b.append("\\t"); break;
        case '\r': b.append("\\r"); break;
        default:
          if (c < 0x20) {
            b.append(String.format("\\u%04x", (int) c));
          } else {
            b.append(c);
          }
      }
    }
    return b.append('"').toString();
  }

  private Yaml() {}
}
