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
	"strings"

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

	// Nullable and Union are both sums. Either side is normalized to a set of
	// plain variants plus a null flag, so that null admitted through a
	// nullable variant and unions nested via $ref are both seen for what
	// they are.
	if isSum(left) || isSum(right) {
		return c.checkSum(left, right, dir, path)
	}

	// Ref: coinductive — assume compatible if already being checked.
	if left.Kind == types.KindRef && right.Kind == types.KindRef {
		return c.checkRef(left, right, path)
	}

	// Enum vs Prim: value-set semantics, direction-dependent (deck slide 2:
	// "T1 ≤ T2 iff every value of T1 is admitted by T2"). Enum vs any other
	// kind falls through to kind-mismatch.
	if (left.Kind == types.KindEnum && right.Kind == types.KindPrim) ||
		(left.Kind == types.KindPrim && right.Kind == types.KindEnum) {
		// A boolean primitive is the two-value enumeration {true, false}
		// (Habib et al.'s canonicalization), so boolean against an enum is
		// an enum-against-enum comparison rather than a primitive one.
		if l, r := boolAsEnum(left), boolAsEnum(right); l.Kind == types.KindEnum && r.Kind == types.KindEnum {
			return c.checkEnum(l, r, dir, path)
		}
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
	default:
		return nil
	}
}

var boolEnum = &types.Node{Kind: types.KindEnum, EnumValues: []string{"true", "false"}, EnumBase: "boolean"}

// boolAsEnum reads a boolean primitive as the enumeration {true, false}.
func boolAsEnum(n *types.Node) *types.Node {
	if n.Kind == types.KindPrim && n.Prim == "boolean" {
		return boolEnum
	}
	return n
}

// noBreaks reports whether a comparison produced no BREAK-severity finding.
func noBreaks(vs []types.Violation) bool {
	for _, v := range vs {
		if v.Severity == types.SevBREAK {
			return false
		}
	}
	return true
}

// exclusiveAlternatives returns the direct alternatives of a oneOf (possibly
// wrapped in Nullable), or nil when the node is not an exclusive union.
func exclusiveAlternatives(n *types.Node) []*types.Node {
	if n.Kind == types.KindNullable {
		n = n.Inner
	}
	if n != nil && n.Kind == types.KindUnion && n.Exclusive {
		return n.Variants
	}
	return nil
}

// --- Sums: Nullable and Union ---
//
// A type is read as a set: its plain variants (nested unions flattened) plus
// whether null is admitted (a Nullable at any union level). The null rules
// are stated over roles, so they hold for every conjunct:
// REQ: sender-nullable requires receiver-nullable (receiver must admit null).
// RES: producer-nullable requires consumer-nullable (consumer must expect null).

func isSum(n *types.Node) bool {
	return n.Kind == types.KindNullable || n.Kind == types.KindUnion || isNullPrim(n)
}

// isNullPrim recognizes the bare `null` type: the value set {null}, which
// flatten reads as "admits null" with no plain variant.
func isNullPrim(n *types.Node) bool {
	return n.Kind == types.KindPrim && n.Prim == "null"
}

// flatten returns the plain variants of n and whether n admits null.
func flatten(n *types.Node) ([]*types.Node, bool) {
	if isNullPrim(n) {
		return nil, true
	}
	switch n.Kind {
	case types.KindNullable:
		vs, _ := flatten(n.Inner)
		return vs, true
	case types.KindUnion:
		var vs []*types.Node
		nullable := false
		for _, v := range n.Variants {
			vv, nn := flatten(v)
			vs = append(vs, vv...)
			nullable = nullable || nn
		}
		return vs, nullable
	}
	return []*types.Node{n}, false
}

func (c *checker) checkSum(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	leftVars, leftNull := flatten(left)
	rightVars, rightNull := flatten(right)

	if leftNull != rightNull {
		switch {
		case dir == types.DirREQ && leftNull:
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "nullable-request-narrowing",
				Message: "sender may send null but receiver rejects null",
				OldType: summary(left), NewType: summary(right),
			}}
		case dir == types.DirRES && rightNull:
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "nullable-response-widening",
				Message: "producer may return null but consumer does not expect null",
				OldType: summary(left), NewType: summary(right),
			}}
		}
		// Sender non-null into a null-admitting receiver, or a null-expecting
		// consumer of a never-null producer: the extra admission is safe.
	}

	// The exactly-one constraint of a oneOf, in the part decidable without
	// negation: a variant admitted outright by two alternatives of the
	// exclusive side is rejected by it whatever else holds. A variant that
	// overlaps a second alternative only partially is not detected.
	var vs []types.Violation
	admitter, emitted, role := right, leftVars, "sender"
	if dir == types.DirRES {
		admitter, emitted, role = left, rightVars, "producer"
	}
	if alts := exclusiveAlternatives(admitter); len(alts) > 1 {
		for i, e := range emitted {
			fits := 0
			for _, alt := range alts {
				var cvs []types.Violation
				if dir == types.DirREQ {
					cvs = c.check(e, alt, dir, path)
				} else {
					cvs = c.check(alt, e, dir, path)
				}
				if noBreaks(cvs) {
					fits++
				}
			}
			if fits > 1 {
				vs = append(vs, types.Violation{
					Path: path, Severity: types.SevBREAK, Rule: "oneof-ambiguity",
					Message: fmt.Sprintf("%s variant %d (%s) fits %d alternatives of a oneOf that admits a value only when exactly one matches", role, i, summary(e), fits),
					OldType: summary(left), NewType: summary(right),
				})
			}
		}
	}

	// One plain variant on each side: compare directly so the precise rule
	// (prim-mismatch, REQ.1, ...) is reported rather than a union rule.
	if len(leftVars) == 1 && len(rightVars) == 1 {
		return append(vs, c.check(leftVars[0], rightVars[0], dir, path)...)
	}
	return append(vs, c.checkUnion(leftVars, rightVars, left, right, dir, path)...)
}

