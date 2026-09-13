package com.netflix.spinnaker.gusx;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.databind.BeanDescription;
import com.fasterxml.jackson.databind.JavaType;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationConfig;
import com.fasterxml.jackson.databind.introspect.AnnotatedClass;
import com.fasterxml.jackson.databind.introspect.AnnotatedMember;
import com.fasterxml.jackson.databind.introspect.BeanPropertyDefinition;
import com.fasterxml.jackson.databind.jsontype.NamedType;
import java.lang.reflect.Method;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * Java type to OpenAPI schema, read through the service's own configured
 * {@link ObjectMapper}.
 *
 * <p>D7 and CLAIM-S5-010/011/012: the Jackson-visible shape is <em>not</em>
 * the reflected shape. Front50's {@code Pipeline} gets its any-getter from
 * {@code PipelineMixins}, registered by {@code Front50ApiModule}; Clouddriver's
 * whole polymorphic surface is mixin-declared; Keel synthesises type resolvers
 * for six unannotated types in an {@code AnnotationIntrospector}. Reflecting
 * the model class sees none of it. Everything below therefore goes through
 * {@code config.introspect(javaType)}, which applies mixins, introspectors and
 * registered subtypes.
 *
 * <p>Direction matters (D4, D8): the same Java type projects differently on
 * the side a service <em>reads</em> and the side it <em>writes</em>.
 */
public final class Shape {

  /** Which side of the wire a schema is being written for. */
  public enum Side {
    /** What the service reads: a provider's request body, a caller's expect. */
    ACCEPT,
    /** What the service writes: a provider's response, a caller's send. */
    RETURN
  }

  private final ObjectMapper mapper;
  private final SerializationConfig sconfig;
  private final Diag diag;
  private final boolean enumsOpenOnAccept;
  private final boolean enumsOpenOnReturn;
  private final boolean globalNonNull;
  private final boolean presenceDeclared;

  /**
   * Components, emitted under components/schemas — and only for types that
   * are genuinely recursive.
   *
   * <p>The loader inlines every non-cyclic {@code $ref} and resolves each
   * component exactly once, reusing the node at every occurrence
   * (loader.go:96-116, compat.go:264-274). One component name can therefore
   * carry only one shape — while D4 and D8 make the projection
   * side-dependent: a Java primitive is required on the return side and not
   * on the accept side, a {@code NON_NULL} field is optional-and-non-nullable
   * only on the return side, and an enum is closed on the side whose mapper
   * is closed. Sharing a component between the two sides would misstate one
   * of them.
   *
   * <p>So every type is inlined per side, and a component is emitted only at
   * a cycle back-edge, where the loader needs a {@code Ref} and where
   * {@code ref-name-mismatch} compares the local name across the two
   * documents (compat.go:276-296). That is exactly the shape the checker's
   * coinduction expects: the one-step unfolding around the back-edge is
   * compared structurally, per side, and only the name has to agree.
   */
  public final Map<String, Schema> components = new TreeMap<>();
  /** component name -> the class it came from, to detect simple-name collisions. */
  private final Map<String, String> componentOwner = new TreeMap<>();
  /** canonical type + side -> the rendered subtree, shared rather than rebuilt. */
  private final Map<String, Schema> inlineCache = new LinkedHashMap<>();
  /** types currently being expanded, so recursion emits a $ref back-edge. */
  private final Set<String> inProgress = new java.util.LinkedHashSet<>();
  /** types that turned out to be recursive, and so became components. */
  public final Set<String> recursive = new java.util.TreeSet<>();

  public Shape(ObjectMapper mapper, Diag diag, boolean enumsOpenOnAccept,
               boolean enumsOpenOnReturn, boolean presenceDeclared) {
    this.mapper = mapper;
    this.sconfig = mapper.getSerializationConfig();
    this.diag = diag;
    this.enumsOpenOnAccept = enumsOpenOnAccept;
    this.enumsOpenOnReturn = enumsOpenOnReturn;
    this.presenceDeclared = presenceDeclared;
    JsonInclude.Include inc = sconfig.getSerializationInclusion();
    this.globalNonNull = inc == JsonInclude.Include.NON_NULL || inc == JsonInclude.Include.NON_ABSENT;
  }

  public boolean globalNonNull() {
    return globalNonNull;
  }

