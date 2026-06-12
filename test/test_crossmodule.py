#!/usr/bin/env python3
"""cross-module scenarios over the fixture project (test/fixture), which depends
on the vendored mach-std. definition / references / hover on a `use`d std symbol
must reach the canonical file:// URI of the decl inside dep/mach-std, while a
local symbol still resolves in the buffer. also covers project-load ordering (a
scratch file opened first must not disable the later project load; a dep source
opened first must still refuse rename via its vendoring project, at one and at
two nesting levels) and percent-encoded document URIs."""
import os

from harness import drive, req, notify, did_open, pos, by_id, file_uri, standalone, FIXTURE, REPO

APP = os.path.join(FIXTURE, "src", "app.mach")
URI = file_uri(APP)

# the canonical URI of str_len's declaring file; emitted locations must match
# it exactly (no '..' segments), or clients cannot correlate them with buffers.
DEP_STRING_URI = file_uri(os.path.join(REPO, "dep", "mach-std", "src", "types", "string.mach"))

# byte positions in app.mach (0-based):
#   line 6:  `use std.types.string.str_len;`
#   line 9:  `fun length(s: str) usize {`        -> `length` at col 4
#   line 10: `    ret str_len(s);`               -> `str_len` at col 8
#   line 16: `    ret str_len(s) + str_len(s);`  -> two more use-sites
STR_LEN = pos(10, 10)
LOCAL = pos(9, 6)

SCRATCH_URI = "file:///scratch.mach"
SCRATCH_SRC = "fun lone() i64 { ret 1; }\n"

# the two-level nesting fixture: project `outer` vendors `mid`, `mid` vendors
# `leaf` (dep/mid/dep/leaf). `outer` closes over mid.api but not leaf.
NESTED = os.path.join(REPO, "test", "fixture-nested")
NESTED_LEAF = os.path.join(NESTED, "dep", "mid", "dep", "leaf", "src", "lib.mach")
NESTED_MID_API = os.path.join(NESTED, "dep", "mid", "src", "api.mach")


def check_dep_definition(failures, msg, dv):
    """assert `dv` is a Location at str_len's decl, canonical URI equality."""
    if not dv or "uri" not in dv:
        failures.append(f"{msg} returned no Location")
        return
    if dv["uri"] != DEP_STRING_URI:
        failures.append(f"{msg} uri is not the canonical dep URI: {dv['uri']} != {DEP_STRING_URI}")


