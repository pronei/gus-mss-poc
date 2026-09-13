package com.netflix.spinnaker.gusx;

import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.lang.reflect.WildcardType;
import java.util.List;

/** Reflected generic types: unwrapping, erasure, and the contentless set. */
public final class Types {

  /** Wrappers that carry the payload one level down (CLAIM-S5-003/050/051). */
  private static final List<String> WRAPPERS =
      List.of(
          "org.springframework.http.ResponseEntity",
          "org.springframework.http.HttpEntity",
          "org.springframework.web.context.request.async.DeferredResult",
          "java.util.concurrent.Callable",
          "java.util.concurrent.CompletableFuture",
          "java.util.Optional",
          "retrofit2.Call",
          "retrofit2.Response",
          "reactor.core.publisher.Mono",
          "reactor.core.publisher.Flux",
          "kotlinx.coroutines.Deferred");

  /**
   * D5/D6: a side with no JSON shape at all. Both caller and provider must
   * emit a contentless 200 for these, or {@code nil} against a schema is a
   * presence-mismatch BREAK (compat.go:62-68).
   */
  private static final List<String> CONTENTLESS =
      List.of(
          "void",
          "java.lang.Void",
          "kotlin.Unit",
          "okhttp3.ResponseBody",
          "com.squareup.okhttp.ResponseBody",
          "retrofit.client.Response",
          "org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody",
          "org.springframework.core.io.Resource",
          "org.springframework.core.io.InputStreamResource",
          "org.springframework.core.io.ByteArrayResource",
          "java.io.InputStream",
          "okhttp3.RequestBody");

  /**
   * Unwrap a return type to the thing that reaches the wire, or null when the
   * response is contentless.
   */
  public static Type unwrapResponse(Type t, Diag diag) {
    Type cur = t;
    for (int i = 0; i < 8; i++) {
      Class<?> raw = erase(cur);
      if (raw == null) {
        return cur;
      }
      String n = raw.getName();
      if (CONTENTLESS.contains(n)) {
        return null;
      }
      if (raw.isArray() && raw.getComponentType() == byte.class) {
        return null; // byte[] is a stream, not a JSON shape
      }
      if (WRAPPERS.contains(n)) {
        Type inner = firstArg(cur);
        if (inner == null) {
          // A raw ResponseEntity carries no declared shape (S2: raw-generic).
          return null;
        }
        cur = inner;
        continue;
      }
      return cur;
    }
    if (diag != null) {
      diag.loss("unwrap-depth", String.valueOf(t));
    }
    return cur;
  }

  /** True when the outermost type is a generic container used raw. */
  public static boolean isRawGeneric(Type t) {
    Class<?> raw = erase(t);
    if (raw == null) {
      return false;
    }
    if (!(t instanceof ParameterizedType) && raw.getTypeParameters().length > 0) {
      String n = raw.getName();
      return WRAPPERS.contains(n)
          || n.equals("java.util.List")
          || n.equals("java.util.Collection")
          || n.equals("java.util.Set")
          || n.equals("java.util.Map");
    }
    return false;
  }

  public static Type firstArg(Type t) {
    if (t instanceof ParameterizedType) {
      Type[] a = ((ParameterizedType) t).getActualTypeArguments();
      if (a.length > 0) {
        return unwild(a[0]);
      }
    }
    return null;
  }

  public static Type elementType(Type t) {
    Class<?> raw = erase(t);
    if (raw != null && raw.isArray()) {
      return raw.getComponentType();
    }
    return firstArg(t);
  }

  private static Type unwild(Type t) {
    if (t instanceof WildcardType) {
      Type[] up = ((WildcardType) t).getUpperBounds();
      if (up.length > 0) {
        return up[0];
      }
    }
    return t;
  }

  public static Class<?> erase(Type t) {
    if (t instanceof Class) {
      return (Class<?>) t;
    }
    if (t instanceof ParameterizedType) {
      return erase(((ParameterizedType) t).getRawType());
    }
    if (t instanceof java.lang.reflect.GenericArrayType) {
      return java.lang.reflect.Array.newInstance(
          erase(((java.lang.reflect.GenericArrayType) t).getGenericComponentType()), 0).getClass();
    }
    if (t instanceof java.lang.reflect.TypeVariable) {
      java.lang.reflect.Type[] b = ((java.lang.reflect.TypeVariable<?>) t).getBounds();
      return b.length > 0 ? erase(b[0]) : Object.class;
    }
    if (t instanceof WildcardType) {
      return erase(unwild(t));
    }
    return null;
  }

  private Types() {}
}
