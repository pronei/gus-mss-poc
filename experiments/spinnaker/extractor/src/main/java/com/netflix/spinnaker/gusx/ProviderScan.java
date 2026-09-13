package com.netflix.spinnaker.gusx;

import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.Parameter;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** Spring MVC controllers to provider endpoints. */
public final class ProviderScan {

  static final String REST_CONTROLLER = "org.springframework.web.bind.annotation.RestController";
  static final String CONTROLLER = "org.springframework.stereotype.Controller";
  static final String REQUEST_MAPPING = "org.springframework.web.bind.annotation.RequestMapping";

  /** Composed mapping annotations and the method each implies. */
  private static final String[][] COMPOSED = {
    {"org.springframework.web.bind.annotation.GetMapping", "GET"},
    {"org.springframework.web.bind.annotation.PostMapping", "POST"},
    {"org.springframework.web.bind.annotation.PutMapping", "PUT"},
    {"org.springframework.web.bind.annotation.DeleteMapping", "DELETE"},
    {"org.springframework.web.bind.annotation.PatchMapping", "PATCH"},
  };

  /** The verbs Spring registers for a mapping that declares none. */
  private static final List<String> ALL_VERBS =
      List.of("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT");

  /** Spring's own "no default" sentinel for @RequestParam#defaultValue. */
  private static final String DEFAULT_NONE = "\n\t\t\n\t\t\n\n\t\t\t\t\n";

  private final ClassLoader cl;
  private final ClassIndex index;
  private final Shape shape;
  private final Diag diag;
  private final String service;
  /** controller -> endpoints emitted, for the memo and the census diff. */
  public final java.util.Map<String, Integer> controllerYield = new java.util.TreeMap<>();

  public ProviderScan(ClassLoader cl, ClassIndex index, Shape shape, Diag diag, String service) {
    this.cl = cl;
    this.index = index;
    this.shape = shape;
    this.diag = diag;
    this.service = service;
  }

  public List<Endpoint> scan() throws Exception {
    List<Endpoint> out = new ArrayList<>();
    List<String> cands =
        index.candidates("L" + REST_CONTROLLER.replace('.', '/') + ";",
                         "L" + CONTROLLER.replace('.', '/') + ";");
    for (String cn : cands) {
      Class<?> k;
      try {
        k = Class.forName(cn, false, cl);
      } catch (Throwable t) {
        diag.loss("controller-load", cn + ": " + t.getClass().getSimpleName());
        continue;
      }
      // The byte prefilter over-matches; this is the confirmation. Reading the
      // annotations can itself fail when an annotation type is absent from
      // this profile's classpath, and a silent skip there would drop a whole
      // controller, so the two cases are distinguished.
      java.lang.annotation.Annotation[] anns;
      try {
        anns = k.getAnnotations();
      } catch (Throwable t) {
        diag.loss("controller-annotations-unreadable", cn + ": " + t);
        continue;
      }
      boolean isController = false;
      for (java.lang.annotation.Annotation an : anns) {
        String n = an.annotationType().getName();
        if (n.equals(REST_CONTROLLER) || n.equals(CONTROLLER)) {
          isController = true;
          break;
        }
      }
      if (!isController) {
        diag.count("prefilter-over-match");
        continue;
      }
      if (k.isInterface() || Modifier.isAbstract(k.getModifiers())) {
        continue;
      }
      java.io.File jar = index.owner.get(cn);
      boolean own = ownJar(jar);
      diag.count(own ? "controllers-confirmed" : "controllers-outside-service");
      try {
        List<Endpoint> got = controller(k);
        if (own) {
          controllerYield.put(cn, got.size());
          out.addAll(got);
        } else {
          // D3: actuator and framework-registered routes are outside the
          // graph, not findings. They are reported rather than emitted, so
          // that the census diff has one line per excluded route.
          for (Endpoint e : got) {
            diag.loss("framework-route-excluded",
                e.method + " " + e.path + "  (" + cn + ", " + (jar == null ? "?" : jar.getName()) + ")");
          }
          diag.count("framework-routes-excluded", got.size());
        }
      } catch (Throwable t) {
        diag.loss("controller-scan", cn + ": " + t);
      }
    }
    out.sort(null);
    return out;
  }

