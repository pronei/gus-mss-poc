// Package compat implements the GUS type compatibility checker (paper §4).
// compat(T₁, T₂, d) returns violations when T₁ is not compatible with T₂
// in direction d ∈ {REQ, RES}.
package compat

import (
	"fmt"
	"sort"

	"github.com/faults-lab/gus/pkg/lattice"
	"github.com/faults-lab/gus/pkg/types"
)

// Config controls compatibility checking behavior.
type Config struct {
	Format lattice.Format // determines which primitive lattice to use
}

// DefaultConfig returns the default configuration (JSON lattice).
func DefaultConfig() Config {
	return Config{Format: lattice.FormatJSON}
}

// Check runs the full compatibility check between old and new schemas.
func Check(old, new *types.Node, dir types.Direction, cfg Config) []types.Violation {
	c := &checker{cfg: cfg, seen: make(map[refPair]bool)}
	return c.check(old, new, dir, "$")
}

type refPair struct{ a, b string }

type checker struct {
	cfg  Config
	seen map[refPair]bool // coinductive guard for recursive types
}

func (c *checker) check(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	if old == nil && new == nil {
		return nil
	}
	if old == nil || new == nil {
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "presence-mismatch",
			Message: "schema presence changed",
			OldType: summary(old), NewType: summary(new),
		}}
	}

	// Any is compatible with everything
	if old.Kind == types.KindAny || new.Kind == types.KindAny {
		return nil
	}

	// Nullable unwrapping
	if old.Kind == types.KindNullable || new.Kind == types.KindNullable {
		return c.checkNullable(old, new, dir, path)
	}

	// Ref: coinductive — assume compatible if already being checked
	if old.Kind == types.KindRef && new.Kind == types.KindRef {
		return c.checkRef(old, new, path)
	}

	// Literal can compare against Enum or Prim (not just itself)
	if old.Kind == types.KindLiteral || new.Kind == types.KindLiteral {
		return c.checkLiteral(old, new, dir, path)
	}

	// Kind mismatch
	if old.Kind != new.Kind {
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "kind-mismatch",
			Message: fmt.Sprintf("type kind changed from %s to %s", old.Kind, new.Kind),
			OldType: summary(old), NewType: summary(new),
		}}
	}

	switch old.Kind {
	case types.KindPrim:
		return c.checkPrim(old, new, dir, path)
	case types.KindEnum:
		return c.checkEnum(old, new, dir, path)
	case types.KindArray:
		return c.check(old.Items, new.Items, dir, path+"[*]")
	case types.KindMap:
		return c.checkMap(old, new, dir, path)
	case types.KindObject:
		return c.checkObject(old, new, dir, path)
	case types.KindUnion:
		return c.checkUnion(old, new, dir, path)
	default:
		return nil
	}
}

// --- Nullable ---

func (c *checker) checkNullable(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	oldInner, oldNull := unwrapNullable(old)
	newInner, newNull := unwrapNullable(new)

	if oldNull == newNull {
		return c.check(oldInner, newInner, dir, path)
	}

	switch dir {
	case types.DirREQ:
		if oldNull && !newNull {
			// nullable → non-null in request: provider now rejects null callers might send
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "nullable-request-narrowing",
				Message: "field became non-nullable in request (rejects null callers might send)",
				OldType: summary(old), NewType: summary(new),
			}}
		}
		// non-null → nullable in request is safe (provider accepts more)
		return c.check(oldInner, newInner, dir, path)

	case types.DirRES:
		if !oldNull && newNull {
			// non-null → nullable in response: consumers don't expect null
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "nullable-response-widening",
				Message: "field became nullable in response (consumers may not handle null)",
				OldType: summary(old), NewType: summary(new),
			}}
		}
		// nullable → non-null in response is safe (provider returns more specific)
		return c.check(oldInner, newInner, dir, path)
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

func (c *checker) checkRef(old, new *types.Node, path string) []types.Violation {
	pair := refPair{old.RefName, new.RefName}
	if c.seen[pair] {
		return nil // coinductive assumption: compatible
	}
	if old.RefName != new.RefName {
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "ref-name-mismatch",
			Message: fmt.Sprintf("recursive type name changed from %s to %s", old.RefName, new.RefName),
			OldType: summary(old), NewType: summary(new),
		}}
	}
	c.seen[pair] = true
	return nil // same name, assume structurally compatible (coinductive)
}

// --- Literal ---

func (c *checker) checkLiteral(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	switch dir {
	case types.DirREQ:
		// Request: the sender sends old, receiver accepts new.
		// Literal(v) ⊑ Enum(S) iff v ∈ S
		// Literal(v) ⊑ Prim if v's base type ≤ Prim
		// Enum(S) ⊑ Literal(v) iff S = {v}
		return c.checkLiteralCompat(old, new, dir, path)
	case types.DirRES:
		// Response: old is Expect, new is Return. Flipped variance.
		return c.checkLiteralCompat(old, new, dir, path)
	}
	return nil
}

