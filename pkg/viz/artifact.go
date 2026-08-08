// Package viz builds a JSON artifact describing a scenario's services,
// edges, violations, and MSS result. The companion static HTML frontend
// (viz/viz.html) consumes this artifact and renders an interactive view.
//
// This package is deliberately free of CLI concerns — see cmd/gus/viz.go
// for the command wiring. The goal is that any program able to produce a
// GUSResult + MSSResult can emit the same JSON shape, so the frontend
// stays a pure static site decoupled from the Go tool.
package viz

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/graph"
	"github.com/faults-lab/gus/pkg/report"
	"github.com/faults-lab/gus/pkg/solver"
	"github.com/faults-lab/gus/pkg/types"
)

// Artifact is the JSON shape consumed by the frontend. Keep fields stable —
// the HTML viewer treats this as the contract.
type Artifact struct {
	Scenario Scenario    `json:"scenario"`
	Services []Service   `json:"services"`
	Edges    []Edge      `json:"edges"`
	Chains   []Chain     `json:"chains,omitempty"`
	MSS      MSSSnapshot `json:"mss"`
}

// Chain is one x-provides/x-requires data-flow chain result.
type Chain struct {
	Key      string   `json:"key"`
	From     string   `json:"from"`
	To       string   `json:"to"`
	Path     []string `json:"path"`
	OK       bool     `json:"ok"`
	Rule     string   `json:"rule,omitempty"`
	Message  string   `json:"message"`
	Culprits []string `json:"culprits,omitempty"`
}

type Scenario struct {
	Name        string            `json:"name"`
	Description string            `json:"description,omitempty"`
	Baseline    map[string]string `json:"baseline"`
	Upgrades    map[string]string `json:"upgrades"`
	Coercion    string            `json:"coercion,omitempty"`
}

type Service struct {
	ID              string `json:"id"`
	BaselineVersion string `json:"baseline_version"`
	CurrentVersion  string `json:"current_version"`
	IsUpgrading     bool   `json:"is_upgrading"`
	IsExcluded      bool   `json:"is_excluded"`
	StatusReason    string `json:"status_reason,omitempty"`
}

type Edge struct {
	Name              string      `json:"name"`
	From              string      `json:"from"`
	To                string      `json:"to"`
	Method            string      `json:"method"`
	Path              string      `json:"path"`
	AffectedByUpgrade bool        `json:"affected_by_upgrade"`
	OK                bool        `json:"ok"`
	FailedConjuncts   []string    `json:"failed_conjuncts,omitempty"`
	CallerSpecUsed    bool        `json:"caller_spec_used"`
	Violations        []Violation `json:"violations,omitempty"`
}

type Violation struct {
	Conjunct    string `json:"conjunct,omitempty"`
	Rule        string `json:"rule"`
	Path        string `json:"path"`
	Severity    string `json:"severity"`
	Message     string `json:"message"`
	OldType     string `json:"old_type,omitempty"`
	NewType     string `json:"new_type,omitempty"`
	Explanation string `json:"explanation"`
}

type MSSSnapshot struct {
	Computed bool            `json:"computed"`
	Safe     []UpgradeRef    `json:"safe"`
	Removed  []RemovedResult `json:"removed"`
	// Order is the staged rollout schedule for the safe set: every service in
	// stage i must be fully rolled out before stage i+1 starts.
	Order [][]string `json:"order,omitempty"`
}

type UpgradeRef struct {
	Service string `json:"service"`
	FromVer string `json:"from_ver"`
	ToVer   string `json:"to_ver"`
}

type RemovedResult struct {
	Service string `json:"service"`
	FromVer string `json:"from_ver"`
	ToVer   string `json:"to_ver"`
	Reason  string `json:"reason"`
}

