// Command iglu runs the pair relation of pkg/compat over every consecutive
// version pair of an Iglu Central checkout, reading each file under the
// JSON Schema dialect of the loader and writes one CSV row per pair,
// for differential comparison against IBM's jsonsubschema (see jss.py and
// compare.py alongside).
//
//	go run ./experiments/iglu --iglu <path/to/iglu-central> --out pairs.csv
package main

import (
	"encoding/csv"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/faults-lab/gus/pkg/compat"
	"github.com/faults-lab/gus/pkg/lattice"
	"github.com/faults-lab/gus/pkg/schema"
	"github.com/faults-lab/gus/pkg/types"
)

type version struct {
	model, revision, addition int
	raw                       string
}

func parseVersion(s string) (version, bool) {
	parts := strings.Split(s, "-")
	if len(parts) != 3 {
		return version{}, false
	}
	var v version
	var err error
	if v.model, err = strconv.Atoi(parts[0]); err != nil {
		return version{}, false
	}
	if v.revision, err = strconv.Atoi(parts[1]); err != nil {
		return version{}, false
	}
	if v.addition, err = strconv.Atoi(parts[2]); err != nil {
		return version{}, false
	}
	v.raw = s
	return v, true
}

func bump(a, b version) string {
	switch {
	case a.model != b.model:
		return "MODEL"
	case a.revision != b.revision:
		return "REVISION"
	default:
		return "ADDITION"
	}
}

// subschema reports whether old <: new under the strict JSON lattice: no
// BREAK-severity finding when old is read as the sender and new as the
// receiver. Warnings (format range risks) do not count, since JSON Schema's
// format keyword carries no validation semantics in the subschema relation.
func subschema(old, new *types.Node) (bool, []string) {
	vs := compat.Check(old, new, types.DirREQ, compat.Config{Format: lattice.FormatJSON, Coercion: lattice.CoercionStrict})
	ok := true
	seen := map[string]bool{}
	var rules []string
	for _, v := range vs {
		if v.Severity != types.SevBREAK {
			continue
		}
		ok = false
		if !seen[v.Rule] {
			seen[v.Rule] = true
			rules = append(rules, v.Rule)
		}
	}
	sort.Strings(rules)
	return ok, rules
}

func main() {
	igluDir := flag.String("iglu", "", "path to an iglu-central checkout")
	out := flag.String("out", "pairs.csv", "output CSV")
	flag.Parse()
	if *igluDir == "" {
		fmt.Fprintln(os.Stderr, "usage: iglu --iglu <dir> --out <csv>")
		os.Exit(2)
	}

	// chains: vendor/name -> versions
	chains := map[string][]version{}
	root := filepath.Join(*igluDir, "schemas")
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return err
		}
		rel, _ := filepath.Rel(root, path)
		parts := strings.Split(filepath.ToSlash(rel), "/")
		if len(parts) != 4 || parts[2] != "jsonschema" {
			return nil
		}
		v, ok := parseVersion(parts[3])
		if !ok {
			return nil
		}
		key := parts[0] + "/" + parts[1]
		chains[key] = append(chains[key], v)
		return nil
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	keys := make([]string, 0, len(chains))
	for k := range chains {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	f, err := os.Create(*out)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	w.Write([]string{"vendor", "name", "old", "new", "bump", "old_path", "new_path",
		"gus_old_sub_new", "gus_old_sub_new_rules", "gus_new_sub_old", "gus_new_sub_old_rules", "error"})

	pairs, loadErrors := 0, 0
	for _, key := range keys {
		vs := chains[key]
		if len(vs) < 2 {
			continue
		}
		sort.Slice(vs, func(i, j int) bool {
			a, b := vs[i], vs[j]
			if a.model != b.model {
				return a.model < b.model
			}
			if a.revision != b.revision {
				return a.revision < b.revision
			}
			return a.addition < b.addition
		})
		vendorName := strings.SplitN(key, "/", 2)
		for i := 0; i+1 < len(vs); i++ {
			oldPath := filepath.Join(root, key, "jsonschema", vs[i].raw)
			newPath := filepath.Join(root, key, "jsonschema", vs[i+1].raw)
			row := []string{vendorName[0], vendorName[1], vs[i].raw, vs[i+1].raw, bump(vs[i], vs[i+1]), oldPath, newPath}
			cfg := schema.Config{Dialect: schema.DialectJSONSchema, ServicePrefix: key}
			oldN, errOld := schema.LoadSchema(oldPath, cfg)
			newN, errNew := schema.LoadSchema(newPath, cfg)
			if errOld != nil || errNew != nil {
				loadErrors++
				msg := ""
				if errOld != nil {
					msg = errOld.Error()
				} else {
					msg = errNew.Error()
				}
				w.Write(append(row, "", "", "", "", msg))
				continue
			}
			fwd, fwdRules := subschema(oldN, newN)
			bwd, bwdRules := subschema(newN, oldN)
			w.Write(append(row, strconv.FormatBool(fwd), strings.Join(fwdRules, "|"),
				strconv.FormatBool(bwd), strings.Join(bwdRules, "|"), ""))
			pairs++
		}
	}
	fmt.Printf("chains: %d, consecutive pairs: %d, load errors: %d\n", len(keys), pairs, loadErrors)
}