  private List<Endpoint> controller(Class<?> k) {
    List<Endpoint> out = new ArrayList<>();
    Annotation classMapping = Anns.on(k, REQUEST_MAPPING);
    List<String> classPaths = classMapping == null ? List.of()
        : Anns.firstNonEmpty(classMapping, "value", "path");
    List<String> classConsumes = classMapping == null ? List.of() : Anns.strings(classMapping, "consumes");
    List<String> classProduces = classMapping == null ? List.of() : Anns.strings(classMapping, "produces");

    byte[] bytes = index.bytes(k.getName());
    ClassFile cf = null;
    if (bytes != null) {
      try {
        cf = new ClassFile(bytes);
      } catch (Throwable t) {
        diag.loss("classfile-parse", k.getName() + ": " + t);
      }
    }

    List<Method> sorted = handlerMethods(k);

    for (Method m : sorted) {
      Mapping map = mappingOf(m);
      if (map == null) {
        continue;
      }
      List<String> paths = map.paths.isEmpty() ? List.of("") : map.paths;
      // A @RequestMapping that declares no method is registered by Spring for
      // every verb, and S2's census records it as the pseudo-method ANY (23
      // rows across the mesh). The document cannot say ANY — the loader reads
      // exactly the seven real verbs (loader.go:118-128) and would drop an
      // `any:` key silently — so the endpoint is emitted once per verb and
      // each copy is marked, which is what D3's "a provider method ANY
      // matches every method" means once it has to be written down.
      boolean anyMethod = map.methods.isEmpty() && map.fromRequestMapping;
      List<String> verbs = anyMethod ? ALL_VERBS : (map.methods.isEmpty() ? List.of("GET") : map.methods);
      if (anyMethod) {
        diag.count("request-mapping-without-method");
      }
      List<String> consumes = map.consumes.isEmpty() ? classConsumes : map.consumes;
      List<String> produces = map.produces.isEmpty() ? classProduces : map.produces;

      for (String cp : classPaths.isEmpty() ? List.of("") : classPaths) {
        for (String mp : paths) {
          for (String verb : verbs) {
            Endpoint e = new Endpoint();
            e.path = Paths.join(cp, mp);
            e.method = verb;
            e.source = k.getName() + "." + m.getName();
            if (anyMethod) {
              e.extras.put("x-method-any", Boolean.TRUE);
            }
            bind(e, k, m, cf, consumes, produces);
            if (e.response == null) {
              e.extras.put("x-response-opaque", Boolean.TRUE);
              diag.count("opaque-provider-responses");
            }
            out.add(e);
          }
        }
      }
    }
    return out;
  }

  /**
   * The methods Spring would register, in a deterministic order.
   *
   * <p>Two things a naive scan gets wrong. Handler methods need not be
   * public: Front50 declares eight of its seventeen controllers with
   * package-private handlers, and Spring registers them anyway — its
   * {@code AbstractHandlerMethodMapping} selects over
   * {@code ReflectionUtils.USER_DECLARED_METHODS}, which ignores access
   * (CLAIM-G1-004). And a mapping may be inherited, so the walk goes up the
   * hierarchy, most-derived first, deduplicating on name and descriptor.
   */
  private List<Method> handlerMethods(Class<?> k) {
    java.util.LinkedHashMap<String, Method> bySig = new java.util.LinkedHashMap<>();
    for (Class<?> c = k; c != null && c != Object.class; c = c.getSuperclass()) {
      Method[] ms;
      try {
        ms = c.getDeclaredMethods();
      } catch (Throwable t) {
        diag.loss("controller-methods", c.getName() + ": " + t);
        continue;
      }
      List<Method> local = new ArrayList<>(Arrays.asList(ms));
      local.sort((a, b) -> {
        int x = a.getName().compareTo(b.getName());
        return x != 0 ? x : sig(a).compareTo(sig(b));
      });
      for (Method m : local) {
        if (m.isSynthetic() || m.isBridge() || Modifier.isStatic(m.getModifiers())) {
          continue;
        }
        if (m.getName().startsWith("lambda$")) {
          continue;
        }
        bySig.putIfAbsent(m.getName() + sig(m), m);
      }
    }
    List<Method> out = new ArrayList<>(bySig.values());
    out.sort((a, b) -> {
      int c = a.getName().compareTo(b.getName());
      return c != 0 ? c : sig(a).compareTo(sig(b));
    });
    return out;
  }