  /** Entry point: a reflected Java type on one side of the wire. */
  public Schema of(Type t, Side side) {
    try {
      return node(mapper.getTypeFactory().constructType(t), side, 0);
    } catch (Throwable e) {
      diag.loss("type-resolution", String.valueOf(t) + ": " + e);
      return Schema.untypedObject();
    }
  }

  // --- the walk ---

  private Schema node(JavaType jt, Side side, int depth) {
    if (depth > 40) {
      diag.loss("depth-limit", jt.toCanonical());
      return Schema.untypedObject();
    }
    Class<?> raw = jt.getRawClass();

    // Untyped scalars (D5): Object, Any, Groovy def, JsonNode and friends.
    if (raw == Object.class || isJsonNode(raw)) {
      return Schema.untypedObject();
    }

    Schema prim = primitive(raw);
    if (prim != null) {
      return prim;
    }

    if (raw.isEnum()) {
      return enumSchema(raw, side);
    }

    if (jt.isArrayType() || jt.isCollectionLikeType()) {
      JavaType ct = jt.getContentType();
      if (ct == null || ct.getRawClass() == Object.class) {
        // raw List / List<Object> (D5, CLAIM-S5-034)
        return Schema.array(Schema.untypedObject()).untyped();
      }
      return Schema.array(node(ct, side, depth + 1));
    }

    if (jt.isMapLikeType()) {
      return mapSchema(jt, side, depth);
    }

    // A named bean: goes into components and is referenced.
    return beanRef(jt, side, depth);
  }

  private Schema mapSchema(JavaType jt, Side side, int depth) {
    Class<?> raw = jt.getRawClass();
    JavaType vt = jt.getContentType();
    boolean namedSubclass = !raw.getName().startsWith("java.util.")
        && !raw.getName().startsWith("java.lang.")
        && !raw.isInterface();

    if (namedSubclass) {
      // CLAIM-S5-023 / S2-005/006: front50's PipelineTemplate and Notification
      // extend HashMap<String,Object>. The loader refuses named properties
      // beside an additionalProperties schema (loader.go:531), so these
      // project as an open object carrying whatever the subclass declares,
      // and count untyped.
      return mapSubclass(jt, side, depth);
    }
    if (vt == null || vt.getRawClass() == Object.class || isJsonNode(vt.getRawClass())) {
      // raw Map, Map<String,Object>, Map<?,?> (D5)
      return Schema.untypedObject();
    }
    // A typed map is typed (D5 as revised, CLAIM-S5-032): it loads as
    // types.Map and checkMap compares key kind and value type.
    Schema val = node(vt, side, depth + 1);
    if (val.isUntyped()) {
      return Schema.untypedObject();
    }
    return Schema.map(val);
  }

  private Schema mapSubclass(JavaType jt, Side side, int depth) {
    Class<?> raw = jt.getRawClass();
    String key = jt.toCanonical() + "#" + side;
    Schema hit = inlineCache.get(key);
    if (hit != null) {
      return hit;
    }
    if (inProgress.contains(key)) {
      return backEdge(raw, key);
    }
    inProgress.add(key);
    Map<String, Schema> props = new TreeMap<>();
    try {
      BeanDescription bd = sconfig.introspect(sconfig.constructType(raw));
      for (BeanPropertyDefinition p : bd.findProperties()) {
        AnnotatedMember m = accessorFor(p, side);
        if (m == null) {
          continue;
        }
        // CLAIM-S5-023 says "the subclass's DECLARED properties". A Map
        // subclass is serialised by Jackson as a map, so the accessors it
        // inherits from java.util.HashMap (isEmpty and friends) never reach
        // the wire at all and must not appear as fields.
        Class<?> decl = m.getDeclaringClass();
        if (decl != null && isJdk(decl.getName())) {
          continue;
        }
        props.put(p.getName(), node(propertyType(p, m), side, depth + 1));
      }
    } catch (Throwable t) {
      diag.loss("map-subclass-introspection", raw.getName() + ": " + t);
    }
    inProgress.remove(key);
    Schema s = Schema.object(props, List.of(), true).untyped();
    s.put("x-java-type", raw.getName());
    diag.count("map-subclass-models");
    inlineCache.put(key, s);
    return s;
  }

