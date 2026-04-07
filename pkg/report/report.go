// Package report formats GUS/MSS check results for human and machine consumption.
package report

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/solver"
	"github.com/faults-lab/gus/pkg/types"
)

// GUSResult holds the full result of a GUS check.
type GUSResult struct {
	Scenario string
	OK       bool
	Edges    []edge.EdgeResult
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
		if !er.OK {
			sb.WriteString(fmt.Sprintf("\nEdge %s [%s] — BREAK (conjunct %s):\n",
				er.Edge.Name, er.Edge.Channel, er.Conjunct))
			for _, v := range er.Violations {
				sb.WriteString(fmt.Sprintf("  [%s] %s\n", v.Severity, v.Path))
				sb.WriteString(fmt.Sprintf("    %s\n", v.Message))
				sb.WriteString(fmt.Sprintf("    old: %s → new: %s\n", v.OldType, v.NewType))
				sb.WriteString(fmt.Sprintf("    rule: %s\n", v.Rule))
			}
		}
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

	if len(r.MSS.Removed) > 0 {
		sb.WriteString("\nExcluded:\n")
		for _, u := range r.MSS.Removed {
			reason := r.MSS.Reasons[u.Service]
			sb.WriteString(fmt.Sprintf("  %s %s→%s — %s\n", u.Service, u.FromVer, u.ToVer, reason))
		}
	}
	return sb.String()
}

// ConsistentResult holds the result of a Consistent(θ) check.
type ConsistentResult struct {
	OK    bool
	Edges []edge.EdgeResult
}

func (r *ConsistentResult) Text() string {
	var sb strings.Builder
	status := "YES"
	if !r.OK {
		status := "NO"
		_ = status
	}
	sb.WriteString(fmt.Sprintf("=== Consistent(θ) ===\nResult: %s\n", status))

	for _, er := range r.Edges {
		if !er.OK {
			sb.WriteString(fmt.Sprintf("\nEdge %s — INCONSISTENT:\n", er.Edge.Name))
			for _, v := range er.Violations {
				sb.WriteString(fmt.Sprintf("  %s\n", v))
			}
		}
	}
	return sb.String()
}

// FormatViolations returns a compact multi-line summary of violations.
func FormatViolations(vs []types.Violation) string {
	if len(vs) == 0 {
		return "  (none)"
	}
	var sb strings.Builder
	for _, v := range vs {
		sb.WriteString(fmt.Sprintf("  %s\n", v))
	}
	return sb.String()
}
