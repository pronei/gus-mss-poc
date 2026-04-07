// Package graph defines the service mesh topology and scenario models for GUS.
package graph

import (
	"fmt"
	"path/filepath"
)

// GraphDef holds the full service mesh definition loaded from YAML.
type GraphDef struct {
	Services map[string]ServiceDef
	Edges    []EdgeDef
}

// ServiceDef describes a service with its available spec versions.
type ServiceDef struct {
	Versions map[string]string // version -> spec file path (relative to graph file dir)
}

// EdgeDef represents a communication edge between two services.
type EdgeDef struct {
	Name    string // auto-generated if empty: "from->to"
	From    string
	To      string
	Channel string // "http" (default) or "kafka"
	Method  string // HTTP method
	Path    string // endpoint path
	Topic   string // Kafka topic
}

// ScenarioDef describes a single upgrade scenario to evaluate.
type ScenarioDef struct {
	Name        string
	Description string
	Baseline    map[string]string // service -> version (theta)
	Upgrades    map[string]string // service -> version (U)
	Expect      *ExpectBlock      // optional expected results
}

// ExpectBlock holds expected outcomes for test assertions.
type ExpectBlock struct {
	GUS    string          // "PASS" or "FAIL"
	MSS    []string        // expected MSS services
	Breaks []ExpectedBreak // expected compatibility breaks
}

// ExpectedBreak describes a single expected rule violation on an edge.
type ExpectedBreak struct {
	Edge string
	Rule string
}

// Graph wraps a GraphDef with its base directory for resolving relative paths.
type Graph struct {
	Def     GraphDef
	BaseDir string
}

// SpecPath resolves the absolute spec file path for a service version.
func (g *Graph) SpecPath(service, version string) (string, error) {
	svc, ok := g.Def.Services[service]
	if !ok {
		return "", fmt.Errorf("service %q not defined in graph", service)
	}
	path, ok := svc.Versions[version]
	if !ok {
		return "", fmt.Errorf("version %q not defined for service %q", version, service)
	}
	return filepath.Join(g.BaseDir, path), nil
}
