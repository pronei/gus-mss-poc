// Package schema loads OpenAPI 3.0 specs into the GUS type AST.
package schema

import (
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/faults-lab/gus/pkg/types"
	"gopkg.in/yaml.v3"
)

// Spec holds all schemas extracted from a single spec file.
type Spec struct {
	Endpoints map[EndpointKey]*EndpointSchemas // per endpoint
}

// EndpointKey identifies an API endpoint.
type EndpointKey struct {
	Path   string
	Method string
}

// EndpointSchemas holds the request and response schemas for an endpoint.
type EndpointSchemas struct {
	Request  *types.Node
	Response *types.Node
	Role     string // "" for the service's own API; "client" for a declared outbound call
}

// Load parses a spec file and returns the extracted schemas.
// Supports .yaml, .yml, and .json extensions for OpenAPI 3.0.
// servicePrefix is used to qualify Ref names (e.g., "checkout").
func Load(path string, servicePrefix string) (*Spec, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("schema: read %s: %w", path, err)
	}

	var doc openAPIDoc
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return nil, fmt.Errorf("schema: parse %s: %w", path, err)
	}

	ctx := &resolveCtx{
		prefix:     servicePrefix,
		components: doc.Components.Schemas,
		resolved:   make(map[string]*types.Node),
	}

	spec := &Spec{
		Endpoints: make(map[EndpointKey]*EndpointSchemas),
	}

	// Resolve all component schemas in sorted name order. Deterministic
	// resolution order matters: under mutual recursion, whichever component
	// resolves first gets fully inlined and the other keeps a Ref back-edge,
	// so map-order iteration would make the AST shape (and hence check
	// results) vary run to run.
	componentNames := make([]string, 0, len(doc.Components.Schemas))
	for name := range doc.Components.Schemas {
		componentNames = append(componentNames, name)
	}
	sort.Strings(componentNames)
	for _, name := range componentNames {
		if _, err := ctx.resolve(name); err != nil {
			return nil, fmt.Errorf("schema: resolve component %s: %w", name, err)
		}
	}

	// Extract endpoint schemas from paths.
	for pathStr, pathItem := range doc.Paths {
		ops := map[string]*operationObj{
			"GET":     pathItem.Get,
			"POST":    pathItem.Post,
			"PUT":     pathItem.Put,
			"PATCH":   pathItem.Patch,
			"DELETE":  pathItem.Delete,
			"OPTIONS": pathItem.Options,
			"HEAD":    pathItem.Head,
		}
		for method, op := range ops {
			if op == nil {
				continue
			}
			key := EndpointKey{Path: pathStr, Method: method}
			ep := &EndpointSchemas{Role: op.XRole}

			// Request schema from requestBody.
			if op.RequestBody != nil {
				if jsonContent, ok := op.RequestBody.Content["application/json"]; ok && jsonContent.Schema != nil {
					req, err := ctx.convertSchema(jsonContent.Schema)
					if err != nil {
						return nil, fmt.Errorf("schema: %s %s request: %w", method, pathStr, err)
					}
					ep.Request = req
				}
			}

			// Response schema from first 2xx status.
			resp, err := ctx.extractResponseSchema(op.Responses)
			if err != nil {
				return nil, fmt.Errorf("schema: %s %s response: %w", method, pathStr, err)
			}
			ep.Response = resp

			spec.Endpoints[key] = ep
		}
	}

	return spec, nil
}

// --- Internal OpenAPI document model (subset we need) ---

type openAPIDoc struct {
	Paths      map[string]*pathItemObj `yaml:"paths"`
	Components componentsObj           `yaml:"components"`
}

type componentsObj struct {
	Schemas map[string]*schemaObj `yaml:"schemas"`
}

type pathItemObj struct {
	Get     *operationObj `yaml:"get"`
	Post    *operationObj `yaml:"post"`
	Put     *operationObj `yaml:"put"`
	Patch   *operationObj `yaml:"patch"`
	Delete  *operationObj `yaml:"delete"`
	Options *operationObj `yaml:"options"`
	Head    *operationObj `yaml:"head"`
}

type operationObj struct {
	RequestBody *requestBodyObj         `yaml:"requestBody"`
	Responses   map[string]*responseObj `yaml:"responses"`
	XRole       string                  `yaml:"x-role"` // "client" marks a declared outbound call
}

