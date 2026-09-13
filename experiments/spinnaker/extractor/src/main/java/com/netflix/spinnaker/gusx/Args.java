package com.netflix.spinnaker.gusx;

import java.io.File;

/** Command line. Kept tiny so that it can be parsed on both sides of the loader boundary. */
public final class Args {

  public static final String USAGE =
      String.join(
          "\n",
          "usage: gus-contract-extractor --classpath <dir> --service <name> --out <file.yaml>",
          "                             [--mesh <mesh.tsv>] [--diag <file.json>]",
          "                             [--version <v>] [--sides provider|client|both]",
          "                             [--kork-rows keep|drop] [--indirect-fiat keep|drop]",
          "                             [--presence declared|none]",
          "",
          "  --classpath  a directory laid out as G2 lays it out: bin/<svc> and lib/*.jar",
          "  --service    gate | orca | clouddriver | front50 | echo | igor | fiat | rosco | kayenta",
          "  --out        the OpenAPI 3.0 document to write",
          "  --mesh       scout/S1/tools/mesh.tsv, for the Retrofit interface -> provider binding",
          "  --diag       a JSON diagnostics file: flagged endpoints, losses, counts",
          "  --sides      which halves to emit (default both)",
          "",
          "  The last three flags are the owner's open decisions (decisions.md); both",
          "  variants are emitted on demand and neither is decided here.");

  public File classpathDir;
  public String service;
  public File out;
  public File mesh;
  public File diag;
  public String version = "";
  public String sides = "both";
  public boolean korkRows = true;
  public boolean indirectFiat = true;
  public boolean presenceDeclared = true;

  public static Args parse(String[] argv) {
    Args a = new Args();
    for (int i = 0; i < argv.length; i++) {
      String k = argv[i];
      String v = (i + 1 < argv.length) ? argv[i + 1] : null;
      switch (k) {
        case "--classpath": a.classpathDir = new File(req(v, k)); i++; break;
        case "--service":   a.service = req(v, k); i++; break;
        case "--out":       a.out = new File(req(v, k)); i++; break;
        case "--mesh":      a.mesh = new File(req(v, k)); i++; break;
        case "--diag":      a.diag = new File(req(v, k)); i++; break;
        case "--version":   a.version = req(v, k); i++; break;
        case "--sides":     a.sides = req(v, k); i++; break;
        case "--kork-rows":     a.korkRows = "keep".equals(req(v, k)); i++; break;
        case "--indirect-fiat": a.indirectFiat = "keep".equals(req(v, k)); i++; break;
        case "--presence":      a.presenceDeclared = "declared".equals(req(v, k)); i++; break;
        default: return null;
      }
    }
    if (a.classpathDir == null || a.service == null || a.out == null) {
      return null;
    }
    return a;
  }

  private static String req(String v, String k) {
    if (v == null) {
      throw new IllegalArgumentException(k + " needs a value");
    }
    return v;
  }
}
