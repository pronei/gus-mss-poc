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
	"os"
	"sort"
	"strings"

	"github.com/faults-lab/gus/pkg/edge"
	"github.com/faults-lab/gus/pkg/graph"
	"github.com/faults-lab/gus/pkg/report"
	"github.com/faults-lab/gus/pkg/solver"
	"github.com/faults-lab/gus/pkg/types"
	"gopkg.in/yaml.v3"
)

// Artifact is the JSON shape consumed by the frontend. Keep fields stable —
// the HTML viewer treats this as the contract.
type Artifact struct {
	Scenario Scenario    `json:"scenario"`
	Services []Service   `json:"services"`
	Edges    []Edge      `json:"edges"`
	MSS      MSSSnapshot `json:"mss"`
}

type Scenario struct {
	Name        string            `json:"name"`
	Description string            `json:"description,omitempty"`
	Baseline    map[string]string `json:"baseline"`
	Upgrades    map[string]string `json:"upgrades"`
}

type Service struct {
	ID              string                 `json:"id"`
	BaselineVersion string                 `json:"baseline_version"`
	CurrentVersion  string                 `json:"current_version"`
	IsUpgrading     bool                   `json:"is_upgrading"`
	IsExcluded      bool                   `json:"is_excluded"`
	StatusReason    string                 `json:"status_reason,omitempty"`
	BaselineSpec    map[string]interface{} `json:"baseline_spec,omitempty"`
	CurrentSpec     map[string]interface{} `json:"current_spec,omitempty"`
}

