package schema

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/faults-lab/gus/pkg/types"
)

func loadDoc(t *testing.T, body string) *Spec {
	t.Helper()
	p := filepath.Join(t.TempDir(), "openapi.yaml")
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	spec, err := Load(p, "svc")
	if err != nil {
		t.Fatal(err)
	}
	return spec
}

func TestEnumBaseFromDeclaredType(t *testing.T) {
	spec := loadDoc(t, `
openapi: 3.0.0
paths:
  /x:
    post:
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                code: { type: string, enum: ["10", "20"] }
                level: { type: integer, enum: [1, 2] }
                loose: { enum: [a, b] }
      responses: {}
`)
	req := spec.Endpoints[EndpointKey{Path: "/x", Method: "POST"}].Request
	if got := req.Fields["code"].Schema.EnumBase; got != "string" {
		t.Errorf("code: EnumBase = %q, want string", got)
	}
	if got := req.Fields["level"].Schema.EnumBase; got != "integer" {
		t.Errorf("level: EnumBase = %q, want integer", got)
	}
	if got := req.Fields["loose"].Schema.EnumBase; got != "" {
		t.Errorf("loose: EnumBase = %q, want empty (no declared type)", got)
	}
}

func TestRequiredWithoutProperty(t *testing.T) {
	spec := loadDoc(t, `
openapi: 3.0.0
paths:
  /x:
    post:
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [id, token]
              properties:
                id: { type: string }
      responses: {}
`)
	req := spec.Endpoints[EndpointKey{Path: "/x", Method: "POST"}].Request
	f, ok := req.Fields["token"]
	if !ok {
		t.Fatal("required name without a property was dropped")
	}
	if !f.Required || f.Schema.Kind != types.KindAny {
		t.Errorf("token: got required=%v kind=%s, want required Any", f.Required, f.Schema.Kind)
	}
}

func TestAnyOfIsUnion(t *testing.T) {
	spec := loadDoc(t, `
openapi: 3.0.0
paths:
  /x:
    post:
      requestBody:
        content:
          application/json:
            schema:
              anyOf:
                - { type: string }
                - { type: integer }
      responses: {}
`)
	req := spec.Endpoints[EndpointKey{Path: "/x", Method: "POST"}].Request
	if req.Kind != types.KindUnion || len(req.Variants) != 2 {
		t.Errorf("anyOf: got %s, want a two-variant union", req.Summary())
	}
}

func TestOneOfIsExclusiveUnion(t *testing.T) {
	spec := loadDoc(t, `
openapi: 3.0.0
paths:
  /x:
    post:
      requestBody:
        content:
          application/json:
            schema:
              oneOf:
                - { type: string }
                - { type: integer }
      responses: {}
`)
	req := spec.Endpoints[EndpointKey{Path: "/x", Method: "POST"}].Request
	if req.Kind != types.KindUnion || !req.Exclusive {
		t.Errorf("oneOf: got %s exclusive=%v, want an exclusive union", req.Summary(), req.Exclusive)
	}
}

