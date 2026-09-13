package com.netflix.spinnaker.gusx;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.Module;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * Builds the service's own configured {@link ObjectMapper}.
 *
 * <p>D1(c)/D7 require the Jackson-visible shape to be read through the mapper
 * the service actually installs, not through plain reflection. Two recipes
 * cover the corpus:
 *
 * <ul>
 *   <li>a service that declares its mapper through a static factory — Orca's
 *       {@code OrcaObjectMapper.newInstance()} is the {@code objectMapper}
 *       bean (D4, WebConfiguration.groovy:66) — is built by calling it;
 *   <li>every other service lets Spring Boot build the MVC mapper from
 *       {@code Jackson2ObjectMapperBuilder.json()} and auto-registers every
 *       {@code Module} bean on the context. That is reproduced by building
 *       from the same Spring class (which is on the service's own classpath)
 *       and registering the service-owned modules found on it.
 * </ul>
 *
 * <p>What this cannot reproduce is a module that is configured in the bean
 * method rather than in its own constructor, or a subtype registered from a
 * Spring bean at runtime (CLAIM-S5-012). Both are reported as losses, not
 * absorbed.
 */
public final class Mapper {

  public final ObjectMapper mapper;
  public final List<String> modulesRegistered = new ArrayList<>();
  public final List<String> modulesFailed = new ArrayList<>();
  public final String recipe;

  /** Static factories that ARE the service's mapper bean, by service. */
  private static final java.util.Map<String, String[]> FACTORY =
      java.util.Map.of(
          "orca", new String[] {"com.netflix.spinnaker.orca.jackson.OrcaObjectMapper", "newInstance"});

  /** Packages whose Jackson modules belong to the mesh rather than to a library. */
  private static final String[] OWNED_PREFIXES = {
    "com.netflix.spinnaker.", "com.netflix.kayenta.", "com.netflix.frigga."
  };

  public Mapper(String service, ClassIndex index, ClassLoader cl, Diag diag) {
    ObjectMapper m = null;
    String how = null;

    String[] f = FACTORY.get(service);
    if (f != null) {
      try {
        Class<?> k = Class.forName(f[0], true, cl);
        Method mm = k.getMethod(f[1]);
        m = (ObjectMapper) mm.invoke(null);
        how = "static factory " + f[0] + "." + f[1] + "()";
      } catch (Throwable t) {
        diag.loss("mapper-factory", f[0] + ": " + t);
      }
    }

    if (m == null) {
      try {
        Class<?> b =
            Class.forName("org.springframework.http.converter.json.Jackson2ObjectMapperBuilder", true, cl);
        Object builder = b.getMethod("json").invoke(null);
        m = (ObjectMapper) b.getMethod("build").invoke(builder);
        how = "Jackson2ObjectMapperBuilder.json().build() + service modules";
      } catch (Throwable t) {
        diag.loss("mapper-spring-builder", String.valueOf(t));
      }
    }
    if (m == null) {
      m = new ObjectMapper();
      // Spring Boot's MVC mapper disables this; without Spring on the
      // classpath the default would misreport openness (D5).
      m.configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
      how = "plain ObjectMapper (Spring builder unavailable) + service modules";
    }

    for (String cn : findModules(index, cl, diag)) {
      try {
        Class<?> k = Class.forName(cn, true, cl);
        Object o = k.getDeclaredConstructor().newInstance();
        m.registerModule((Module) o);
        modulesRegistered.add(cn);
      } catch (Throwable t) {
        modulesFailed.add(cn + ": " + t.getClass().getSimpleName());
        diag.loss("module-instantiation", cn + ": " + t);
      }
    }
    this.mapper = m;
    this.recipe = how;
  }

  /**
   * Service-owned Jackson modules on the classpath, in classpath order. The
   * prefilter is the {@code SimpleModule} superclass name in the constant
   * pool; the confirmation is that the class is a concrete {@code Module}
   * with a public no-argument constructor.
   */
  private static List<String> findModules(ClassIndex index, ClassLoader cl, Diag diag) {
    List<String> out = new ArrayList<>();
    List<String> cands;
    try {
      cands = index.candidates("com/fasterxml/jackson/databind/module/SimpleModule");
    } catch (Exception e) {
      diag.loss("module-scan", String.valueOf(e));
      return out;
    }
    for (String cn : cands) {
      boolean owned = false;
      for (String p : OWNED_PREFIXES) {
        if (cn.startsWith(p)) {
          owned = true;
          break;
        }
      }
      if (!owned) {
        continue;
      }
      try {
        Class<?> k = Class.forName(cn, false, cl);
        if (k.isInterface() || java.lang.reflect.Modifier.isAbstract(k.getModifiers())) {
          continue;
        }
        if (!Module.class.isAssignableFrom(k)) {
          continue;
        }
        k.getDeclaredConstructor(); // must be no-arg
        out.add(cn);
      } catch (Throwable ignored) {
        // Not instantiable without arguments, or not loadable: not a module we
        // can install. Counted only when we try above.
      }
    }
    return out;
  }

  /**
   * D8: closedness is read from the mapper, not assumed. A side whose mapper
   * tolerates an unknown constant must project the enum open
   * ({@code type: string}), or enum-request-narrowing fires into a service
   * that in fact accepts the value.
   */
  public boolean enumsOpenOnAccept() {
    return mapper.isEnabled(DeserializationFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
        || mapper.isEnabled(DeserializationFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE);
  }
}
