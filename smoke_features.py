#!/usr/bin/env python3
# smoke test: drive the mach-lsp server over stdio with framed JSON-RPC and
# assert the language features (hover, definition, references, rename,
# prepareRename, documentSymbol, completion) against a small typed source.
import json
import subprocess
import sys

BIN = "out/linux/bin/mach-lsp"

SRC = (
    "fun helper(a: i64) i64 { ret a; }\n"   # line 0
    "fun main() i64 {\n"                     # line 1
    "    val x: i64 = helper(7);\n"          # line 2
    "    ret x;\n"                            # line 3
    "}\n"                                     # line 4
)
URI = "file:///feat.mach"


def frame(obj):
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def read_messages(data):
    msgs = []
    i = 0
    while i < len(data):
        hdr_end = data.find(b"\r\n\r\n", i)
        if hdr_end < 0:
            break
        header = data[i:hdr_end].decode(errors="replace")
        clen = None
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                clen = int(line.split(":", 1)[1].strip())
        if clen is None:
            break
        bstart = hdr_end + 4
        body = data[bstart:bstart + clen]
        msgs.append(json.loads(body.decode()))
        i = bstart + clen
    return msgs


def pos(line, ch):
    return {"line": line, "character": ch}


requests = b"".join([
    frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}}),
    frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}),
    frame({"jsonrpc": "2.0", "method": "textDocument/didOpen",
           "params": {"textDocument": {"uri": URI, "languageId": "mach", "version": 1, "text": SRC}}}),
    # hover on `helper` at its call site (line 2, char ~17)
    frame({"jsonrpc": "2.0", "id": 10, "method": "textDocument/hover",
           "params": {"textDocument": {"uri": URI}, "position": pos(2, 17)}}),
    # hover on `x` use at `ret x` (line 3, char 8)
    frame({"jsonrpc": "2.0", "id": 11, "method": "textDocument/hover",
           "params": {"textDocument": {"uri": URI}, "position": pos(3, 8)}}),
    # definition of `helper` call (line 2) -> decl on line 0
    frame({"jsonrpc": "2.0", "id": 20, "method": "textDocument/definition",
           "params": {"textDocument": {"uri": URI}, "position": pos(2, 17)}}),
    # references of `helper` (decl + the one call)
    frame({"jsonrpc": "2.0", "id": 30, "method": "textDocument/references",
           "params": {"textDocument": {"uri": URI}, "position": pos(0, 4),
                      "context": {"includeDeclaration": True}}}),
    # prepareRename on `x`
    frame({"jsonrpc": "2.0", "id": 40, "method": "textDocument/prepareRename",
           "params": {"textDocument": {"uri": URI}, "position": pos(2, 8)}}),
    # rename `x` -> `y`
    frame({"jsonrpc": "2.0", "id": 41, "method": "textDocument/rename",
           "params": {"textDocument": {"uri": URI}, "position": pos(2, 8), "newName": "y"}}),
    # rename parameter `a` from its binding site (line 0, char 11) -> `arg`;
    # must rewrite the binding plus the `ret a` use (a correct, compiling rename)
    frame({"jsonrpc": "2.0", "id": 42, "method": "textDocument/rename",
           "params": {"textDocument": {"uri": URI}, "position": pos(0, 11), "newName": "arg"}}),
    # documentSymbol
    frame({"jsonrpc": "2.0", "id": 50, "method": "textDocument/documentSymbol",
           "params": {"textDocument": {"uri": URI}}}),
    # completion at statement position inside main
    frame({"jsonrpc": "2.0", "id": 60, "method": "textDocument/completion",
           "params": {"textDocument": {"uri": URI}, "position": pos(3, 4)}}),
    frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None}),
    frame({"jsonrpc": "2.0", "method": "exit", "params": None}),
])

