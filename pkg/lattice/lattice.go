// Package lattice defines primitive type partial orders for different schema formats.
//
// JSON Schema order (strict, the default): integer < number only. This is the
// widening every mainstream decoder accepts (an integer token is a valid
// number). Note it still silently loses precision above 2^53 when the
// consumer models number as IEEE-754 double.
//
// Lenient profile (opt-in): adds number < string, integer < string, and
// boolean < string. These model scalar-to-string coercion that only some
// stacks perform (Jackson by default; untyped JavaScript consumers survive
// decode but risk use-site type errors). Strict decoders — Go encoding/json,
// serde_json, pydantic v2, JSON Schema validation — reject all three, so the
// lenient profile must be an explicit per-scenario choice, never the default.
//
// Proto3 order: int32 ⊑ int64, uint32 ⊑ uint64, sint32 ⊑ sint64 (one-way
// varint widenings where no truncation can occur). float ⊑ double is NOT
// included: float is wire type I32 and double is wire type I64, so the
// pairing is wire-incompatible per the protobuf encoding spec — an old
// float writer read as double yields an unknown field, not a widened value.
// The official conditionally-compatible equivalence classes
// ({int32,uint32,int64,uint64,bool}, {string,bytes}, fixed-width siblings,
// enum~int) carry truncation/reinterpretation side-conditions and are out of
// scope for this POC.
package lattice

// Format identifies the schema format, which determines the primitive lattice.
type Format int

const (
	FormatJSON  Format = iota // JSON Schema / OpenAPI
	FormatProto               // Protocol Buffers
)

// Coercion selects the JSON widening profile.
type Coercion int

const (
	CoercionStrict  Coercion = iota // integer < number only (default)
	CoercionLenient                 // adds int/num/bool < string (Jackson-style consumers)
)

// Leq returns true if primitive type a ≤ b in the order for the given format
// and coercion profile: a value of type a can safely be read where b is
// declared.
func Leq(a, b string, fmt Format, coercion Coercion) bool {
	if a == b {
		return true
	}
	switch fmt {
	case FormatJSON:
		return jsonLeq(a, b, coercion)
	case FormatProto:
		return protoLeq(a, b)
	default:
		return a == b
	}
}

func jsonLeq(a, b string, coercion Coercion) bool {
	if a == "integer" && b == "number" {
		return true
	}
	if coercion == CoercionLenient {
		switch {
		case a == "integer" && b == "string":
			return true
		case a == "number" && b == "string":
			return true
		case a == "boolean" && b == "string":
			return true
		}
	}
	return false
}

// protoLeq: one-directional varint widenings only. See package comment for
// why float ⊑ double is deliberately absent.
func protoLeq(a, b string) bool {
	switch {
	case a == "int32" && b == "int64":
		return true
	case a == "uint32" && b == "uint64":
		return true
	case a == "sint32" && b == "sint64":
		return true
	default:
		return false
	}
}

// FormatLeq checks whether OpenAPI format annotation a fits within b, i.e. a
// value produced under format a is representable under format b. Callers must
// orient the arguments per direction: for requests, sender-format ≤
// receiver-format; for responses, producer-format ≤ consumer-format.
// An absent format on either side is treated as unconstrained.
func FormatLeq(a, b string) bool {
	if a == b || a == "" || b == "" {
		return true
	}
	widenings := map[string]string{
		"int32": "int64",
		"float": "double",
	}
	return widenings[a] == b
}
