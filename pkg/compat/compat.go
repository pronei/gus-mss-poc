// Package compat implements the GUS type compatibility checker (paper §4).
//
// Check(sender, receiver, d) returns violations when the left schema is not
// compatible with the right schema in direction d ∈ {REQ, RES}.
//
// Argument roles, NOT chronology:
//   - DirREQ: left = what the sender emits (Send), right = what the receiver
//     accepts (Accept). Compatible iff every value the sender may emit is
//     admitted by the receiver.
//   - DirRES: left = what the consumer expects (Expect), right = what the
//     producer returns (Return). Compatible iff every value the producer may
//     return is admitted by the consumer.
//
// Which deployment version supplies each role is the caller's business (see
// pkg/edge for the C1–C4 conjuncts). Violation messages are therefore phrased
// in role terms (sender/receiver, producer/consumer), never "old"/"new";
// pkg/edge fills Violation.OldType/NewType chronologically per conjunct.
package compat

import (
	"fmt"
	"sort"

	"github.com/faults-lab/gus/pkg/lattice"
	"github.com/faults-lab/gus/pkg/types"
)

// Config controls compatibility checking behavior.
type Config struct {
	Format   lattice.Format   // which primitive lattice to use
	Coercion lattice.Coercion // JSON widening profile (strict by default)
}

// DefaultConfig returns the default configuration: JSON lattice, strict
// coercion. Lenient coercion (int/bool/num ≤ string) is opt-in per scenario.
func DefaultConfig() Config {
	return Config{Format: lattice.FormatJSON, Coercion: lattice.CoercionStrict}
}

// Check runs the full compatibility check between the two role schemas.
func Check(left, right *types.Node, dir types.Direction, cfg Config) []types.Violation {
	c := &checker{cfg: cfg, seen: make(map[refPair]bool)}
	return c.check(left, right, dir, "$")
}

type refPair struct{ a, b string }

type checker struct {
	cfg  Config
	seen map[refPair]bool // coinductive guard for recursive types
}

// leq applies the configured primitive lattice.
func (c *checker) leq(a, b string) bool {
	return lattice.Leq(a, b, c.cfg.Format, c.cfg.Coercion)
}

func (c *checker) check(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	if left == nil && right == nil {
		return nil
	}
	if left == nil || right == nil {
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "presence-mismatch",
			Message: "schema present on one side only",
			OldType: summary(left), NewType: summary(right),
		}}
	}

	// Any is compatible with everything.
	if left.Kind == types.KindAny || right.Kind == types.KindAny {
		return nil
	}

	// Nullable unwrapping.
	if left.Kind == types.KindNullable || right.Kind == types.KindNullable {
		return c.checkNullable(left, right, dir, path)
	}

	// Ref: coinductive — assume compatible if already being checked.
	if left.Kind == types.KindRef && right.Kind == types.KindRef {
		return c.checkRef(left, right, path)
	}

	// Literal can compare against Enum or Prim (not just itself).
	if left.Kind == types.KindLiteral || right.Kind == types.KindLiteral {
		return c.checkLiteral(left, right, dir, path)
	}

	// Union vs anything: width subtyping via existential matching.
	if left.Kind == types.KindUnion || right.Kind == types.KindUnion {
		return c.checkUnion(left, right, dir, path)
	}

	// Enum vs Prim: value-set semantics, direction-dependent (deck slide 2:
	// "T1 ≤ T2 iff every value of T1 is admitted by T2"). Enum vs any other
	// kind falls through to kind-mismatch.
	if (left.Kind == types.KindEnum && right.Kind == types.KindPrim) ||
		(left.Kind == types.KindPrim && right.Kind == types.KindEnum) {
		return c.checkEnumPrim(left, right, dir, path)
	}

	// Kind mismatch.
	if left.Kind != right.Kind {
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "kind-mismatch",
			Message: fmt.Sprintf("type kind %s is not admitted where %s is declared", left.Kind, right.Kind),
			OldType: summary(left), NewType: summary(right),
		}}
	}

	switch left.Kind {
	case types.KindPrim:
		return c.checkPrim(left, right, dir, path)
	case types.KindEnum:
		return c.checkEnum(left, right, dir, path)
	case types.KindArray:
		return c.check(left.Items, right.Items, dir, path+"[*]")
	case types.KindMap:
		return c.checkMap(left, right, dir, path)
	case types.KindObject:
		return c.checkObject(left, right, dir, path)
	case types.KindUnion:
		return c.checkUnion(left, right, dir, path)
	default:
		return nil
	}
}