type requestBodyObj struct {
	Content map[string]*mediaTypeObj `yaml:"content"`
}

type responseObj struct {
	Content map[string]*mediaTypeObj `yaml:"content"`
}

type mediaTypeObj struct {
	Schema *schemaObj `yaml:"schema"`
}

type schemaObj struct {
	Ref                  string                `yaml:"$ref"`
	Type                 string                `yaml:"type"`
	Format               string                `yaml:"format"`
	Nullable             bool                  `yaml:"nullable"`
	Enum                 []string              `yaml:"enum"`
	Items                *schemaObj            `yaml:"items"`
	Properties           map[string]*schemaObj `yaml:"properties"`
	Required             []string              `yaml:"required"`
	AdditionalProperties *additionalProps      `yaml:"additionalProperties"`
	OneOf                []*schemaObj          `yaml:"oneOf"`
	AllOf                []*schemaObj          `yaml:"allOf"`
	AnyOf                []*schemaObj          `yaml:"anyOf"`
	Default              interface{}           `yaml:"default"`

	// GUS extensions.
	XProvides string `yaml:"x-provides"`
	XRequires string `yaml:"x-requires"`
	XAlias    string `yaml:"x-alias"`
}

// additionalProps handles the dual nature of additionalProperties:
// it can be either a boolean or a schema object.
type additionalProps struct {
	Bool   *bool
	Schema *schemaObj
}

func (a *additionalProps) UnmarshalYAML(value *yaml.Node) error {
	// Try boolean first.
	if value.Kind == yaml.ScalarNode {
		var b bool
		if err := value.Decode(&b); err == nil {
			a.Bool = &b
			return nil
		}
	}
	// Otherwise, it's a schema.
	var s schemaObj
	if err := value.Decode(&s); err != nil {
		return err
	}
	a.Schema = &s
	return nil
}

// --- Schema resolution ---

type resolveCtx struct {
	prefix     string
	components map[string]*schemaObj
	resolved   map[string]*types.Node
	resolving  map[string]bool // cycle detection
}

// resolve resolves a named component schema, caching the result.
func (ctx *resolveCtx) resolve(name string) (*types.Node, error) {
	if node, ok := ctx.resolved[name]; ok {
		return node, nil
	}

	s, ok := ctx.components[name]
	if !ok {
		// Return a Ref node for unresolvable references.
		qualified := ctx.prefix + "." + name
		return types.Ref(qualified), nil
	}

	// Cycle detection: if we're already resolving this, produce a Ref.
	if ctx.resolving == nil {
		ctx.resolving = make(map[string]bool)
	}
	if ctx.resolving[name] {
		qualified := ctx.prefix + "." + name
		return types.Ref(qualified), nil
	}
	ctx.resolving[name] = true

	node, err := ctx.convertSchema(s)
	if err != nil {
		return nil, err
	}

	delete(ctx.resolving, name)
	ctx.resolved[name] = node
	return node, nil
}

// convertSchema converts a schemaObj into a types.Node.
func (ctx *resolveCtx) convertSchema(s *schemaObj) (*types.Node, error) {
	if s == nil {
		return types.Any(), nil
	}

	// Handle $ref.
	if s.Ref != "" {
		return ctx.resolveRef(s.Ref)
	}

	// allOf/anyOf are not modeled. Degrading them to Any would silently
	// disable checking for the whole subtree (a false-PASS machine), so they
	// are hard errors until composition is implemented.
	if len(s.AllOf) > 0 {
		return nil, fmt.Errorf("allOf is not supported by the GUS loader (schemas using it must be flattened)")
	}
	if len(s.AnyOf) > 0 {
		return nil, fmt.Errorf("anyOf is not supported by the GUS loader (schemas using it must be flattened)")
	}

	// Handle oneOf -> Union.
	if len(s.OneOf) > 0 {
		variants := make([]*types.Node, 0, len(s.OneOf))
		for _, v := range s.OneOf {
			vn, err := ctx.convertSchema(v)
			if err != nil {
				return nil, err
			}
			variants = append(variants, vn)
		}
		node := types.Union(variants)
		if s.Nullable {
			node = types.Nullable(node)
		}
		return node, nil
	}

	// Handle enum.
	if len(s.Enum) > 0 {
		node := types.Enum(s.Enum)
		if s.Nullable {
			node = types.Nullable(node)
		}
		return node, nil
	}

	var node *types.Node

	switch s.Type {
	case "string":
		node = types.Prim("string", s.Format)
	case "integer":
		node = types.Prim("integer", s.Format)
	case "number":
		node = types.Prim("number", s.Format)
	case "boolean":
		node = types.Prim("boolean", "")

	case "array":
		items, err := ctx.convertSchema(s.Items)
		if err != nil {
			return nil, err
		}
		node = types.Array(items)

	case "object":
		obj, err := ctx.convertObject(s)
		if err != nil {
			return nil, err
		}
		node = obj

	default:
		// No type specified: check if it has properties (implicit object)
		// or just treat as Any.
		if len(s.Properties) > 0 {
			obj, err := ctx.convertObject(s)
			if err != nil {
				return nil, err
			}
			node = obj
		} else {
			node = types.Any()
		}
	}

	if s.Nullable {
		node = types.Nullable(node)
	}

	return node, nil
}

