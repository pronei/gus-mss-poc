// Package solver implements the MSS (maximal safe subset) computation.
//
// The clause layer is classic Dowling–Gallier unit propagation over definite
// Horn clauses (¬x_a ∨ x_b, "a can only ship if b ships") plus negative unit
// clauses (¬x_s, "s cannot ship in this batch"). For that fragment the
// satisfying true-sets are closed under union, so a unique maximum-cardinality
// model exists and propagation finds it in O(|clauses| + |U|).
//
// The ordering layer is what makes the answer sound for ROLLING deployments:
// a failed mixed-pairing conjunct does not just couple two upgrades, it
// constrains their rollout ORDER (a C1 failure on u→v means every old-u
// instance must be gone before the first new-v instance appears). Those
// constraints are passed in as Precedence edges. A precedence cycle among
// co-shipped services (e.g. C1 and C4 both failing on one edge) means no
// rollout order exists — the services deadlock and cannot ship in the same
// rolling batch, so the solver excludes the whole cycle and re-propagates.
//
// With cycle exclusion the result is no longer guaranteed maximum-cardinality:
// once "not both u and v" constraints exist, satisfying sets stop being
// union-closed and maximizing |true| is NP-hard (it embeds maximum
// independent set). Excluding every member of a deadlock cycle is the
// deterministic, conservative choice; a weighted MaxSAT solver could do
// better and is deliberately out of scope for this POC.
package solver

import "sort"

// Upgrade represents a proposed service version change.
type Upgrade struct {
	Service string
	FromVer string
	ToVer   string
}

// Clause is a Horn clause: ¬Cause ∨ Dep.
// Semantics: "Cause can ship only if Dep also ships."
// If Dep is "", it is a negative unit clause ¬Cause (unconditional exclusion).
type Clause struct {
	Cause  string
	Dep    string
	Reason string
}

// Precedence records a rollout ordering constraint between two co-shipped
// upgrades: First must be fully rolled out before Then starts rolling.
type Precedence struct {
	First  string
	Then   string
	Reason string
}

// MSSResult holds the result of the MSS computation.
type MSSResult struct {
	Safe    []Upgrade
	Removed []Upgrade
	Reasons map[string]string // service -> why excluded (first cause)
	// Order is a valid rollout schedule for the safe set: services in stage i
	// must be fully rolled out before stage i+1 starts. Stages with no
	// ordering constraints between them are merged and sorted by name.
	Order [][]string
}

// ComputeMSS returns the safe subset of the proposed upgrades under the given
// Horn clauses and rollout-order constraints, plus a rollout schedule.
func ComputeMSS(proposed []Upgrade, clauses []Clause, precedences []Precedence) MSSResult {
	inU := make(map[string]bool, len(proposed))
	for _, u := range proposed {
		inU[u.Service] = true
	}

	assignment := make(map[string]bool, len(proposed))
	for _, u := range proposed {
		assignment[u.Service] = true
	}
	reasons := make(map[string]string)

	// Index definite clauses by Dep for falsity propagation.
	depIndex := make(map[string][]Clause)
	for _, c := range clauses {
		depIndex[c.Dep] = append(depIndex[c.Dep], c)
	}

	exclude := func(svc, reason string, queue *[]string) {
		if inU[svc] && assignment[svc] {
			assignment[svc] = false
			if _, ok := reasons[svc]; !ok {
				reasons[svc] = reason
			}
			*queue = append(*queue, svc)
		}
	}

	propagate := func(queue []string) {
		// Falsity propagation: v false makes every (¬cause ∨ v) reduce to ¬cause.
		for len(queue) > 0 {
			v := queue[0]
			queue = queue[1:]
			for _, c := range depIndex[v] {
				if c.Cause != "" && assignment[c.Cause] {
					assignment[c.Cause] = false
					if _, ok := reasons[c.Cause]; !ok {
						reasons[c.Cause] = c.Reason
					}
					queue = append(queue, c.Cause)
				}
			}
		}
	}

	// Seed: negative unit clauses, and Deps outside the batch (false by definition).
	var queue []string
	for _, c := range depIndex[""] {
		exclude(c.Cause, c.Reason, &queue)
	}
	seen := make(map[string]bool)
	for _, c := range clauses {
		if c.Dep == "" || inU[c.Dep] || seen[c.Dep] {
			continue
		}
		seen[c.Dep] = true
		queue = append(queue, c.Dep)
	}
	propagate(queue)

	// Ordering layer: exclude precedence cycles among still-safe services,
	// re-propagating after each round (an exclusion can trigger definite
	// clauses, which can break or create no new cycles — the loop shrinks the
	// safe set monotonically, so it terminates).
	for {
		cycleMembers := findCycleMembers(precedences, assignment)
		if len(cycleMembers) == 0 {
			break
		}
		var q []string
		for _, svc := range cycleMembers {
			exclude(svc, "rollout deadlock: ordering constraints among co-shipped upgrades form a cycle (no rolling order exists; requires an atomic switchover)", &q)
		}
		propagate(q)
	}

	result := MSSResult{Reasons: reasons}
	sortedProposed := append([]Upgrade(nil), proposed...)
	sort.Slice(sortedProposed, func(i, j int) bool { return sortedProposed[i].Service < sortedProposed[j].Service })
	for _, u := range sortedProposed {
		if assignment[u.Service] {
			result.Safe = append(result.Safe, u)
		} else {
			result.Removed = append(result.Removed, u)
		}
	}

	result.Order = rolloutOrder(result.Safe, precedences, assignment)
	return result
}

