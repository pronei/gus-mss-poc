package com.netflix.spinnaker.gusx;

import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.Parameter;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Retrofit interfaces to caller endpoints.
 *
 * <p>Emitted under {@code /_calls/<provider><path>} with {@code x-role: client}
 * (README §5.3), which is the form the checker reads for C2, C4 and TGT. Both
 * Retrofit generations are handled: the corpus is mid-migration
 * (CLAIM-S1-018), the annotation names are the same in both, and the
 * difference shows up only in the return type — Retrofit 1 returns the payload
 * or {@code retrofit.client.Response} directly, Retrofit 2 wraps it in
 * {@code Call<T>}.
 */
public final class CallerScan {

  private static final String[] VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"};

  private final ClassLoader cl;
  private final ClassIndex index;
  private final Shape shape;
  private final Diag diag;
  private final Mesh mesh;
  private final String service;
  private final boolean keepKork;
  private final boolean keepIndirectFiat;

  public CallerScan(ClassLoader cl, ClassIndex index, Shape shape, Diag diag, Mesh mesh,
                    String service, boolean keepKork, boolean keepIndirectFiat) {
    this.cl = cl;
    this.index = index;
    this.shape = shape;
    this.diag = diag;
    this.mesh = mesh;
    this.service = service;
    this.keepKork = keepKork;
    this.keepIndirectFiat = keepIndirectFiat;
  }

  public List<Endpoint> scan() throws Exception {
    List<Endpoint> out = new ArrayList<>();
    List<String> cands = index.candidates("Lretrofit/http/", "Lretrofit2/http/");
    for (String cn : cands) {
      Class<?> k;
      try {
        k = Class.forName(cn, false, cl);
      } catch (Throwable t) {
        diag.loss("retrofit-load", cn + ": " + t.getClass().getSimpleName());
        continue;
      }
      if (!k.isInterface()) {
        // CLAIM-S1-016: two Spring MVC controllers import Retrofit's @Query and
        // apply it to handler-method parameters. Spring has no binding for it;
        // they are not clients.
        if (hasRetrofitVerb(k)) {
          diag.loss("retrofit-annotations-on-non-interface", cn);
        }
        continue;
      }
      if (!hasRetrofitVerb(k)) {
        continue;
      }
      List<Mesh.Binding> bindings = mesh == null ? List.of() : mesh.lookup(service, k.getName());
      if (bindings.isEmpty()) {
        // Out of mesh (Jenkins, Slack, a metric store) or unresolved
        // (CLAIM-S1-012's dynamic selector). Either way: no provider, no edge.
        diag.loss("retrofit-no-provider", cn);
        diag.count("retrofit-interfaces-out-of-mesh");
        continue;
      }
      if (bindings.size() > 1) {
        diag.count("interfaces-bound-to-several-providers");
      }
      for (Mesh.Binding b : bindings) {
        if ("KORK".equals(b.token) && !keepKork) {
          diag.count("kork-rows-dropped-by-flag");
          continue;
        }
        if ("FIATAPI".equals(b.token) && !keepIndirectFiat && isIndirectFiatCaller(service)) {
          diag.count("indirect-fiat-rows-dropped-by-flag");
          continue;
        }
        try {
          out.addAll(iface(k, b));
        } catch (Throwable t) {
          diag.loss("retrofit-scan", cn + " -> " + b.provider + ": " + t);
        }
      }
    }
    out.sort(null);
    return out;
  }

  /**
   * CLAIM-S1-009 and clients.md: in Clouddriver, Echo, Igor and Keel no
   * application code injects {@code FiatService}; the calls are issued by
   * {@code FiatPermissionEvaluator} inside fiat-api. Whether those rows belong
   * in the graph is the owner's call (decisions.md); the flag exposes both.
   */
  private static boolean isIndirectFiatCaller(String service) {
    return service.equals("clouddriver") || service.equals("echo")
        || service.equals("igor") || service.equals("keel");
  }