  /**
   * Whether a jar is one of the service's own modules. Spinnaker publishes
   * them as {@code <svc>-<module>[-<version>].jar} in both eras (S3: the
   * naming flips on versioning, not on the prefix), which is exactly the
   * scope S2's source census covered.
   */
  private boolean ownJar(java.io.File jar) {
    return jar != null && jar.getName().startsWith(service + "-");
  }

  // --- the mapping annotation ---

  private static final class Mapping {
    List<String> paths = List.of();
    List<String> methods = List.of();
    List<String> consumes = List.of();
    List<String> produces = List.of();
    boolean fromRequestMapping;
  }

  private Mapping mappingOf(Method m) {
    for (String[] c : COMPOSED) {
      Annotation a = Anns.on(m, c[0]);
      if (a != null) {
        Mapping map = new Mapping();
        map.paths = Anns.firstNonEmpty(a, "value", "path");
        map.methods = List.of(c[1]);
        map.consumes = Anns.strings(a, "consumes");
        map.produces = Anns.strings(a, "produces");
        return map;
      }
    }
    Annotation a = Anns.on(m, REQUEST_MAPPING);
    if (a == null) {
      return null;
    }
    Mapping map = new Mapping();
    map.fromRequestMapping = true;
    map.paths = Anns.firstNonEmpty(a, "value", "path");
    List<String> verbs = new ArrayList<>();
    Object mo = Anns.attr(a, "method");
    if (mo != null && mo.getClass().isArray()) {
      int n = java.lang.reflect.Array.getLength(mo);
      for (int i = 0; i < n; i++) {
        verbs.add(String.valueOf(java.lang.reflect.Array.get(mo, i)));
      }
    }
    map.methods = verbs;
    map.consumes = Anns.strings(a, "consumes");
    map.produces = Anns.strings(a, "produces");
    return map;
  }

  // --- parameters and payloads ---

