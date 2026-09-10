// Command gen projects every historical version of Online Boutique's
// demo.proto onto OpenAPI 3.0 documents the checker can read, then writes a
// mesh graph and an upgrade scenario for every consecutive commit pair.
//
//	go run ./experiments/boutique-proto/gen --history experiments/boutique-proto/history --out experiments/boutique-proto/generated
//
// The mapping is deliberately NOT the proto3 JSON encoding: 64-bit integers
// stay integers (format int64/uint64), field names stay snake_case, tag
// numbers are kept as x-proto-field-number, oneof members are plain optional
// properties tagged x-proto-oneof, messages are open objects (unknown fields
// are ignored on the proto wire), and nothing is required (proto3 has no
// required). Enums become closed string enums, which is a distortion the
// README records: proto3 enums are open.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/bufbuild/protocompile"
	"google.golang.org/protobuf/reflect/protoreflect"
	"gopkg.in/yaml.v3"
)

// serviceID maps a proto service name to the mesh's service id.
func serviceID(protoService string) string {
	s := strings.TrimSuffix(protoService, "Service")
	s = strings.ToLower(s)
	if s == "ads" {
		s = "ad"
	}
	return s
}

// edge templates: caller -> provider service id -> methods the caller's
// code invokes (taken from src/frontend and src/checkoutservice at the
// commits of this history, see README). An edge is written into a pair's
// graph only when the method's path exists in the provider at both
// versions; additions and removals are reported separately.
var edgeTemplates = []struct {
	from, to string
	methods  []string
}{
	{"frontend", "cart", []string{"AddItem", "GetCart", "EmptyCart"}},
	{"frontend", "productcatalog", []string{"ListProducts", "GetProduct"}},
	{"frontend", "currency", []string{"GetSupportedCurrencies", "Convert"}},
	{"frontend", "recommendation", []string{"ListRecommendations"}},
	{"frontend", "shipping", []string{"GetQuote"}},
	{"frontend", "checkout", []string{"CreateOrder", "PlaceOrder"}},
	{"frontend", "ad", []string{"GetAds"}},
	{"checkout", "cart", []string{"GetCart", "EmptyCart"}},
	{"checkout", "productcatalog", []string{"GetProduct"}},
	{"checkout", "currency", []string{"Convert"}},
	{"checkout", "shipping", []string{"GetQuote", "ShipOrder"}},
	{"checkout", "payment", []string{"Charge"}},
	{"checkout", "email", []string{"SendOrderConfirmation"}},
	{"recommendation", "productcatalog", []string{"ListProducts"}},
}

type version struct {
	id      string // "01-e926f33"
	dir     string
	sha     string
	message string
}

type endpoint struct {
	path, in, out string
}

// projection of one proto version: per service id, its endpoints; plus the
// rendered document per service.
type projection struct {
	endpoints map[string][]endpoint     // service id -> endpoints
	docs      map[string]map[string]any // service id -> OpenAPI document
	pkg       string
	fd        protoreflect.FileDescriptor
}