// --- Nullable ---
//
// The rules are stated over roles, so they hold for every conjunct:
// REQ: sender-nullable requires receiver-nullable (receiver must admit null).
// RES: producer-nullable requires consumer-nullable (consumer must expect null).

func (c *checker) checkNullable(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	leftInner, leftNull := unwrapNullable(left)
	rightInner, rightNull := unwrapNullable(right)

	if leftNull == rightNull {
		return c.check(leftInner, rightInner, dir, path)
	}

	switch dir {
	case types.DirREQ:
		if leftNull && !rightNull {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "nullable-request-narrowing",
				Message: "sender may send null but receiver rejects null",
				OldType: summary(left), NewType: summary(right),
			}}
		}
		// Sender non-null, receiver nullable: receiver admits more — safe.
		return c.check(leftInner, rightInner, dir, path)

	case types.DirRES:
		if !leftNull && rightNull {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "nullable-response-widening",
				Message: "producer may return null but consumer does not expect null",
				OldType: summary(left), NewType: summary(right),
			}}
		}
		// Consumer expects nullable, producer never returns null — safe.
		return c.check(leftInner, rightInner, dir, path)
	}
	return nil
}

func unwrapNullable(n *types.Node) (*types.Node, bool) {
	if n.Kind == types.KindNullable {
		return n.Inner, true
	}
	return n, false
}

// --- Ref (coinductive) ---
//
// The loader inlines every non-cyclic $ref and resolves components in sorted
// name order, so Ref nodes appear only at cycle back-edges and at the same
// positions in both trees. Comparing the one-step unfolding (the inlined
// bodies around the back-edge) and assuming compatibility at same-named
// back-edges is standard coinductive practice; a renamed component is
// reported rather than unfolded because the checker has no component table.

func (c *checker) checkRef(left, right *types.Node, path string) []types.Violation {
	pair := refPair{left.RefName, right.RefName}
	if c.seen[pair] {
		return nil // coinductive assumption: compatible
	}
	if left.RefName != right.RefName {
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "ref-name-mismatch",
			Message: fmt.Sprintf("recursive type name differs: %s vs %s", left.RefName, right.RefName),
			OldType: summary(left), NewType: summary(right),
		}}
	}
	c.seen[pair] = true
	return nil
}

// --- Literal ---

// literalBase infers the JSON primitive a literal value belongs to.
// The loader stores literal values as strings without a type tag, so this is
// a best-effort classification for lattice checks.
func literalBase(v string) string {
	if v == "true" || v == "false" {
		return "boolean"
	}
	isInt, isNum := true, len(v) > 0
	for i, r := range v {
		switch {
		case r >= '0' && r <= '9':
		case (r == '-' || r == '+') && i == 0:
		case r == '.' || r == 'e' || r == 'E':
			isInt = false
		default:
			isInt, isNum = false, false
		}
	}
	if isNum && isInt {
		return "integer"
	}
	if isNum {
		return "number"
	}
	return "string"
}

