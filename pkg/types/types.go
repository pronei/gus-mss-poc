// Package types defines the type AST for the GUS compatibility checker.
// This covers the full type language from the GUS-MSS paper §3.3:
// Prim | Literal(v) | Enum(S) | Array(T) | Map(K,V) | Object(F,o) | Union(S) | Nullable(T) | Ref(n) | Any
package types

import (
	"fmt"
	"strings"
)

// Kind enumerates the type constructors in the GUS type language.
type Kind int

const (
	KindPrim     Kind = iota // Primitive: string, integer, number, boolean
	KindLiteral              // Literal(v): a single constant value
	KindEnum                 // Enum(S): a set of allowed values
	KindArray                // Array(T): homogeneous list
	KindMap                  // Map(K,V): key-value collection
	KindObject               // Object(F,o): record with named fields
	KindUnion                // Union(S): oneOf / oneof
	KindNullable             // Nullable(T): T | null
	KindRef                  // Ref(n): named recursive type
	KindAny                  // Any: unconstrained
)

func (k Kind) String() string {
	switch k {
	case KindPrim:
		return "prim"
	case KindLiteral:
		return "literal"
	case KindEnum:
		return "enum"
	case KindArray:
		return "array"
	case KindMap:
		return "map"
	case KindObject:
		return "object"
	case KindUnion:
		return "union"
	case KindNullable:
		return "nullable"
	case KindRef:
		return "ref"
	case KindAny:
		return "any"
	default:
		return "unknown"
	}
}

// Node is the core type AST node.
type Node struct {
	Kind Kind

	// KindPrim
	Prim   string // "string", "integer", "number", "boolean"
	Format string // "int32", "int64", "float", "double", etc.

	// KindLiteral
	LiteralValue string

	// KindEnum
	EnumValues []string

	// KindArray
	Items *Node

	// KindMap
	MapKey   *Node
	MapValue *Node

	// KindObject
	Fields map[string]*Field
	Open   bool // additionalProperties: true by default in JSON Schema

	// KindUnion
	Variants []*Node

	// KindNullable
	Inner *Node

	// KindRef
	RefName string // service-qualified: "serviceA.Address"
}

// Field is a named entry in an Object type.
type Field struct {
	Schema     *Node
	Required   bool
	HasDefault bool   // whether a default value is declared
	XProvides  string // data-flow identity this field provides
	XRequires  string // data-flow identity this field requires
	XAlias     string // field rename bridge for chain tracing
}

// Direction indicates variance for compatibility checking.
type Direction int

const (
	DirREQ Direction = iota // contravariant: request/accept side
	DirRES                  // covariant: response/return side
)

func (d Direction) String() string {
	if d == DirREQ {
		return "REQ"
	}
	return "RES"
}

// Severity of a compatibility violation.
type Severity int

const (
	SevBREAK Severity = iota // Runtime incompatibility
	SevWARN                  // Semantic risk
	SevINFO                  // Style/codegen concern
)

func (s Severity) String() string {
	switch s {
	case SevBREAK:
		return "BREAK"
	case SevWARN:
		return "WARN"
	case SevINFO:
		return "INFO"
	default:
		return "UNKNOWN"
	}
}

// Violation records a single type incompatibility.
type Violation struct {
	Path     string
	Severity Severity
	Rule     string // e.g., "REQ.1", "enum-request-narrowing"
	Message  string
	OldType  string
	NewType  string
}

func (v Violation) String() string {
	return fmt.Sprintf("[%s] %s: %s (old: %s, new: %s) [%s]",
		v.Severity, v.Path, v.Message, v.OldType, v.NewType, v.Rule)
}

// --- Constructors ---

func Prim(name, format string) *Node {
	return &Node{Kind: KindPrim, Prim: name, Format: format}
}

func Literal(value string) *Node {
	return &Node{Kind: KindLiteral, LiteralValue: value}
}

func Enum(values []string) *Node {
	return &Node{Kind: KindEnum, EnumValues: values}
}

func Array(items *Node) *Node {
	return &Node{Kind: KindArray, Items: items}
}

func Map(key, value *Node) *Node {
	return &Node{Kind: KindMap, MapKey: key, MapValue: value}
}

func Object(fields map[string]*Field, open bool) *Node {
	return &Node{Kind: KindObject, Fields: fields, Open: open}
}

func Union(variants []*Node) *Node {
	return &Node{Kind: KindUnion, Variants: variants}
}

// Nullable wraps a type with null-allowance.
// Normalizes Nullable(Nullable(T)) → Nullable(T).
func Nullable(inner *Node) *Node {
	if inner != nil && inner.Kind == KindNullable {
		return inner // normalization: flatten nested nullable
	}
	return &Node{Kind: KindNullable, Inner: inner}
}

func Ref(name string) *Node {
	return &Node{Kind: KindRef, RefName: name}
}

func Any() *Node {
	return &Node{Kind: KindAny}
}

// Summary returns a compact string representation for diagnostics.
func (n *Node) Summary() string {
	if n == nil {
		return "<nil>"
	}
	switch n.Kind {
	case KindPrim:
		if n.Format != "" {
			return fmt.Sprintf("%s(%s)", n.Prim, n.Format)
		}
		return n.Prim
	case KindLiteral:
		return fmt.Sprintf("literal(%q)", n.LiteralValue)
	case KindEnum:
		return fmt.Sprintf("enum{%s}", strings.Join(n.EnumValues, ","))
	case KindArray:
		return fmt.Sprintf("array(%s)", n.Items.Summary())
	case KindMap:
		return fmt.Sprintf("map(%s,%s)", n.MapKey.Summary(), n.MapValue.Summary())
	case KindObject:
		parts := make([]string, 0, len(n.Fields))
		for name, f := range n.Fields {
			mark := ""
			if f.Required {
				mark = "*"
			}
			parts = append(parts, name+mark+":"+f.Schema.Summary())
		}
		tag := "open"
		if !n.Open {
			tag = "closed"
		}
		return fmt.Sprintf("object(%s){%s}", tag, strings.Join(parts, ", "))
	case KindUnion:
		parts := make([]string, 0, len(n.Variants))
		for _, v := range n.Variants {
			parts = append(parts, v.Summary())
		}
		return fmt.Sprintf("union(%s)", strings.Join(parts, " | "))
	case KindNullable:
		return fmt.Sprintf("nullable(%s)", n.Inner.Summary())
	case KindRef:
		return fmt.Sprintf("ref(%s)", n.RefName)
	case KindAny:
		return "any"
	default:
		return "unknown"
	}
}
