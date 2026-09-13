#!/usr/bin/env python3
"""Acceptance 3: golden fragments of an emitted document.

Each case names an operation (or a pair of schemas) in the document and is
compared byte for byte against a file under golden/.  --update rewrites them.

  golden_check.py --doc out/front50-2.41.0.yaml [--update] [--case NAME]
"""
import argparse
import difflib
import io
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "..", "golden")


def op(doc, path, method):
    return doc["paths"][path][method]


def body_schema(o):
    return o["requestBody"]["content"]["application/json"]["schema"]


def resp_schema(o):
    c = o["responses"]["200"].get("content")
    return None if not c else c["application/json"]["schema"]


def cases(doc):
    """name -> the object to freeze.  Comments say what each one is evidence of."""
    out = {}

    # D6 params fold: five optional query parameters, two carrying a default;
    # the return is an array of an OPEN Pipeline object (S5 CLAIM-S5-001/031).
    out["front50_GET_pipelines"] = op(doc, "/pipelines", "get")

    # A required path parameter, and Application on both sides (D6).
    out["front50_PATCH_v2_applications"] = op(
        doc, "/v2/applications/{applicationName}", "patch")

    # CLAIM-S5-023: PipelineTemplate extends HashMap<String,Object>, so it is
    # an open object carrying its declared properties, additionalProperties
    # true, and untyped.
    out["front50_GET_pipelineTemplates_id"] = op(doc, "/pipelineTemplates/{id}", "get")

    # CLAIM-S5-022 + D6: multipart request -> no body; ResponseEntity<byte[]>
    # -> a contentless 200.
    out["front50_POST_pluginBinaries"] = op(
        doc, "/pluginBinaries/{id}/{version}", "post")

    # D4/CLAIM-S5-037 read through the mixin (D7): Pipeline's fields carry
    # @JsonInclude(NON_NULL) from PipelineMixins, so on the RETURN side they
    # are optional and not nullable, and on the ACCEPT side they are plain.
    post = op(doc, "/pipelines", "post")
    out["front50_nonnull_two_sides"] = {
        "accept.application": body_schema(post)["properties"]["body"]["properties"]["application"],
        "return.application": resp_schema(post)["properties"]["application"],
        "accept.required": body_schema(post)["properties"]["body"].get("required"),
        "return.required": resp_schema(post).get("required"),
    }
    return out


def dump(obj):
    return yaml.safe_dump(obj, default_flow_style=False, sort_keys=True, width=100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--case")
    a = ap.parse_args()

    doc = yaml.safe_load(open(a.doc))
    os.makedirs(GOLDEN, exist_ok=True)
    bad = 0
    for name, obj in sorted(cases(doc).items()):
        if a.case and a.case != name:
            continue
        f = os.path.join(GOLDEN, name + ".yaml")
        got = dump(obj)
        if a.update:
            open(f, "w").write(got)
            print("wrote %s (%d lines)" % (os.path.relpath(f), got.count("\n")))
            continue
        if not os.path.exists(f):
            print("MISSING golden %s" % os.path.relpath(f))
            bad += 1
            continue
        want = open(f).read()
        if want == got:
            print("ok   %s" % name)
        else:
            bad += 1
            print("FAIL %s" % name)
            for line in difflib.unified_diff(want.splitlines(), got.splitlines(),
                                             "golden", "extracted", lineterm="", n=2):
                print("   " + line)
    return 1 if bad else 0


sys.exit(main())