  private Schema beanRef(JavaType jt, Side side, int depth) {
    Class<?> raw = jt.getRawClass();
    if (isJdk(raw.getName())) {
      // A JDK type that is neither a scalar nor a container: Iterable, a raw
      // functional interface, something behind a custom serialiser. It has no
      // declared shape and must not become a named component that a second
      // service could accidentally agree with.
      diag.loss("jdk-type-as-payload", raw.getName());
      return Schema.untypedObject();
    }
    // A generic bean is cached per parameterisation AND per side, so
    // Foo<Bar> and Foo<Baz> do not share a projection and neither do the
    // accept and return readings of one type.
    String key = jt.toCanonical() + "#" + side;
    Schema hit = inlineCache.get(key);
    if (hit != null) {
      return hit;
    }
    if (inProgress.contains(key)) {
      return backEdge(raw, key);
    }
    inProgress.add(key);
    Schema body;
    try {
      body = bean(jt, side, depth);
    } finally {
      inProgress.remove(key);
    }
    // If the expansion came back through itself, the component the back-edge
    // named has to exist, and it has to carry one shape for both sides.
    String comp = pendingComponent.remove(key);
    if (comp != null) {
      register(comp, raw.getName(), body);
      recursive.add(raw.getName());
      diag.count("recursive-components");
      diag.loss("recursive-type-side-neutral",
          raw.getName() + " as " + comp + " (first seen on the " + side + " side)");
      inlineCache.put(key, Schema.ref(comp));
      return Schema.ref(comp);
    }
    inlineCache.put(key, body);
    return body;
  }

  /** components awaiting a body: key -> component name promised to a back-edge. */
  private final Map<String, String> pendingComponent = new LinkedHashMap<>();

  /**
   * CLAIM-S5-019: a cycle back-edge becomes a {@code $ref} named after the
   * Java simple class name, so that a caller's document and a provider's
   * document agree at the back-edge — {@code ref-name-mismatch} compares that
   * local name (compat.go:276-296).
   */
  private Schema backEdge(Class<?> raw, String key) {
    String comp = componentName(raw);
    pendingComponent.put(key, comp);
    return Schema.ref(comp);
  }

  private Schema bean(JavaType jt, Side side, int depth) {
    Class<?> raw = jt.getRawClass();
    BeanDescription bd;
    try {
      bd = sconfig.introspect(jt);
    } catch (Throwable t) {
      diag.loss("introspection", raw.getName() + ": " + t);
      return Schema.untypedObject();
    }

    // D7: a polymorphic base projects as oneOf over its registered subtypes,
    // each variant carrying a closed one-value enum discriminator. Two open
    // variants would admit each other and oneof-ambiguity would fire on every
    // payload (compat.go:243-254).
    Schema poly = polymorphic(bd, jt, side, depth);
    if (poly != null) {
      return poly;
    }

    // @JsonValue: the object is serialised as whatever the accessor returns
    // (CLAIM-S5-043).
    AnnotatedMember jsonValue = safeJsonValue(bd);
    if (jsonValue != null) {
      diag.count("json-value-types");
      return node(jsonValue.getType(), side, depth + 1);
    }

    Map<String, Schema> props = new TreeMap<>();
    List<String> required = new ArrayList<>();
    boolean open = true;

    List<BeanPropertyDefinition> defs;
    try {
      defs = bd.findProperties();
    } catch (Throwable t) {
      diag.loss("property-introspection", raw.getName() + ": " + t);
      return Schema.untypedObject();
    }

    boolean classNonNull = classNonNull(bd);

    for (BeanPropertyDefinition p : defs) {
      AnnotatedMember m = accessorFor(p, side);
      if (m == null) {
        continue; // write-only on the return side, read-only on the accept side
      }
      Schema ps;
      try {
        ps = node(propertyType(p, m), side, depth + 1);
      } catch (Throwable t) {
        diag.loss("property-type", raw.getName() + "." + p.getName() + ": " + t);
        ps = Schema.untypedObject();
      }
      Class<?> praw = p.getPrimaryType() == null ? null : p.getPrimaryType().getRawClass();

      // Nullability and NON_NULL inclusion are properties of the FIELD, not
      // of the direction: they are read from every member of the property —
      // getter, setter, field, creator parameter — and unioned. Reading only
      // the member chosen for this side made the same kork field nullable on
      // a provider's return and non-nullable on a caller's expect, which is a
      // nullable-response-widening BREAK invented by the projection
      // (CLAIM-G1-012).
      // NON_NULL inclusion is a statement about what this service WRITES, so
      // it governs the return side only (D4: "on the return side such a field
      // must be projected optional and non-nullable"). Applying it to the
      // accept side too suppressed @Nullable on a caller's expect while the
      // provider's return kept it — for the same kork class, reached from the
      // same jar on both sides — and invented a nullable-response-widening
      // BREAK (CLAIM-G1-012).
      boolean nonNull =
          side == Side.RETURN && (classNonNull || globalNonNull || anyMemberNonNull(p));
      boolean nullable = !nonNull && anyMemberNullable(p);
      if (nullable) {
        ps = ps.nullable();
      }
      if (nonNull && side == Side.RETURN) {
        // D4/CLAIM-S5-014/037: a field this service never serialises when
        // null is absent, not null. Recorded so the projection is legible and
        // so G3 can tell "optional because never written" from "optional
        // because nothing is declared".
        ps.put("x-non-null", Boolean.TRUE);
        diag.count("non-null-return-fields");
      }
      if (presenceDeclared && requiredHere(p, m, praw, side, nonNull)) {
        required.add(p.getName());
      }
      if (hasDefaultMarker(m)) {
        ps.put("default", "");
      }
      props.put(p.getName(), ps);
    }

    // @JsonAnyGetter / @JsonAnySetter (CLAIM-S5-005): a declared shape plus an
    // open remainder. Keep the named properties, set additionalProperties:
    // true; the any-map's value type is dropped, which the loader would refuse
    // to carry beside properties anyway (loader.go:531).
    if (hasAnyAccessor(bd, side)) {
      open = true;
      diag.count("any-getter-setter-types");
    }

    if (props.isEmpty()) {
      // Nothing Jackson can see: an interface with no getters, a type behind a
      // custom serializer (CLAIM-S5-042), or a bean whose accessors are all
      // ignored. An open object with no fields is exactly D5's untyped.
      diag.loss("no-visible-properties", raw.getName());
      return Schema.untypedObject();
    }

    Schema s = Schema.object(props, required, open);
    s.put("x-java-type", raw.getName());
    return s;
  }

