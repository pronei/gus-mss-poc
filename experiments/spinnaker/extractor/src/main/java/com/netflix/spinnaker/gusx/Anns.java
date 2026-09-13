package com.netflix.spinnaker.gusx;

import java.lang.annotation.Annotation;
import java.lang.reflect.AnnotatedElement;
import java.lang.reflect.Array;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * Annotations read by name.
 *
 * <p>Nothing here compiles against Spring or Retrofit. The extractor sees
 * nine services spanning Spring 4 to 6 and both Retrofit generations
 * (CLAIM-S1-018); binding to any one of them at compile time would make the
 * tool version-specific for no gain, since every attribute it needs
 * ({@code value}, {@code path}, {@code method}, {@code required},
 * {@code defaultValue}, {@code consumes}, {@code produces}) has been stable
 * under those names throughout.
 */
public final class Anns {

  /** The annotation on {@code el} whose type has one of these binary names. */
  public static Annotation on(AnnotatedElement el, String... names) {
    for (Annotation a : safeAnnotations(el)) {
      String n = a.annotationType().getName();
      for (String want : names) {
        if (n.equals(want)) {
          return a;
        }
      }
    }
    return null;
  }

  /** The annotation on {@code el} whose type's <em>simple</em> name matches. */
  public static Annotation onSimple(AnnotatedElement el, String... simpleNames) {
    for (Annotation a : safeAnnotations(el)) {
      String n = a.annotationType().getSimpleName();
      for (String want : simpleNames) {
        if (n.equals(want)) {
          return a;
        }
      }
    }
    return null;
  }

  public static boolean hasSimple(AnnotatedElement el, String... simpleNames) {
    return onSimple(el, simpleNames) != null;
  }

  /**
   * Annotations of an element, or an empty list. {@code getAnnotations} throws
   * when an annotation type is missing from the classpath, which happens on a
   * runtime classpath assembled for a different profile.
   */
  public static List<Annotation> safeAnnotations(AnnotatedElement el) {
    try {
      Annotation[] as = el.getAnnotations();
      List<Annotation> out = new ArrayList<>(as.length);
      for (Annotation a : as) {
        out.add(a);
      }
      return out;
    } catch (Throwable t) {
      return List.of();
    }
  }

  /** An attribute of an annotation, or null if absent or unreadable. */
  public static Object attr(Annotation a, String name) {
    if (a == null) {
      return null;
    }
    try {
      Method m = a.annotationType().getMethod(name);
      return m.invoke(a);
    } catch (Throwable t) {
      return null;
    }
  }

  /** A String attribute, empty string when absent. */
  public static String str(Annotation a, String name) {
    Object o = attr(a, name);
    return (o instanceof String) ? (String) o : "";
  }

  public static boolean bool(Annotation a, String name, boolean dflt) {
    Object o = attr(a, name);
    return (o instanceof Boolean) ? (Boolean) o : dflt;
  }

  /**
   * A String[] attribute flattened to a list; a scalar String is wrapped. An
   * absent attribute gives an empty list.
   */
  public static List<String> strings(Annotation a, String name) {
    Object o = attr(a, name);
    List<String> out = new ArrayList<>();
    if (o == null) {
      return out;
    }
    if (o instanceof String) {
      if (!((String) o).isEmpty()) {
        out.add((String) o);
      }
      return out;
    }
    if (o.getClass().isArray()) {
      int n = Array.getLength(o);
      for (int i = 0; i < n; i++) {
        Object e = Array.get(o, i);
        if (e != null) {
          String s = String.valueOf(e);
          if (!s.isEmpty()) {
            out.add(s);
          }
        }
      }
    }
    return out;
  }

  /**
   * The first non-empty of a list of attributes. Spring's mapping annotations
   * carry the path under both {@code value} and {@code path} (aliases), and
   * Retrofit carries it under {@code value} only.
   */
  public static List<String> firstNonEmpty(Annotation a, String... names) {
    for (String n : names) {
      List<String> v = strings(a, n);
      if (!v.isEmpty()) {
        return v;
      }
    }
    return List.of();
  }

  private Anns() {}
}