// Build assembles an Artifact from a resolved GUS + MSS computation.
//
// `g` and `sc` describe the mesh and the upgrade scenario. `gusResult` is the
// output of per-edge GUS checks. `mssResult` is the Horn solver's decision
// about which upgrades can safely roll together.
func Build(g *graph.Graph, sc *graph.ScenarioDef, gusResult *report.GUSResult, mssResult *solver.MSSResult) Artifact {
	art := Artifact{
		Scenario: Scenario{
			Name:        sc.Name,
			Description: sc.Description,
			Baseline:    copyMap(sc.Baseline),
			Upgrades:    copyMap(sc.Upgrades),
			Coercion:    sc.Coercion,
		},
	}

	// All services referenced by graph or scenario (not every graph service
	// must appear in the scenario, and vice versa).
	svcSet := map[string]bool{}
	for id := range g.Def.Services {
		svcSet[id] = true
	}
	for id := range sc.Baseline {
		svcSet[id] = true
	}
	for id := range sc.Upgrades {
		svcSet[id] = true
	}

	excluded := map[string]string{}
	for _, r := range mssResult.Removed {
		reason := ""
		if mssResult.Reasons != nil {
			reason = mssResult.Reasons[r.Service]
		}
		excluded[r.Service] = reason
	}

	for id := range svcSet {
		baseVer := resolveVersion(sc.Baseline, id, "v1")
		curVer := baseVer
		if v, ok := sc.Upgrades[id]; ok {
			curVer = v
		}

		svc := Service{
			ID:              id,
			BaselineVersion: baseVer,
			CurrentVersion:  curVer,
			IsUpgrading:     baseVer != curVer,
		}
		if reason, isExcluded := excluded[id]; isExcluded {
			svc.IsExcluded = true
			svc.StatusReason = reason
		}

		art.Services = append(art.Services, svc)
	}

	sort.Slice(art.Services, func(i, j int) bool {
		return art.Services[i].ID < art.Services[j].ID
	})

	edgeIndex := map[string]*edge.EdgeResult{}
	for i := range gusResult.Edges {
		er := &gusResult.Edges[i]
		edgeIndex[er.Edge.Name] = er
	}

	for _, ed := range g.Def.Edges {
		_, callerUpgrading := sc.Upgrades[ed.From]
		_, providerUpgrading := sc.Upgrades[ed.To]
		affected := callerUpgrading || providerUpgrading

		ve := Edge{
			Name:              ed.Name,
			From:              ed.From,
			To:                ed.To,
			Method:            ed.Method,
			Path:              ed.Path,
			AffectedByUpgrade: affected,
			OK:                true,
		}

		if er, ok := edgeIndex[ed.Name]; ok {
			ve.OK = er.OK
			ve.FailedConjuncts = er.FailedConjuncts
			ve.CallerSpecUsed = er.CallerSpecUsed
			for _, v := range er.Violations {
				conj, cleanPath := stripConjunctTag(v.Path)
				cleaned := v
				cleaned.Path = cleanPath
				ve.Violations = append(ve.Violations, Violation{
					Conjunct:    conj,
					Rule:        v.Rule,
					Path:        cleanPath,
					Severity:    v.Severity.String(),
					Message:     v.Message,
					OldType:     v.OldType,
					NewType:     v.NewType,
					Explanation: ExplainViolation(ed, conj, cleaned),
				})
			}
		}

		art.Edges = append(art.Edges, ve)
	}

	for _, cr := range gusResult.Chains {
		art.Chains = append(art.Chains, Chain{
			Key:      cr.Key,
			From:     cr.Provider.Service,
			To:       cr.Requirer.Service,
			Path:     cr.ChainPath,
			OK:       cr.OK,
			Rule:     cr.Rule,
			Message:  cr.Message,
			Culprits: cr.Culprits,
		})
	}

	art.MSS.Computed = true
	for _, u := range mssResult.Safe {
		art.MSS.Safe = append(art.MSS.Safe, UpgradeRef{
			Service: u.Service, FromVer: u.FromVer, ToVer: u.ToVer,
		})
	}
	for _, r := range mssResult.Removed {
		reason := ""
		if mssResult.Reasons != nil {
			reason = mssResult.Reasons[r.Service]
		}
		art.MSS.Removed = append(art.MSS.Removed, RemovedResult{
			Service: r.Service, FromVer: r.FromVer, ToVer: r.ToVer, Reason: reason,
		})
	}
	art.MSS.Order = mssResult.Order

	return art
}

// Marshal serialises an Artifact as JSON. If `pretty` is true, it uses
// 2-space indentation for human readability.
func Marshal(art Artifact, pretty bool) ([]byte, error) {
	if pretty {
		return json.MarshalIndent(art, "", "  ")
	}
	return json.Marshal(art)
}

