#!/usr/bin/env python3
"""out-of-closure import diagnostics (#78).

a project whose entry imports only std.types.size never loads std.types.option
into its dep closure. opening a buffer under that root which imports
std.types.option must now PUBLISH a diagnostic ("imported module is not in the
dep set") instead of resolving silently to nothing — keeping the published
diagnostics consistent with go-to-definition's inability to bind the symbol. a
control buffer importing only the in-closure std.types.size must stay clean (no
false positives from the dep-aware diagnostics pass)."""
import os

from harness import drive, req, notify, did_open, by_id, file_uri, standalone, REPO

FIXTURE = os.path.join(REPO, "test", "fixture-outofclosure")
OOC = os.path.join(FIXTURE, "src", "outofclosure.mach")
APP = os.path.join(FIXTURE, "src", "app.mach")
OOC_URI = file_uri(OOC)
APP_URI = file_uri(APP)


def _diags_for(msgs, uri):
    """the diagnostics array of the last publishDiagnostics for `uri`, or None."""
    pubs = [m for m in msgs
            if m.get("method") == "textDocument/publishDiagnostics"
            and m["params"]["uri"] == uri]
    if not pubs:
        return None
    return pubs[-1]["params"]["diagnostics"]


def run():
    """drive the out-of-closure diagnostics scenario; return failure strings."""
    if not os.path.exists(OOC) or not os.path.exists(APP):
        return [f"fixture not found under {FIXTURE}"]

    ooc_text = open(OOC).read()
    app_text = open(APP).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(OOC_URI, ooc_text),
        did_open(APP_URI, app_text),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    init = by_id(msgs, 1)
    if not init or "result" not in init or "capabilities" not in init["result"]:
        failures.append("missing/invalid initialize result")

    # the out-of-closure import must surface a diagnostic, not resolve silently.
    ooc = _diags_for(msgs, OOC_URI)
    if ooc is None:
        failures.append("no publishDiagnostics for the out-of-closure buffer")
    elif not ooc:
        failures.append("out-of-closure import produced 0 diagnostics (the #78 silence)")
    else:
        msgs_text = " ".join(d.get("message", "") for d in ooc)
        if "dep set" not in msgs_text:
            failures.append(
                f"out-of-closure diagnostics do not name the missing dep set: {msgs_text!r}")
        d0 = ooc[0]
        if "range" not in d0 or "start" not in d0["range"] or "end" not in d0["range"]:
            failures.append("out-of-closure diagnostic missing range")
        if "severity" not in d0:
            failures.append("out-of-closure diagnostic missing severity")

    # the in-closure control must stay clean: no false positives.
    app = _diags_for(msgs, APP_URI)
    if app is None:
        failures.append("no publishDiagnostics for the in-closure control buffer")
    elif app:
        failures.append(f"in-closure control buffer produced diagnostics: {app!r}")

    sh = by_id(msgs, 2)
    if not sh or "result" not in sh:
        failures.append("missing shutdown result")
    if code != 0:
        failures.append("non-zero exit code after clean shutdown")

    return failures


if __name__ == "__main__":
    standalone("outofclosure", run)
