#!/usr/bin/env python3
# smoke test: drive the mach-lsp server over stdio with framed JSON-RPC and
# assert publishDiagnostics behaviour for a broken buffer and a clean buffer.
import json
import subprocess
import sys

BIN = "out/linux/bin/mach-lsp"


def frame(obj):
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def read_messages(data):
    msgs = []
    i = 0
    while i < len(data):
        # parse one header block
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


BROKEN = "fun g(a: i64 { ret a ` ; }\n"
CLEAN = "fun f(a: i64) i64 { ret a; }\n"

requests = b"".join([
    frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}}),
    frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}),
    frame({"jsonrpc": "2.0", "method": "textDocument/didOpen",
           "params": {"textDocument": {"uri": "file:///broken.mach", "languageId": "mach",
                                       "version": 1, "text": BROKEN}}}),
    frame({"jsonrpc": "2.0", "method": "textDocument/didOpen",
           "params": {"textDocument": {"uri": "file:///clean.mach", "languageId": "mach",
                                       "version": 1, "text": CLEAN}}}),
    # edit the broken file to a clean one: diagnostics should clear.
    frame({"jsonrpc": "2.0", "method": "textDocument/didChange",
           "params": {"textDocument": {"uri": "file:///broken.mach", "version": 2},
                      "contentChanges": [{"text": CLEAN}]}}),
    # close the clean file: diagnostics should clear (empty publish).
    frame({"jsonrpc": "2.0", "method": "textDocument/didClose",
           "params": {"textDocument": {"uri": "file:///clean.mach"}}}),
    frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None}),
    frame({"jsonrpc": "2.0", "method": "exit", "params": None}),
])

proc = subprocess.run([BIN], input=requests, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
msgs = read_messages(proc.stdout)

print("=== server exit code:", proc.returncode)
print("=== messages received:", len(msgs))
for m in msgs:
    print(json.dumps(m))

failures = []

# initialize response
init = next((m for m in msgs if m.get("id") == 1), None)
if not init or "result" not in init or "capabilities" not in init["result"]:
    failures.append("missing/invalid initialize result")

# publishDiagnostics: collect in order; broken file's first publish has errors,
# its didChange publish is empty; clean file is always empty.
pubs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
broken_pubs = [m for m in pubs if m["params"]["uri"] == "file:///broken.mach"]
clean_pubs = [m for m in pubs if m["params"]["uri"] == "file:///clean.mach"]

if not broken_pubs:
    failures.append("no publishDiagnostics for broken file")
else:
    diags = broken_pubs[0]["params"]["diagnostics"]
    if not diags:
        failures.append("broken file produced 0 diagnostics")
    else:
        d0 = diags[0]
        if "range" not in d0 or "start" not in d0["range"] or "end" not in d0["range"]:
            failures.append("diagnostic missing range")
        if not d0.get("message"):
            failures.append("diagnostic missing message")
        if "severity" not in d0:
            failures.append("diagnostic missing severity")
    # didChange to clean text should clear diagnostics for the broken file
    if len(broken_pubs) < 2:
        failures.append("no didChange publishDiagnostics for broken file")
    elif broken_pubs[-1]["params"]["diagnostics"]:
        failures.append("didChange to clean text did not clear diagnostics")

if not clean_pubs:
    failures.append("no publishDiagnostics for clean file")
elif clean_pubs[0]["params"]["diagnostics"]:
    failures.append("clean file produced non-empty diagnostics")

# shutdown response
sh = next((m for m in msgs if m.get("id") == 2), None)
if not sh or "result" not in sh:
    failures.append("missing shutdown result")

if proc.returncode != 0:
    failures.append("non-zero exit code after clean shutdown")

print()
if failures:
    print("SMOKE TEST FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("SMOKE TEST PASSED")