func TestBareJSONSchemaTypeLists(t *testing.T) {
	p := filepath.Join(t.TempDir(), "s.json")
	if err := os.WriteFile(p, []byte(`{
	"$schema": "http://json-schema.org/draft-04/schema#",
	"self": {"vendor": "x", "name": "y"},
	"definitions": {"Tag": {"type": "object", "properties": {"k": {"type": "string"}}}},
	"type": "object",
	"properties": {
		"maybe": {"type": ["string", "null"]},
		"either": {"type": ["string", "integer"]},
		"tags": {"type": "array", "items": {"$ref": "#/definitions/Tag"}},
		"level": {"type": ["integer", "null"], "enum": [1, 2, null]}
	},
	"required": ["either"],
	"additionalProperties": false
}`), 0o644); err != nil {
		t.Fatal(err)
	}
	n, err := LoadSchema(p, Config{Dialect: DialectJSONSchema, ServicePrefix: "svc"})
	if err != nil {
		t.Fatal(err)
	}
	if n.Kind != types.KindObject || n.Open {
		t.Fatalf("root: got %s, want closed object", n.Summary())
	}
	if f := n.Fields["maybe"].Schema; f.Kind != types.KindNullable || f.Inner.Prim != "string" {
		t.Errorf("maybe: got %s, want nullable(string)", f.Summary())
	}
	if f := n.Fields["either"].Schema; f.Kind != types.KindUnion || len(f.Variants) != 2 {
		t.Errorf("either: got %s, want a two-variant union", f.Summary())
	}
	if f := n.Fields["tags"].Schema; f.Kind != types.KindArray || f.Items.Kind != types.KindObject {
		t.Errorf("tags: got %s, want array of the Tag definition", f.Summary())
	}
	if f := n.Fields["level"].Schema; f.Kind != types.KindNullable || f.Inner.Kind != types.KindEnum || f.Inner.EnumBase != "integer" {
		t.Errorf("level: got %s, want nullable(enum<integer>)", f.Summary())
	}
	if !n.Fields["either"].Required || n.Fields["maybe"].Required {
		t.Error("required list not applied")
	}
}

func TestBareNullType(t *testing.T) {
	p := filepath.Join(t.TempDir(), "n.json")
	if err := os.WriteFile(p, []byte(`{"type": "object", "properties": {"auth": {"oneOf": [{"type": "object", "properties": {"k": {"type": "string"}}, "required": ["k"]}, {"type": "null"}]}}}`), 0o644); err != nil {
		t.Fatal(err)
	}
	n, err := LoadSchema(p, Config{Dialect: DialectJSONSchema, ServicePrefix: "svc"})
	if err != nil {
		t.Fatal(err)
	}
	u := n.Fields["auth"].Schema
	if u.Kind != types.KindUnion || !u.Exclusive || len(u.Variants) != 2 || u.Variants[1].Kind != types.KindPrim || u.Variants[1].Prim != "null" {
		t.Errorf("auth: got %s, want oneOf(object, null)", u.Summary())
	}
}

// The sum syntaxes of JSON Schema are refused under the OpenAPI dialect
// rather than misread, and accepted under the JSON Schema dialect.
func TestDialectGatesSumSyntax(t *testing.T) {
	dir := t.TempDir()
	for _, tc := range []struct {
		name, body, want string
	}{
		{"type list", `{"type": ["string", "integer"]}`, "is a list"},
		{"null type", `{"type": "null"}`, "nullable: true"},
	} {
		p := filepath.Join(dir, tc.name+".json")
		if err := os.WriteFile(p, []byte(tc.body), 0o644); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadSchema(p, Config{ServicePrefix: "svc"}); err == nil {
			t.Errorf("%s: OpenAPI dialect should refuse it", tc.name)
		} else if !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s: error %q, want it to mention %q", tc.name, err, tc.want)
		}
		if _, err := LoadSchema(p, Config{Dialect: DialectJSONSchema, ServicePrefix: "svc"}); err != nil {
			t.Errorf("%s: JSON Schema dialect should accept it, got %v", tc.name, err)
		}
	}
}

// definitions/$defs references resolve only under the JSON Schema dialect.
func TestDialectGatesDefinitionRefs(t *testing.T) {
	p := filepath.Join(t.TempDir(), "d.json")
	if err := os.WriteFile(p, []byte(`{"definitions": {"T": {"type": "string"}}, "type": "object", "properties": {"a": {"$ref": "#/definitions/T"}}}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadSchema(p, Config{ServicePrefix: "svc"}); err == nil {
		t.Error("OpenAPI dialect should refuse a #/definitions/ ref")
	}
	n, err := LoadSchema(p, Config{Dialect: DialectJSONSchema, ServicePrefix: "svc"})
	if err != nil {
		t.Fatal(err)
	}
	if got := n.Fields["a"].Schema; got.Kind != types.KindPrim || got.Prim != "string" {
		t.Errorf("a: got %s, want the inlined string definition", got.Summary())
	}
}
