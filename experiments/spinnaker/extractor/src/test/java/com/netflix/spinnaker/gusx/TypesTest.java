package com.netflix.spinnaker.gusx;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Callable;
import org.junit.jupiter.api.Test;

/** Return-type unwrapping (CLAIM-S5-003/050/051) and the contentless set (D6). */
class TypesTest {

  @SuppressWarnings("unused")
  interface Sample {
    Optional<String> opt();

    Callable<List<String>> callable();

    void nothing();

    Void voidBox();

    byte[] bytes();

    List rawList();

    Map<String, String> typedMap();

    String plain();
  }

  private static java.lang.reflect.Type ret(String name) throws Exception {
    for (Method m : Sample.class.getMethods()) {
      if (m.getName().equals(name)) {
        return m.getGenericReturnType();
      }
    }
    throw new AssertionError(name);
  }

  @Test
  void wrappersAreUnwrapped() throws Exception {
    assertEquals(String.class, Types.unwrapResponse(ret("opt"), null));
    assertEquals("java.util.List<java.lang.String>", Types.unwrapResponse(ret("callable"), null).getTypeName());
  }

  @Test
  void voidAndStreamsAreContentless() throws Exception {
    assertNull(Types.unwrapResponse(ret("nothing"), null));
    assertNull(Types.unwrapResponse(ret("voidBox"), null));
    assertNull(Types.unwrapResponse(ret("bytes"), null));
  }

  @Test
  void aPlainTypeIsItself() throws Exception {
    assertEquals(String.class, Types.unwrapResponse(ret("plain"), null));
  }

  @Test
  void rawContainersAreRawGenerics() throws Exception {
    assertTrue(Types.isRawGeneric(ret("rawList")));
    assertFalse(Types.isRawGeneric(ret("typedMap")));
    assertFalse(Types.isRawGeneric(ret("plain")));
  }

  @Test
  void erasureHandlesTheShapesTheWalkMeets() throws Exception {
    assertEquals(Map.class, Types.erase(ret("typedMap")));
    assertEquals(String.class, Types.erase(String.class));
  }
}
