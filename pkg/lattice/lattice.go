// Package lattice defines primitive type partial orders for different schema formats.
// JSON Schema lattice: int < num < str, bool < str (models implicit coercion).
// Proto3 lattice: int32 ⊑ int64, float ⊑ double, flat otherwise.
package lattice

// Format identifies the schema format, which determines the primitive lattice.
type Format int

const (
	FormatJSON  Format = iota // JSON Schema / OpenAPI
	FormatProto               // Protocol Buffers
)

// Leq returns true if primitive type a ≤ b in the lattice for the given format.
// "a ≤ b" means a value of type a can safely widen to type b.
func Leq(a, b string, fmt Format) bool {
	if a == b {
		return true
	}
	switch fmt {
	case FormatJSON:
		return jsonLeq(a, b)
	case FormatProto:
		return protoLeq(a, b)
	default:
		return a == b
	}
}

// JSON Schema lattice: int < num < str, bool < str.
// Models safe widening under implicit coercion.
func jsonLeq(a, b string) bool {
	switch {
	case a == "integer" && (b == "number" || b == "string"):
		return true
	case a == "number" && b == "string":
		return true
	case a == "boolean" && b == "string":
		return true
	default:
		return false
	}
}

// Proto3 lattice: assumes safe type widening for numeric types.
// int32 ⊑ int64, uint32 ⊑ uint64, sint32 ⊑ sint64, float ⊑ double.
// All other primitives are incomparable (flat).
func protoLeq(a, b string) bool {
	switch {
	case a == "int32" && b == "int64":
		return true
	case a == "uint32" && b == "uint64":
		return true
	case a == "sint32" && b == "sint64":
		return true
	case a == "float" && b == "double":
		return true
	default:
		return false
	}
}

// FormatLeq checks if format a ≤ format b within the same primitive type.
// e.g., int32 ≤ int64 means widening is safe.
func FormatLeq(a, b string) bool {
	if a == b || a == "" || b == "" {
		return true
	}
	widenings := map[string]string{
		"int32":  "int64",
		"uint32": "uint64",
		"sint32": "sint64",
		"float":  "double",
	}
	return widenings[a] == b
}
