package com.netflix.spinnaker.gusx;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class YamlTest {

  @Test
  void schemaKeysComeOutInTheFixedOrder() {
    Schema s = Schema.of();
    s.put("x-untyped", Boolean.TRUE);
    s.put("additionalProperties", Boolean.TRUE);
    s.put("type", "object");
    Map<String, Object> doc = new LinkedHashMap<>();
    doc.put("schema", s);
    assertEquals(
        "schema:\n  type: object\n  additionalProperties: true\n  x-untyped: true\n",
        Yaml.write(doc));
  }

  @Test
  void pathsThatWouldReadAsSomethingElseAreQuoted() {
    Map<String, Object> doc = new LinkedHashMap<>();
    Map<String, Object> paths = new LinkedHashMap<>();
    paths.put("/a/{id}", new LinkedHashMap<String, Object>());
    paths.put("/plain", new LinkedHashMap<String, Object>());
    doc.put("paths", paths);
    String out = Yaml.write(doc);
    assertTrue(out.contains("\"/a/{id}\": {}"), out);
    assertTrue(out.contains("/plain: {}"), out);
  }

  @Test
  void listsOfSchemasNest() {
    Map<String, Object> doc = new LinkedHashMap<>();
    doc.put("oneOf", List.of(Schema.prim("string", ""), Schema.prim("integer", "int32")));
    assertEquals(
        "oneOf:\n  -\n    type: string\n  -\n    type: integer\n    format: int32\n",
        Yaml.write(doc));
  }

  @Test
  void emptyContainersAreInline() {
    Map<String, Object> doc = new LinkedHashMap<>();
    doc.put("schemas", new LinkedHashMap<String, Object>());
    doc.put("required", List.of());
    assertEquals("schemas: {}\nrequired: []\n", Yaml.write(doc));
  }

  @Test
  void scalarsThatLookNumericOrBooleanAreQuoted() {
    Map<String, Object> doc = new LinkedHashMap<>();
    doc.put("a", "true");
    doc.put("b", "12");
    doc.put("c", Boolean.TRUE);
    doc.put("d", "ok");
    assertEquals("a: \"true\"\nb: \"12\"\nc: true\nd: ok\n", Yaml.write(doc));
  }
}