  // --- polymorphism ---

  private Schema polymorphic(BeanDescription bd, JavaType jt, Side side, int depth) {
    AnnotatedClass ac;
    try {
      ac = bd.getClassInfo();
    } catch (Throwable t) {
      return null;
    }
    // AnnotatedClass merges the mixin's annotations with the class's own, so
    // this sees Clouddriver's CredentialsDefinitionMixin and Keel's
    // ClusterDeployStrategyMixin as well as an annotation on the type itself
    // (S2 SS5, CLAIM-S5-010/011).
    JsonTypeInfo ti;
    try {
      ti = ac.getAnnotation(JsonTypeInfo.class);
    } catch (Throwable t) {
      ti = null;
    }
    if (ti == null) {
      // The third mechanism: a custom AnnotationIntrospector that synthesises
      // a resolver for a type carrying no annotation at all (Keel's
      // KeelApiAnnotationIntrospector, six types). The resolver does not
      // expose the subtype set, so the base is projected open and counted;
      // Keel is out of the first run (D2). CLAIM-G1-010.
      if (introspectorSynthesisedResolver(ac, jt)) {
        diag.loss("polymorphic-introspector-synthesised", jt.getRawClass().getName());
        diag.count("polymorphic-bases-introspector-synthesised");
        return Schema.untypedObject();
      }
      return null;
    }
    if (ti.use() == JsonTypeInfo.Id.NONE) {
      return null;
    }
    Collection<NamedType> subs;
    try {
      subs = sconfig.getSubtypeResolver().collectAndResolveSubtypesByClass(sconfig, ac);
    } catch (Throwable t) {
      subs = List.of();
    }
    List<NamedType> concrete = new ArrayList<>();
    for (NamedType nt : subs) {
      Class<?> c = nt.getType();
      if (c == null || c == jt.getRawClass()) {
        continue;
      }
      if (c.isInterface() || java.lang.reflect.Modifier.isAbstract(c.getModifiers())) {
        continue;
      }
      concrete.add(nt);
    }
    if (concrete.isEmpty()) {
      // CLAIM-S5-012: Clouddriver registers subtypes from Spring beans at
      // runtime. Nothing static can enumerate them; the accepted loss is the
      // base as an open object, counted untyped.
      diag.loss("polymorphic-no-static-subtypes", jt.getRawClass().getName());
      diag.count("polymorphic-bases-unenumerable");
      return Schema.untypedObject();
    }
    String disc = ti.property();
    if (disc == null || disc.isEmpty()) {
      disc = defaultDiscriminatorName(ti.use());
    }
    concrete.sort((a, b) -> a.getType().getName().compareTo(b.getType().getName()));

    List<Object> variants = new ArrayList<>();
    for (NamedType nt : concrete) {
      String id = typeId(nt, ti);
      Schema v;
      try {
        v = bean(sconfig.getTypeFactory().constructType(nt.getType()), side, depth + 1);
      } catch (Throwable t) {
        diag.loss("polymorphic-variant", nt.getType().getName() + ": " + t);
        v = Schema.untypedObject();
      }
      if (ti.include() == JsonTypeInfo.As.EXTERNAL_PROPERTY
          || ti.include() == JsonTypeInfo.As.WRAPPER_ARRAY
          || ti.include() == JsonTypeInfo.As.WRAPPER_OBJECT) {
        // The discriminator is not a property of the payload object.
        diag.count("polymorphic-discriminator-outside-payload");
        variants.add(v);
        continue;
      }
      Object propsObj = v.get("properties");
      if (propsObj instanceof Map) {
        @SuppressWarnings("unchecked")
        Map<String, Object> pm = (Map<String, Object>) propsObj;
        // D7: a closed one-value enum. Two open-object variants admit each
        // other's values and oneof-ambiguity fires on every payload
        // (compat.go:243-254).
        pm.put(disc, Schema.enumOf(List.of(id), "string"));
        Object req = v.get("required");
        @SuppressWarnings("unchecked")
        List<String> r = (req instanceof List) ? new ArrayList<>((List<String>) req) : new ArrayList<>();
        if (!r.contains(disc)) {
          r.add(disc);
          r.sort(null);
          v.put("required", r);
        }
      }
      variants.add(v);
    }
    diag.count("polymorphic-bases");
    return Schema.of().put("oneOf", variants);
  }

