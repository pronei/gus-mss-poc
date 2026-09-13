package com.netflix.spinnaker.gusx;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * The LocalVariableTable fallback of D1(a).
 *
 * <p>The fixture below is compiled by this build without {@code -parameters}
 * — the same way every jar in the corpus was — so its class file is the same
 * shape the extractor meets at run time: no {@code MethodParameters}, a
 * {@code LocalVariableTable} present because {@code -g} is on.
 */
class ClassFileTest {

  /** Deliberately package-private, like eight of Front50's seventeen controllers. */
  @SuppressWarnings("unused")
  static final class Fixture {
    String one(String applicationName) {
      return applicationName;
    }

    String wide(long offset, double ratio, String tail) {
      return tail;
    }

    static String stat(String first, int second) {
      return first;
    }

    String none() {
      return "";
    }
  }

  private ClassFile fixture() throws Exception {
    String res = Fixture.class.getName().replace('.', '/') + ".class";
    try (InputStream in = getClass().getClassLoader().getResourceAsStream(res)) {
      assertNotNull(in, "fixture class file not on the test classpath");
      return new ClassFile(in.readAllBytes());
    }
  }

  @Test
  void readsAParameterName() throws Exception {
    assertArrayEquals(
        new String[] {"applicationName"},
        fixture().parameterNames("one", "(Ljava/lang/String;)Ljava/lang/String;"));
  }

  @Test
  void longAndDoubleTakeTwoSlots() throws Exception {
    // The slot arithmetic is the whole reason this reader exists: a long or a
    // double occupies two local-variable slots, so a naive index-to-slot map
    // renames every parameter after the first wide one.
    assertArrayEquals(
        new String[] {"offset", "ratio", "tail"},
        fixture().parameterNames("wide", "(JDLjava/lang/String;)Ljava/lang/String;"));
  }

  @Test
  void staticMethodsStartAtSlotZero() throws Exception {
    assertArrayEquals(
        new String[] {"first", "second"},
        fixture().parameterNames("stat", "(Ljava/lang/String;I)Ljava/lang/String;"));
  }

  @Test
  void aMethodWithNoParametersYieldsNothing() throws Exception {
    assertEquals(0, fixture().parameterNames("none", "()Ljava/lang/String;").length);
  }

  @Test
  void unknownMethodIsNotAnError() throws Exception {
    assertEquals(0, fixture().parameterNames("nosuch", "()V").length);
  }

  @Test
  void descriptorArgumentsSplitAtTheTopLevel() {
    assertEquals(
        List.of("J", "D", "Ljava/lang/String;", "[I", "[[Ljava/lang/Object;"),
        ClassFile.descriptorArgs("(JDLjava/lang/String;[I[[Ljava/lang/Object;)V"));
    assertEquals(List.of(), ClassFile.descriptorArgs("()V"));
  }
}
