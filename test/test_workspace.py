#!/usr/bin/env python3
"""workspace-wide references / rename scenarios over test/fixture-ws, a depless
two-module project: lib.mach declares `pub fun shared` and the entry app.mach
imports and uses it. references must reach use-sites in both files, and rename
must rewrite the declaration, the importer's `use` path leaf, and every use-site
across both files — from either the using buffer or the declaring buffer."""
import os

from harness import drive, req, notify, did_open, pos, by_id, file_uri, standalone, REPO

FIX = os.path.join(REPO, "test", "fixture-ws")
APP = os.path.join(FIX, "src", "app.mach")
LIB = os.path.join(FIX, "src", "lib.mach")
APP_URI = file_uri(APP)
LIB_URI = file_uri(LIB)

# byte positions (0-based):
#   app.mach line 2:  `use wsfix.lib.shared;`        -> `shared` leaf at col 14
#   app.mach line 5:  `    ret shared(1) + shared(2);` -> uses at col 8 and col 20
#   lib.mach line 4:  `pub fun shared(x: i64) i64 {`  -> decl name `shared` at col 8
APP_USE = pos(5, 8)
LIB_DECL = pos(4, 8)


def from_using_buffer():
    """references / rename invoked on a use-site in the importing buffer reach
    both files (cross-module symbol declared in a sibling project module)."""
    text = open(APP).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(APP_URI, text),
        req(20, "textDocument/references",
            {"textDocument": {"uri": APP_URI}, "position": APP_USE,
             "context": {"includeDeclaration": True}}),
        req(21, "textDocument/rename",
            {"textDocument": {"uri": APP_URI}, "position": APP_USE, "newName": "renamed"}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)
    failures = []

    rv = (by_id(msgs, 20) or {}).get("result")
    if not isinstance(rv, list):
        failures.append("references(shared) result is not an array")
    else:
        uris = [e.get("uri", "") for e in rv]
        if APP_URI not in uris:
            failures.append("references(shared) missing the importer's use-sites")
        if LIB_URI not in uris:
            failures.append(f"references(shared) missing the cross-file declaration in lib.mach (got {sorted(set(uris))})")
        if len(rv) < 4:
            failures.append(f"references(shared) found {len(rv)}, expected >= 4 (decl + use leaf + 2 uses)")

    rn = (by_id(msgs, 21) or {}).get("result")
    if not rn or "changes" not in rn:
        failures.append("rename(shared) returned no WorkspaceEdit")
    else:
        changes = rn["changes"]
        if APP_URI not in changes:
            failures.append("rename(shared) did not edit the importing file")
        if LIB_URI not in changes:
            failures.append(f"rename(shared) did not edit the declaring file (changed {sorted(changes.keys())})")
        all_edits = [e for edits in changes.values() for e in edits]
        if any(e.get("newText") != "renamed" for e in all_edits):
            failures.append("rename(shared) edit newText is not 'renamed'")
        # the declaration in lib.mach is rewritten at its name span (line 4)
        lib_lines = {e["range"]["start"]["line"] for e in changes.get(LIB_URI, [])}
        if 4 not in lib_lines:
            failures.append(f"rename(shared) did not rewrite the lib.mach declaration on line 4 (lines {sorted(lib_lines)})")
        # the importer's `use` path leaf (line 2) is rewritten so it keeps compiling
        app_lines = {e["range"]["start"]["line"] for e in changes.get(APP_URI, [])}
        if 2 not in app_lines:
            failures.append(f"rename(shared) did not rewrite the app.mach `use` path leaf on line 2 (lines {sorted(app_lines)})")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def from_declaring_buffer():
    """rename invoked on the declaration itself reaches the importer; prepareRename
    offers the name range for the project-owned symbol."""
    text = open(LIB).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(LIB_URI, text),
        req(30, "textDocument/prepareRename", {"textDocument": {"uri": LIB_URI}, "position": LIB_DECL}),
        req(31, "textDocument/rename",
            {"textDocument": {"uri": LIB_URI}, "position": LIB_DECL, "newName": "passthru"}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)
    failures = []

    prv = (by_id(msgs, 30) or {}).get("result")
    if not prv or "start" not in prv:
        failures.append("prepareRename(shared decl) returned no range")

    rn = (by_id(msgs, 31) or {}).get("result")
    if not rn or "changes" not in rn:
        failures.append("rename(shared decl) returned no WorkspaceEdit")
    else:
        changes = rn["changes"]
        if LIB_URI not in changes or APP_URI not in changes:
            failures.append(f"rename(shared decl) is not cross-file (changed {sorted(changes.keys())})")
        all_edits = [e for edits in changes.values() for e in edits]
        if any(e.get("newText") != "passthru" for e in all_edits):
            failures.append("rename(shared decl) edit newText is not 'passthru'")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def run():
    """drive the workspace cross-file scenarios; return a list of failure strings."""
    if not os.path.exists(APP):
        return [f"fixture not found at {APP}"]
    failures = []
    failures += from_using_buffer()
    failures += from_declaring_buffer()
    return failures


if __name__ == "__main__":
    standalone("workspace", run)
