package lattice

import "testing"

func TestJSONStrict(t *testing.T) {
	cases := []struct {
		a, b string
		want bool
	}{
		{"integer", "number", true},
		{"integer", "integer", true},
		{"number", "integer", false},
		{"integer", "string", false}, // strict decoders reject number tokens in string fields
		{"boolean", "string", false},
		{"number", "string", false},
	}
	for _, c := range cases {
		if got := Leq(c.a, c.b, FormatJSON, CoercionStrict); got != c.want {
			t.Errorf("strict %s ≤ %s = %v, want %v", c.a, c.b, got, c.want)
		}
	}
}

func TestJSONLenient(t *testing.T) {
	for _, pair := range [][2]string{{"integer", "string"}, {"number", "string"}, {"boolean", "string"}} {
		if !Leq(pair[0], pair[1], FormatJSON, CoercionLenient) {
			t.Errorf("lenient %s ≤ %s should hold", pair[0], pair[1])
		}
	}
	if Leq("string", "integer", FormatJSON, CoercionLenient) {
		t.Error("lenient must not admit string ≤ integer")
	}
}

// float ⊑ double is deliberately absent: float is wire type I32, double is
// I64 — the pairing is wire-incompatible per the protobuf encoding spec.
func TestProtoWireCompat(t *testing.T) {
	ok := [][2]string{{"int32", "int64"}, {"uint32", "uint64"}, {"sint32", "sint64"}}
	for _, p := range ok {
		if !Leq(p[0], p[1], FormatProto, CoercionStrict) {
			t.Errorf("proto %s ⊑ %s should hold", p[0], p[1])
		}
	}
	bad := [][2]string{{"float", "double"}, {"int64", "int32"}, {"fixed32", "fixed64"}}
	for _, p := range bad {
		if Leq(p[0], p[1], FormatProto, CoercionStrict) {
			t.Errorf("proto %s ⊑ %s must NOT hold", p[0], p[1])
		}
	}
}

func TestFormatLeq(t *testing.T) {
	if !FormatLeq("int32", "int64") || !FormatLeq("float", "double") || !FormatLeq("", "int32") {
		t.Error("expected widenings to hold")
	}
	if FormatLeq("int64", "int32") {
		t.Error("narrowing must not hold")
	}
}
