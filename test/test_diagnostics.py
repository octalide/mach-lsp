#!/usr/bin/env python3
"""publishDiagnostics scenarios: a broken buffer reports diagnostics with
ranges; editing it clean clears them; a clean buffer is always empty; closing
clears."""
from harness import drive, req, notify, did_open, by_id, standalone

BROKEN = "fun g(a: i64 { ret a ` ; }\n"
CLEAN = "fun f(a: i64) i64 { ret a; }\n"
BROKEN_URI = "file:///broken.mach"
CLEAN_URI = "file:///clean.mach"


def run():
    """drive the diagnostics scenarios; return a list of failure strings."""
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(BROKEN_URI, BROKEN),
        did_open(CLEAN_URI, CLEAN),
        notify("textDocument/didChange",
               {"textDocument": {"uri": BROKEN_URI, "version": 2},
                "contentChanges": [{"text": CLEAN}]}),
        notify("textDocument/didClose", {"textDocument": {"uri": CLEAN_URI}}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    init = by_id(msgs, 1)
    if not init or "result" not in init or "capabilities" not in init["result"]:
        failures.append("missing/invalid initialize result")

    pubs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    broken = [m for m in pubs if m["params"]["uri"] == BROKEN_URI]
    clean = [m for m in pubs if m["params"]["uri"] == CLEAN_URI]

    if not broken:
        failures.append("no publishDiagnostics for broken file")
    else:
        diags = broken[0]["params"]["diagnostics"]
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
        if len(broken) < 2:
            failures.append("no didChange publishDiagnostics for broken file")
        elif broken[-1]["params"]["diagnostics"]:
            failures.append("didChange to clean text did not clear diagnostics")

    if not clean:
        failures.append("no publishDiagnostics for clean file")
    elif clean[0]["params"]["diagnostics"]:
        failures.append("clean file produced non-empty diagnostics")

    sh = by_id(msgs, 2)
    if not sh or "result" not in sh:
        failures.append("missing shutdown result")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")

    return failures


if __name__ == "__main__":
    standalone("diagnostics", run)