def main_scenario():
    """definition / hover / references on a cross-module symbol, plus a local one."""
    text = open(APP).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(URI, text),
        req(20, "textDocument/definition", {"textDocument": {"uri": URI}, "position": STR_LEN}),
        req(21, "textDocument/hover", {"textDocument": {"uri": URI}, "position": STR_LEN}),
        req(22, "textDocument/references",
            {"textDocument": {"uri": URI}, "position": STR_LEN,
             "context": {"includeDeclaration": True}}),
        req(23, "textDocument/definition", {"textDocument": {"uri": URI}, "position": LOCAL}),
        req(24, "textDocument/prepareRename", {"textDocument": {"uri": URI}, "position": STR_LEN}),
        req(25, "textDocument/rename",
            {"textDocument": {"uri": URI}, "position": STR_LEN, "newName": "nope"}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    check_dep_definition(failures, "definition(str_len)", (by_id(msgs, 20) or {}).get("result"))

    # hover on str_len -> renders the dependency's signature (and its doc comment)
    hv = (by_id(msgs, 21) or {}).get("result")
    if not hv or "contents" not in hv:
        failures.append("hover(str_len) returned no contents")
    else:
        hval = hv["contents"].get("value", "")
        if "str_len" not in hval:
            failures.append("hover(str_len) value does not mention 'str_len'")
        if "fun" not in hval:
            failures.append(f"hover(str_len) value does not render a signature: {hval!r}")

    # references on str_len -> the dep decl (canonical URI) plus the in-buffer use-sites
    rv = (by_id(msgs, 22) or {}).get("result")
    if not isinstance(rv, list):
        failures.append("references(str_len) result is not an array")
    else:
        if len(rv) < 2:
            failures.append(f"references(str_len) found {len(rv)}, expected >= 2 (decl + use-sites)")
        uris = [e.get("uri", "") for e in rv]
        if DEP_STRING_URI not in uris:
            failures.append(f"references(str_len) has no canonical dep decl location (got {sorted(set(uris))})")
        if not any(u == URI for u in uris):
            failures.append("references(str_len) has no in-buffer use-site")

    # definition on the local `length` -> stays in the buffer
    lv = (by_id(msgs, 23) or {}).get("result")
    if not lv or "uri" not in lv:
        failures.append("definition(length) returned no Location")
    else:
        if lv["uri"] != URI:
            failures.append(f"definition(length) left the buffer: {lv['uri']}")
        if lv["range"]["start"]["line"] != 9:
            failures.append(f"definition(length) points to line {lv['range']['start']['line']}, expected 9")

    # a dependency symbol is not the editor's to rewrite: prepareRename refuses
    # (null) and rename yields an empty WorkspaceEdit.
    prv = (by_id(msgs, 24) or {}).get("result", "missing")
    if prv is not None:
        failures.append(f"prepareRename(str_len dep) should be null, got {prv!r}")
    rnv = (by_id(msgs, 25) or {}).get("result")
    if not isinstance(rnv, dict) or rnv.get("changes") != {}:
        failures.append(f"rename(str_len dep) should be an empty WorkspaceEdit, got {rnv!r}")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def scratch_ordering_scenario():
    """a scratch file with no project root, resolved first, must not latch the
    no-project outcome: a project document opened later still loads the graph."""
    text = open(APP).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(SCRATCH_URI, SCRATCH_SRC),
        # force a resolve of the rootless scratch buffer before the project doc
        req(10, "textDocument/definition", {"textDocument": {"uri": SCRATCH_URI}, "position": pos(0, 5)}),
        did_open(URI, text),
        req(20, "textDocument/definition", {"textDocument": {"uri": URI}, "position": STR_LEN}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    # the scratch buffer's own local symbol still resolves in-buffer
    sv = (by_id(msgs, 10) or {}).get("result")
    if not sv or sv.get("uri") != SCRATCH_URI:
        failures.append(f"definition(lone) in the scratch buffer did not resolve locally: {sv}")

    check_dep_definition(failures, "definition(str_len) after scratch-first ordering",
                         (by_id(msgs, 20) or {}).get("result"))

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def percent_encoding_scenario():
    """a percent-encoded document URI must decode for project discovery: the
    fixture URI with 'app.mach' spelled '%61pp.mach' still loads the project."""
    text = open(APP).read()
    enc_uri = URI.replace("app.mach", "%61pp.mach")
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(enc_uri, text),
        req(20, "textDocument/definition", {"textDocument": {"uri": enc_uri}, "position": STR_LEN}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []
    check_dep_definition(failures, "definition(str_len) via percent-encoded URI",
                         (by_id(msgs, 20) or {}).get("result"))
    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def _strlen_decl():
    """(dep text, position of the str_len declaration name) from the vendored
    string.mach, or (None, None) when it cannot be located."""
    dep_path = os.path.join(REPO, "dep", "mach-std", "src", "types", "string.mach")
    dep_text = open(dep_path).read()
    for i, line in enumerate(dep_text.splitlines()):
        if "pub fun str_len" in line:
            return dep_text, pos(i, line.find("str_len"))
    return None, None


def dep_buffer_rename_scenario():
    """a dependency source opened directly (as after go-to-definition) is not the
    editor's to rewrite: even though its symbols resolve buffer-locally, its
    on-disk twin is a non-project module, so prepareRename refuses and rename
    yields an empty WorkspaceEdit (regression: the local-symbol path skipped the
    project-ownership check)."""
    dep_text, dep_pos = _strlen_decl()
    if dep_text is None:
        return ["str_len declaration not found in dep/mach-std"]

    app_text = open(APP).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(URI, app_text),
        # resolve the project document first so the fixture graph is loaded
        req(10, "textDocument/definition", {"textDocument": {"uri": URI}, "position": STR_LEN}),
        did_open(DEP_STRING_URI, dep_text),
        req(20, "textDocument/prepareRename",
            {"textDocument": {"uri": DEP_STRING_URI}, "position": dep_pos}),
        req(21, "textDocument/rename",
            {"textDocument": {"uri": DEP_STRING_URI}, "position": dep_pos, "newName": "nope"}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []
    check_dep_definition(failures, "definition(str_len) before the dep open",
                         (by_id(msgs, 10) or {}).get("result"))
    prv = (by_id(msgs, 20) or {}).get("result", "missing")
    if prv is not None:
        failures.append(f"prepareRename(dep buffer decl) should be null, got {prv!r}")
    rnv = (by_id(msgs, 21) or {}).get("result")
    if not isinstance(rnv, dict) or rnv.get("changes") != {}:
        failures.append(f"rename(dep buffer decl) should be an empty WorkspaceEdit, got {rnv!r}")
    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def dep_buffer_first_scenario():
    """a dependency source opened cold — before any project document — must
    still refuse rename: the vendoring project above it (this repo, which
    declares mach-std as a dep) is loaded and the document routed as its
    read-only twin, instead of the dep's own manifest dir becoming a renameable
    project root (regression: open-order dependence of the refusal)."""
    dep_text, dep_pos = _strlen_decl()
    if dep_text is None:
        return ["str_len declaration not found in dep/mach-std"]

    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(DEP_STRING_URI, dep_text),
        req(20, "textDocument/prepareRename",
            {"textDocument": {"uri": DEP_STRING_URI}, "position": dep_pos}),
        req(21, "textDocument/rename",
            {"textDocument": {"uri": DEP_STRING_URI}, "position": dep_pos, "newName": "nope"}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []
    prv = (by_id(msgs, 20) or {}).get("result", "missing")
    if prv is not None:
        failures.append(f"prepareRename(cold dep buffer decl) should be null, got {prv!r}")
    rnv = (by_id(msgs, 21) or {}).get("result")
    if not isinstance(rnv, dict) or rnv.get("changes") != {}:
        failures.append(f"rename(cold dep buffer decl) should be an empty WorkspaceEdit, got {rnv!r}")
    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def _decl_pos(path, needle):
    """(file text, position of `needle` on the first line that contains it), or
    (None, None) when the file has no such line."""
    text = open(path).read()
    for i, line in enumerate(text.splitlines()):
        if needle in line:
            return text, pos(i, line.find(needle))
    return None, None


def nested_dep_first_scenario():
    """a dependency nested two levels deep — `outer` vendors `mid`, `mid` vendors
    `leaf` — opened cold before any project document must still refuse rename: the
    leaf source routes read-only to the project that vendors it, and `mid`'s
    outer-imported module then routes to `outer` rather than entrenching `mid` as
    its own renameable project. depth- and open-order-independent refusal (#57)."""
    if not os.path.exists(NESTED):
        return [f"nested fixture not found at {NESTED}"]
    leaf_text, leaf_pos = _decl_pos(NESTED_LEAF, "b_thing")
    api_text, api_pos = _decl_pos(NESTED_MID_API, "a_thing")
    if leaf_text is None or api_text is None:
        return ["nested fixture declarations not found"]

    leaf_uri = file_uri(NESTED_LEAF)
    api_uri = file_uri(NESTED_MID_API)
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        # the innermost dependency, opened cold before any project document
        did_open(leaf_uri, leaf_text),
        req(20, "textDocument/prepareRename",
            {"textDocument": {"uri": leaf_uri}, "position": leaf_pos}),
        req(21, "textDocument/rename",
            {"textDocument": {"uri": leaf_uri}, "position": leaf_pos, "newName": "nope"}),
        # mid's outer-imported module: must route to `outer`, not to an entrenched
        # `mid`, so its declaration is read-only too
        did_open(api_uri, api_text),
        req(22, "textDocument/prepareRename",
            {"textDocument": {"uri": api_uri}, "position": api_pos}),
        req(23, "textDocument/rename",
            {"textDocument": {"uri": api_uri}, "position": api_pos, "newName": "nope"}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []
    prv = (by_id(msgs, 20) or {}).get("result", "missing")
    if prv is not None:
        failures.append(f"prepareRename(cold leaf decl, depth 2) should be null, got {prv!r}")
    rnv = (by_id(msgs, 21) or {}).get("result")
    if not isinstance(rnv, dict) or rnv.get("changes") != {}:
        failures.append(f"rename(cold leaf decl, depth 2) should be an empty WorkspaceEdit, got {rnv!r}")
    prv2 = (by_id(msgs, 22) or {}).get("result", "missing")
    if prv2 is not None:
        failures.append(f"prepareRename(mid.api decl) should be null (routed to outer), got {prv2!r}")
    rnv2 = (by_id(msgs, 23) or {}).get("result")
    if not isinstance(rnv2, dict) or rnv2.get("changes") != {}:
        failures.append(f"rename(mid.api decl) should be an empty WorkspaceEdit (routed to outer), got {rnv2!r}")
    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def run():
    """drive the cross-module scenarios; return a list of failure strings."""
    if not os.path.exists(APP):
        return [f"fixture not found at {APP}"]
    failures = []
    failures += main_scenario()
    failures += scratch_ordering_scenario()
    failures += percent_encoding_scenario()
    failures += dep_buffer_rename_scenario()
    failures += dep_buffer_first_scenario()
    failures += nested_dep_first_scenario()
    return failures


if __name__ == "__main__":
    standalone("crossmodule", run)
