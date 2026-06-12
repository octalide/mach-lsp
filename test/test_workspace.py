#!/usr/bin/env python3
"""workspace-wide references / rename scenarios over test/fixture-ws, a depless
two-module project: lib.mach declares `pub fun shared` (and `pub val LIMIT`) and
the entry app.mach imports and uses them. references must reach use-sites in
both files, and rename must rewrite the declaration, the importer's `use` path
leaf, and every use-site across both files — from either the using buffer or
the declaring buffer. a block-local shadow of a pub name must stay
buffer-local, and a pub declaration already renamed by unsaved edits must
refuse rather than emit a partial edit."""
import os

from harness import drive, req, notify, did_open, pos, by_id, file_uri, standalone, REPO

FIX = os.path.join(REPO, "test", "fixture-ws")
APP = os.path.join(FIX, "src", "app.mach")
LIB = os.path.join(FIX, "src", "lib.mach")
APP_URI = file_uri(APP)
LIB_URI = file_uri(LIB)

# byte positions (0-based):
#   app.mach line 2:  `use wsfix.lib.shared;`        -> `shared` leaf at col 14
#   app.mach line 6:  `    ret shared(1) + shared(2) + LIMIT;` -> uses at col 8 / 20
#   lib.mach line 4:  `pub fun shared(x: i64) i64 {`  -> decl name `shared` at col 8
APP_USE = pos(6, 8)
LIB_DECL = pos(4, 8)

# lib.mach with unsaved edits appended: `other` shadows the module-scope pub
# LIMIT with a block-local binding. renaming the local must not bridge to the
# pub symbol app.mach imports.
SHADOW_SRC = (
    "pub fun shared(x: i64) i64 {\n"   # line 0
    "    ret x;\n"
    "}\n"
    "\n"
    "pub val LIMIT: i64 = 10;\n"       # line 4 (the pub the shadow must not touch)
    "\n"
    "fun other() i64 {\n"
    "    val LIMIT: i64 = 3;\n"        # line 7, name at col 8
    "    ret LIMIT;\n"                 # line 8, use at col 8
    "}\n"
)

# lib.mach with the pub declaration renamed by unsaved edits: the on-disk twin
# still exports `shared`, so `shared2`'s cross-file identity is unrecoverable.
STALE_SRC = (
    "pub fun shared2(x: i64) i64 {\n"  # line 0, name at col 8
    "    ret x;\n"
    "}\n"
)


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


def local_shadow_stays_local():
    """renaming a block-local binding that shadows a module-scope pub name must
    stay buffer-local: it must not bridge to the pub symbol and rewrite the
    importer's references (regression: the bridge keyed on (name, kind) alone)."""
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(LIB_URI, SHADOW_SRC),
        req(40, "textDocument/references",
            {"textDocument": {"uri": LIB_URI}, "position": pos(7, 8),
             "context": {"includeDeclaration": True}}),
        req(41, "textDocument/rename",
            {"textDocument": {"uri": LIB_URI}, "position": pos(7, 8), "newName": "CAP"}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)
    failures = []

    rv = (by_id(msgs, 40) or {}).get("result")
    if not isinstance(rv, list):
        failures.append("references(local LIMIT) result is not an array")
    else:
        uris = {e.get("uri", "") for e in rv}
        if uris - {LIB_URI}:
            failures.append(f"references(local LIMIT) leaked across files: {sorted(uris)}")
        lines = {e["range"]["start"]["line"] for e in rv}
        if 4 in lines:
            failures.append("references(local LIMIT) included the shadowed pub declaration on line 4")

    rn = (by_id(msgs, 41) or {}).get("result")
    if not rn or "changes" not in rn:
        failures.append("rename(local LIMIT) returned no WorkspaceEdit")
    else:
        changes = rn["changes"]
        if set(changes.keys()) - {LIB_URI}:
            failures.append(f"rename(local LIMIT) edited other files: {sorted(changes.keys())}")
        lines = {e["range"]["start"]["line"] for e in changes.get(LIB_URI, [])}
        if 4 in lines:
            failures.append("rename(local LIMIT) rewrote the shadowed pub declaration on line 4")
        if not {7, 8} <= lines:
            failures.append(f"rename(local LIMIT) missed the local binding/use (lines {sorted(lines)})")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def stale_twin_refuses_rename():
    """renaming a module-scope pub declaration whose name unsaved edits already
    changed must refuse (empty edit): the stale on-disk twin cannot supply the
    cross-file identity, and a buffer-local edit would be a partial rename.
    references still answers buffer-locally."""
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(LIB_URI, STALE_SRC),
        req(50, "textDocument/rename",
            {"textDocument": {"uri": LIB_URI}, "position": pos(0, 8), "newName": "shared3"}),
        req(51, "textDocument/references",
            {"textDocument": {"uri": LIB_URI}, "position": pos(0, 8),
             "context": {"includeDeclaration": True}}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)
    failures = []

    rn = (by_id(msgs, 50) or {}).get("result")
    if not isinstance(rn, dict) or rn.get("changes") != {}:
        failures.append(f"rename(stale shared2) should be an empty WorkspaceEdit, got {rn!r}")

    rv = (by_id(msgs, 51) or {}).get("result")
    if not isinstance(rv, list) or len(rv) < 1:
        failures.append(f"references(stale shared2) should still answer buffer-locally, got {rv!r}")
    elif any(e.get("uri") != LIB_URI for e in rv):
        failures.append("references(stale shared2) left the buffer")

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
    failures += local_shadow_stays_local()
    failures += stale_twin_refuses_rename()
    return failures


if __name__ == "__main__":
    standalone("workspace", run)