// convertObject builds an Object node from a schema with properties.
func (ctx *resolveCtx) convertObject(s *schemaObj) (*types.Node, error) {
	requiredSet := make(map[string]bool, len(s.Required))
	for _, r := range s.Required {
		requiredSet[r] = true
	}

	fields := make(map[string]*types.Field, len(s.Properties))
	for name, propSchema := range s.Properties {
		fieldSchema, err := ctx.convertSchema(propSchema)
		if err != nil {
			// Propagate: degrading a field to Any silently disables checking.
			return nil, fmt.Errorf("property %q: %w", name, err)
		}

		f := &types.Field{
			Schema:   fieldSchema,
			Required: requiredSet[name],
		}

		// Default value.
		if propSchema.Default != nil {
			f.HasDefault = true
		}

		// GUS extensions.
		if propSchema.XProvides != "" {
			f.XProvides = propSchema.XProvides
		}
		if propSchema.XRequires != "" {
			f.XRequires = propSchema.XRequires
		}
		if propSchema.XAlias != "" {
			f.XAlias = propSchema.XAlias
		}

		fields[name] = f
	}

	// Determine openness: default is open (true) per JSON Schema.
	open := true
	if s.AdditionalProperties != nil {
		if s.AdditionalProperties.Bool != nil && !*s.AdditionalProperties.Bool {
			open = false
		}
		// additionalProperties as a schema: a property-less object with a
		// value schema is a Map; mixing named properties with a value schema
		// is not modeled and would silently drop the value schema, so error.
		if s.AdditionalProperties.Schema != nil {
			if len(fields) > 0 {
				return nil, fmt.Errorf("object mixing named properties with an additionalProperties schema is not supported")
			}
			val, err := ctx.convertSchema(s.AdditionalProperties.Schema)
			if err != nil {
				return nil, fmt.Errorf("additionalProperties: %w", err)
			}
			return types.Map(types.Prim("string", ""), val), nil
		}
	}

	return types.Object(fields, open), nil
}

// resolveRef resolves a $ref string like "#/components/schemas/Foo".
func (ctx *resolveCtx) resolveRef(ref string) (*types.Node, error) {
	const prefix = "#/components/schemas/"
	if !strings.HasPrefix(ref, prefix) {
		return nil, fmt.Errorf("unsupported $ref: %s", ref)
	}
	name := ref[len(prefix):]
	return ctx.resolve(name)
}

// extractResponseSchema finds the first 2xx response with a JSON schema.
func (ctx *resolveCtx) extractResponseSchema(responses map[string]*responseObj) (*types.Node, error) {
	if len(responses) == 0 {
		return nil, nil
	}

	// Collect and sort 2xx status codes.
	var codes []string
	for code := range responses {
		if len(code) == 3 && code[0] == '2' {
			codes = append(codes, code)
		}
	}
	sort.Strings(codes)

	for _, code := range codes {
		resp := responses[code]
		if resp == nil {
			continue
		}
		if jsonContent, ok := resp.Content["application/json"]; ok && jsonContent.Schema != nil {
			node, err := ctx.convertSchema(jsonContent.Schema)
			if err != nil {
				return nil, fmt.Errorf("status %s: %w", code, err)
			}
			return node, nil
		}
	}

	return nil, nil
}