  /**
   * Whether the configured AnnotationIntrospector produces a type resolver for
   * a class that carries no {@code @JsonTypeInfo}. Probed reflectively because
   * the method moved between Jackson versions and the corpus spans several
   * (2.9 through 2.13 in the 1.30.0-1.38.0 range).
   */
  private boolean introspectorSynthesisedResolver(AnnotatedClass ac, JavaType jt) {
    Object ai;
    try {
      ai = sconfig.getAnnotationIntrospector();
    } catch (Throwable t) {
      return false;
    }
    for (String name : new String[] {"findPolymorphicTypeInfo", "findTypeResolver"}) {
      for (Method m : ai.getClass().getMethods()) {
        if (!m.getName().equals(name)) {
          continue;
        }
        try {
          Object r =
              m.getParameterCount() == 2
                  ? m.invoke(ai, sconfig, ac)
                  : m.invoke(ai, sconfig, ac, jt);
          if (r != null) {
            return true;
          }
        } catch (Throwable ignored) {
          // wrong overload; try the next
        }
      }
    }
    return false;
  }

  private static String defaultDiscriminatorName(JsonTypeInfo.Id id) {
    if (id == JsonTypeInfo.Id.CLASS || id == JsonTypeInfo.Id.MINIMAL_CLASS) {
      return "@class";
    }
    return "@type";
  }

  private static String typeId(NamedType nt, JsonTypeInfo ti) {
    JsonTypeInfo.Id id = ti.use();
    if (id == JsonTypeInfo.Id.CLASS || id == JsonTypeInfo.Id.MINIMAL_CLASS) {
      // CLAIM-S5-024: Id.CLASS discriminators are fully-qualified class names.
      return nt.getType().getName();
    }
    if (nt.hasName()) {
      return nt.getName();
    }
    return nt.getType().getSimpleName();
  }

  /**
   * The property's type as Jackson resolves it, with generic bindings of the
   * declaring type applied. {@code getPrimaryType} is preferred over the
   * chosen member's own type because a setter's member type is its return
   * type, not the property's.
   */
  private JavaType propertyType(BeanPropertyDefinition p, AnnotatedMember m) {
    try {
      JavaType t = p.getPrimaryType();
      if (t != null) {
        return t;
      }
    } catch (Throwable ignored) {
      // fall through to the member
    }
    return m.getType();
  }

