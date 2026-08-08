// Package evolve maintains a provenance ledger for data-flow identities
// across successive rollouts.
//
// Why per-step chain checks are not enough: a guarantee can erode while
// nobody requires it. If checkout makes shipment_ref optional in a sprint
// where no x-requires exists, every chain check passes (there is no chain),
// the change ships, and the erosion becomes invisible baseline. When a
// requirer finally appears three rollouts later, the per-step checker can
// only blame the requirer's upgrade — the true origin is gone. The ledger
// closes that hole: it records every provided identity's guarantee tuple
// (field, type, required, nullable, carrying paths) at every SHIPPED state,
// so mutations are attributed to the rollout that made them, and a later
// violation can be traced to the erosion step instead of the exposure step.
//
// The ledger is a plain JSON file meant to persist between invocations —
// state that survives rollouts, exactly like the mesh it describes.
package evolve

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

// Guarantee is the provenance tuple for an identity at one shipped state.
type Guarantee struct {
	Provider string   `json:"provider"`
	Field    string   `json:"field"`
	Type     string   `json:"type"`
	Required bool     `json:"required"`
	Nullable bool     `json:"nullable"`
	Paths    []string `json:"paths,omitempty"` // "a>b>c" per carrying path to each requirer
}

func (g Guarantee) tupleKey() string {
	return fmt.Sprintf("%s|%s|%s|%v|%v|%s", g.Provider, g.Field, g.Type, g.Required, g.Nullable, strings.Join(g.Paths, ","))
}

// Event is one ledger entry for an identity.
type Event struct {
	Step   string `json:"step"`
	Kind   string `json:"kind"` // born | mutated | eroded | restored | withdrawn | demanded | demand-dropped | violated | path-changed
	Detail string `json:"detail"`
}

// IdentityHistory accumulates the life of one identity key.
type IdentityHistory struct {
	Key       string     `json:"key"`
	Events    []Event    `json:"events"`
	Current   *Guarantee `json:"current,omitempty"`
	Requirers []string   `json:"requirers,omitempty"`
}

// Ledger is the persistent cross-rollout state.
type Ledger struct {
	Identities map[string]*IdentityHistory `json:"identities"`
	Steps      []string                    `json:"steps"` // step names already recorded, in order
}

func NewLedger() *Ledger {
	return &Ledger{Identities: map[string]*IdentityHistory{}}
}

// LoadLedger reads a ledger file; a missing file yields a fresh ledger.
func LoadLedger(path string) (*Ledger, error) {
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return NewLedger(), nil
	}
	if err != nil {
		return nil, err
	}
	var l Ledger
	if err := json.Unmarshal(data, &l); err != nil {
		return nil, fmt.Errorf("ledger %s: %w", path, err)
	}
	if l.Identities == nil {
		l.Identities = map[string]*IdentityHistory{}
	}
	return &l, nil
}

// Save writes the ledger to path.
func (l *Ledger) Save(path string) error {
	data, err := json.MarshalIndent(l, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0644)
}

// Recorded reports whether a step name is already in the ledger.
func (l *Ledger) Recorded(step string) bool {
	for _, s := range l.Steps {
		if s == step {
			return true
		}
	}
	return false
}

// StepObservation is what the runner saw for one identity at one step.
type StepObservation struct {
	Key       string
	Guarantee *Guarantee // nil = no provider at the shipped state
	Requirers []string   // services demanding the identity in the PROPOSED state
	Violated  string     // chain rule if the proposed state broke this identity's chain ("" = fine)
	Rejected  bool       // the violation caused exclusions (the demand did not ship)
}

