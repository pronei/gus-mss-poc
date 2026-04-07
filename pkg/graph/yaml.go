package graph

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// --- YAML wire types ---

type graphYAML struct {
	Services map[string]serviceYAML `yaml:"services"`
	Edges    []edgeYAML             `yaml:"edges"`
}

type serviceYAML = map[string]string // version -> path

type edgeYAML struct {
	Name    string `yaml:"name"`
	From    string `yaml:"from"`
	To      string `yaml:"to"`
	Channel string `yaml:"channel"`
	Method  string `yaml:"method"`
	Path    string `yaml:"path"`
	Topic   string `yaml:"topic"`
}

type scenarioYAML struct {
	Name        string            `yaml:"name"`
	Description string            `yaml:"description"`
	Baseline    map[string]string `yaml:"baseline"`
	Upgrades    map[string]string `yaml:"upgrades"`
	Expect      *expectYAML       `yaml:"expect"`
}

type expectYAML struct {
	GUS    string        `yaml:"gus"`
	MSS    []string      `yaml:"mss"`
	Breaks []breakYAML   `yaml:"breaks"`
}

type breakYAML struct {
	Edge string `yaml:"edge"`
	Rule string `yaml:"rule"`
}

// --- Public loaders ---

// LoadGraph reads a graph YAML file.
func LoadGraph(path string) (*Graph, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("graph: read %s: %w", path, err)
	}

	var raw graphYAML
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("graph: parse %s: %w", path, err)
	}

	def := GraphDef{
		Services: make(map[string]ServiceDef, len(raw.Services)),
	}

	for name, versions := range raw.Services {
		def.Services[name] = ServiceDef{Versions: versions}
	}

	for _, e := range raw.Edges {
		edge := EdgeDef{
			Name:    e.Name,
			From:    e.From,
			To:      e.To,
			Channel: e.Channel,
			Method:  strings.ToUpper(e.Method),
			Path:    e.Path,
			Topic:   e.Topic,
		}
		// Default channel.
		if edge.Channel == "" {
			edge.Channel = "http"
		}
		// Auto-generate name.
		if edge.Name == "" {
			edge.Name = edge.From + "->" + edge.To
		}
		def.Edges = append(def.Edges, edge)
	}

	absDir, err := filepath.Abs(filepath.Dir(path))
	if err != nil {
		return nil, fmt.Errorf("graph: resolve dir for %s: %w", path, err)
	}

	return &Graph{Def: def, BaseDir: absDir}, nil
}

// LoadScenario reads a scenario YAML file.
func LoadScenario(path string) (*ScenarioDef, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("graph: read scenario %s: %w", path, err)
	}

	var raw scenarioYAML
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("graph: parse scenario %s: %w", path, err)
	}

	sc := &ScenarioDef{
		Name:        raw.Name,
		Description: raw.Description,
		Baseline:    raw.Baseline,
		Upgrades:    raw.Upgrades,
	}

	if raw.Expect != nil {
		eb := &ExpectBlock{
			GUS: strings.ToUpper(raw.Expect.GUS),
			MSS: raw.Expect.MSS,
		}
		for _, b := range raw.Expect.Breaks {
			eb.Breaks = append(eb.Breaks, ExpectedBreak{
				Edge: b.Edge,
				Rule: b.Rule,
			})
		}
		sc.Expect = eb
	}

	return sc, nil
}

// LoadScenarioDir reads all .yaml files from a directory as scenarios.
func LoadScenarioDir(dir string) ([]*ScenarioDef, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("graph: read scenario dir %s: %w", dir, err)
	}

	var scenarios []*ScenarioDef
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		ext := strings.ToLower(filepath.Ext(name))
		if ext != ".yaml" && ext != ".yml" {
			continue
		}

		sc, err := LoadScenario(filepath.Join(dir, name))
		if err != nil {
			return nil, err
		}
		scenarios = append(scenarios, sc)
	}

	return scenarios, nil
}
