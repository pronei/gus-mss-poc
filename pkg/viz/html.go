package viz

import (
	"fmt"
	"os"
	"strings"
)

// EmbedInTemplate injects a JSON artifact into the viz.html template by
// replacing the `/*__VIZ_DATA__*/` placeholder. The template ships the
// placeholder inside a <script type="application/json"> block so no string
// escaping is needed beyond sealing any stray </script> inside the payload.
func EmbedInTemplate(tpl string, compactJSON []byte) string {
	safe := strings.ReplaceAll(string(compactJSON), "</script>", "<\\/script>")
	return strings.Replace(tpl, "/*__VIZ_DATA__*/", safe, 1)
}

// LoadTemplate reads the viz.html template from `override` if given, else
// tries a short list of common relative locations. Returning a clear error
// if none are found keeps the CLI message useful.
func LoadTemplate(override string) (string, error) {
	candidates := []string{override}
	if override == "" {
		candidates = []string{
			"viz/viz.html",
			"./viz/viz.html",
			"../viz/viz.html",
			"../../viz/viz.html",
		}
	}
	var lastErr error
	for _, c := range candidates {
		if c == "" {
			continue
		}
		data, err := os.ReadFile(c)
		if err == nil {
			return string(data), nil
		}
		lastErr = err
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("viz.html not found in: %v", candidates)
	}
	return "", lastErr
}
