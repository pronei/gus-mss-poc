package com.netflix.spinnaker.gusx;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * The OpenAPI 3.0 document the checker reads.
 *
 * <p>Everything here is shaped by what {@code pkg/schema/loader.go} actually
 * looks at: {@code requestBody.content["application/json"].schema}
 * (loader.go:138), the lowest 2xx {@code content["application/json"].schema}
 * (loader.go:605-632), {@code x-role} on the operation, and
 * {@code components/schemas}. A {@code parameters:} block would be dropped
 * silently (loader.go:182-186, CLAIM-S5-001), which is why D6 folds path,
 * query and header parameters into the request object instead.
 */
public final class Doc {

  /**
   * D6: one wrapper for every request, payload under {@code body}. Putting
   * {@code params} beside the payload's own properties would let a body field
   * and a query parameter of the same name collide, and for a Map-typed body
   * the loader errors outright on named properties beside an
   * {@code additionalProperties} schema (loader.go:531).
   */
  static Schema request(Endpoint e) {
    Map<String, Schema> wrapper = new TreeMap<>();
    List<String> required = new ArrayList<>();

    if (!e.params.isEmpty() || e.paramsOpen) {
      Schema p = Schema.object(e.params, new ArrayList<>(e.paramsRequired), true);
      if (e.paramsOpen) {
        // A catch-all binder: the names are not declared, so the request side
        // is untyped (D6).
        p.untyped();
      }
      wrapper.put("params", p);
      if (!e.paramsRequired.isEmpty()) {
        required.add("params");
      }
    }
    if (!e.headers.isEmpty()) {
      wrapper.put("headers", Schema.object(e.headers, new ArrayList<>(e.headersRequired), true));
      if (!e.headersRequired.isEmpty()) {
        required.add("headers");
      }
    }
    if (e.body != null) {
      wrapper.put("body", e.body);
      if (e.bodyRequired) {
        required.add("body");
      }
    }
    // The wrapper is emitted even when it is empty. D6/CLAIM-S5-048: a schema
    // present on one side and nil on the other is a presence-mismatch BREAK
    // (compat.go:62-68), and a caller with no parameters against a provider
    // with one optional query parameter is exactly that shape. Two open
    // objects compare vacuously; a nil against an object does not.
    Schema s = Schema.object(wrapper, required, true);
    boolean untyped = e.body != null && e.body.isUntyped();
    if (e.body == null && e.paramsOpen) {
      untyped = true;
    }
    if (untyped) {
      s.untyped();
    }
    return s;
  }

  public static Map<String, Object> build(String service, String version, List<Endpoint> endpoints,
                                          Map<String, Schema> components, Diag diag) {
    Map<String, Object> doc = new LinkedHashMap<>();
    doc.put("openapi", "3.0.3");

    Map<String, Object> info = new LinkedHashMap<>();
    info.put("title", service);
    info.put("version", version.isEmpty() ? "0" : version);
    doc.put("info", info);

    Map<String, Object> paths = new TreeMap<>();
    List<Endpoint> sorted = new ArrayList<>(endpoints);
    sorted.sort(null);
    for (Endpoint e : sorted) {
      @SuppressWarnings("unchecked")
      Map<String, Object> item =
          (Map<String, Object>) paths.computeIfAbsent(e.path, k -> new TreeMap<String, Object>());
      String verb = e.method.toLowerCase(java.util.Locale.ROOT);
      if (item.containsKey(verb)) {
        // Two controller methods mapped to the same path and verb: Spring
        // would refuse to start, but a document can only carry one. Keep the
        // first in deterministic order and report the collision.
        diag.loss("duplicate-endpoint", e.method + " " + e.path + " (" + e.source + ")");
        continue;
      }
      item.put(verb, operation(e));
    }
    doc.put("paths", paths);

    // Only components something reaches. The loader resolves every entry
    // under components/schemas before it looks at any path (loader.go:104-116),
    // so an orphan left behind by a discarded endpoint would be validated —
    // and could fail the load — for a shape no edge can ever reach.
    java.util.Set<String> reachable = new java.util.TreeSet<>();
    for (Endpoint e : sorted) {
      collectRefs(request(e), reachable);
      collectRefs(e.response, reachable);
    }
    java.util.Deque<String> queue = new java.util.ArrayDeque<>(reachable);
    while (!queue.isEmpty()) {
      Schema c = components.get(queue.poll());
      if (c == null) {
        continue;
      }
      java.util.Set<String> more = new java.util.TreeSet<>();
      collectRefs(c, more);
      for (String n : more) {
        if (reachable.add(n)) {
          queue.add(n);
        }
      }
    }
    Map<String, Object> comps = new LinkedHashMap<>();
    Map<String, Object> schemas = new TreeMap<>();
    for (Map.Entry<String, Schema> en : components.entrySet()) {
      if (reachable.contains(en.getKey())) {
        schemas.put(en.getKey(), en.getValue());
      } else {
        diag.count("components-pruned-unreferenced");
      }
    }
    comps.put("schemas", schemas);
    doc.put("components", comps);
    return doc;
  }

