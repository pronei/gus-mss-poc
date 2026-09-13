package com.netflix.spinnaker.gusx;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;

/** One path+method in the emitted document. */
public final class Endpoint implements Comparable<Endpoint> {

  public String path;
  public String method;
  /** "" for the service's own API, "client" for a declared outbound call (README §5.3). */
  public String role = "";
  /** Where it came from, for the census diff; not emitted. */
  public String source = "";

  /** params.<name> */
  public final Map<String, Schema> params = new TreeMap<>();
  public final java.util.Set<String> paramsRequired = new java.util.TreeSet<>();
  /** A catch-all Map/MultiValueMap binder makes params an open object (D6). */
  public boolean paramsOpen;

  /** headers.<name> */
  public final Map<String, Schema> headers = new TreeMap<>();
  public final java.util.Set<String> headersRequired = new java.util.TreeSet<>();

  /** The JSON payload, or null for a contentless request (multipart, none). */
  public Schema body;
  public boolean bodyRequired;

  /** The lowest 2xx JSON response, or null for a contentless 200 (D6). */
  public Schema response;

  public Map<String, Object> extras = new LinkedHashMap<>();

  public String key() {
    return method + " " + path;
  }

  @Override
  public int compareTo(Endpoint o) {
    int c = path.compareTo(o.path);
    return c != 0 ? c : method.compareTo(o.method);
  }
}