func (c *checker) checkLiteral(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	// Literal vs Literal: values must match.
	if left.Kind == types.KindLiteral && right.Kind == types.KindLiteral {
		if left.LiteralValue != right.LiteralValue {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "literal-mismatch",
				Message: fmt.Sprintf("literal value %q does not match %q", left.LiteralValue, right.LiteralValue),
				OldType: summary(left), NewType: summary(right),
			}}
		}
		return nil
	}

	// Literal(v) on the left: the left side produces exactly v.
	// REQ: sender sends v — receiver must admit v.
	// RES: consumer expects exactly v — producer may return anything in its
	// type, so anything broader than {v} breaks.
	if left.Kind == types.KindLiteral {
		switch right.Kind {
		case types.KindEnum:
			if dir == types.DirREQ {
				if !contains(right.EnumValues, left.LiteralValue) {
					return []types.Violation{{
						Path: path, Severity: types.SevBREAK, Rule: "literal-not-in-enum",
						Message: fmt.Sprintf("literal %q is not among accepted values %v", left.LiteralValue, right.EnumValues),
						OldType: summary(left), NewType: summary(right),
					}}
				}
				return nil
			}
			// RES: producer returns any of the enum; consumer expects one value.
			if len(right.EnumValues) == 1 && right.EnumValues[0] == left.LiteralValue {
				return nil
			}
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "literal-widening",
				Message: fmt.Sprintf("consumer expects exactly %q but producer may return any of %v", left.LiteralValue, right.EnumValues),
				OldType: summary(left), NewType: summary(right),
			}}
		case types.KindPrim:
			if dir == types.DirREQ {
				// Sender sends the literal; receiver accepts the primitive:
				// safe iff the literal's base type fits the primitive.
				if c.leq(literalBase(left.LiteralValue), right.Prim) {
					return nil
				}
				return []types.Violation{{
					Path: path, Severity: types.SevBREAK, Rule: "literal-prim-mismatch",
					Message: fmt.Sprintf("literal %q (base %s) is not admitted by %s", left.LiteralValue, literalBase(left.LiteralValue), right.Prim),
					OldType: summary(left), NewType: summary(right),
				}}
			}
			// RES: consumer expects exactly the literal; producer may return
			// any value of the primitive — break.
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "literal-widening",
				Message: fmt.Sprintf("consumer expects exactly %q but producer may return any %s", left.LiteralValue, right.Prim),
				OldType: summary(left), NewType: summary(right),
			}}
		}
	}

	// Literal(v) on the right: the right side admits/returns exactly v.
	if right.Kind == types.KindLiteral {
		switch left.Kind {
		case types.KindEnum:
			if dir == types.DirRES {
				// Producer returns exactly v; consumer expects one of the enum.
				if contains(left.EnumValues, right.LiteralValue) {
					return nil
				}
			}
			// REQ: sender may send any enum value; receiver admits only v.
			if dir == types.DirREQ && len(left.EnumValues) == 1 && left.EnumValues[0] == right.LiteralValue {
				return nil
			}
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "literal-narrowing",
				Message: fmt.Sprintf("only literal %q is admitted but the other side covers %v", right.LiteralValue, left.EnumValues),
				OldType: summary(left), NewType: summary(right),
			}}
		case types.KindPrim:
			if dir == types.DirRES {
				// Producer returns exactly v; consumer expects the primitive:
				// safe iff v fits the expected primitive.
				if c.leq(literalBase(right.LiteralValue), left.Prim) {
					return nil
				}
			}
			// REQ: sender may send any value of the primitive; receiver
			// admits only the literal — break.
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "literal-narrowing",
				Message: fmt.Sprintf("only literal %q is admitted but the other side covers all of %s", right.LiteralValue, left.Prim),
				OldType: summary(left), NewType: summary(right),
			}}
		}
	}

	return []types.Violation{{
		Path: path, Severity: types.SevBREAK, Rule: "kind-mismatch",
		Message: fmt.Sprintf("type kind %s is not admitted where %s is declared", left.Kind, right.Kind),
		OldType: summary(left), NewType: summary(right),
	}}
}