func main() {
	histDir := flag.String("history", "", "directory of NN-sha/demo.proto versions with index.tsv")
	outDir := flag.String("out", "", "output directory")
	flag.Parse()
	if *histDir == "" || *outDir == "" {
		fmt.Fprintln(os.Stderr, "usage: gen --history <dir> --out <dir>")
		os.Exit(2)
	}
	versions, err := readIndex(*histDir)
	check(err)

	projections := make([]projection, len(versions))
	for i, v := range versions {
		p, err := project(v)
		check(err)
		projections[i] = p
		for svc, doc := range p.docs {
			dir := filepath.Join(*outDir, "specs", svc, v.id[:2])
			check(os.MkdirAll(dir, 0o755))
			check(writeYAML(filepath.Join(dir, "openapi.yaml"), doc))
		}
		// The frontend has no proto: it is a pure caller with no declared
		// outbound contracts, so it gets an empty document per version and
		// the checker anchors it to each provider's old contract (Tier-3).
		dir := filepath.Join(*outDir, "specs", "frontend", v.id[:2])
		check(os.MkdirAll(dir, 0o755))
		check(writeYAML(filepath.Join(dir, "openapi.yaml"), map[string]any{
			"openapi": "3.0.3",
			"info":    map[string]any{"title": "frontend (no proto; pure caller)", "version": v.id},
			"paths":   map[string]any{},
		}))
	}

	check(os.MkdirAll(filepath.Join(*outDir, "scenarios"), 0o755))
	var changes strings.Builder
	for i := 0; i+1 < len(versions); i++ {
		a, b := versions[i], versions[i+1]
		pa, pb := projections[i], projections[i+1]
		pair := a.id[:2] + "-" + b.id[:2]

		// services present at both versions, with their spec paths
		// A service belongs to the pair's mesh only if it exists at the
		// baseline; one that first appears at b is a new deployment, not an
		// upgrade, and is reported instead.
		services := map[string]any{}
		ids := union(keys(pa.docs), keys(pb.docs))
		for _, svc := range ids {
			if _, ok := pa.docs[svc]; !ok {
				continue
			}
			vs := map[string]any{ver(a): fmt.Sprintf("specs/%s/%s/openapi.yaml", svc, a.id[:2])}
			if _, ok := pb.docs[svc]; ok {
				vs[ver(b)] = fmt.Sprintf("specs/%s/%s/openapi.yaml", svc, b.id[:2])
			}
			services[svc] = vs
		}
		services["frontend"] = map[string]any{
			ver(a): fmt.Sprintf("specs/frontend/%s/openapi.yaml", a.id[:2]),
			ver(b): fmt.Sprintf("specs/frontend/%s/openapi.yaml", b.id[:2]),
		}

		// edges whose path exists at both versions of the provider
		var edges []map[string]any
		var dropped []string
		for _, t := range edgeTemplates {
			for _, m := range t.methods {
				pathA := findPath(pa.endpoints[t.to], m)
				pathB := findPath(pb.endpoints[t.to], m)
				switch {
				case pathA != "" && pathA == pathB:
					edges = append(edges, map[string]any{
						"name": fmt.Sprintf("%s->%s-%s", t.from, t.to, m),
						"from": t.from, "to": t.to, "method": "POST", "path": pathA,
					})
				case pathA != "" && pathB == "":
					dropped = append(dropped, fmt.Sprintf("%s->%s %s: endpoint REMOVED at %s (%s)", t.from, t.to, m, b.id, pathA))
				case pathA == "" && pathB != "":
					dropped = append(dropped, fmt.Sprintf("%s->%s %s: endpoint ADDED at %s (%s)", t.from, t.to, m, b.id, pathB))
				case pathA != "" && pathB != "" && pathA != pathB:
					dropped = append(dropped, fmt.Sprintf("%s->%s %s: endpoint path CHANGED %s -> %s", t.from, t.to, m, pathA, pathB))
				}
			}
		}
		check(writeYAML(filepath.Join(*outDir, "graph-"+pair+".yaml"), map[string]any{
			"services": services, "edges": edges,
		}))

		// scenario: baseline = version a everywhere; upgrades = services whose
		// document changed (services that exist only at b are additions and
		// cannot be "upgraded" from a baseline; they are reported instead).
		baseline := map[string]any{"frontend": ver(a)}
		upgrades := map[string]any{}
		var added []string
		for _, svc := range ids {
			da, okA := pa.docs[svc]
			db, okB := pb.docs[svc]
			switch {
			case okA && okB:
				baseline[svc] = ver(a)
				if !sameDoc(da, db) {
					upgrades[svc] = ver(b)
				}
			case okA && !okB:
				baseline[svc] = ver(a)
				dropped = append(dropped, fmt.Sprintf("service %s REMOVED at %s", svc, b.id))
			case !okA && okB:
				added = append(added, fmt.Sprintf("service %s ADDED at %s (no baseline to upgrade from)", svc, b.id))
			}
		}
		notes := append(append([]string(nil), dropped...), added...)
		desc := fmt.Sprintf("%s -> %s: %s (%s)", a.id, b.id, b.message, b.sha[:7])
		if len(notes) > 0 {
			desc += "\nOutside the per-edge model: " + strings.Join(notes, "; ")
		}
		sc := map[string]any{
			"id":          "P" + pair,
			"name":        b.message,
			"description": desc,
			"baseline":    baseline,
			"upgrades":    upgrades,
		}
		check(writeYAML(filepath.Join(*outDir, "scenarios", pair+".yaml"), sc))
		wf := compareServices(pa.fd, pb.fd)
		check(os.MkdirAll(filepath.Join(*outDir, "wire"), 0o755))
		check(os.WriteFile(filepath.Join(*outDir, "wire", pair+".txt"), []byte(formatWire(wf)), 0o644))
		fmt.Fprintf(&changes, "%s  %-60s upgrades=%v\n", pair, truncate(b.message, 60), keys(upgrades))
		for _, n := range notes {
			fmt.Fprintf(&changes, "        %s\n", n)
		}
	}
	check(os.WriteFile(filepath.Join(*outDir, "changes.txt"), []byte(changes.String()), 0o644))
	fmt.Print(changes.String())
}