  private List<Endpoint> iface(Class<?> k, Mesh.Binding b) {
    List<Endpoint> out = new ArrayList<>();
    byte[] bytes = index.bytes(k.getName());
    ClassFile cf = null;
    if (bytes != null) {
      try {
        cf = new ClassFile(bytes);
      } catch (Throwable t) {
        diag.loss("classfile-parse", k.getName() + ": " + t);
      }
    }
    List<Method> ms = new ArrayList<>(Arrays.asList(k.getMethods()));
    ms.sort((x, y) -> {
      int c = x.getName().compareTo(y.getName());
      return c != 0 ? c : ProviderScan.sig(x).compareTo(ProviderScan.sig(y));
    });
    for (Method m : ms) {
      if (m.isSynthetic() || m.isBridge() || Modifier.isStatic(m.getModifiers())) {
        continue;
      }
      String[] vp = verbAndPath(m);
      if (vp == null) {
        continue;
      }
      Endpoint e = new Endpoint();
      e.role = "client";
      e.method = vp[0];
      String rawPath = vp[1];
      e.path = "/_calls/" + b.provider + Paths.normalize(rawPath);
      e.source = k.getName() + "." + m.getName();
      e.extras.put("x-provider", b.provider);
      e.extras.put("x-interface", k.getName());
      e.extras.put("x-resolved-by", b.resolvedBy);

      // D6: a baked-in query string becomes params with a default, or the `?`
      // is part of the endpoint key and the edge can never match
      // (CLAIM-S5-016).
      for (String[] pair : Paths.bakedQuery(rawPath)) {
        // The literal in the template is the whole declaration, so it is also
        // the evidence for the type: `?restricted=false` against a provider
        // that binds a boolean is otherwise a prim-mismatch on every payload.
        Schema s = literal(pair[1]);
        e.params.put(pair[0], s);
        diag.count("baked-in-query-pairs");
      }

      bindParams(e, k, m, cf);
      e.response = callerResponse(m);
      if (e.response == null) {
        // Declared opaque (Call<ResponseBody>, retrofit-1 Response, Void),
        // not merely undetermined. D6 wants a contentless 200 on BOTH sides
        // of an edge, which only G3 can arrange because only G3 sees both
        // documents; this marker is what it needs to arrange it.
        e.extras.put("x-response-opaque", Boolean.TRUE);
        diag.count("opaque-caller-responses");
      }
      out.add(e);
    }
    return out;
  }

  private void bindParams(Endpoint e, Class<?> k, Method m, ClassFile cf) {
    Parameter[] ps = m.getParameters();
    Type[] gts = m.getGenericParameterTypes();
    String[] lvt = new String[ps.length];
    if (cf != null) {
      try {
        String[] got = cf.parameterNames(m.getName(), ProviderScan.sig(m));
        System.arraycopy(got, 0, lvt, 0, Math.min(got.length, lvt.length));
      } catch (Throwable ignored) {
        // flagged below if a name is actually missing
      }
    }
    boolean multipart = Anns.onSimple(m, "Multipart") != null;
    for (int i = 0; i < ps.length; i++) {
      Parameter p = ps[i];
      Type gt = gts[i];
      Annotation path = Anns.onSimple(p, "Path");
      Annotation query = Anns.onSimple(p, "Query");
      Annotation qmap = Anns.onSimple(p, "QueryMap");
      Annotation header = Anns.onSimple(p, "Header");
      Annotation hmap = Anns.onSimple(p, "HeaderMap");
      Annotation body = Anns.onSimple(p, "Body");
      Annotation part = Anns.onSimple(p, "Part", "PartMap");

      if (part != null) {
        multipart = true;
        continue;
      }
      if (body != null) {
        if (multipart) {
          continue;
        }
        e.body = shape.of(gt, Shape.Side.RETURN); // what this service sends
        e.bodyRequired = true;
        continue;
      }
      if (qmap != null) {
        e.paramsOpen = true;
        diag.count("catch-all-query-binders");
        continue;
      }
      if (hmap != null) {
        diag.count("catch-all-header-binders");
        continue;
      }
      if (path != null) {
        String n = name(path, p, lvt, i, e, "@Path");
        if (n != null) {
          e.params.put(n, scalar(gt));
          e.paramsRequired.add(n);
        }
        continue;
      }
      if (query != null) {
        String n = name(query, p, lvt, i, e, "@Query");
        if (n != null) {
          // A Retrofit @Query is sent when non-null and omitted otherwise, so
          // the caller does not require it of itself.
          e.params.putIfAbsent(n, scalar(gt));
        }
        continue;
      }
      if (header != null) {
        String n = name(header, p, lvt, i, e, "@Header");
        if (n != null) {
          e.headers.put(n, scalar(gt));
        }
      }
    }
    // @Headers({"Accept: application/json"}) declares fixed headers, not a
    // contract the provider must satisfy; recorded, not emitted.
    if (Anns.onSimple(m, "Headers") != null) {
      diag.count("retrofit-fixed-headers");
    }
  }

