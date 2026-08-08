// Package edge implements the EdgeOK predicate from the GUS paper.
// It checks cross-version compatibility for RPC edges — the four mixed-pairing
// conjuncts C1–C4 plus the (θ',θ') target-state conjunct — and the
// Consistent(θ) predicate for a single deployment state. Pub/sub edges are
// out of scope: the loader has no topic→schema resolution, so kafka edges
// are rejected upstream rather than silently skipped.
//
// Pairing bookkeeping: the two mixed deployment pairings are
// (old caller, new provider) — checked by C1 (request leg) and C3 (response
// leg) — and (new caller, old provider) — checked by C2 and C4. The (old,old)
// pairing is the baseline (see Consistent); the (new,new) pairing is the
// TGT conjunct, which is excluded from Horn clause generation (see the
// solver) but is part of the EdgeOK decision.
package edge

import (
	"fmt"

	"github.com/faults-lab/gus/pkg/compat"
	"github.com/faults-lab/gus/pkg/types"
)

// Edge represents a typed interaction between two services.
type Edge struct {
	Name    string
	From    string // caller service
	To      string // provider service
	Channel string // "http" or "kafka"
	Method  string
	Path    string
	Topic   string
}

// VersionedSchemas holds the four schemas for one endpoint at a specific version.
type VersionedSchemas struct {
	Send   *types.Node // what the caller sends
	Accept *types.Node // what the provider accepts (request schema)
	Return *types.Node // what the provider returns
	Expect *types.Node // what the caller expects back
}

// EdgeResult holds the result for a single edge.
type EdgeResult struct {
	Edge            Edge
	OK              bool
	Violations      []types.Violation
	FailedConjuncts []string // every failing conjunct, in C1..C4,TGT order
	CallerSpecUsed  bool     // false = Tier-3 fallback (caller schemas anchored to the old provider contract)
}

// CheckEdgeRPC checks the cross-version pairings for an RPC edge:
//
//	C1  Send(θ)  ≤ Accept(θ')  — old caller request, new provider   (REQ)
//	C2  Send(θ') ≤ Accept(θ)   — new caller request, old provider   (REQ)
//	C3  Return(θ') ≤ Expect(θ) — new provider response, old caller  (RES)
//	C4  Return(θ) ≤ Expect(θ') — old provider response, new caller  (RES)
//	TGT Send(θ') ≤ Accept(θ') ∧ Return(θ') ≤ Expect(θ') — target state
//
// checkTarget should be true only when real caller schemas are in play
// (Tier 1/2); under the Tier-3 fallback the caller schemas are anchored to
// the old provider contract, which makes TGT a duplicate of C1/C3.
//
// Chronology of violation labels: compat fills OldType/NewType positionally
// (left arg, right arg). For C2 and C4 the left argument is the θ'-side
// schema, so the labels are swapped after the fact to keep OldType = θ and
// NewType = θ' in every reported violation.
func CheckEdgeRPC(e Edge, old, new VersionedSchemas, checkTarget bool, cfg compat.Config) EdgeResult {
	result := EdgeResult{Edge: e, OK: true, CallerSpecUsed: checkTarget}

	// A conjunct fails (and the edge breaks) only on BREAK-severity
	// violations. WARN-only findings are recorded for display but do not
	// block the upgrade or feed clause generation.
	record := func(tag string, vs []types.Violation, swapChronology bool) {
		if len(vs) == 0 {
			return
		}
		if swapChronology {
			for i := range vs {
				vs[i].OldType, vs[i].NewType = vs[i].NewType, vs[i].OldType
			}
		}
		result.Violations = append(result.Violations, tagViolations(vs, tag)...)
		for _, v := range vs {
			if v.Severity == types.SevBREAK {
				result.FailedConjuncts = append(result.FailedConjuncts, tag)
				result.OK = false
				break
			}
		}
	}

	// C1: old caller sends to new provider.
	record("C1", compat.Check(old.Send, new.Accept, types.DirREQ, cfg), false)

	// C2: new caller sends to old provider (left arg is θ'-side).
	record("C2", compat.Check(new.Send, old.Accept, types.DirREQ, cfg), true)

	// C3: new provider responds to old caller.
	record("C3", compat.Check(old.Expect, new.Return, types.DirRES, cfg), false)

	// C4: old provider responds to new caller (left arg is θ'-side).
	record("C4", compat.Check(new.Expect, old.Return, types.DirRES, cfg), true)

	// TGT: both sides on the new version — the steady state after the roll.
	if checkTarget {
		var vs []types.Violation
		vs = append(vs, compat.Check(new.Send, new.Accept, types.DirREQ, cfg)...)
		vs = append(vs, compat.Check(new.Expect, new.Return, types.DirRES, cfg)...)
		record("TGT", vs, false)
	}

	return result
}

// Consistent checks that a single deployment state is internally compatible:
// Send(e,θ) ≤ Accept(e,θ) AND Return(e,θ) ≤ Expect(e,θ).
func Consistent(e Edge, schemas VersionedSchemas, cfg compat.Config) EdgeResult {
	result := EdgeResult{Edge: e, OK: true}

	vs := compat.Check(schemas.Send, schemas.Accept, types.DirREQ, cfg)
	if len(vs) > 0 {
		result.Violations = append(result.Violations, tagViolations(vs, "CONSIST-REQ")...)
		result.FailedConjuncts = append(result.FailedConjuncts, "CONSIST-REQ")
		result.OK = false
	}

	vs = compat.Check(schemas.Expect, schemas.Return, types.DirRES, cfg)
	if len(vs) > 0 {
		result.Violations = append(result.Violations, tagViolations(vs, "CONSIST-RES")...)
		result.FailedConjuncts = append(result.FailedConjuncts, "CONSIST-RES")
		result.OK = false
	}

	return result
}

// tagViolations prefixes each violation's path with the conjunct tag.
func tagViolations(vs []types.Violation, tag string) []types.Violation {
	out := make([]types.Violation, len(vs))
	for i, v := range vs {
		out[i] = v
		out[i].Path = fmt.Sprintf("[%s]%s", tag, v.Path)
	}
	return out
}