// --- Ref (coinductive) ---
//
// The loader inlines every non-cyclic $ref and resolves components in sorted
// name order, so Ref nodes appear only at cycle back-edges and at the same
// positions in both trees. Comparing the one-step unfolding (the inlined
// bodies around the back-edge) and assuming compatibility at same-named
// back-edges is standard coinductive practice; a renamed component is
// reported rather than unfolded because the checker has no component table.

// localName strips the service qualifier the loader prepends ("svc.Name" ->
// "Name"). The two sides of an edge come from different services' documents,
// and the coinductive hypothesis is keyed by the component's name, not by
// which document declared it; the one-step unfolding around the back-edge is
// still compared structurally.
func localName(qualified string) string {
	if i := strings.Index(qualified, "."); i >= 0 {
		return qualified[i+1:]
	}
	return qualified
}

func (c *checker) checkRef(left, right *types.Node, path string) []types.Violation {
	pair := refPair{left.RefName, right.RefName}
	if c.seen[pair] {
		return nil // coinductive assumption: compatible
	}
	if localName(left.RefName) != localName(right.RefName) {
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "ref-name-mismatch",
			Message: fmt.Sprintf("recursive type name differs: %s vs %s", left.RefName, right.RefName),
			OldType: summary(left), NewType: summary(right),
		}}
	}
	c.seen[pair] = true
	return nil
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

// valueBase infers the JSON primitive an enum value string belongs to. It is
// the fallback for schemas that declare an enum without a type; when a type
// is declared the loader records it as EnumBase and that is authoritative.
func valueBase(v string) string {
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

func (c *checker) checkEnumPrim(left, right *types.Node, dir types.Direction, path string) []types.Violation {
	enumFits := func(e *types.Node, prim string) bool {
		if e.EnumBase != "" {
			return c.leq(e.EnumBase, prim)
		}
		for _, v := range e.EnumValues {
			if !c.leq(valueBase(v), prim) {
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
	// Values are compared as spellings, so a change of declared base type
	// (integer 1 to string "1") is caught here, direction-aware.
	if left.EnumBase != "" && right.EnumBase != "" && left.EnumBase != right.EnumBase {
		from, to := left.EnumBase, right.EnumBase
		if dir == types.DirRES {
			from, to = right.EnumBase, left.EnumBase
		}
		if !c.leq(from, to) {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "prim-mismatch",
				Message: fmt.Sprintf("enum base type %s is not admitted where %s is declared", from, to),
				OldType: summary(left), NewType: summary(right),
			}}
		}
	}

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
// Width subtyping over flattened variant sets: REQ requires every sender
// variant to be admitted by some receiver variant, RES every producer
// variant to be understood by some consumer variant. A candidate pair
// matches when the comparison yields no BREAK-severity violation; a
// WARN-only match still matches, and its warnings are reported, so that a
// warning neither blocks nor vanishes because the type sits inside a union.

func (c *checker) checkUnion(leftVars, rightVars []*types.Node, left, right *types.Node, dir types.Direction, path string) []types.Violation {
	// matchOne looks for a candidate admitting the probed variant: a clean
	// match wins outright; otherwise the first WARN-only match counts and
	// carries its warnings.
	matchOne := func(probe func(cand *types.Node) []types.Violation, cands []*types.Node) (bool, []types.Violation) {
		var warnOnly []types.Violation
		found := false
		for _, cand := range cands {
			cvs := probe(cand)
			if len(cvs) == 0 {
				return true, nil
			}
			if !found && noBreaks(cvs) {
				found, warnOnly = true, cvs
			}
		}
		return found, warnOnly
	}

	var vs []types.Violation
	switch dir {
	case types.DirREQ:
		for i, lv := range leftVars {
			ok, warns := matchOne(func(rv *types.Node) []types.Violation {
				return c.check(lv, rv, types.DirREQ, path)
			}, rightVars)
			if !ok {
				vs = append(vs, types.Violation{
					Path: path, Severity: types.SevBREAK, Rule: "union-request-narrowing",
					Message: fmt.Sprintf("sender union variant %d (%s) is not admitted by any receiver variant", i, summary(lv)),
					OldType: summary(left), NewType: summary(right),
				})
				continue
			}
			vs = append(vs, warns...)
		}
	case types.DirRES:
		for i, rv := range rightVars {
			ok, warns := matchOne(func(lv *types.Node) []types.Violation {
				return c.check(lv, rv, types.DirRES, path)
			}, leftVars)
			if !ok {
				vs = append(vs, types.Violation{
					Path: path, Severity: types.SevBREAK, Rule: "union-response-widening",
					Message: fmt.Sprintf("producer union variant %d (%s) is not understood by any consumer variant", i, summary(rv)),
					OldType: summary(left), NewType: summary(right),
				})
				continue
			}
			vs = append(vs, warns...)
		}
	}
	return vs
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