func (c *checker) checkLiteralCompat(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	// Literal ⊑ Literal: values must match
	if old.Kind == types.KindLiteral && new.Kind == types.KindLiteral {
		if old.LiteralValue != new.LiteralValue {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "literal-mismatch",
				Message: fmt.Sprintf("literal value changed from %q to %q", old.LiteralValue, new.LiteralValue),
				OldType: summary(old), NewType: summary(new),
			}}
		}
		return nil
	}

	// Literal(v) vs Enum(S)
	if old.Kind == types.KindLiteral && new.Kind == types.KindEnum {
		if dir == types.DirREQ {
			// sender sends literal v, receiver accepts enum S: v must be in S
			if !contains(new.EnumValues, old.LiteralValue) {
				return []types.Violation{{
					Path: path, Severity: types.SevBREAK, Rule: "literal-not-in-enum",
					Message: fmt.Sprintf("literal %q not in target enum %v", old.LiteralValue, new.EnumValues),
					OldType: summary(old), NewType: summary(new),
				}}
			}
			return nil
		}
		// RES: response narrows from enum to literal — only safe if enum had just that value
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "kind-mismatch",
			Message: fmt.Sprintf("type changed from %s to %s", old.Kind, new.Kind),
			OldType: summary(old), NewType: summary(new),
		}}
	}

	if old.Kind == types.KindEnum && new.Kind == types.KindLiteral {
		if dir == types.DirRES {
			// response narrows from enum to literal — literal must be in old enum
			if contains(old.EnumValues, new.LiteralValue) {
				return nil // safe narrowing
			}
		}
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "kind-mismatch",
			Message: fmt.Sprintf("type changed from %s to %s", old.Kind, new.Kind),
			OldType: summary(old), NewType: summary(new),
		}}
	}

	// Literal vs Prim: check lattice
	if old.Kind == types.KindLiteral && new.Kind == types.KindPrim {
		// Literal is always compatible upward to its base prim type
		return nil // literal value can be received as its primitive type
	}
	if old.Kind == types.KindPrim && new.Kind == types.KindLiteral {
		// Narrowing from prim to literal: always a break (can't guarantee exact value)
		return []types.Violation{{
			Path: path, Severity: types.SevBREAK, Rule: "prim-to-literal",
			Message: "type narrowed from primitive to literal",
			OldType: summary(old), NewType: summary(new),
		}}
	}

	// Fallback: incompatible
	return []types.Violation{{
		Path: path, Severity: types.SevBREAK, Rule: "kind-mismatch",
		Message: fmt.Sprintf("type kind changed from %s to %s", old.Kind, new.Kind),
		OldType: summary(old), NewType: summary(new),
	}}
}

// --- Primitive ---

func (c *checker) checkPrim(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	switch dir {
	case types.DirREQ:
		// Contravariant: old (what caller sends) ≤ new (what provider accepts)
		if !lattice.Leq(old.Prim, new.Prim, c.cfg.Format) {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "prim-mismatch",
				Message: fmt.Sprintf("request type %s not ≤ %s in lattice", old.Prim, new.Prim),
				OldType: summary(old), NewType: summary(new),
			}}
		}
	case types.DirRES:
		// Covariant: new (what provider returns) ≤ old (what caller expects)
		if !lattice.Leq(new.Prim, old.Prim, c.cfg.Format) {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "prim-mismatch",
				Message: fmt.Sprintf("response type %s not ≤ %s in lattice", new.Prim, old.Prim),
				OldType: summary(old), NewType: summary(new),
			}}
		}
	}

	// Format change within same primitive: warn
	if old.Format != new.Format && old.Format != "" && new.Format != "" {
		if !lattice.FormatLeq(old.Format, new.Format) {
			return []types.Violation{{
				Path: path, Severity: types.SevWARN, Rule: "format-change",
				Message: fmt.Sprintf("format changed from %s to %s", old.Format, new.Format),
				OldType: summary(old), NewType: summary(new),
			}}
		}
	}
	return nil
}

// --- Enum ---

func (c *checker) checkEnum(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	oldSet := toSet(old.EnumValues)
	newSet := toSet(new.EnumValues)

	switch dir {
	case types.DirREQ:
		// Contravariant: new must accept at least everything old accepted (old ⊆ new)
		missing := setDiff(oldSet, newSet)
		if len(missing) > 0 {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "enum-request-narrowing",
				Message: fmt.Sprintf("request enum narrowed: values %v no longer accepted", sortedKeys(missing)),
				OldType: summary(old), NewType: summary(new),
			}}
		}
	case types.DirRES:
		// Covariant: new must produce only values old consumers understand (new ⊆ old)
		extra := setDiff(newSet, oldSet)
		if len(extra) > 0 {
			return []types.Violation{{
				Path: path, Severity: types.SevBREAK, Rule: "enum-response-widening",
				Message: fmt.Sprintf("response enum widened: new values %v not understood by consumers", sortedKeys(extra)),
				OldType: summary(old), NewType: summary(new),
			}}
		}
	}
	return nil
}