  /** Component names a schema tree refers to, one level deep. */
  @SuppressWarnings("unchecked")
  static void collectRefs(Object node, java.util.Set<String> out) {
    if (node == null) {
      return;
    }
    if (node instanceof Schema) {
      Schema s = (Schema) node;
      Object r = s.get("$ref");
      if (r instanceof String) {
        String v = (String) r;
        int i = v.lastIndexOf('/');
        out.add(i < 0 ? v : v.substring(i + 1));
      }
      for (Object v : s.keys.values()) {
        collectRefs(v, out);
      }
      return;
    }
    if (node instanceof Map) {
      for (Object v : ((Map<String, Object>) node).values()) {
        collectRefs(v, out);
      }
      return;
    }
    if (node instanceof java.util.List) {
      for (Object v : (java.util.List<Object>) node) {
        collectRefs(v, out);
      }
    }
  }

  private static Map<String, Object> operation(Endpoint e) {
    Map<String, Object> op = new LinkedHashMap<>();
    op.put("operationId", opId(e));
    // The D3 match key: variable names erased, so that G3 can pair a caller's
    // declaration with a provider's mapping without re-deriving anything and
    // can see when the two spell a variable differently (R1(a)).
    op.put("x-match-key", e.method + " " + Paths.matchKey(clientPath(e)));
    if (!e.role.isEmpty()) {
      op.put("x-role", e.role);
    }
    for (Map.Entry<String, Object> x : e.extras.entrySet()) {
      op.put(x.getKey(), x.getValue());
    }
    Schema req = request(e);
    if (req != null) {
      Map<String, Object> rb = new LinkedHashMap<>();
      rb.put("required", Boolean.TRUE);
      Map<String, Object> content = new LinkedHashMap<>();
      Map<String, Object> json = new LinkedHashMap<>();
      json.put("schema", req);
      content.put("application/json", json);
      rb.put("content", content);
      op.put("requestBody", rb);
    }
    Map<String, Object> responses = new LinkedHashMap<>();
    Map<String, Object> ok = new LinkedHashMap<>();
    ok.put("description", "");
    if (e.response != null) {
      Map<String, Object> content = new LinkedHashMap<>();
      Map<String, Object> json = new LinkedHashMap<>();
      json.put("schema", e.response);
      content.put("application/json", json);
      ok.put("content", content);
    }
    // D6/CLAIM-S5-048: a contentless 200 on BOTH sides. A response absent on
    // one side and present on the other is a presence-mismatch BREAK for a
    // body that never existed (compat.go:62-68).
    responses.put("200", ok);
    op.put("responses", responses);
    return op;
  }

  /** For a client endpoint the /_calls/<provider> prefix is not part of the key. */
  private static String clientPath(Endpoint e) {
    if (!"client".equals(e.role)) {
      return e.path;
    }
    String p = e.path.substring("/_calls/".length());
    int slash = p.indexOf('/');
    return slash < 0 ? "/" : p.substring(slash);
  }

  private static String opId(Endpoint e) {
    StringBuilder b = new StringBuilder(e.method.toLowerCase(java.util.Locale.ROOT));
    for (String seg : e.path.split("/")) {
      if (seg.isEmpty()) {
        continue;
      }
      String s = seg.replaceAll("[{}]", "").replaceAll("[^A-Za-z0-9]", "_");
      if (s.isEmpty()) {
        continue;
      }
      b.append('_').append(s);
    }
    return b.toString();
  }

  private Doc() {}
}