// RecordStep folds one step's observations into the ledger.
func (l *Ledger) RecordStep(step string, obs []StepObservation) {
	seen := map[string]bool{}
	for _, o := range obs {
		seen[o.Key] = true
		h := l.Identities[o.Key]
		if h == nil {
			h = &IdentityHistory{Key: o.Key}
			l.Identities[o.Key] = h
		}
		add := func(kind, detail string) {
			h.Events = append(h.Events, Event{Step: step, Kind: kind, Detail: detail})
		}

		switch {
		case h.Current == nil && o.Guarantee != nil:
			add("born", fmt.Sprintf("%s provides it as %s on field %q (required=%v, nullable=%v)",
				o.Guarantee.Provider, o.Guarantee.Type, o.Guarantee.Field, o.Guarantee.Required, o.Guarantee.Nullable))
		case h.Current != nil && o.Guarantee == nil:
			add("withdrawn", fmt.Sprintf("%s no longer provides it", h.Current.Provider))
		case h.Current != nil && o.Guarantee != nil && h.Current.tupleKey() != o.Guarantee.tupleKey():
			prev, cur := h.Current, o.Guarantee
			switch {
			case prev.Required && !cur.Required:
				add("eroded", fmt.Sprintf("field %q went required→optional at %s — the identity is no longer guaranteed present", cur.Field, cur.Provider))
			case !prev.Nullable && cur.Nullable:
				add("eroded", fmt.Sprintf("field %q became nullable at %s — the identity is no longer guaranteed non-null", cur.Field, cur.Provider))
			case (!prev.Required && cur.Required) || (prev.Nullable && !cur.Nullable):
				add("restored", fmt.Sprintf("field %q guarantee strengthened at %s (required=%v, nullable=%v)", cur.Field, cur.Provider, cur.Required, cur.Nullable))
			case prev.Type != cur.Type:
				add("mutated", fmt.Sprintf("type drifted %s → %s at %s (identities are strictly typed: any requirer pinned to %s breaks)", prev.Type, cur.Type, cur.Provider, prev.Type))
			case strings.Join(prev.Paths, ",") != strings.Join(cur.Paths, ","):
				add("path-changed", fmt.Sprintf("carrying paths changed: [%s] → [%s] — the identity now transits hops that never carried it before",
					strings.Join(prev.Paths, " "), strings.Join(cur.Paths, " ")))
			default:
				add("mutated", fmt.Sprintf("guarantee changed at %s: field %q → %q", cur.Provider, prev.Field, cur.Field))
			}
		}
		if o.Guarantee != nil {
			h.Current = o.Guarantee
		} else {
			h.Current = nil
		}

		// Demands.
		prevReq := strings.Join(h.Requirers, ",")
		newReq := strings.Join(o.Requirers, ",")
		if newReq != prevReq {
			if len(o.Requirers) > len(h.Requirers) {
				suffix := ""
				if o.Rejected {
					suffix = " — the proposal was REJECTED because the guarantee no longer holds"
				}
				add("demanded", fmt.Sprintf("now required by [%s]%s", newReq, suffix))
			} else if newReq == "" {
				add("demand-dropped", "no service requires it any more")
			}
			if !o.Rejected {
				h.Requirers = o.Requirers
			}
		}
		if o.Violated != "" {
			// Point at the origin, not just the exposure.
			origin := ""
			for i := len(h.Events) - 1; i >= 0; i-- {
				if h.Events[i].Kind == "eroded" || h.Events[i].Kind == "mutated" {
					origin = fmt.Sprintf(" — guarantee last weakened at step %q (%s)", h.Events[i].Step, h.Events[i].Detail)
					break
				}
			}
			add("violated", fmt.Sprintf("chain check fails (%s)%s", o.Violated, origin))
		}
	}
	l.Steps = append(l.Steps, step)
}

// Verdict summarizes an identity's current standing.
func (h *IdentityHistory) Verdict() string {
	lastViolated := ""
	eroded := false
	for _, e := range h.Events {
		switch e.Kind {
		case "violated":
			lastViolated = e.Step
		case "eroded", "mutated":
			eroded = true
		case "restored":
			eroded = false
		}
	}
	switch {
	case lastViolated != "":
		return "EXPOSED"
	case h.Current == nil:
		return "WITHDRAWN"
	case eroded && len(h.Requirers) == 0:
		return "ERODED (dormant — nothing requires it yet)"
	case eroded:
		return "ERODED"
	case len(h.Requirers) == 0:
		return "PROVIDED (nothing requires it yet)"
	default:
		return "SURVIVING"
	}
}

// Text renders the survival report.
func (l *Ledger) Text() string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("=== Provenance ledger — %d rollout step(s) recorded ===\n", len(l.Steps)))

	keys := make([]string, 0, len(l.Identities))
	for k := range l.Identities {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	for _, k := range keys {
		h := l.Identities[k]
		sb.WriteString(fmt.Sprintf("\nidentity %q — %s\n", k, h.Verdict()))
		if h.Current != nil {
			sb.WriteString(fmt.Sprintf("  now: %s.%s : %s (required=%v, nullable=%v)",
				h.Current.Provider, h.Current.Field, h.Current.Type, h.Current.Required, h.Current.Nullable))
			if len(h.Current.Paths) > 0 {
				sb.WriteString(fmt.Sprintf(" via %s", strings.Join(h.Current.Paths, " | ")))
			}
			sb.WriteString("\n")
		}
		for _, e := range h.Events {
			sb.WriteString(fmt.Sprintf("  %-14s @ %s: %s\n", e.Kind, e.Step, e.Detail))
		}
	}
	return sb.String()
}
