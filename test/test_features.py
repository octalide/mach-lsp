#!/usr/bin/env python3
"""local language-feature scenarios over a small typed buffer: hover renders
signatures / types / doc comments, definition lands on the decl, references
finds decl + use-sites, rename emits a WorkspaceEdit (including a parameter
binding), documentSymbol lists the top-level decls, completion includes the
file's functions."""
import sys

from harness import drive, req, notify, did_open, pos, by_id

DOC = "helper returns its argument unchanged."
SRC = (
    f"# {DOC}\n"                                          # line 0 (doc comment)
    "# exercised by the hover doc-comment assertion.\n"  # line 1 (doc comment)
    "fun helper(a: i64) i64 { ret a; }\n"                # line 2
    "fun main() i64 {\n"                                 # line 3
    "    val x: i64 = helper(7);\n"                       # line 4
    "    ret x;\n"                                         # line 5
    "}\n"                                                 # line 6
)
URI = "file:///feat.mach"


def run():
    """drive the local feature scenarios; return a list of failure strings."""
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(URI, SRC),
        req(10, "textDocument/hover", {"textDocument": {"uri": URI}, "position": pos(4, 17)}),
        req(11, "textDocument/hover", {"textDocument": {"uri": URI}, "position": pos(5, 8)}),
        req(20, "textDocument/definition", {"textDocument": {"uri": URI}, "position": pos(4, 17)}),
        req(30, "textDocument/references",
            {"textDocument": {"uri": URI}, "position": pos(2, 4),
             "context": {"includeDeclaration": True}}),
        req(40, "textDocument/prepareRename", {"textDocument": {"uri": URI}, "position": pos(4, 8)}),
        req(41, "textDocument/rename",
            {"textDocument": {"uri": URI}, "position": pos(4, 8), "newName": "y"}),
        req(42, "textDocument/rename",
            {"textDocument": {"uri": URI}, "position": pos(2, 11), "newName": "arg"}),
        req(50, "textDocument/documentSymbol", {"textDocument": {"uri": URI}}),
        req(60, "textDocument/completion", {"textDocument": {"uri": URI}, "position": pos(5, 4)}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    init = by_id(msgs, 1)
    caps = (init or {}).get("result", {}).get("capabilities", {})
    for cap in ["hoverProvider", "definitionProvider", "referencesProvider",
                "renameProvider", "documentSymbolProvider", "completionProvider"]:
        if cap not in caps:
            failures.append(f"initialize missing capability {cap}")

    # hover on helper -> signature plus its doc comment
    hv = (by_id(msgs, 10) or {}).get("result")
    if not hv or "contents" not in hv:
        failures.append("hover(helper) returned no contents")
    else:
        hval = hv["contents"].get("value", "")
        if "helper" not in hval:
            failures.append("hover(helper) value does not mention 'helper'")
        if DOC not in hval:
            failures.append(f"hover(helper) value does not include the doc comment {DOC!r}")

    # hover on x -> mentions i64
    hv2 = (by_id(msgs, 11) or {}).get("result")
    if not hv2 or "contents" not in hv2:
        failures.append("hover(x) returned no contents")
    elif "i64" not in hv2["contents"].get("value", ""):
        failures.append("hover(x) value does not mention type 'i64'")

    # definition of helper -> Location on its decl line (2)
    dv = (by_id(msgs, 20) or {}).get("result")
    if not dv or "range" not in dv:
        failures.append("definition(helper) returned no Location")
    elif dv["range"]["start"]["line"] != 2:
        failures.append(f"definition(helper) points to line {dv['range']['start']['line']}, expected 2")

    # references of helper -> decl + call
    rv = (by_id(msgs, 30) or {}).get("result")
    if not isinstance(rv, list):
        failures.append("references(helper) result is not an array")
    elif len(rv) < 2:
        failures.append(f"references(helper) found {len(rv)}, expected >= 2 (decl + call)")

    # prepareRename of x -> a range
    prv = (by_id(msgs, 40) or {}).get("result")
    if not prv or "start" not in prv:
        failures.append("prepareRename(x) returned no range")

    # rename x -> y, >= 2 edits all spelled 'y'
    rnv = (by_id(msgs, 41) or {}).get("result")
    if not rnv or "changes" not in rnv:
        failures.append("rename(x) returned no WorkspaceEdit")
    else:
        edits = rnv["changes"].get(URI, [])
        if len(edits) < 2:
            failures.append(f"rename(x) produced {len(edits)} edits, expected >= 2")
        elif any(e.get("newText") != "y" for e in edits):
            failures.append("rename(x) edit newText is not 'y'")

    # rename parameter a -> arg: binding site (col 11) + the use
    rp2 = (by_id(msgs, 42) or {}).get("result")
    if not rp2 or "changes" not in rp2:
        failures.append("rename(param a) returned no WorkspaceEdit")
    else:
        pedits = rp2["changes"].get(URI, [])
        if len(pedits) < 2:
            failures.append(f"rename(param a) produced {len(pedits)} edits, expected >= 2 (binding + use)")
        elif any(e.get("newText") != "arg" for e in pedits):
            failures.append("rename(param a) edit newText is not 'arg'")
        else:
            cols = {e["range"]["start"]["character"] for e in pedits if e["range"]["start"]["line"] == 2}
            if 11 not in cols:
                failures.append(f"rename(param a) did not rewrite the binding at col 11 (cols {sorted(cols)})")

    # documentSymbol -> helper and main, not the nested local x
    dsv = (by_id(msgs, 50) or {}).get("result")
    if not isinstance(dsv, list):
        failures.append("documentSymbol result is not an array")
    else:
        names = {s.get("name") for s in dsv}
        for want in ("helper", "main"):
            if want not in names:
                failures.append(f"documentSymbol missing '{want}' (got {sorted(names)})")
        if "x" in names:
            failures.append("documentSymbol leaked the nested local 'x' as a top-level symbol")

    # completion -> includes helper and main
    cpv = (by_id(msgs, 60) or {}).get("result")
    items = (cpv or {}).get("items", []) if isinstance(cpv, dict) else []
    labels = {it.get("label") for it in items}
    for want in ("helper", "main"):
        if want not in labels:
            failures.append(f"completion missing '{want}' (got {sorted(labels)})")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")

    return failures


if __name__ == "__main__":
    fails = run()
    for f in fails:
        print("  -", f)
    print("features:", "FAILED" if fails else "PASSED")
    sys.exit(1 if fails else 0)