// --- Map ---

func (c *checker) checkMap(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	var vs []types.Violation

	// Key types must be strictly equal (no subtyping on map keys)
	if old.MapKey != nil && new.MapKey != nil {
		if old.MapKey.Kind != new.MapKey.Kind || old.MapKey.Prim != new.MapKey.Prim {
			vs = append(vs, types.Violation{
				Path: path + ".key", Severity: types.SevBREAK, Rule: "map-key-mismatch",
				Message: fmt.Sprintf("map key type changed from %s to %s", summary(old.MapKey), summary(new.MapKey)),
				OldType: summary(old.MapKey), NewType: summary(new.MapKey),
			})
		}
	}

	// Value types: recurse with direction
	vs = append(vs, c.check(old.MapValue, new.MapValue, dir, path+".value")...)
	return vs
}

// --- Object ---

func (c *checker) checkObject(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	var vs []types.Violation

	switch dir {
	case types.DirREQ:
		vs = c.checkObjectReq(old, new, path)
	case types.DirRES:
		vs = c.checkObjectRes(old, new, path)
	}

	// Recurse on shared fields
	for name, oldF := range old.Fields {
		newF, exists := new.Fields[name]
		if !exists {
			continue
		}
		vs = append(vs, c.check(oldF.Schema, newF.Schema, dir, path+"."+name)...)
	}
	return vs
}

func (c *checker) checkObjectReq(old, new *types.Node, path string) []types.Violation {
	var vs []types.Violation

	// REQ.1: New required fields without defaults → BREAK
	for name, f := range new.Fields {
		if !f.Required {
			continue
		}
		if _, existed := old.Fields[name]; !existed && !f.HasDefault {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "REQ.1",
				Message: "new required field without default (old callers won't send it)",
				OldType: "<absent>", NewType: summary(f.Schema),
			})
		}
	}

	// REQ.2: optional → required → BREAK
	for name, oldF := range old.Fields {
		newF, exists := new.Fields[name]
		if !exists {
			continue
		}
		if !oldF.Required && newF.Required {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "REQ.2",
				Message: "field became required (old callers may not send it)",
				OldType: "optional " + summary(oldF.Schema), NewType: "required " + summary(newF.Schema),
			})
		}
	}

	// REQ.4: Removed fields on closed schema → BREAK
	for name, oldF := range old.Fields {
		if _, exists := new.Fields[name]; exists {
			continue
		}
		if !new.Open {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "REQ.4",
				Message: "field removed from closed schema (old callers sending it will be rejected)",
				OldType: summary(oldF.Schema), NewType: "<absent>",
			})
		}
	}

	return vs
}

func (c *checker) checkObjectRes(old, new *types.Node, path string) []types.Violation {
	var vs []types.Violation

	// RES.1: Required field removed → BREAK
	for name, oldF := range old.Fields {
		if !oldF.Required {
			continue
		}
		newF, exists := new.Fields[name]
		if !exists {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "RES.1",
				Message: "required field removed from response (consumers expect it)",
				OldType: summary(oldF.Schema), NewType: "<absent>",
			})
			continue
		}
		// RES.4: required → optional → BREAK
		if !newF.Required {
			vs = append(vs, types.Violation{
				Path: path + "." + name, Severity: types.SevBREAK, Rule: "RES.4",
				Message: "required field became optional in response",
				OldType: "required " + summary(oldF.Schema), NewType: "optional " + summary(newF.Schema),
			})
		}
	}

	return vs
}

// --- Union (existential matching) ---

func (c *checker) checkUnion(old, new *types.Node, dir types.Direction, path string) []types.Violation {
	switch dir {
	case types.DirREQ:
		// ∀T∈old.Variants ∃T'∈new.Variants: compat(T,T',REQ)
		for i, oldV := range old.Variants {
			found := false
			for _, newV := range new.Variants {
				if len(c.check(oldV, newV, types.DirREQ, path)) == 0 {
					found = true
					break
				}
			}
			if !found {
				return []types.Violation{{
					Path: path, Severity: types.SevBREAK, Rule: "union-request-narrowing",
					Message: fmt.Sprintf("request union variant %d (%s) has no compatible match in new union", i, summary(oldV)),
					OldType: summary(old), NewType: summary(new),
				}}
			}
		}
	case types.DirRES:
		// ∀T∈new.Variants ∃T'∈old.Variants: compat(T',T,RES)
		for i, newV := range new.Variants {
			found := false
			for _, oldV := range old.Variants {
				if len(c.check(oldV, newV, types.DirRES, path)) == 0 {
					found = true
					break
				}
			}
			if !found {
				return []types.Violation{{
					Path: path, Severity: types.SevBREAK, Rule: "union-response-widening",
					Message: fmt.Sprintf("response union variant %d (%s) has no compatible match in old union", i, summary(newV)),
					OldType: summary(old), NewType: summary(new),
				}}
			}
		}
	}
	return nil
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