proc = subprocess.run([BIN], input=requests, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
msgs = read_messages(proc.stdout)


def by_id(i):
    return next((m for m in msgs if m.get("id") == i), None)


print("=== server exit code:", proc.returncode)
print("=== messages received:", len(msgs))
for m in msgs:
    if m.get("id") in (10, 11, 20, 30, 40, 41, 42, 50, 60):
        print(json.dumps(m))

failures = []

# initialize capabilities
init = by_id(1)
caps = (init or {}).get("result", {}).get("capabilities", {})
for cap in ["hoverProvider", "definitionProvider", "referencesProvider",
            "renameProvider", "documentSymbolProvider", "completionProvider"]:
    if cap not in caps:
        failures.append(f"initialize missing capability {cap}")

# hover on helper -> markdown mentioning helper signature
h = by_id(10)
hv = (h or {}).get("result")
if not hv or "contents" not in hv:
    failures.append("hover(helper) returned no contents")
elif "helper" not in hv["contents"].get("value", ""):
    failures.append("hover(helper) value does not mention 'helper'")

# hover on x -> mentions x and i64
h2 = by_id(11)
hv2 = (h2 or {}).get("result")
if not hv2 or "contents" not in hv2:
    failures.append("hover(x) returned no contents")
elif "i64" not in hv2["contents"].get("value", ""):
    failures.append("hover(x) value does not mention type 'i64'")

# definition of helper -> a Location on line 0
d = by_id(20)
dv = (d or {}).get("result")
if not dv or "range" not in dv:
    failures.append("definition(helper) returned no Location")
elif dv["range"]["start"]["line"] != 0:
    failures.append(f"definition(helper) points to line {dv['range']['start']['line']}, expected 0")

# references of helper -> at least 2 (decl + call)
r = by_id(30)
rv = (r or {}).get("result")
if not isinstance(rv, list):
    failures.append("references(helper) result is not an array")
elif len(rv) < 2:
    failures.append(f"references(helper) found {len(rv)}, expected >= 2 (decl + call)")

# prepareRename of x -> a range
pr = by_id(40)
prv = (pr or {}).get("result")
if not prv or "start" not in prv:
    failures.append("prepareRename(x) returned no range")

# rename x -> y produces a WorkspaceEdit with >= 2 edits (decl + use)
rn = by_id(41)
rnv = (rn or {}).get("result")
if not rnv or "changes" not in rnv:
    failures.append("rename(x) returned no WorkspaceEdit")
else:
    edits = rnv["changes"].get(URI, [])
    if len(edits) < 2:
        failures.append(f"rename(x) produced {len(edits)} edits, expected >= 2")
    elif any(e.get("newText") != "y" for e in edits):
        failures.append("rename(x) edit newText is not 'y'")

# rename of parameter `a` -> `arg`: binding site + the `ret a` use (>= 2 edits)
rp2 = by_id(42)
rp2v = (rp2 or {}).get("result")
if not rp2v or "changes" not in rp2v:
    failures.append("rename(param a) returned no WorkspaceEdit")
else:
    pedits = rp2v["changes"].get(URI, [])
    if len(pedits) < 2:
        failures.append(f"rename(param a) produced {len(pedits)} edits, expected >= 2 (binding + use)")
    elif any(e.get("newText") != "arg" for e in pedits):
        failures.append("rename(param a) edit newText is not 'arg'")
    else:
        # the binding site is on line 0 (the signature); a use is on line 0 too,
        # but there must be an edit at the binding column (char 11)
        cols = {e["range"]["start"]["character"] for e in pedits if e["range"]["start"]["line"] == 0}
        if 11 not in cols:
            failures.append(f"rename(param a) did not rewrite the binding at col 11 (cols {sorted(cols)})")

# documentSymbol -> helper and main present
ds = by_id(50)
dsv = (ds or {}).get("result")
if not isinstance(dsv, list):
    failures.append("documentSymbol result is not an array")
else:
    names = {s.get("name") for s in dsv}
    for want in ("helper", "main"):
        if want not in names:
            failures.append(f"documentSymbol missing '{want}' (got {sorted(names)})")
    # `x` is a local val inside main's body, not a module-level decl
    if "x" in names:
        failures.append("documentSymbol leaked the nested local 'x' as a top-level symbol")

# completion -> includes helper and main
cp = by_id(60)
cpv = (cp or {}).get("result")
items = (cpv or {}).get("items", []) if isinstance(cpv, dict) else []
labels = {it.get("label") for it in items}
for want in ("helper", "main"):
    if want not in labels:
        failures.append(f"completion missing '{want}' (got {sorted(labels)})")

if proc.returncode != 0:
    failures.append("non-zero exit code after clean shutdown")

print()
if failures:
    print("FEATURES SMOKE TEST FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("FEATURES SMOKE TEST PASSED")
