#!/usr/bin/env python3
"""diagnostics publish never triggers a project load (#96).

#78 routed publish through project.root_for, which loads the project on first
use — putting the full ~tens-of-seconds build on the didOpen/didChange hot path
and freezing the single-threaded server. the fix decouples them: publish uses a
load-free lookup, so an open buffer publishes parse-only until a feature request
loads the project, after which the server re-publishes dep-aware.

this asserts the decoupling by behavior, not timing: the out-of-closure import
diagnostic (a dep-aware, name-resolution result that only exists once the
project's dep closure is known) must be ABSENT from the buffer's publish on
didOpen — proving publish did not load the project — and must APPEAR only after
a definition request triggers the load and the re-publish."""
import os

from harness import drive, req, notify, did_open, pos, by_id, file_uri, standalone, REPO

FIXTURE = os.path.join(REPO, "test", "fixture-outofclosure")
OOC = os.path.join(FIXTURE, "src", "outofclosure.mach")
APP = os.path.join(FIXTURE, "src", "app.mach")
OOC_URI = file_uri(OOC)
APP_URI = file_uri(APP)


def _pubs_for(msgs, uri):
    """every publishDiagnostics diagnostics-array for `uri`, in order."""
    return [m["params"]["diagnostics"] for m in msgs
            if m.get("method") == "textDocument/publishDiagnostics"
            and m["params"]["uri"] == uri]


def _has_depset(diags):
    """whether any diagnostic names the missing dep set (the dep-aware signal)."""
    return any("dep set" in d.get("message", "") for d in diags)


def run():
    """drive open-then-load and assert publish stays off the load path."""
    if not os.path.exists(OOC) or not os.path.exists(APP):
        return [f"fixture not found under {FIXTURE}"]

    ooc_text = open(OOC).read()
    app_text = open(APP).read()

    # open both buffers, then issue a definition that triggers the lazy load.
    # the definition's id (2) lets us split publishes into pre-load (on open)
    # and post-load (re-published by the server after the load).
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(OOC_URI, ooc_text),
        did_open(APP_URI, app_text),
        req(2, "textDocument/definition",
            {"textDocument": {"uri": APP_URI}, "position": pos(8, 11)}),
        req(3, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    # the out-of-closure buffer must publish on open (the editor sees diagnostics
    # immediately) and that first publish must be parse-only — no dep-set
    # diagnostic, proving publish did not load the project's dep closure.
    ooc_pubs = _pubs_for(msgs, OOC_URI)
    if not ooc_pubs:
        failures.append("no publishDiagnostics for the out-of-closure buffer on open")
    else:
        if _has_depset(ooc_pubs[0]):
            failures.append(
                "first publish carried a dep-aware diagnostic — publish loaded the "
                "project on the hot path (the #96 regression)")
        # after the definition loads the project, the server must re-publish the
        # buffer with the dep-aware out-of-closure diagnostic.
        if not _has_depset(ooc_pubs[-1]):
            failures.append(
                "out-of-closure diagnostic never appeared after the load — "
                "re-publish-after-load did not fire")

    # the definition request must still be answered (the load happened on the
    # feature path, as before #78), so the server stayed responsive.
    if by_id(msgs, 2) is None:
        failures.append("no response to the definition request")

    sh = by_id(msgs, 3)
    if not sh or "result" not in sh:
        failures.append("missing shutdown result")
    if code != 0:
        failures.append("non-zero exit code after clean shutdown")

    return failures


if __name__ == "__main__":
    standalone("hotpath", run)