  private Schema callerResponse(Method m) {
    Type rt = Types.unwrapResponse(m.getGenericReturnType(), diag);
    if (rt == null) {
      return null; // Call<ResponseBody>, retrofit1 Response, Void: contentless
    }
    if (Types.isRawGeneric(m.getGenericReturnType())) {
      diag.count("raw-generic-returns");
      return Schema.untypedObject();
    }
    return shape.of(rt, Shape.Side.ACCEPT); // what this service expects back
  }

  /** The schema a fixed query-string literal declares. */
  static Schema literal(String v) {
    Schema s;
    if (v.equalsIgnoreCase("true") || v.equalsIgnoreCase("false")) {
      s = Schema.prim("boolean", "");
      s.put("default", Boolean.valueOf(v.equalsIgnoreCase("true")));
      return s;
    }
    try {
      long n = Long.parseLong(v);
      s = Schema.prim("integer", "int64");
      s.put("default", n);
      return s;
    } catch (NumberFormatException ignored) {
      // not a number: a string literal
    }
    s = Schema.prim("string", "");
    s.put("default", v);
    return s;
  }

  private Schema scalar(Type t) {
    Class<?> raw = Types.erase(t);
    if (raw != null && (raw.isArray() || java.util.Collection.class.isAssignableFrom(raw))) {
      Type ct = Types.elementType(t);
      return Schema.array(ct == null ? Schema.prim("string", "") : scalar(ct));
    }
    if (raw != null && raw.isEnum()) {
      return shape.of(t, Shape.Side.RETURN);
    }
    Schema p = raw == null ? null : Shape.primitive(raw);
    return p != null ? p : Schema.prim("string", "");
  }

  private String name(Annotation a, Parameter p, String[] lvt, int i, Endpoint e, String what) {
    String n = Anns.str(a, "value");
    if (!n.isEmpty()) {
      return n;
    }
    if (p.isNamePresent()) {
      diag.count("param-name-from-methodparameters");
      return p.getName();
    }
    if (i < lvt.length && lvt[i] != null && !lvt[i].isEmpty()) {
      diag.count("param-name-from-localvariabletable");
      return lvt[i];
    }
    diag.flag(e.method + " " + e.path, what + " parameter " + i + " has no name");
    return null;
  }

  private static String[] verbAndPath(Method m) {
    for (Annotation a : Anns.safeAnnotations(m)) {
      String n = a.annotationType().getName();
      if (!n.startsWith("retrofit.http.") && !n.startsWith("retrofit2.http.")) {
        continue;
      }
      String simple = a.annotationType().getSimpleName();
      for (String v : VERBS) {
        if (simple.equals(v)) {
          return new String[] {v, Anns.str(a, "value")};
        }
      }
      if (simple.equals("HTTP")) {
        String method = Anns.str(a, "method");
        String path = Anns.str(a, "path");
        if (!method.isEmpty()) {
          return new String[] {method, path};
        }
      }
    }
    return null;
  }

  private static boolean hasRetrofitVerb(Class<?> k) {
    try {
      for (Method m : k.getMethods()) {
        if (verbAndPath(m) != null) {
          return true;
        }
      }
    } catch (Throwable ignored) {
      return false;
    }
    return false;
  }
}