  // --- presence, nullability, enums ---

  private boolean requiredHere(BeanPropertyDefinition p, AnnotatedMember m, Class<?> praw,
                               Side side, boolean nonNull) {
    // D4 as revised, and only D4's legs. Jackson's own
    // BeanPropertyDefinition#isRequired is wider than the plan's *declared*
    // profile — it also reports a creator parameter Jackson must have in
    // order to construct the bean, which says nothing about what has to be on
    // the wire — so the annotation is read directly. It occurs zero times in
    // this corpus (CLAIM-S5-017); it is honoured if it ever appears.
    for (AnnotatedMember mm : members(p)) {
      if (declaredRequired(mm)) {
        return true;
      }
    }
    if (side == Side.RETURN) {
      if (nonNull) {
        // CLAIM-S5-014/037: a field the service never serialises when null is
        // absent, not null. Optional and not nullable, or
        // nullable-response-widening fires for a value that never reaches the
        // wire.
        return false;
      }
      // The one leg of the declared profile that carries weight on this
      // corpus: a Java primitive can never be absent on the way out.
      return praw != null && praw.isPrimitive();
    }
    // Accept side: only a validation annotation gated by @Valid/@Validated
    // counts (CLAIM-S5-018), and that gate lives on the controller parameter,
    // not here; Provider passes it in through the body wrapper.
    return false;
  }

  /** An explicit {@code @JsonProperty(required = true)} on the member. */
  private static boolean declaredRequired(AnnotatedMember m) {
    try {
      com.fasterxml.jackson.annotation.JsonProperty a =
          m.getAnnotation(com.fasterxml.jackson.annotation.JsonProperty.class);
      return a != null && a.required();
    } catch (Throwable t) {
      return false;
    }
  }

  private boolean classNonNull(BeanDescription bd) {
    try {
      JsonInclude.Value v = bd.findPropertyInclusion(JsonInclude.Value.empty());
      JsonInclude.Include inc = v == null ? null : v.getValueInclusion();
      return inc == JsonInclude.Include.NON_NULL || inc == JsonInclude.Include.NON_ABSENT;
    } catch (Throwable t) {
      return false;
    }
  }

  /** Every member Jackson associates with the property, in a stable order. */
  private static List<AnnotatedMember> members(BeanPropertyDefinition p) {
    List<AnnotatedMember> out = new ArrayList<>(4);
    try {
      if (p.getGetter() != null) {
        out.add(p.getGetter());
      }
      if (p.getSetter() != null) {
        out.add(p.getSetter());
      }
      if (p.getField() != null) {
        out.add(p.getField());
      }
      if (p.getConstructorParameter() != null) {
        out.add(p.getConstructorParameter());
      }
    } catch (Throwable ignored) {
      // whatever was collected is what we use
    }
    return out;
  }

  private static boolean anyMemberNonNull(BeanPropertyDefinition p) {
    for (AnnotatedMember m : members(p)) {
      if (memberNonNull(m)) {
        return true;
      }
    }
    return false;
  }

  private static boolean anyMemberNullable(BeanPropertyDefinition p) {
    for (AnnotatedMember m : members(p)) {
      if (nullableMember(m)) {
        return true;
      }
    }
    return false;
  }

  private static boolean memberNonNull(AnnotatedMember m) {
    try {
      JsonInclude a = m.getAnnotation(JsonInclude.class);
      if (a == null) {
        return false;
      }
      return a.value() == JsonInclude.Include.NON_NULL || a.value() == JsonInclude.Include.NON_ABSENT;
    } catch (Throwable t) {
      return false;
    }
  }

  private static boolean nullableMember(AnnotatedMember m) {
    try {
      for (java.lang.annotation.Annotation a : m.getAnnotated() instanceof java.lang.reflect.AnnotatedElement
          ? ((java.lang.reflect.AnnotatedElement) m.getAnnotated()).getAnnotations()
          : new java.lang.annotation.Annotation[0]) {
        String n = a.annotationType().getSimpleName();
        if (n.equals("Nullable") || n.equals("CheckForNull")) {
          return true;
        }
      }
    } catch (Throwable ignored) {
      // fall through
    }
    return false;
  }

