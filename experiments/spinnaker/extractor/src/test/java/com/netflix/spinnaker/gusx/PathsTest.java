package com.netflix.spinnaker.gusx;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;
import org.junit.jupiter.api.Test;

/** D3 normalization, as R1(a) fixed it. */
class PathsTest {

  @Test
  void leadingSlashIsForced() {
    // 101 of S1's 564 rows are Retrofit-2 relative paths (CLAIM-S1-031).
    assertEquals("/roles/sync", Paths.normalize("roles/sync"));
    assertEquals("/roles/sync", Paths.normalize("/roles/sync"));
  }

  @Test
  void dotIsTheBaseUrl() {
    assertEquals("/", Paths.normalize("."));
    assertEquals("/", Paths.normalize(""));
  }

  @Test
  void bakedInQueryStringIsStripped() {
    assertEquals("/v2/applications", Paths.normalize("/v2/applications?restricted=false"));
  }

  @Test
  void bakedInQueryStringIsReadable() {
    List<String[]> q = Paths.bakedQuery("/pipelines/triggeredBy/{id}/{status}?restricted=false&x=1");
    assertEquals(2, q.size());
    assertEquals("restricted", q.get(0)[0]);
    assertEquals("false", q.get(0)[1]);
    assertEquals("x", q.get(1)[0]);
    assertEquals("1", q.get(1)[1]);
  }

  @Test
  void regexGoesButTheNameStays() {
    // CLAIM-S5-020: 79 sites carry a regex. The name is what keys params (D6).
    assertEquals("/jobs/{master}", Paths.normalize("/jobs/{master:.+}"));
    assertEquals("/a/{x}/b/{y}", Paths.normalize("/a/{x:[0-9]+}/b/{y}"));
  }

  @Test
  void doubledAndTrailingSlashesGo() {
    assertEquals("/a/b", Paths.normalize("//a//b/"));
    assertEquals("/", Paths.normalize("/"));
  }

  @Test
  void classPrefixJoinsWithoutADoubleSlash() {
    assertEquals("/pipelines", Paths.join("pipelines", ""));
    assertEquals("/pipelines/{id}", Paths.join("/pipelines", "/{id}"));
    assertEquals("/pipelines/{id}", Paths.join("pipelines", "{id}"));
  }

  @Test
  void matchKeyErasesVariableNames() {
    assertEquals("/a/{}/b/{}", Paths.matchKey("/a/{x}/b/{y:.+}"));
  }
}