// --- Enum vs Prim ---
//
// Value-set semantics: Enum(S) over base type T satisfies Enum(S) ≤ T.
// REQ with enum sender + prim receiver: safe iff every enum value's base type
// fits the receiver primitive. REQ with prim sender + enum receiver: the
// sender may emit values outside S — break.
// RES with prim consumer + enum producer: safe iff enum values fit the
// expected primitive. RES with enum consumer + prim producer: the producer
// may return values outside S — break (consumer switch statements).

func (c *checker) checkEnumPrim(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	enumFits := func(e *types.Node, prim string) bool {
		for _, v := range e.EnumValues {
			if !c.leq(literalBase(v), prim) {
				return false
			}
		}
		return true
	}

	if left.Kind == types.KindEnum && right.Kind == types.KindPrim {
		// REQ: enum sender → prim receiver (safe widening).
		// RES: enum consumer ← prim producer (unsafe: unknown values).
		if dir == types.DirREQ {
			if enumFits(left, right.Prim) {
				return nil
			}
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "enum-prim-mismatch",
				Message: fmt.Sprintf("enum values %v do not fit primitive %s", left.EnumValues, right.Prim),
				OldType: summary(left), NewType: summary(right),
			}}
		}
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "enum-response-widening",
			Message: fmt.Sprintf("producer may return any %s but consumer only handles %v", right.Prim, left.EnumValues),
			OldType: summary(left), NewType: summary(right),
		}}
	}

	// left prim, right enum.
	if dir == types.DirRES {
		// Prim consumer ← enum producer: safe narrowing if values fit.
		if enumFits(right, left.Prim) {
			return nil
		}
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "enum-prim-mismatch",
			Message: fmt.Sprintf("returned enum values %v do not fit expected primitive %s", right.EnumValues, left.Prim),
			OldType: summary(left), NewType: summary(right),
		}}
	}
	// REQ: prim sender → enum receiver: sender may emit values outside the set.
	return []types.Violation{{
		Path: path, Severity: types.SevBREAK, Rule: "enum-request-narrowing",
		Message: fmt.Sprintf("sender may send any %s but receiver only accepts %v", left.Prim, right.EnumValues),
		OldType: summary(left), NewType: summary(right),
	}}
}

// --- Primitive ---

func (c *checker) checkPrim(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	switch dir {
	case types.DirREQ:
		// Sender's type must be admitted by the receiver's type.
		if !c.leq(left.Prim, right.Prim) {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "prim-mismatch",
				Message: fmt.Sprintf("sender type %s is not admitted by receiver type %s in the lattice", left.Prim, right.Prim),
				OldType: summary(left), NewType: summary(right),
			}}
		}
		// Format: sender's range must fit the receiver's range.
		if !lattice.FormatLeq(left.Format, right.Format) {
			return []types.Violation{{
				Path: path, Severity: types.SevWARN, Rule: "format-change",
				Message: fmt.Sprintf("sender format %s may exceed receiver format %s (range overflow risk)", left.Format, right.Format),
				OldType: summary(left), NewType: summary(right),
			}}
		}
	case types.DirRES:
		// Producer's type must be admitted by the consumer's type.
		if !c.leq(right.Prim, left.Prim) {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "prim-mismatch",
				Message: fmt.Sprintf("producer returns %s but consumer expects %s (not admitted in the lattice)", right.Prim, left.Prim),
				OldType: summary(left), NewType: summary(right),
			}}
		}
		// Format: producer's range must fit the consumer's range.
		if !lattice.FormatLeq(right.Format, left.Format) {
			return []types.Violation{{
				Path: path, Severity: types.SevWARN, Rule: "format-change",
				Message: fmt.Sprintf("producer format %s may exceed consumer format %s (range overflow risk)", right.Format, left.Format),
				OldType: summary(left), NewType: summary(right),
			}}
		}
	}
	return nil
}

// --- Enum ---

