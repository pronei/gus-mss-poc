package com.netflix.spinnaker.gusx;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * The classpath as bytes: which jar holds which class, and a constant-pool
 * prefilter so that only candidate classes are ever loaded.
 *
 * <p>Loading every class on a Spinnaker classpath (Front50 at 2.41.0 is 408
 * jars) is slow and throws on anything whose optional dependency is absent.
 * An annotation's descriptor — {@code Lorg/springframework/stereotype/Controller;}
 * — appears verbatim as a UTF-8 constant in any class that carries it, so a
 * byte scan is a sound (over-approximating) prefilter.
 */
public final class ClassIndex {

  /** binary class name -> the jar that first defines it, in classpath order. */
  public final Map<String, File> owner = new TreeMap<>();
  /** jar -> its entries, kept open for byte reads. */
  private final List<File> jars;

  public ClassIndex(List<File> jars) throws IOException {
    this.jars = jars;
    for (File jar : jars) {
      try (ZipFile zf = new ZipFile(jar)) {
        Enumeration<? extends ZipEntry> en = zf.entries();
        while (en.hasMoreElements()) {
          ZipEntry e = en.nextElement();
          String n = e.getName();
          if (!n.endsWith(".class") || n.startsWith("META-INF/")) {
            continue;
          }
          String cn = n.substring(0, n.length() - 6).replace('/', '.');
          // Classpath order wins: the first jar that defines a name is the one
          // the class loader will use.
          owner.putIfAbsent(cn, jar);
        }
      } catch (IOException ignored) {
        // A non-jar or unreadable entry on the classpath is not fatal.
      }
    }
  }

  public List<File> jars() {
    return jars;
  }

  /** Raw bytes of a class, or null. */
  public byte[] bytes(String binaryName) {
    File jar = owner.get(binaryName);
    if (jar == null) {
      return null;
    }
    String entry = binaryName.replace('.', '/') + ".class";
    try (ZipFile zf = new ZipFile(jar)) {
      ZipEntry e = zf.getEntry(entry);
      if (e == null) {
        return null;
      }
      try (InputStream in = zf.getInputStream(e)) {
        return in.readAllBytes();
      }
    } catch (IOException ex) {
      return null;
    }
  }

  /**
   * Class names whose bytes contain any of the given descriptors. Result is
   * in classpath order of the defining jar, then class-name order, so the
   * output document does not depend on directory iteration.
   */
  public List<String> candidates(String... descriptors) throws IOException {
    byte[][] needles = new byte[descriptors.length][];
    for (int i = 0; i < descriptors.length; i++) {
      needles[i] = descriptors[i].getBytes(StandardCharsets.UTF_8);
    }
    Map<File, List<String>> byJar = new LinkedHashMap<>();
    for (File jar : jars) {
      byJar.put(jar, new ArrayList<>());
    }
    for (File jar : jars) {
      try (ZipFile zf = new ZipFile(jar)) {
        Enumeration<? extends ZipEntry> en = zf.entries();
        while (en.hasMoreElements()) {
          ZipEntry e = en.nextElement();
          String n = e.getName();
          if (!n.endsWith(".class") || n.startsWith("META-INF/")) {
            continue;
          }
          String cn = n.substring(0, n.length() - 6).replace('/', '.');
          if (!jar.equals(owner.get(cn))) {
            continue; // shadowed by an earlier jar
          }
          byte[] b;
          try (InputStream in = zf.getInputStream(e)) {
            b = in.readAllBytes();
          }
          for (byte[] needle : needles) {
            if (indexOf(b, needle) >= 0) {
              byJar.get(jar).add(cn);
              break;
            }
          }
        }
      } catch (IOException ignored) {
        // skip
      }
    }
    List<String> out = new ArrayList<>();
    for (List<String> v : byJar.values()) {
      v.sort(null);
      out.addAll(v);
    }
    return out;
  }

  static int indexOf(byte[] hay, byte[] needle) {
    outer:
    for (int i = 0; i + needle.length <= hay.length; i++) {
      for (int j = 0; j < needle.length; j++) {
        if (hay[i + j] != needle[j]) {
          continue outer;
        }
      }
      return i;
    }
    return -1;
  }
}