  private void bind(Endpoint e, Class<?> k, Method m, ClassFile cf,
                    List<String> consumes, List<String> produces) {
    Parameter[] ps = m.getParameters();
    Type[] gts = m.getGenericParameterTypes();
    String[] lvt = new String[ps.length];
    if (cf != null) {
      try {
        String[] got = cf.parameterNames(m.getName(), sig(m));
        System.arraycopy(got, 0, lvt, 0, Math.min(got.length, lvt.length));
      } catch (Throwable t) {
        diag.loss("localvariabletable", k.getName() + "." + m.getName() + ": " + t);
      }
    }

    boolean multipart = consumes.stream().anyMatch(c -> c.startsWith("multipart/"));
    boolean validated = false;

    for (int i = 0; i < ps.length; i++) {
      Parameter p = ps[i];
      Type gt = gts[i];
      if (Anns.hasSimple(p, "Valid", "Validated")) {
        validated = true;
      }
      Annotation pv = Anns.on(p, "org.springframework.web.bind.annotation.PathVariable");
      Annotation rp = Anns.on(p, "org.springframework.web.bind.annotation.RequestParam");
      Annotation rh = Anns.on(p, "org.springframework.web.bind.annotation.RequestHeader");
      Annotation rb = Anns.on(p, "org.springframework.web.bind.annotation.RequestBody");
      Annotation rpart = Anns.on(p, "org.springframework.web.bind.annotation.RequestPart");

      if (rpart != null || isMultipart(p.getType())) {
        multipart = true;
        continue;
      }
      if (rb != null) {
        if (multipart) {
          continue; // CLAIM-S5-022: no application/json request content
        }
        e.body = shape.of(gt, Shape.Side.ACCEPT);
        e.bodyRequired = Anns.bool(rb, "required", true);
        continue;
      }
      if (pv != null) {
        String name = paramName(pv, p, lvt, i, e, "@PathVariable");
        if (name == null) {
          continue;
        }
        e.params.put(name, scalarParam(gt));
        if (Anns.bool(pv, "required", true)) {
          e.paramsRequired.add(name); // D6: a path variable is always required
        }
        continue;
      }
      if (rp != null) {
        if (isCatchAll(p.getType())) {
          // D6 / S2 §2: 23 endpoints bind a catch-all Map or MultiValueMap
          // rather than named parameters; params becomes an open object and
          // the request side is untyped.
          e.paramsOpen = true;
          diag.count("catch-all-query-binders");
          continue;
        }
        String name = paramName(rp, p, lvt, i, e, "@RequestParam");
        if (name == null) {
          continue;
        }
        Schema s = scalarParam(gt);
        String dv = Anns.str(rp, "defaultValue");
        boolean hasDefault = !dv.isEmpty() && !DEFAULT_NONE.equals(dv);
        if (hasDefault) {
          // CLAIM-S5-031: only the presence of `default` is read
          // (loader.go:494-496); the value suppresses REQ.1/REQ.2. It is
          // still emitted in the declared type so the document reads as
          // valid OpenAPI rather than as a string under type: boolean.
          s.put("default", typedDefault(dv, String.valueOf(s.get("type"))));
        }
        e.params.put(name, s);
        if (Anns.bool(rp, "required", true) && !hasDefault) {
          e.paramsRequired.add(name);
        }
        continue;
      }
      if (rh != null) {
        if (isCatchAll(p.getType()) || p.getType().getName().equals("org.springframework.http.HttpHeaders")) {
          diag.count("catch-all-header-binders");
          continue;
        }
        String name = paramName(rh, p, lvt, i, e, "@RequestHeader");
        if (name == null) {
          continue;
        }
        e.headers.put(name, scalarParam(gt));
        if (Anns.bool(rh, "required", true) && Anns.str(rh, "defaultValue").isEmpty()) {
          e.headersRequired.add(name);
        }
      }
    }
    if (validated) {
      // CLAIM-S5-018: a validation annotation counts as presence only under
      // @Valid/@Validated. The gate is recorded so that a later pass can read
      // the body's own @NotNull fields; nothing is inferred without it.
      e.extras.put("x-validated", Boolean.TRUE);
      diag.count("validated-bodies");
    }

    e.response = response(m, produces, e);
  }

  private Schema response(Method m, List<String> produces, Endpoint e) {
    Annotation rs = Anns.on(m, "org.springframework.web.bind.annotation.ResponseStatus");
    if (rs != null) {
      Object code = Anns.attr(rs, "value");
      String s = String.valueOf(code);
      if (!s.startsWith("OK") && !s.startsWith("ACCEPTED") && !s.startsWith("CREATED")
          && !s.startsWith("NO_CONTENT") && !s.startsWith("2")) {
        diag.count("response-status-non-2xx-dropped");
      }
    }
    // D6: any non-JSON produces is a contentless 200 on both sides.
    boolean nonJson = !produces.isEmpty()
        && produces.stream().noneMatch(p -> p.contains("json") || p.equals("*/*"));
    if (nonJson) {
      diag.count("non-json-produces");
      return null;
    }
    Type rt = Types.unwrapResponse(m.getGenericReturnType(), diag);
    if (rt == null) {
      return null; // void / Void / byte[] / StreamingResponseBody: contentless
    }
    if (Types.isRawGeneric(m.getGenericReturnType())) {
      diag.count("raw-generic-returns");
      return Schema.untypedObject();
    }
    return shape.of(rt, Shape.Side.RETURN);
  }