  private static boolean hasDefaultMarker(AnnotatedMember m) {
    return false; // model defaults are not declared in this corpus; see decisions.md
  }

  private Schema enumSchema(Class<?> raw, Side side) {
    List<String> names = new ArrayList<>();
    for (Object o : raw.getEnumConstants()) {
      names.add(((Enum<?>) o).name());
    }
    boolean open = (side == Side.ACCEPT) ? enumsOpenOnAccept : enumsOpenOnReturn;
    if (open) {
      // D8: where the mapper on that side accepts an unknown constant, a
      // closed enum would make enum-request-narrowing fire on a value the
      // service in fact tolerates.
      diag.count("enums-open");
      return Schema.prim("string", "");
    }
    diag.count("enums-closed");
    return Schema.enumOf(names, "string");
  }

  // --- helpers ---

  private AnnotatedMember accessorFor(BeanPropertyDefinition p, Side side) {
    try {
      AnnotatedMember m = (side == Side.RETURN) ? p.getAccessor() : p.getMutator();
      if (m == null) {
        m = p.getPrimaryMember();
      }
      return m;
    } catch (Throwable t) {
      return null;
    }
  }

  private static AnnotatedMember safeJsonValue(BeanDescription bd) {
    try {
      return bd.findJsonValueAccessor();
    } catch (Throwable t) {
      return null;
    }
  }

  private static boolean hasAnyAccessor(BeanDescription bd, Side side) {
    try {
      return (side == Side.RETURN ? bd.findAnyGetter() : bd.findAnySetterAccessor()) != null;
    } catch (Throwable t) {
      return false;
    }
  }

  static boolean isJdk(String name) {
    return name.startsWith("java.") || name.startsWith("javax.") || name.startsWith("jakarta.")
        || name.startsWith("sun.") || name.startsWith("com.sun.") || name.startsWith("jdk.");
  }

  private static boolean isJsonNode(Class<?> c) {
    for (Class<?> k = c; k != null; k = k.getSuperclass()) {
      if (k.getName().equals("com.fasterxml.jackson.databind.JsonNode")) {
        return true;
      }
    }
    return false;
  }

  static Schema primitive(Class<?> c) {
    String n = c.getName();
    switch (n) {
      case "boolean": case "java.lang.Boolean": return Schema.prim("boolean", "");
      case "byte": case "java.lang.Byte":
      case "short": case "java.lang.Short":
      case "int": case "java.lang.Integer": return Schema.prim("integer", "int32");
      case "long": case "java.lang.Long":
      case "java.math.BigInteger": return Schema.prim("integer", "int64");
      case "float": case "java.lang.Float": return Schema.prim("number", "float");
      case "double": case "java.lang.Double": return Schema.prim("number", "double");
      case "java.math.BigDecimal": return Schema.prim("number", "double");
      case "char": case "java.lang.Character":
      case "java.lang.String":
      case "java.lang.CharSequence":
      case "groovy.lang.GString": return Schema.prim("string", "");
      case "java.util.UUID": return Schema.prim("string", "uuid");
      case "java.net.URI": case "java.net.URL": return Schema.prim("string", "uri");
      case "java.util.Date":
      case "java.time.Instant":
      case "java.time.OffsetDateTime":
      case "java.time.ZonedDateTime":
      case "java.time.LocalDateTime": return Schema.prim("string", "date-time");
      case "java.time.LocalDate": return Schema.prim("string", "date");
      case "java.time.Duration": return Schema.prim("string", "");
      default: return null;
    }
  }

  private void register(String comp, String owner, Schema s) {
    String prev = componentOwner.get(comp);
    if (prev != null && !prev.equals(owner)) {
      diag.loss("component-name-collision", comp + ": " + prev + " vs " + owner);
    }
    componentOwner.put(comp, owner);
    components.put(comp, s);
  }

  /**
   * CLAIM-S5-019: name a component after the Java simple class name, so that a
   * caller's document and a provider's document agree at a recursive back-edge
   * (ref-name-mismatch compares the local component name, compat.go:270-296).
   */
  static String componentName(Class<?> c) {
    String n = c.getSimpleName();
    Class<?> outer = c.getEnclosingClass();
    while (outer != null) {
      n = outer.getSimpleName() + "." + n;
      outer = outer.getEnclosingClass();
    }
    return n.replace('$', '.');
  }
}
