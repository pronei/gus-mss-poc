package com.netflix.spinnaker.gusx;

import java.io.File;
import java.lang.reflect.Method;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.ArrayList;
import java.util.List;

/**
 * Bootstrap. Runs in the launcher's own class loader, builds the service's
 * runtime class loader from the {@code CLASSPATH=} line of {@code bin/<svc>}
 * (D1(b): never from file names), puts this tool's own jar inside it, and
 * hands control to {@link Extract}.
 *
 * <p>The service loader's parent is the <em>platform</em> loader, not the
 * application loader, so the service's Jackson, Spring and Retrofit are the
 * only ones on it. That isolation is what lets {@link Shape} drive the
 * service's own {@code ObjectMapper} (D7) instead of one of ours. Only
 * {@code String[]} crosses the boundary.
 */
public final class Main {

  public static void main(String[] args) throws Exception {
    Args a = Args.parse(args);
    if (a == null) {
      System.err.println(Args.USAGE);
      System.exit(2);
    }

    List<File> entries = Classpath.read(a.classpathDir, a.service);
    List<URL> urls = new ArrayList<>();
    for (File f : entries) {
      urls.add(f.toURI().toURL());
    }
    // This tool's own classes go last so that no service class is shadowed.
    urls.add(Main.class.getProtectionDomain().getCodeSource().getLocation());

    ClassLoader svc =
        new URLClassLoader("service", urls.toArray(new URL[0]), ClassLoader.getPlatformClassLoader());
    Thread.currentThread().setContextClassLoader(svc);

    Class<?> extract = Class.forName(Extract.class.getName(), true, svc);
    Method run = extract.getMethod("run", String[].class);
    Object rc = run.invoke(null, (Object) args);
    System.exit(((Integer) rc).intValue());
  }

  private Main() {}
}