// ver is the version label used in graphs and scenarios: "c01" rather than
// a bare "01", which YAML would read as a number.
func ver(v version) string { return "c" + v.id[:2] }

func readIndex(dir string) ([]version, error) {
	data, err := os.ReadFile(filepath.Join(dir, "index.tsv"))
	if err != nil {
		return nil, err
	}
	var vs []version
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		f := strings.Split(line, "\t")
		if len(f) < 4 {
			continue
		}
		vs = append(vs, version{id: f[0], dir: filepath.Join(dir, f[0]), sha: f[2], message: f[3]})
	}
	sort.Slice(vs, func(i, j int) bool { return vs[i].id < vs[j].id })
	return vs, nil
}

func project(v version) (projection, error) {
	c := protocompile.Compiler{Resolver: protocompile.WithStandardImports(&protocompile.SourceResolver{ImportPaths: []string{v.dir}})}
	files, err := c.Compile(context.Background(), "demo.proto")
	if err != nil {
		return projection{}, fmt.Errorf("%s: %w", v.id, err)
	}
	fd := files[0]
	p := projection{endpoints: map[string][]endpoint{}, docs: map[string]map[string]any{}, pkg: string(fd.Package()), fd: fd}

	// every message of the file, rendered once; each service document then
	// carries only the messages reachable from its own endpoints, so that a
	// service's document changes only when its own interface does.
	allMsgs := map[string]protoreflect.MessageDescriptor{}
	var walkMsgs func(msgs protoreflect.MessageDescriptors)
	walkMsgs = func(msgs protoreflect.MessageDescriptors) {
		for i := 0; i < msgs.Len(); i++ {
			m := msgs.Get(i)
			if m.IsMapEntry() {
				continue
			}
			allMsgs[string(m.Name())] = m
			walkMsgs(m.Messages())
		}
	}
	walkMsgs(fd.Messages())
	closure := func(roots []string) map[string]any {
		out := map[string]any{}
		var visit func(name string)
		visit = func(name string) {
			if _, done := out[name]; done {
				return
			}
			m, ok := allMsgs[name]
			if !ok {
				return
			}
			out[name] = messageSchema(m)
			fields := m.Fields()
			for i := 0; i < fields.Len(); i++ {
				f := fields.Get(i)
				if f.IsMap() {
					f = f.MapValue()
				}
				if f.Kind() == protoreflect.MessageKind || f.Kind() == protoreflect.GroupKind {
					visit(string(f.Message().Name()))
				}
			}
		}
		for _, r := range roots {
			visit(r)
		}
		return out
	}

	svcs := fd.Services()
	for i := 0; i < svcs.Len(); i++ {
		s := svcs.Get(i)
		id := serviceID(string(s.Name()))
		paths := map[string]any{}
		var roots []string
		for j := 0; j < s.Methods().Len(); j++ {
			m := s.Methods().Get(j)
			path := fmt.Sprintf("/%s.%s/%s", fd.Package(), s.Name(), m.Name())
			in, out := string(m.Input().Name()), string(m.Output().Name())
			p.endpoints[id] = append(p.endpoints[id], endpoint{path: path, in: in, out: out})
			roots = append(roots, in, out)
			op := map[string]any{
				"operationId": string(m.Name()),
				"requestBody": map[string]any{"required": true, "content": map[string]any{
					"application/json": map[string]any{"schema": ref(in)}}},
				"responses": map[string]any{"200": map[string]any{"description": out, "content": map[string]any{
					"application/json": map[string]any{"schema": ref(out)}}}},
			}
			if m.IsStreamingClient() || m.IsStreamingServer() {
				op["x-proto-streaming"] = true
			}
			paths[path] = map[string]any{"post": op}
		}
		p.docs[id] = map[string]any{
			"openapi": "3.0.3",
			"info": map[string]any{
				"title":       string(s.FullName()),
				"version":     v.id,
				"description": fmt.Sprintf("Projected from demo.proto at %s (%s)", v.sha[:7], v.message),
			},
			"paths":      paths,
			"components": map[string]any{"schemas": closure(roots)},
		}
	}
	return p, nil
}

