package com.netflix.spinnaker.gusx;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * S1's hand-verified interface to provider binding
 * ({@code scout/S1/tools/mesh.tsv}).
 *
 * <p>Columns are {@code caller, repo_path, provider, resolved_by}. Three
 * repo_path values are tokens rather than paths, for the interfaces declared
 * in one artifact and compiled into others: {@code FIATAPI} (fiat-api's
 * {@code FiatService}), {@code HEALTH:<provider>} (Gate's
 * {@code HealthCheckableService}) and {@code KORK} (kork-plugins'
 * {@code Front50Service}, CLAIM-S1-022).
 */
public final class Mesh {

  public static final class Binding {
    public final String caller;
    public final String provider;
    public final String resolvedBy;
    public final String token;
    /** The interface's simple name, from the repo path or the token. */
    public final String iface;
    /** The declaring class, which is the only unambiguous key (see below). */
    public final String className;

    Binding(String caller, String provider, String resolvedBy, String token, String iface,
            String className) {
      this.caller = caller;
      this.provider = provider;
      this.resolvedBy = resolvedBy;
      this.token = token;
      this.iface = iface;
      this.className = className;
    }
  }

  /**
   * caller -> interface simple name -> bindings.
   *
   * <p>A list, not a single binding: Gate's {@code HealthCheckableService} is
   * one interface instantiated once per entry of
   * {@code healthCheckableServices} and is the only interface in the corpus
   * bound to more than one provider (CLAIM-S1-005). Six of its providers are
   * among the nine.
   */
  public final Map<String, Map<String, List<Binding>>> byCaller = new LinkedHashMap<>();
  public final List<Binding> all = new ArrayList<>();

  public Mesh(File tsv) throws IOException {
    try (BufferedReader r = new BufferedReader(new FileReader(tsv))) {
      String line = r.readLine(); // header
      while ((line = r.readLine()) != null) {
        if (line.isBlank()) {
          continue;
        }
        String[] f = line.split("\t", -1);
        if (f.length < 4) {
          continue;
        }
        String caller = f[0].trim();
        String repoPath = f[1].trim();
        String provider = f[2].trim();
        String resolvedBy = f[3].trim();
        String token = "";
        String fqcn;
        if (repoPath.equals("FIATAPI")) {
          token = "FIATAPI";
          fqcn = "com.netflix.spinnaker.fiat.shared.FiatService";
        } else if (repoPath.equals("KORK")) {
          token = "KORK";
          fqcn = "com.netflix.spinnaker.kork.plugins.update.internal.Front50Service";
        } else if (repoPath.startsWith("HEALTH:")) {
          token = repoPath;
          fqcn = "com.netflix.spinnaker.gate.services.internal.HealthCheckableService";
        } else {
          fqcn = classNameOf(repoPath);
        }
        String iface = fqcn.substring(fqcn.lastIndexOf('.') + 1);
        Binding b = new Binding(caller, provider, resolvedBy, token, iface, fqcn);
        all.add(b);
        byCaller
            .computeIfAbsent(caller, k -> new LinkedHashMap<>())
            .computeIfAbsent(fqcn, k -> new ArrayList<>())
            .add(b);
      }
    }
  }

  /**
   * The providers one of a caller's Retrofit interfaces is bound to, keyed by
   * the DECLARING CLASS; empty when S1 left it unresolved or out of mesh.
   *
   * <p>Keying on the simple name is wrong and S1 says so: "Front50Service is
   * declared six times in the ten plus once in kork, EchoService five times
   * ... join on claim, not on interface" (clients.md, Conventions 5). Under a
   * simple-name key Gate's own {@code Front50Service} and the kork-plugins one
   * each matched both bindings, and each interface was walked twice
   * (CLAIM-G1-013).
   */
  public List<Binding> lookup(String caller, String className) {
    Map<String, List<Binding>> m = byCaller.get(caller);
    if (m == null) {
      return List.of();
    }
    List<Binding> b = m.get(className);
    return b == null ? List.of() : b;
  }

  /**
   * The Java class a repo path declares: everything after the source root,
   * dots for slashes, extension dropped.
   */
  static String classNameOf(String repoPath) {
    String p = repoPath;
    for (String root : new String[] {"/src/main/java/", "/src/main/groovy/", "/src/main/kotlin/"}) {
      int i = p.indexOf(root);
      if (i >= 0) {
        p = p.substring(i + root.length());
        break;
      }
    }
    int dot = p.lastIndexOf('.');
    if (dot > 0) {
      p = p.substring(0, dot);
    }
    return p.replace('/', '.');
  }
}
