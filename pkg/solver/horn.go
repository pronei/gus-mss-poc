// Package solver implements the HORN_MSS algorithm from the GUS-MSS paper section 6.
// Given a set of proposed upgrades and Horn clauses derived from EdgeOK violations,
// it computes the maximal safe subset (MSS) of upgrades that can be deployed together.
package solver

// Upgrade represents a proposed service version change.
type Upgrade struct {
	Service string
	FromVer string
	ToVer   string
}

// Clause is a Horn clause: not(cause) OR dep.
// Semantics: "If cause upgrades, dep must also upgrade."
// If Dep is "", it is a unit clause not(cause) meaning unconditional exclusion.
type Clause struct {
	Cause  string // service whose upgrade causes the dependency
	Dep    string // service that must also upgrade ("" = unit clause)
	Reason string // why this clause exists (edge name + violation)
}

// MSSResult holds the result of the MSS computation.
type MSSResult struct {
	Safe    []Upgrade
	Removed []Upgrade
	Reasons map[string]string // service -> why excluded
}

// ComputeMSS implements the Horn SAT MSS solver.
//
// proposed: the set U of proposed upgrades.
// clauses: Horn clauses derived from EdgeOK violations.
//
// Algorithm:
//  1. Initialize: x_s = true for all s in U, x_s = false for all s not in U.
//  2. Seed the queue with: services that appear as Dep in a clause but are not in U
//     (they are false and may force their Cause false), plus any unit-clause targets.
//  3. Propagate: for each false variable v, find all clauses where v is the Dep.
//     For each such clause, the Cause must be forced false (since its only way
//     to satisfy the clause was for Dep to be true). Add Cause to queue.
//  4. MSS = {s in U : x_s still true}.
//
// For Horn clauses (at most one positive literal), this is O(|clauses| + |U|).
func ComputeMSS(proposed []Upgrade, clauses []Clause) MSSResult {
	// Build the set of proposed services and their upgrade info.
	inU := make(map[string]bool, len(proposed))
	upgradeMap := make(map[string]Upgrade, len(proposed))
	for _, u := range proposed {
		inU[u.Service] = true
		upgradeMap[u.Service] = u
	}

	// x_s: assignment. true = upgrade included, false = excluded.
	assignment := make(map[string]bool, len(proposed))
	for _, u := range proposed {
		assignment[u.Service] = true
	}

	// reasons tracks why each service was excluded.
	reasons := make(map[string]string)

	// Index clauses by Dep: depIndex[dep] = list of clauses where Dep == dep.
	// For unit clauses (Dep == ""), we handle them separately.
	depIndex := make(map[string][]Clause)
	for _, c := range clauses {
		depIndex[c.Dep] = append(depIndex[c.Dep], c)
	}

	// Build the initial queue.
	queue := make([]string, 0)

	// Unit clauses: not(cause) -- unconditionally exclude cause.
	for _, c := range depIndex[""] {
		if inU[c.Cause] && assignment[c.Cause] {
			assignment[c.Cause] = false
			reasons[c.Cause] = c.Reason
			queue = append(queue, c.Cause)
		}
	}

	// Services that appear as Dep but are not in U (they are false).
	seen := make(map[string]bool)
	for _, c := range clauses {
		if c.Dep == "" {
			continue // already handled as unit clause
		}
		if !inU[c.Dep] && !seen[c.Dep] {
			seen[c.Dep] = true
			queue = append(queue, c.Dep)
		}
	}

	// Propagation: process the queue.
	for len(queue) > 0 {
		v := queue[0]
		queue = queue[1:]

		// v is false. Find all clauses where v is the Dep.
		// For each such clause (not(cause) OR v), since v is false,
		// the clause reduces to not(cause), so cause must be false.
		for _, c := range depIndex[v] {
			if c.Cause == "" {
				continue
			}
			if assignment[c.Cause] {
				assignment[c.Cause] = false
				reasons[c.Cause] = c.Reason
				queue = append(queue, c.Cause)
			}
		}
	}

	// Partition into safe and removed.
	result := MSSResult{
		Reasons: reasons,
	}
	for _, u := range proposed {
		if assignment[u.Service] {
			result.Safe = append(result.Safe, u)
		} else {
			result.Removed = append(result.Removed, u)
		}
	}

	return result
}