func (c *checker) checkEnum(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	leftSet := toSet(left.EnumValues)
	rightSet := toSet(right.EnumValues)

	switch dir {
	case types.DirREQ:
		// Receiver must admit everything the sender may send (left ⊆ right).
		missing := setDiff(leftSet, rightSet)
		if len(missing) > 0 {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "enum-request-narrowing",
				Message: fmt.Sprintf("sender may send enum values %v that receiver does not accept", sortedKeys(missing)),
				OldType: summary(left), NewType: summary(right),
			}}
		}
	case types.DirRES:
		// Consumer must understand everything the producer may return (right ⊆ left).
		extra := setDiff(rightSet, leftSet)
		if len(extra) > 0 {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "enum-response-widening",
				Message: fmt.Sprintf("producer may return enum values %v that consumer does not understand", sortedKeys(extra)),
				OldType: summary(left), NewType: summary(right),
			}}
		}
	}
	return nil
}

// --- Map ---

func (c *checker) checkMap(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	var vs []types.Violation

	// Key types must be strictly equal (no subtyping on map keys).
	if left.MapKey != nil && right.MapKey != nil {
		if left.MapKey.Kind != right.MapKey.Kind || left.MapKey.Prim != right.MapKey.Prim {
			vs = append(vs, types.Violation{
				Path: path + ".key", Severity: types.SevBREAK, Rule: "map-key-mismatch",
				Message: fmt.Sprintf("map key types differ: %s vs %s (keys are invariant)", summary(left.MapKey), summary(right.MapKey)),
				OldType: summary(left.MapKey), NewType: summary(right.MapKey),
			})
		}
	}

	vs = append(vs, c.check(left.MapValue, right.MapValue, dir, path+".value")...)
	return vs
}

// --- Object ---

func (c *checker) checkObject(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	var vs []types.Violation

	switch dir {
	case types.DirREQ:
		vs = c.checkObjectReq(left, right, path)
	case types.DirRES:
		vs = c.checkObjectRes(left, right, path)
	}

	// Recurse on shared fields.
	for _, name := range sortedFieldNames(left.Fields) {
		rightF, exists := right.Fields[name]
		if !exists {
			continue
		}
		vs = append(vs, c.check(left.Fields[name].Schema, rightF.Schema, dir, path+"."+name)...)
	}
	return vs
}

// checkObjectReq: left = sender's object, right = receiver's accepted object.
func (c *checker) checkObjectReq(sender, receiver *types.Node, path string) []types.Violation {
	var vs []types.Violation

	// REQ.1: receiver requires a field the sender does not have, with no default.
	for _, name := range sortedFieldNames(receiver.Fields) {
		f := receiver.Fields[name]
		if !f.Required {
			continue
		}
		if _, sent := sender.Fields[name]; !sent && !f.HasDefault {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "REQ.1",
				Message: "receiver requires field the sender does not send (and no default is declared)",
				OldType: "<absent>", NewType: summary(f.Schema),
			})
		}
	}

	// REQ.2: field is optional for the sender but required by the receiver.
	for _, name := range sortedFieldNames(sender.Fields) {
		sF := sender.Fields[name]
		rF, exists := receiver.Fields[name]
		if !exists {
			continue
		}
		if !sF.Required && rF.Required && !rF.HasDefault {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "REQ.2",
				Message: "field is optional for the sender but required by the receiver",
				OldType: "optional " + summary(sF.Schema), NewType: "required " + summary(rF.Schema),
			})
		}
	}

	// REQ.4: sender has a field the receiver's closed schema rejects.
	for _, name := range sortedFieldNames(sender.Fields) {
		if _, exists := receiver.Fields[name]; exists {
			continue
		}
		if !receiver.Open {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "REQ.4",
				Message: "sender sends field the receiver's closed schema rejects",
				OldType: summary(sender.Fields[name].Schema), NewType: "<absent>",
			})
		}
	}

	return vs
}

