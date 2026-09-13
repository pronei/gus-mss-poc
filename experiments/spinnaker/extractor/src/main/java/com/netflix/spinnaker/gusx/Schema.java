package com.netflix.spinnaker.gusx;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * One OpenAPI 3.0 schema object.
 *
 * <p>A thin ordered map rather than a type hierarchy, because every rule the
 * projection has to honour is a statement about which keys are emitted
 * together — {@code additionalProperties: true} beside {@code properties} is
 * an open object, an {@code additionalProperties} <em>schema</em> beside
 * {@code properties} is a hard loader error (loader.go:531), and
 * {@code Object} must never become {@code {}} (loader.go:462). Keeping the
 * keys explicit keeps those rules readable.
 */
public final class Schema {

  /** Emission order, fixed so that golden files are stable. */
  static final List<String> KEY_ORDER =
      List.of(
          "$ref", "type", "format", "nullable", "enum", "items", "properties",
          "required", "additionalProperties", "oneOf", "default",
          "x-untyped", "x-non-null", "x-provides", "x-requires", "x-alias", "x-java-type",
          "x-note");

  public final Map<String, Object> keys = new LinkedHashMap<>();

  public static Schema of() {
    return new Schema();
  }

  public Schema put(String k, Object v) {
    keys.put(k, v);
    return this;
  }

  public Object get(String k) {
    return keys.get(k);
  }

  public boolean has(String k) {
    return keys.containsKey(k);
  }

  public boolean isUntyped() {
    return Boolean.TRUE.equals(keys.get("x-untyped"));
  }

  // --- constructors for the shapes the projection uses ---

  public static Schema ref(String component) {
    return of().put("$ref", "#/components/schemas/" + component);
  }

  public static Schema prim(String type, String format) {
    Schema s = of().put("type", type);
    if (format != null && !format.isEmpty()) {
      s.put("format", format);
    }
    return s;
  }

  /**
   * D5: {@code Object}, {@code JsonNode}, a raw {@code Map}, {@code Map<String,Object>}
   * and Groovy {@code def} all project here — an open object, never
   * {@code {}}. An empty schema loads as {@code types.Any} and short-circuits
   * every comparison (loader.go:462, compat.go:71-73), so a change from
   * {@code Object} to {@code String} would pass silently.
   */
  public static Schema untypedObject() {
    return of().put("type", "object").put("additionalProperties", Boolean.TRUE).put("x-untyped", Boolean.TRUE);
  }

  /** An object that lists its declared fields and admits others. */
  public static Schema object(Map<String, Schema> props, List<String> required, boolean open) {
    Schema s = of().put("type", "object");
    Map<String, Object> p = new TreeMap<>();
    p.putAll(props);
    s.put("properties", p);
    if (required != null && !required.isEmpty()) {
      List<String> r = new ArrayList<>(required);
      r.sort(null);
      s.put("required", r);
    }
    s.put("additionalProperties", open);
    return s;
  }

  public static Schema array(Schema items) {
    Schema s = of().put("type", "array").put("items", items);
    if (items.isUntyped()) {
      s.put("x-untyped", Boolean.TRUE);
    }
    return s;
  }

  /** A typed map: property-less object with a value schema. Loads as types.Map. */
  public static Schema map(Schema value) {
    return of().put("type", "object").put("additionalProperties", value);
  }

  public static Schema enumOf(List<String> values, String base) {
    Schema s = of();
    if (base != null && !base.isEmpty()) {
      s.put("type", base);
    }
    List<String> v = new ArrayList<>(values);
    v.sort(null);
    s.put("enum", v);
    return s;
  }

  public Schema nullable() {
    keys.put("nullable", Boolean.TRUE);
    return this;
  }

  public Schema untyped() {
    keys.put("x-untyped", Boolean.TRUE);
    return this;
  }
}
