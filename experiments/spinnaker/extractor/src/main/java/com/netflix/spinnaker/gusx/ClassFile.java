package com.netflix.spinnaker.gusx;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * A minimal class-file reader, present for exactly one reason: parameter
 * names.
 *
 * <p>D1(a): the Spinnaker services are not compiled with {@code -parameters},
 * so {@code MethodParameters} is absent from every jar in the corpus and
 * {@code java.lang.reflect.Parameter#getName} returns {@code arg0}. A name
 * therefore comes from the annotation value first and from
 * {@code LocalVariableTable} second; this class reads the second. Where
 * neither yields a name the endpoint is flagged rather than guessed at.
 */
public final class ClassFile {

  private final byte[] b;
  private int p;
  private Object[] cp;
  /** "name:descriptor" -> parameter slot -> local variable name. */
  private final Map<String, Map<Integer, String>> methodLocals = new HashMap<>();
  /** "name:descriptor" -> is static. */
  private final Map<String, Boolean> methodStatic = new HashMap<>();

  public ClassFile(byte[] bytes) {
    this.b = bytes;
    parse();
  }

  /**
   * Parameter names of a method, in declaration order; an entry is null where
   * the table does not name that slot.
   */
  public String[] parameterNames(String name, String descriptor) {
    String key = name + ":" + descriptor;
    Map<Integer, String> locals = methodLocals.get(key);
    List<String> argTypes = descriptorArgs(descriptor);
    String[] out = new String[argTypes.size()];
    if (locals == null) {
      return out;
    }
    boolean isStatic = Boolean.TRUE.equals(methodStatic.get(key));
    int slot = isStatic ? 0 : 1;
    for (int i = 0; i < argTypes.size(); i++) {
      out[i] = locals.get(slot);
      String t = argTypes.get(i);
      slot += ("J".equals(t) || "D".equals(t)) ? 2 : 1;
    }
    return out;
  }

  /** Top-level argument descriptors of a method descriptor, in order. */
  public static List<String> descriptorArgs(String d) {
    List<String> out = new ArrayList<>();
    int i = d.indexOf('(') + 1;
    int end = d.lastIndexOf(')');
    while (i < end) {
      int start = i;
      while (d.charAt(i) == '[') {
        i++;
      }
      if (d.charAt(i) == 'L') {
        i = d.indexOf(';', i) + 1;
      } else {
        i++;
      }
      out.add(d.substring(start, i));
    }
    return out;
  }

  // --- parsing ---

  private void parse() {
    p = 0;
    u4(); // magic
    u2(); // minor
    u2(); // major
    int cpCount = u2();
    cp = new Object[cpCount];
    for (int i = 1; i < cpCount; i++) {
      int tag = u1();
      switch (tag) {
        case 1: { // Utf8
          int len = u2();
          cp[i] = new String(b, p, len, StandardCharsets.UTF_8);
          p += len;
          break;
        }
        case 7: case 8: case 16: case 19: case 20: p += 2; break;
        case 15: p += 3; break;
        case 3: case 4: case 9: case 10: case 11: case 12: case 17: case 18: p += 4; break;
        case 5: case 6: p += 8; i++; break; // long/double take two slots
        default: throw new IllegalStateException("bad constant pool tag " + tag + " at " + p);
      }
    }
    u2(); // access_flags
    u2(); // this_class
    u2(); // super_class
    int ifaces = u2();
    p += 2 * ifaces;
    skipMembers(); // fields
    int methods = u2();
    for (int i = 0; i < methods; i++) {
      int access = u2();
      String name = utf8(u2());
      String desc = utf8(u2());
      String key = name + ":" + desc;
      methodStatic.put(key, (access & 0x0008) != 0);
      int attrs = u2();
      for (int j = 0; j < attrs; j++) {
        String an = utf8(u2());
        int alen = u4();
        int aend = p + alen;
        if ("Code".equals(an)) {
          readCode(key, aend);
        }
        p = aend;
      }
    }
  }

  private void readCode(String methodKey, int aend) {
    u2(); // max_stack
    u2(); // max_locals
    int codeLen = u4();
    p += codeLen;
    int exc = u2();
    p += 8 * exc;
    int attrs = u2();
    for (int i = 0; i < attrs; i++) {
      String an = utf8(u2());
      int alen = u4();
      int end = p + alen;
      if ("LocalVariableTable".equals(an)) {
        int n = u2();
        Map<Integer, String> slots =
            methodLocals.computeIfAbsent(methodKey, k -> new HashMap<>());
        for (int j = 0; j < n; j++) {
          int startPc = u2();
          u2(); // length
          String nm = utf8(u2());
          u2(); // descriptor
          int idx = u2();
          // Parameters are live from offset 0; a slot reused later in the
          // body would otherwise overwrite the parameter's name.
          if (startPc == 0) {
            slots.putIfAbsent(idx, nm);
          }
        }
      }
      p = end;
    }
    p = aend;
  }

  private void skipMembers() {
    int n = u2();
    for (int i = 0; i < n; i++) {
      p += 6; // access, name, descriptor
      int attrs = u2();
      for (int j = 0; j < attrs; j++) {
        p += 2;
        int alen = u4();
        p += alen;
      }
    }
  }

  private String utf8(int i) {
    Object o = (i >= 0 && i < cp.length) ? cp[i] : null;
    return (o instanceof String) ? (String) o : "";
  }

  private int u1() {
    return b[p++] & 0xff;
  }

  private int u2() {
    return (u1() << 8) | u1();
  }

  private int u4() {
    return (u2() << 16) | u2();
  }
}