func ref(name string) map[string]any {
	return map[string]any{"$ref": "#/components/schemas/" + name}
}

func messageSchema(m protoreflect.MessageDescriptor) map[string]any {
	props := map[string]any{}
	fields := m.Fields()
	for i := 0; i < fields.Len(); i++ {
		f := fields.Get(i)
		props[string(f.Name())] = fieldSchema(f)
	}
	obj := map[string]any{"type": "object", "properties": props}
	if m.Fields().Len() == 0 {
		obj["description"] = "empty message"
	}
	return obj
}

func fieldSchema(f protoreflect.FieldDescriptor) map[string]any {
	var s map[string]any
	switch {
	case f.IsMap():
		s = map[string]any{"type": "object", "additionalProperties": scalarSchema(f.MapValue())}
	case f.IsList():
		s = map[string]any{"type": "array", "items": scalarSchema(f)}
	default:
		s = scalarSchema(f)
	}
	s["x-proto-field-number"] = int(f.Number())
	if o := f.ContainingOneof(); o != nil {
		s["x-proto-oneof"] = string(o.Name())
	}
	return s
}

// scalarSchema maps one (non-repeated) field type. Kept lossless where the
// grammar allows: 64-bit integers are integers with a format, not the
// strings of the proto3 JSON encoding.
func scalarSchema(f protoreflect.FieldDescriptor) map[string]any {
	switch f.Kind() {
	case protoreflect.BoolKind:
		return map[string]any{"type": "boolean"}
	case protoreflect.StringKind:
		return map[string]any{"type": "string"}
	case protoreflect.BytesKind:
		return map[string]any{"type": "string", "format": "byte"}
	case protoreflect.Int32Kind, protoreflect.Sint32Kind, protoreflect.Sfixed32Kind:
		return map[string]any{"type": "integer", "format": "int32"}
	case protoreflect.Int64Kind, protoreflect.Sint64Kind, protoreflect.Sfixed64Kind:
		return map[string]any{"type": "integer", "format": "int64"}
	case protoreflect.Uint32Kind, protoreflect.Fixed32Kind:
		return map[string]any{"type": "integer", "format": "uint32"}
	case protoreflect.Uint64Kind, protoreflect.Fixed64Kind:
		return map[string]any{"type": "integer", "format": "uint64"}
	case protoreflect.FloatKind:
		return map[string]any{"type": "number", "format": "float"}
	case protoreflect.DoubleKind:
		return map[string]any{"type": "number", "format": "double"}
	case protoreflect.EnumKind:
		vals := f.Enum().Values()
		names := make([]string, 0, vals.Len())
		for i := 0; i < vals.Len(); i++ {
			names = append(names, string(vals.Get(i).Name()))
		}
		// proto3 enums are OPEN (unknown values are carried through); the
		// grammar has only closed enums. Recorded for the README.
		return map[string]any{"type": "string", "enum": names, "x-proto-open-enum": true}
	case protoreflect.MessageKind, protoreflect.GroupKind:
		return ref(string(f.Message().Name()))
	}
	return map[string]any{}
}

func findPath(eps []endpoint, method string) string {
	for _, e := range eps {
		if strings.HasSuffix(e.path, "/"+method) {
			return e.path
		}
	}
	return ""
}

func sameDoc(a, b map[string]any) bool {
	// compare everything except the per-version info block
	ca, cb := copyWithoutInfo(a), copyWithoutInfo(b)
	ya, _ := yaml.Marshal(ca)
	yb, _ := yaml.Marshal(cb)
	return string(ya) == string(yb)
}

func copyWithoutInfo(d map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range d {
		if k != "info" {
			out[k] = v
		}
	}
	return out
}

func writeYAML(path string, v any) error {
	data, err := yaml.Marshal(v)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

func keys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func union(a, b []string) []string {
	seen := map[string]bool{}
	for _, s := range append(a, b...) {
		seen[s] = true
	}
	return keys(seen)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}

func check(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
