package types

import (
	"strings"
	"testing"
)

func TestConstructorsSetKind(t *testing.T) {
	cases := []struct {
		name string
		node *Node
		want Kind
	}{
		{"prim", Prim("string", ""), KindPrim},
		{"enum", Enum([]string{"a"}), KindEnum},
		{"array", Array(Prim("integer", "")), KindArray},
		{"map", Map(Prim("string", ""), Prim("integer", "")), KindMap},
		{"object", Object(map[string]*Field{}, true), KindObject},
		{"union", Union([]*Node{Prim("string", "")}), KindUnion},
		{"nullable", Nullable(Prim("string", "")), KindNullable},
		{"ref", Ref("svc.T"), KindRef},
		{"any", Any(), KindAny},
	}
	for _, c := range cases {
		if c.node.Kind != c.want {
			t.Errorf("%s: Kind = %v, want %v", c.name, c.node.Kind, c.want)
		}
	}
}

func TestNullableFlattens(t *testing.T) {
	twice := Nullable(Nullable(Prim("string", "")))
	if twice.Kind != KindNullable || twice.Inner.Kind != KindPrim {
		t.Errorf("Nullable(Nullable(T)) should flatten to Nullable(T), got %s", twice.Summary())
	}
}

func TestKindString(t *testing.T) {
	all := map[Kind]string{
		KindPrim: "prim", KindEnum: "enum", KindArray: "array", KindMap: "map", KindObject: "object",
		KindUnion: "union", KindNullable: "nullable", KindRef: "ref", KindAny: "any", Kind(999): "unknown",
	}
	for k, want := range all {
		if got := k.String(); got != want {
			t.Errorf("Kind(%d).String() = %q, want %q", k, got, want)
		}
	}
}

func TestDirectionAndSeverityString(t *testing.T) {
	if DirREQ.String() != "REQ" || DirRES.String() != "RES" {
		t.Error("Direction.String mismatch")
	}
	for s, want := range map[Severity]string{SevBREAK: "BREAK", SevWARN: "WARN", SevINFO: "INFO"} {
		if got := s.String(); got != want {
			t.Errorf("Severity(%d).String() = %q, want %q", s, got, want)
		}
	}
}

func TestViolationString(t *testing.T) {
	v := Violation{Path: "$.x", Severity: SevBREAK, Rule: "REQ.1", Message: "boom", OldType: "<absent>", NewType: "string"}
	s := v.String()
	for _, want := range []string{"BREAK", "$.x", "boom", "<absent>", "string", "REQ.1"} {
		if !strings.Contains(s, want) {
			t.Errorf("Violation.String() = %q, missing %q", s, want)
		}
	}
}

func TestSummary(t *testing.T) {
	var n *Node
	if got := n.Summary(); got != "<nil>" {
		t.Errorf("nil.Summary() = %q, want <nil>", got)
	}
	obj := Object(map[string]*Field{"id": {Schema: Prim("string", ""), Required: true}}, false)
	if got := obj.Summary(); !strings.Contains(got, "id*") || !strings.Contains(got, "closed") {
		t.Errorf("object summary = %q, want required mark and closed tag", got)
	}
	if got := Array(Prim("integer", "int64")).Summary(); !strings.Contains(got, "array(") || !strings.Contains(got, "int64") {
		t.Errorf("array summary = %q", got)
	}
	if got := (&Node{Kind: KindArray}).Summary(); !strings.Contains(got, "<nil>") {
		t.Errorf("array(nil) summary = %q, want <nil> child", got)
	}
	if got := Enum([]string{"a", "b"}).Summary(); got != "enum{a,b}" {
		t.Errorf("enum summary = %q", got)
	}
}