// ExplainViolation produces a human-readable narrative for why a violation
// matters during rolling deployment, phrased for the specific conjunct (which
// mixed-version window is broken).
func ExplainViolation(ed graph.EdgeDef, conj string, v types.Violation) string {
	caller, provider := ed.From, ed.To
	field := fieldNameFromPath(v.Path)
	ep := fmt.Sprintf("%s %s", strings.ToUpper(ed.Method), ed.Path)

	// Which instances collide in this conjunct's window.
	var window string
	switch conj {
	case "1": // C1: old caller → new provider (request leg)
		window = fmt.Sprintf("old %s instances calling new %s instances", caller, provider)
	case "2": // C2: new caller → old provider (request leg)
		window = fmt.Sprintf("new %s instances calling old %s instances", caller, provider)
	case "3": // C3: new provider responding to old caller
		window = fmt.Sprintf("new %s instances responding to old %s instances", provider, caller)
	case "4": // C4: old provider responding to new caller
		window = fmt.Sprintf("old %s instances responding to new %s instances", provider, caller)
	case "TGT":
		window = fmt.Sprintf("the steady state after both %s and %s finish rolling", caller, provider)
	default:
		window = fmt.Sprintf("a mixed-version window on %s", ep)
	}

	switch v.Rule {
	case "REQ.1":
		return fmt.Sprintf("During %s, %s requests omit %q which the receiving side requires (no default declared) — those requests are rejected.", window, ep, field)
	case "REQ.2":
		return fmt.Sprintf("During %s, the sending side treats %q as optional on %s but the receiving side requires it — requests omitting it are rejected.", window, field, ep)
	case "REQ.4":
		return fmt.Sprintf("During %s, the sending side still sends %q on %s but the receiving side's closed schema rejects unknown fields.", window, field, ep)
	case "RES.1":
		return fmt.Sprintf("During %s, %s responses omit required field %q that the consuming side depends on — consumer code fails reading the missing field.", window, ep, field)
	case "RES.4":
		return fmt.Sprintf("During %s, %q in the %s response is only optionally returned but the consuming side assumes it is always present.", window, field, ep)
	case "enum-request-narrowing":
		return fmt.Sprintf("During %s, enum values still sent for %s on %s are no longer accepted — an asymmetric break: this pairing direction fails even if others pass.", window, field, ep)
	case "enum-response-widening":
		return fmt.Sprintf("During %s, the response enum for %s on %s carries values the consuming side does not recognize — strict clients crash on the unknown variant.", window, field, ep)
	case "prim-mismatch":
		return fmt.Sprintf("During %s, the primitive type of %s is incompatible under the configured lattice (%s vs %s). Cross-version pairings can fail asymmetrically: check which conjuncts fired.", window, field, v.OldType, v.NewType)
	case "kind-mismatch":
		return fmt.Sprintf("Type kind for %s changed fundamentally (%s vs %s) — no pairing direction can bridge the change.", field, v.OldType, v.NewType)
	case "literal-mismatch":
		return fmt.Sprintf("Literal value for %s differs across versions (%s vs %s).", field, v.OldType, v.NewType)
	case "literal-not-in-enum":
		return fmt.Sprintf("During %s, the literal sent for %s is not among the accepted enum values on %s.", window, field, ep)
	case "map-key-mismatch":
		return fmt.Sprintf("Map key type for %s changed — GUS treats map keys as invariant.", field)
	case "union-request-narrowing":
		return fmt.Sprintf("During %s, at least one union variant still sent for %s on %s is no longer handled.", window, field, ep)
	case "union-response-widening":
		return fmt.Sprintf("During %s, the response union for %s on %s carries variants the consuming side does not handle.", window, field, ep)
	case "format-change":
		return fmt.Sprintf("Format range risk for %s (%s vs %s): the primitive type is compatible but values may exceed the narrower side's range.", field, v.OldType, v.NewType)
	default:
		return fmt.Sprintf("%s: %s", v.Rule, v.Message)
	}
}

// --- Helpers ---

func fieldNameFromPath(p string) string {
	if p == "" {
		return ""
	}
	p = strings.ReplaceAll(p, "[*]", "")
	if i := strings.LastIndex(p, "."); i >= 0 {
		return p[i+1:]
	}
	return p
}

// stripConjunctTag splits a "[TAG]$.path" violation path into (tag, path).
// Tags are C1–C4, TGT, SUB-*, CONSIST-*.
func stripConjunctTag(p string) (string, string) {
	if !strings.HasPrefix(p, "[") {
		return "", p
	}
	end := strings.Index(p, "]")
	if end < 0 {
		return "", p
	}
	tag := p[1:end]
	if strings.HasPrefix(tag, "C") && len(tag) == 2 {
		tag = tag[1:] // "C3" -> "3" (the frontend's historical shape)
	}
	return tag, p[end+1:]
}

func resolveVersion(versions map[string]string, svc, fallback string) string {
	if v, ok := versions[svc]; ok {
		return v
	}
	return fallback
}

func copyMap(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}
