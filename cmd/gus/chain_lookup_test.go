package main

import (
	"testing"

	"github.com/faults-lab/gus/pkg/types"
)

func obj(fields map[string]bool) *types.Node {
	fs := map[string]*types.Field{}
	for name, required := range fields {
		fs[name] = &types.Field{Schema: types.Prim("string", ""), Required: required}
	}
	return types.Object(fs, true)
}

// A hop that forwards on the arrival path answers only from that contract:
// a same-named field of another payload must not stand in for a missing one,
// and an absent field on the arrival path is a miss even if another contract
// carries the name.
func TestResolveOutboundPrefersArrivalPathExclusively(t *testing.T) {
	sends := []outboundContract{
		{path: "/v1/traces/rpc.server", schema: obj(map[string]bool{"rpc.system": true})},
		{path: "/v1/traces/rpc.client", schema: obj(map[string]bool{"rpc.service": false})},
	}
	if fi := resolveOutbound(sends, "rpc.system", "/v1/traces/rpc.client"); fi != nil {
		t.Errorf("field absent on the arrival path must not resolve through another contract, got %+v", fi)
	}
	if fi := resolveOutbound(sends, "rpc.system", "/v1/traces/rpc.server"); fi == nil || !fi.Required || fi.Path != "/v1/traces/rpc.server" {
		t.Errorf("field on the arrival path must resolve with its path, got %+v", fi)
	}
	// No contract on the arrival path: the hop calls a different path, so every contract is searched.
	if fi := resolveOutbound(sends, "rpc.service", "/placeorder"); fi == nil || fi.Path != "/v1/traces/rpc.client" {
		t.Errorf("without an arrival-path contract all contracts answer, got %+v", fi)
	}
}
