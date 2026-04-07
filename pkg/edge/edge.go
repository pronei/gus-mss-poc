// Package edge implements the EdgeOK predicate from the GUS paper.
// It checks cross-version compatibility for RPC, pub/sub, and Kafka edges,
// including the full 4-pairing check for RPC and the Consistent(theta) predicate.
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
	Edge       Edge
	OK         bool
	Violations []types.Violation
	Conjunct   string // which conjunct failed: "1", "2", "3", "4", or "" if all pass
}

// CheckEdgeRPC checks all 4 cross-version pairings for an RPC edge:
//  1. Send(old) <= Accept(new) -- old caller, new provider        (d=REQ)
//  2. Send(new) <= Accept(old) -- new caller, old provider        (d=REQ)
//  3. Return(new) <= Expect(old) -- new provider resp, old caller (d=RES)
//  4. Return(old) <= Expect(new) -- old provider resp, new caller (d=RES)
func CheckEdgeRPC(e Edge, old, new VersionedSchemas, cfg compat.Config) EdgeResult {
	result := EdgeResult{Edge: e, OK: true}

	// Conjunct 1: Send(old) <= Accept(new)  [old caller sends to new provider]
	vs := compat.Check(old.Send, new.Accept, types.DirREQ, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "C1")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "1"
		}
		result.OK = false
	}

	// Conjunct 2: Send(new) <= Accept(old)  [new caller sends to old provider]
	vs = compat.Check(new.Send, old.Accept, types.DirREQ, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "C2")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "2"
		}
		result.OK = false
	}

	// Conjunct 3: Return(new) <= Expect(old)  [new provider response, old caller expects]
	vs = compat.Check(old.Expect, new.Return, types.DirRES, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "C3")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "3"
		}
		result.OK = false
	}

	// Conjunct 4: Return(old) <= Expect(new)  [old provider response, new caller expects]
	vs = compat.Check(new.Expect, old.Return, types.DirRES, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "C4")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "4"
		}
		result.OK = false
	}

	return result
}

// CheckEdgePublish checks a publish edge: Send(publisher) <= Accept(topic_schema).
func CheckEdgePublish(e Edge, send, accept *types.Node, cfg compat.Config) EdgeResult {
	result := EdgeResult{Edge: e, OK: true}

	vs := compat.Check(send, accept, types.DirREQ, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "PUB")
		result.Violations = append(result.Violations, tagged...)
		result.Conjunct = "1"
		result.OK = false
	}

	return result
}

// CheckEdgeSubscribe checks a subscribe edge with 3 conjuncts including retention:
//  1. Send(pub_new) <= Expect(sub_new) -- both upgraded
//  2. Send(pub_new) <= Expect(sub_old) -- new publisher, old subscriber
//  3. Send(pub_old) <= Expect(sub_new) -- buffered old messages, new subscriber (retention)
func CheckEdgeSubscribe(e Edge, pubOld, pubNew, subOld, subNew *types.Node, cfg compat.Config) EdgeResult {
	result := EdgeResult{Edge: e, OK: true}

	// Conjunct 1: both upgraded
	vs := compat.Check(subNew, pubNew, types.DirRES, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "SUB-C1")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "1"
		}
		result.OK = false
	}

	// Conjunct 2: new publisher, old subscriber
	vs = compat.Check(subOld, pubNew, types.DirRES, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "SUB-C2")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "2"
		}
		result.OK = false
	}

	// Conjunct 3: old publisher (retention), new subscriber
	vs = compat.Check(subNew, pubOld, types.DirRES, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "SUB-C3")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "3"
		}
		result.OK = false
	}

	return result
}

// Consistent checks that a single deployment state is internally compatible:
// Send(e,theta) <= Accept(e,theta) AND Return(e,theta) <= Expect(e,theta)
func Consistent(e Edge, schemas VersionedSchemas, cfg compat.Config) EdgeResult {
	result := EdgeResult{Edge: e, OK: true}

	// Request direction: Send <= Accept
	vs := compat.Check(schemas.Send, schemas.Accept, types.DirREQ, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "CONSIST-REQ")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "1"
		}
		result.OK = false
	}

	// Response direction: Return <= Expect
	vs = compat.Check(schemas.Expect, schemas.Return, types.DirRES, cfg)
	if len(vs) > 0 {
		tagged := tagViolations(vs, "CONSIST-RES")
		result.Violations = append(result.Violations, tagged...)
		if result.Conjunct == "" {
			result.Conjunct = "2"
		}
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
