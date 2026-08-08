// Package report formats GUS/MSS check results for human and machine consumption.
package report

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/faults-lab/gus/pkg/chain"
	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/solver"
)

// GUSResult holds the full result of a GUS check: per-edge cross-version
// conjuncts plus data-flow chain integrity.
type GUSResult struct {
	Scenario string
	OK       bool
	Edges    []edge.EdgeResult
	Chains   []chain.ChainResult
}

func (r *GUSResult) Text() string {
	var sb strings.Builder
	status := "YES"
	if !r.OK {
		status = "NO"
	}
	sb.WriteString(fmt.Sprintf("=== GUS Check: %s ===\n", r.Scenario))
	sb.WriteString(fmt.Sprintf("Decision: %s\n", status))

	for _, er := range r.Edges {
		if er.OK {
			continue
		}
		sb.WriteString(fmt.Sprintf("\nEdge %s [%s] — BREAK (conjuncts %s):\n",
			er.Edge.Name, er.Edge.Channel, strings.Join(er.FailedConjuncts, ",")))
		if !er.CallerSpecUsed {
			sb.WriteString("  (caller schema unavailable — Tier-3 fallback: caller assumed pinned to the old provider contract)\n")
		}
		for _, v := range er.Violations {
			sb.WriteString(fmt.Sprintf("  [%s] %s\n", v.Severity, v.Path))
			sb.WriteString(fmt.Sprintf("    %s\n", v.Message))
			sb.WriteString(fmt.Sprintf("    old: %s → new: %s\n", v.OldType, v.NewType))
			sb.WriteString(fmt.Sprintf("    rule: %s\n", v.Rule))
		}
	}

	for _, cr := range r.Chains {
		if cr.OK {
			continue
		}
		sb.WriteString(fmt.Sprintf("\nChain %s — BREAK (%s):\n", cr.Key, cr.Rule))
		sb.WriteString(fmt.Sprintf("  %s -> %s via %s\n",
			cr.Provider.Service, cr.Requirer.Service, strings.Join(cr.ChainPath, " -> ")))
		sb.WriteString(fmt.Sprintf("  %s\n", cr.Message))
	}

	return sb.String()
}

func (r *GUSResult) JSON() ([]byte, error) {
	return json.MarshalIndent(r, "", "  ")
}

// MSSReport holds the full result of an MSS computation.
type MSSReport struct {
	Scenario string
	GUS      *GUSResult
	MSS      *solver.MSSResult
	// PostHocOK reports whether re-running GUS restricted to the safe subset
	// passed (the target-state verification the formalism requires).
	PostHocOK  bool
	PostHocRan bool
}

func (r *MSSReport) Text() string {
	var sb strings.Builder
	sb.WriteString(r.GUS.Text())

	if r.GUS.OK {
		sb.WriteString("\nAll upgrades are safe. No MSS computation needed.\n")
		return sb.String()
	}

	sb.WriteString("\n--- MSS Result ---\n")
	if len(r.MSS.Safe) == 0 {
		sb.WriteString("Safe subset: {} (empty — no upgrades can deploy safely)\n")
	} else {
		parts := make([]string, len(r.MSS.Safe))
		for i, u := range r.MSS.Safe {
			parts[i] = fmt.Sprintf("%s %s→%s", u.Service, u.FromVer, u.ToVer)
		}
		sb.WriteString(fmt.Sprintf("Safe subset: {%s}\n", strings.Join(parts, ", ")))
	}

	if len(r.MSS.Order) > 1 {
		sb.WriteString("Rollout order (each stage must fully complete before the next):\n")
		for i, stage := range r.MSS.Order {
			sb.WriteString(fmt.Sprintf("  %d. %s\n", i+1, strings.Join(stage, ", ")))
		}
	}

	if len(r.MSS.Removed) > 0 {
		sb.WriteString("\nExcluded:\n")
		for _, u := range r.MSS.Removed {
			reason := r.MSS.Reasons[u.Service]
			sb.WriteString(fmt.Sprintf("  %s %s→%s — %s\n", u.Service, u.FromVer, u.ToVer, reason))
		}
	}

	if r.PostHocRan {
		verdict := "PASS"
		if !r.PostHocOK {
			verdict = "FAIL (solver returned an unsafe subset — please report this)"
		}
		sb.WriteString(fmt.Sprintf("\nPost-hoc verification of the safe subset: %s\n", verdict))
	}
	return sb.String()
}

// ConsistentResult holds the result of a Consistent(θ) check.
type ConsistentResult struct {
	State string // which deployment state was checked: "baseline" or "target"
	OK    bool
	Edges []edge.EdgeResult
}

func (r *ConsistentResult) Text() string {
	var sb strings.Builder
	status := "YES"
	if !r.OK {
		status = "NO"
	}
	sb.WriteString(fmt.Sprintf("=== Consistent(θ) [%s] ===\nResult: %s\n", r.State, status))

	for _, er := range r.Edges {
		if er.OK {
			continue
		}
		sb.WriteString(fmt.Sprintf("\nEdge %s — INCONSISTENT:\n", er.Edge.Name))
		for _, v := range er.Violations {
			sb.WriteString(fmt.Sprintf("  %s\n", v))
		}
	}
	return sb.String()
}
