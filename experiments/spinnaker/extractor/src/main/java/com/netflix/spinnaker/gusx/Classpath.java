package com.netflix.spinnaker.gusx;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Reads the runtime classpath out of a service's start script.
 *
 * <p>D1(b): the service's own jars are unversioned in the gcr.io era
 * ({@code gate-web.jar}) and versioned in the GAR era
 * ({@code gate-web-6.69.0.jar}), so a file-name pattern breaks across the
 * boundary. The Gradle start script writes one literal line,
 * {@code CLASSPATH=$APP_HOME/config:$APP_HOME/lib/a.jar:...}, in dependency
 * order; that line is the classpath.
 */
public final class Classpath {

  /** Entries of the CLASSPATH= line, in order, that exist under {@code dir}. */
  public static List<File> read(File dir, String service) throws IOException {
    File script = new File(new File(dir, "bin"), service);
    if (!script.isFile()) {
      throw new IOException(
          "no start script at " + script + " (expected G2's layout: bin/<svc>, lib/*.jar)");
    }
    String line = null;
    try (BufferedReader r = new BufferedReader(new FileReader(script))) {
      String s;
      while ((s = r.readLine()) != null) {
        // The script also carries a Windows CLASSPATH under a different name;
        // take the first POSIX assignment.
        if (s.startsWith("CLASSPATH=")) {
          line = s.substring("CLASSPATH=".length());
          break;
        }
      }
    }
    if (line == null) {
      throw new IOException("no CLASSPATH= line in " + script);
    }
    List<File> out = new ArrayList<>();
    for (String raw : line.split(":")) {
      String e = raw.trim();
      if (e.isEmpty()) {
        continue;
      }
      // $APP_HOME is the directory the script lives beside.
      e = e.replace("$APP_HOME/", "").replace("${APP_HOME}/", "");
      File f = new File(dir, e);
      if (f.exists()) {
        out.add(f);
      }
    }
    if (out.isEmpty()) {
      throw new IOException("CLASSPATH= in " + script + " resolved to nothing under " + dir);
    }
    return out;
  }

  /** The jar entries only, in classpath order. */
  public static List<File> jars(List<File> entries) {
    List<File> out = new ArrayList<>();
    for (File f : entries) {
      if (f.isFile() && f.getName().endsWith(".jar")) {
        out.add(f);
      }
    }
    return out;
  }

  private Classpath() {}
}