// findCycleMembers returns every service that sits on a precedence cycle
// among currently-safe services (deterministically sorted). Uses iterative
// Tarjan SCC; SCCs of size > 1 and self-loops are cycles.
func findCycleMembers(precedences []Precedence, assignment map[string]bool) []string {
	adj := make(map[string][]string)
	nodes := make(map[string]bool)
	for _, p := range precedences {
		if !assignment[p.First] || !assignment[p.Then] {
			continue
		}
		adj[p.First] = append(adj[p.First], p.Then)
		nodes[p.First] = true
		nodes[p.Then] = true
	}
	if len(nodes) == 0 {
		return nil
	}

	names := make([]string, 0, len(nodes))
	for n := range nodes {
		names = append(names, n)
	}
	sort.Strings(names)
	for n := range adj {
		sort.Strings(adj[n])
	}

	index := make(map[string]int)
	low := make(map[string]int)
	onStack := make(map[string]bool)
	var stack []string
	next := 0
	var members []string

	type frame struct {
		node string
		ci   int
	}
	for _, root := range names {
		if _, visited := index[root]; visited {
			continue
		}
		frames := []frame{{root, 0}}
		index[root], low[root] = next, next
		next++
		stack = append(stack, root)
		onStack[root] = true

		for len(frames) > 0 {
			f := &frames[len(frames)-1]
			if f.ci < len(adj[f.node]) {
				child := adj[f.node][f.ci]
				f.ci++
				if _, visited := index[child]; !visited {
					index[child], low[child] = next, next
					next++
					stack = append(stack, child)
					onStack[child] = true
					frames = append(frames, frame{child, 0})
				} else if onStack[child] && index[child] < low[f.node] {
					low[f.node] = index[child]
				}
				continue
			}
			// Pop frame.
			node := f.node
			frames = frames[:len(frames)-1]
			if len(frames) > 0 {
				parent := frames[len(frames)-1].node
				if low[node] < low[parent] {
					low[parent] = low[node]
				}
			}
			if low[node] == index[node] {
				var scc []string
				for {
					top := stack[len(stack)-1]
					stack = stack[:len(stack)-1]
					onStack[top] = false
					scc = append(scc, top)
					if top == node {
						break
					}
				}
				if len(scc) > 1 {
					members = append(members, scc...)
				} else if hasSelfLoop(adj, scc[0]) {
					members = append(members, scc[0])
				}
			}
		}
	}
	sort.Strings(members)
	return members
}

func hasSelfLoop(adj map[string][]string, node string) bool {
	for _, n := range adj[node] {
		if n == node {
			return true
		}
	}
	return false
}

// rolloutOrder computes Kahn layers of the (acyclic, post-exclusion)
// precedence graph restricted to the safe set.
func rolloutOrder(safe []Upgrade, precedences []Precedence, assignment map[string]bool) [][]string {
	if len(safe) == 0 {
		return nil
	}
	indeg := make(map[string]int, len(safe))
	adj := make(map[string][]string)
	for _, u := range safe {
		indeg[u.Service] = 0
	}
	for _, p := range precedences {
		if !assignment[p.First] || !assignment[p.Then] {
			continue
		}
		adj[p.First] = append(adj[p.First], p.Then)
		indeg[p.Then]++
	}

	var order [][]string
	remaining := len(indeg)
	for remaining > 0 {
		var layer []string
		for svc, d := range indeg {
			if d == 0 {
				layer = append(layer, svc)
			}
		}
		if len(layer) == 0 {
			// Unreachable after cycle exclusion; guard against infinite loop.
			break
		}
		sort.Strings(layer)
		order = append(order, layer)
		for _, svc := range layer {
			for _, next := range adj[svc] {
				indeg[next]--
			}
			delete(indeg, svc)
			remaining--
		}
	}
	return order
}