  /** A path or query parameter: a scalar, or an array for a repeated one. */
  private Schema scalarParam(Type t) {
    Class<?> raw = Types.erase(t);
    if (raw != null && (raw.isArray() || java.util.Collection.class.isAssignableFrom(raw))) {
      Type ct = Types.elementType(t);
      Schema inner = ct == null ? Schema.prim("string", "") : scalarParam(ct);
      return Schema.array(inner);
    }
    if (raw != null && raw.isEnum()) {
      return shape.of(t, Shape.Side.ACCEPT);
    }
    Schema p = raw == null ? null : Shape.primitive(raw);
    // Everything arriving in a path segment, a query string or a header is a
    // string on the wire; the declared Java type gives the intended kind.
    return p != null ? p : Schema.prim("string", "");
  }

  private String paramName(Annotation a, Parameter p, String[] lvt, int i, Endpoint e, String what) {
    String n = Anns.str(a, "value");
    if (n.isEmpty()) {
      n = Anns.str(a, "name");
    }
    if (!n.isEmpty()) {
      return n;
    }
    // D1(a): MethodParameters is absent from every jar in the corpus, so
    // Parameter#getName is arg0; LocalVariableTable is the fallback.
    if (p.isNamePresent()) {
      diag.count("param-name-from-methodparameters");
      return p.getName();
    }
    if (i < lvt.length && lvt[i] != null && !lvt[i].isEmpty()) {
      diag.count("param-name-from-localvariabletable");
      return lvt[i];
    }
    diag.flag(e.method + " " + e.path, what + " parameter " + i + " has no name (annotation, MethodParameters and LocalVariableTable all silent)");
    return null;
  }

  /** A default literal in the parameter's declared JSON type. */
  static Object typedDefault(String raw, String type) {
    if ("boolean".equals(type)) {
      if (raw.equalsIgnoreCase("true")) {
        return Boolean.TRUE;
      }
      if (raw.equalsIgnoreCase("false")) {
        return Boolean.FALSE;
      }
      return raw;
    }
    if ("integer".equals(type)) {
      try {
        return Long.valueOf(raw);
      } catch (NumberFormatException e) {
        return raw;
      }
    }
    return raw;
  }

  private static boolean isCatchAll(Class<?> t) {
    if (t == null) {
      return false;
    }
    String n = t.getName();
    return n.equals("java.util.Map")
        || n.equals("org.springframework.util.MultiValueMap")
        || n.equals("org.springframework.util.LinkedMultiValueMap");
  }

  private static boolean isMultipart(Class<?> t) {
    if (t == null) {
      return false;
    }
    String n = t.getName();
    return n.equals("org.springframework.web.multipart.MultipartFile")
        || n.equals("jakarta.servlet.http.Part")
        || n.equals("javax.servlet.http.Part");
  }

  static String sig(Method m) {
    StringBuilder b = new StringBuilder("(");
    for (Class<?> c : m.getParameterTypes()) {
      b.append(desc(c));
    }
    return b.append(')').append(desc(m.getReturnType())).toString();
  }

  static String desc(Class<?> c) {
    if (c.isPrimitive()) {
      switch (c.getName()) {
        case "void": return "V";
        case "boolean": return "Z";
        case "byte": return "B";
        case "char": return "C";
        case "short": return "S";
        case "int": return "I";
        case "long": return "J";
        case "float": return "F";
        default: return "D";
      }
    }
    if (c.isArray()) {
      return "[" + desc(c.getComponentType());
    }
    return "L" + c.getName().replace('.', '/') + ";";
  }

  /** Distinct source classes seen, for the memo. */
  public Set<String> sources(List<Endpoint> eps) {
    Set<String> s = new LinkedHashSet<>();
    for (Endpoint e : eps) {
      s.add(e.source.substring(0, e.source.lastIndexOf('.')));
    }
    return s;
  }
}
