package main

import (
	"fmt"
	"sort"
	"strings"

	"google.golang.org/protobuf/reflect/protoreflect"
)

// Wire-level comparison of two proto versions, by field NUMBER, under the
// compatibility rules protobuf documents for "updating a message type":
//
//	int32, uint32, int64, uint64 and bool are mutually compatible (varint);
//	sint32 and sint64; fixed32 and sfixed32; fixed64 and sfixed64;
//	string and bytes (if valid UTF-8); an enum with int32/uint32/int64/uint64;
//	a message field with another message of compatible structure.
//
// Anything else at the same number is a WIRE break: a reader of the old
// version cannot parse a payload written by the new one, or vice versa.
// Changes that keep the wire parseable but alter meaning are recorded as
// SEMANTIC: a field deleted (old readers see the default), a field renamed
// or a number reused under a new name (old readers see the wrong value under
// the right name), an enum value removed (readers see an unknown value).
// Field additions are silent, as on the wire.

type wireFinding struct {
	Service string
	Kind    string // "WIRE" or "SEMANTIC"
	Where   string
	Detail  string
}

var varintFamily = map[protoreflect.Kind]bool{
	protoreflect.Int32Kind: true, protoreflect.Uint32Kind: true, protoreflect.Int64Kind: true,
	protoreflect.Uint64Kind: true, protoreflect.BoolKind: true, protoreflect.EnumKind: true,
}

func kindsCompatible(a, b protoreflect.Kind) bool {
	if a == b {
		return true
	}
	if varintFamily[a] && varintFamily[b] {
		return true
	}
	pair := func(x, y protoreflect.Kind) bool { return (a == x && b == y) || (a == y && b == x) }
	return pair(protoreflect.Sint32Kind, protoreflect.Sint64Kind) ||
		pair(protoreflect.Fixed32Kind, protoreflect.Sfixed32Kind) ||
		pair(protoreflect.Fixed64Kind, protoreflect.Sfixed64Kind) ||
		pair(protoreflect.StringKind, protoreflect.BytesKind)
}

// compareServices walks every RPC of every service present in both
// versions and compares request and response structures by number.
func compareServices(old, new protoreflect.FileDescriptor) []wireFinding {
	var out []wireFinding
	oldSvcs := map[string]protoreflect.ServiceDescriptor{}
	for i := 0; i < old.Services().Len(); i++ {
		s := old.Services().Get(i)
		oldSvcs[serviceID(string(s.Name()))] = s
	}
	newSvcs := map[string]protoreflect.ServiceDescriptor{}
	for i := 0; i < new.Services().Len(); i++ {
		s := new.Services().Get(i)
		newSvcs[serviceID(string(s.Name()))] = s
	}
	for _, id := range keys(oldSvcs) {
		os, ok := newSvcs[id]
		if !ok {
			out = append(out, wireFinding{id, "WIRE", "service", "service removed"})
			continue
		}
		s := oldSvcs[id]
		if s.Name() != os.Name() {
			out = append(out, wireFinding{id, "WIRE", "service", fmt.Sprintf("service renamed %s -> %s: every RPC path changes", s.Name(), os.Name())})
		}
		for j := 0; j < s.Methods().Len(); j++ {
			m := s.Methods().Get(j)
			nm := os.Methods().ByName(m.Name())
			if nm == nil {
				out = append(out, wireFinding{id, "WIRE", string(m.Name()), "rpc removed"})
				continue
			}
			for _, side := range []struct {
				label    string
				om, nmsg protoreflect.MessageDescriptor
			}{{"request", m.Input(), nm.Input()}, {"response", m.Output(), nm.Output()}} {
				if side.om.Name() != side.nmsg.Name() {
					out = append(out, wireFinding{id, "SEMANTIC", string(m.Name()) + " " + side.label,
						fmt.Sprintf("type renamed %s -> %s (structure compared below)", side.om.Name(), side.nmsg.Name())})
				}
				out = append(out, compareMessages(id, string(m.Name())+" "+side.label, side.om, side.nmsg, map[string]bool{})...)
			}
		}
	}
	return out
}

func compareMessages(svc, where string, old, new protoreflect.MessageDescriptor, seen map[string]bool) []wireFinding {
	key := string(old.FullName()) + "|" + string(new.FullName())
	if seen[key] {
		return nil
	}
	seen[key] = true
	var out []wireFinding
	oldByNum := map[protoreflect.FieldNumber]protoreflect.FieldDescriptor{}
	for i := 0; i < old.Fields().Len(); i++ {
		f := old.Fields().Get(i)
		oldByNum[f.Number()] = f
	}
	nums := make([]int, 0, len(oldByNum))
	for n := range oldByNum {
		nums = append(nums, int(n))
	}
	sort.Ints(nums)
	for _, n := range nums {
		of := oldByNum[protoreflect.FieldNumber(n)]
		nf := new.Fields().ByNumber(protoreflect.FieldNumber(n))
		at := fmt.Sprintf("%s.%s#%d", old.Name(), of.Name(), n)
		if nf == nil {
			out = append(out, wireFinding{svc, "SEMANTIC", where, at + ": field deleted (old readers see the default)"})
			continue
		}
		if of.IsList() != nf.IsList() || of.IsMap() != nf.IsMap() {
			out = append(out, wireFinding{svc, "WIRE", where, at + ": cardinality changed"})
			continue
		}
		if !kindsCompatible(of.Kind(), nf.Kind()) {
			out = append(out, wireFinding{svc, "WIRE", where, fmt.Sprintf("%s: %s -> %s is not wire-compatible", at, of.Kind(), nf.Kind())})
			continue
		}
		if of.Name() != nf.Name() {
			out = append(out, wireFinding{svc, "SEMANTIC", where, fmt.Sprintf("%s: number %d now named %q (old readers take %q's value as %q)", at, n, nf.Name(), nf.Name(), of.Name())})
		}
		if of.Kind() == protoreflect.EnumKind && nf.Kind() == protoreflect.EnumKind {
			for i := 0; i < of.Enum().Values().Len(); i++ {
				v := of.Enum().Values().Get(i)
				if nf.Enum().Values().ByNumber(v.Number()) == nil {
					out = append(out, wireFinding{svc, "SEMANTIC", where, fmt.Sprintf("%s: enum value %s=%d removed", at, v.Name(), v.Number())})
				}
			}
		}
		if of.Kind() == protoreflect.MessageKind && nf.Kind() == protoreflect.MessageKind {
			om, nm := of.Message(), nf.Message()
			if of.IsMap() {
				om, nm = of.MapValue().Message(), nf.MapValue().Message()
				if om == nil || nm == nil {
					continue
				}
			}
			out = append(out, compareMessages(svc, where, om, nm, seen)...)
		}
	}
	return out
}

func formatWire(fs []wireFinding) string {
	if len(fs) == 0 {
		return "(no wire or semantic findings)\n"
	}
	var b strings.Builder
	for _, f := range fs {
		fmt.Fprintf(&b, "%-8s %-15s %-32s %s\n", f.Kind, f.Service, f.Where, f.Detail)
	}
	return b.String()
}
