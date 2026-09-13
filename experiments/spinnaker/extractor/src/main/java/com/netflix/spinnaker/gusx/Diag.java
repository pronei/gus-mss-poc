package com.netflix.spinnaker.gusx;

import java.io.File;
import java.io.IOException;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * What the extraction could not do, and how often.
 *
 * <p>The plan's discipline is that a loss is reported, never absorbed: an
 * endpoint whose parameter has no name is flagged rather than guessed at
 * (D1(a)), a polymorphic base whose subtypes come from Spring beans is
 * counted as an accepted loss (CLAIM-S5-012), a response code other than the
 * lowest 2xx is dropped and counted (D6).
 */
public final class Diag {

  public final Map<String, Integer> counts = new TreeMap<>();
  public final Map<String, List<String>> losses = new TreeMap<>();
  public final List<String> flagged = new ArrayList<>();

  public void count(String k) {
    counts.merge(k, 1, Integer::sum);
  }

  public void count(String k, int n) {
    counts.merge(k, n, Integer::sum);
  }

  public void loss(String kind, String detail) {
    losses.computeIfAbsent(kind, k -> new ArrayList<>()).add(detail);
    count("loss." + kind);
  }

  /** An endpoint that is emitted but that a consumer must not trust blindly. */
  public void flag(String endpoint, String why) {
    flagged.add(endpoint + " :: " + why);
    count("flagged-endpoints");
  }

  public void writeJson(File f) throws IOException {
    f.getAbsoluteFile().getParentFile().mkdirs();
    try (PrintWriter w = new PrintWriter(f, StandardCharsets.UTF_8)) {
      w.println("{");
      w.println("  \"counts\": {");
      List<String> ks = new ArrayList<>(counts.keySet());
      for (int i = 0; i < ks.size(); i++) {
        w.printf("    %s: %d%s%n", q(ks.get(i)), counts.get(ks.get(i)), i + 1 < ks.size() ? "," : "");
      }
      w.println("  },");
      w.println("  \"flagged\": [");
      List<String> fl = new ArrayList<>(flagged);
      fl.sort(null);
      for (int i = 0; i < fl.size(); i++) {
        w.printf("    %s%s%n", q(fl.get(i)), i + 1 < fl.size() ? "," : "");
      }
      w.println("  ],");
      w.println("  \"losses\": {");
      List<String> lk = new ArrayList<>(losses.keySet());
      for (int i = 0; i < lk.size(); i++) {
        List<String> v = new ArrayList<>(losses.get(lk.get(i)));
        v.sort(null);
        w.printf("    %s: [%n", q(lk.get(i)));
        for (int j = 0; j < v.size(); j++) {
          w.printf("      %s%s%n", q(v.get(j)), j + 1 < v.size() ? "," : "");
        }
        w.printf("    ]%s%n", i + 1 < lk.size() ? "," : "");
      }
      w.println("  }");
      w.println("}");
    }
  }

  private static String q(String s) {
    StringBuilder b = new StringBuilder("\"");
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      switch (c) {
        case '"': b.append("\\\""); break;
        case '\\': b.append("\\\\"); break;
        case '\n': b.append("\\n"); break;
        case '\r': b.append("\\r"); break;
        case '\t': b.append("\\t"); break;
        default:
          if (c < 0x20) {
            b.append(String.format("\\u%04x", (int) c));
          } else {
            b.append(c);
          }
      }
    }
    return b.append('"').toString();
  }
}