type Edge struct {
	Name              string      `json:"name"`
	From              string      `json:"from"`
	To                string      `json:"to"`
	Method            string      `json:"method"`
	Path              string      `json:"path"`
	AffectedByUpgrade bool        `json:"affected_by_upgrade"`
	OK                bool        `json:"ok"`
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
// about which upgrades can safely roll together. Raw OpenAPI specs for each
// service are read via g.SpecPath so the frontend can render schema context
// for safe upgrades.
func Build(g *graph.Graph, sc *graph.ScenarioDef, gusResult *report.GUSResult, mssResult *solver.MSSResult) Artifact {
	art := Artifact{
		Scenario: Scenario{
			Name:        sc.Name,
			Description: sc.Description,
			Baseline:    copyMap(sc.Baseline),
			Upgrades:    copyMap(sc.Upgrades),
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

		if p, err := g.SpecPath(id, baseVer); err == nil {
			if spec, err := loadSpecAsMap(p); err == nil {
				svc.BaselineSpec = spec
			}
		}
		if p, err := g.SpecPath(id, curVer); err == nil {
			if spec, err := loadSpecAsMap(p); err == nil {
				svc.CurrentSpec = spec
			}
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
					Explanation: ExplainViolation(ed, cleaned),
				})
			}
		}

		art.Edges = append(art.Edges, ve)
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
// matters during rolling deployment. The templates reference the
// caller/provider/direction/conjunct context that simpler tools (Pact, Buf)
// can't express together.
func ExplainViolation(ed graph.EdgeDef, v types.Violation) string {
	caller, provider := ed.From, ed.To
	field := fieldNameFromPath(v.Path)
	ep := fmt.Sprintf("%s %s", strings.ToUpper(ed.Method), ed.Path)

	switch v.Rule {
	case "REQ.1":
		return fmt.Sprintf(
			"During rolling deployment, old %s instances send %s requests that omit %q — but new %s requires it. "+
				"Any request routed from an old caller to a new provider instance is rejected.",
			caller, ep, field, provider,
		)
	case "REQ.2":
		return fmt.Sprintf(
			"New %s makes %q required on %s requests, but old %s callers treated it as optional. "+
				"Requests that historically omitted the field will be rejected by new provider instances.",
			provider, field, ep, caller,
		)
	case "REQ.4":
		return fmt.Sprintf(
			"New %s removes field %q from %s (closed schema), yet old %s callers still send it. "+
				"New provider instances reject the unknown field.",
			provider, field, ep, caller,
		)
	case "RES.1":
		return fmt.Sprintf(
			"New %s responses for %s omit required field %q that old %s callers depend on. "+
				"Old caller code will fail when reading the missing field from a new provider's response.",
			provider, ep, field, caller,
		)
	case "RES.4":
		return fmt.Sprintf(
			"%s downgrades %q in the %s response from required to optional. "+
				"Old %s callers that assume the field is always present will crash when it's absent.",
			provider, field, ep, caller,
		)
	case "enum-request-narrowing":
		return fmt.Sprintf(
			"New %s narrows the accepted enum for %s on %s: values old %s callers still send will be rejected. "+
				"This is an asymmetric break — one direction of the 4-pairing fails.",
			provider, field, ep, caller,
		)
	case "enum-response-widening":
		return fmt.Sprintf(
			"New %s widens the response enum for %s on %s with values old %s callers don't recognize. "+
				"Old callers may parse an unknown variant and crash or behave incorrectly.",
			provider, field, ep, caller,
		)
	case "prim-mismatch":
		return fmt.Sprintf(
			"Primitive type for %s changed incompatibly in the JSON lattice (old=%s, new=%s). "+
				"One direction of the 4-pairing (C3/C4) fails even when the other passes — a GUS-unique check "+
				"that Pact and Buf can't express.",
			field, v.OldType, v.NewType,
		)
	case "kind-mismatch":
		return fmt.Sprintf(
			"Type kind for %s changed fundamentally (old=%s, new=%s). "+
				"No compat direction can bridge the change; the edge breaks in every 4-pairing conjunct that touches this field.",
			field, v.OldType, v.NewType,
		)
	case "literal-mismatch":
		return fmt.Sprintf("Literal value for %s changed from %s to %s.", field, v.OldType, v.NewType)
	case "literal-not-in-enum":
		return fmt.Sprintf("Literal value for %s is no longer accepted by the new enum on %s.", field, ep)
	case "map-key-mismatch":
		return fmt.Sprintf("Map key type for %s changed — GUS treats map keys as invariant.", field)
	case "union-request-narrowing":
		return fmt.Sprintf(
			"New %s narrows the accepted union variants for %s on %s — at least one variant old callers send is no longer handled.",
			provider, field, ep,
		)
	case "union-response-widening":
		return fmt.Sprintf(
			"New %s returns union variants for %s on %s that old %s callers don't handle.",
			provider, field, ep, caller,
		)
	case "format-change":
		return fmt.Sprintf(
			"Format of %s changed (old=%s, new=%s). Warning-level: the primitive type is compatible, but the format shift may surprise downstream code.",
			field, v.OldType, v.NewType,
		)
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

func stripConjunctTag(p string) (string, string) {
	if !strings.HasPrefix(p, "[C") {
		return "", p
	}
	end := strings.Index(p, "]")
	if end < 0 {
		return "", p
	}
	return p[2:end], p[end+1:]
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

func loadSpecAsMap(path string) (map[string]interface{}, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var doc map[string]interface{}
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return nil, err
	}
	return normalizeMapKeys(doc), nil
}

func normalizeMapKeys(v interface{}) map[string]interface{} {
	out, _ := normalizeValue(v).(map[string]interface{})
	return out
}

func normalizeValue(v interface{}) interface{} {
	switch t := v.(type) {
	case map[string]interface{}:
		m := make(map[string]interface{}, len(t))
		for k, val := range t {
			m[k] = normalizeValue(val)
		}
		return m
	case map[interface{}]interface{}:
		m := make(map[string]interface{}, len(t))
		for k, val := range t {
			m[fmt.Sprintf("%v", k)] = normalizeValue(val)
		}
		return m
	case []interface{}:
		s := make([]interface{}, len(t))
		for i, val := range t {
			s[i] = normalizeValue(val)
		}
		return s
	default:
		return v
	}
}
