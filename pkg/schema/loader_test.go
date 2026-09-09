package schema

import (
	"os"
	"path/filepath"
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