// checkObjectRes: left = consumer's expected object, right = producer's returned object.
func (c *checker) checkObjectRes(consumer, producer *types.Node, path string) []types.Violation {
	var vs []types.Violation

	for _, name := range sortedFieldNames(consumer.Fields) {
		cF := consumer.Fields[name]
		if !cF.Required {
			continue
		}
		pF, exists := producer.Fields[name]
		if !exists {
			// RES.1: consumer requires a field the producer does not return.
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "RES.1",
				Message: "consumer requires field the producer does not return",
				OldType: summary(cF.Schema), NewType: "<absent>",
			})
			continue
		}
		// RES.4: consumer requires the field but the producer marks it optional.
		if !pF.Required {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "RES.4",
				Message: "consumer requires field the producer only returns optionally",
				OldType: "required " + summary(cF.Schema), NewType: "optional " + summary(pF.Schema),
			})
		}
	}

	// RES.5: producer returns fields the consumer's closed schema rejects.
	if !consumer.Open {
		for _, name := range sortedFieldNames(producer.Fields) {
			if _, exists := consumer.Fields[name]; !exists {
				vs = append(vs, types.Violation{
					Path: path + "." + name, Severity: types.SevBREAK, Rule: "RES.5",
					Message: "producer returns field the consumer's closed schema rejects",
					OldType: "<absent>", NewType: summary(producer.Fields[name].Schema),
				})
			}
		}
	}

	return vs
}

// --- Union (existential matching) ---
//
// A variant pair matches when the comparison yields no BREAK-severity
// violations; WARN-only pairs still match (a warning must not escalate to a
// break just because the type is wrapped in oneOf). A non-union compared
// against a union is treated as a single-variant union (width subtyping).

func (c *checker) checkUnion(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	leftVars := variants(left)
	rightVars := variants(right)

	noBreaks := func(vs []types.Violation) bool {
		for _, v := range vs {
			if v.Severity == types.SevBREAK {
				return false
			}
		}
		return true
	}

	var vs []types.Violation
	switch dir {
	case types.DirREQ:
		// Every value the sender may emit must be admitted: ∀L ∃R compat.
		for i, lv := range leftVars {
			found := false
			for _, rv := range rightVars {
				if noBreaks(c.check(lv, rv, types.DirREQ, path)) {
					found = true
					break
				}
			}
			if !found {
				vs = append(vs, types.Violation{
					Path: path, Severity: types.SevBREAK, Rule: "union-request-narrowing",
					Message: fmt.Sprintf("sender union variant %d (%s) is not admitted by any receiver variant", i, summary(lv)),
					OldType: summary(left), NewType: summary(right),
				})
			}
		}
	case types.DirRES:
		// Every value the producer may return must be understood: ∀R ∃L compat.
		for i, rv := range rightVars {
			found := false
			for _, lv := range leftVars {
				if noBreaks(c.check(lv, rv, types.DirRES, path)) {
					found = true
					break
				}
			}
			if !found {
				vs = append(vs, types.Violation{
					Path: path, Severity: types.SevBREAK, Rule: "union-response-widening",
					Message: fmt.Sprintf("producer union variant %d (%s) is not understood by any consumer variant", i, summary(rv)),
					OldType: summary(left), NewType: summary(right),
				})
			}
		}
	}
	return vs
}

func variants(n *types.Node) []*types.Node {
	if n.Kind == types.KindUnion {
		return n.Variants
	}
	return []*types.Node{n}
}

// --- Helpers ---

func summary(n *types.Node) string {
	if n == nil {
		return "<nil>"
	}
	return n.Summary()
}

func contains(vals []string, v string) bool {
	for _, val := range vals {
		if val == v {
			return true
		}
	}
	return false
}

func toSet(vals []string) map[string]bool {
	s := make(map[string]bool, len(vals))
	for _, v := range vals {
		s[v] = true
	}
	return s
}

func setDiff(a, b map[string]bool) map[string]bool {
	d := make(map[string]bool)
	for k := range a {
		if !b[k] {
			d[k] = true
		}
	}
	return d
}

func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func sortedFieldNames(fields map[string]*types.Field) []string {
	names := make([]string, 0, len(fields))
	for n := range fields {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}
