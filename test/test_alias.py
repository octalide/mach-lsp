#!/usr/bin/env python3
"""aliased-import member go-to-definition (#75) over test/fixture-alias.

the fixture binds the std string and bool modules under aliases (`use strmod:
std.types.string;`, `use bln: std.types.bool;`) and references their members.
go-to-definition / hover / references on a qualified member must reach the
member's declaration inside dep/mach-std, exactly as a directly `use`d symbol
does — a module-alias qualified member is a resolved cross-module reference, not
an unresolved field access. the three member kinds exercise distinct resolution
paths: a function member (expr_resolved), a type member (type_resolved), and a
value member."""
import os

from harness import drive, req, notify, did_open, pos, by_id, file_uri, standalone, REPO

FIXTURE = os.path.join(REPO, "test", "fixture-alias")
APP = os.path.join(FIXTURE, "src", "app.mach")
URI = file_uri(APP)

# canonical URIs of the declaring files; emitted locations must match exactly
# (no '..' segments), or clients cannot correlate them with buffers.
DEP_STRING_URI = file_uri(os.path.join(REPO, "dep", "mach-std", "src", "types", "string.mach"))
DEP_BOOL_URI = file_uri(os.path.join(REPO, "dep", "mach-std", "src", "types", "bool.mach"))


def _member_pos(qualified):
    """position of the member token in the first code (non-comment) occurrence of
    `qualified` (an `alias.member` spelling), or None."""
    alias = qualified.split(".", 1)[0]
    for i, line in enumerate(open(APP).read().splitlines()):
        if line.lstrip().startswith("#"):
            continue
        c = line.find(qualified)
        if c >= 0:
            return pos(i, c + len(alias) + 1)
    return None


def member_scenario():
    """definition / hover / references on the aliased module's function member."""
    mpos = _member_pos("strmod.str_len")
    if mpos is None:
        return ["strmod.str_len call not found in fixture-alias app.mach"]
    text = open(APP).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(URI, text),
        req(20, "textDocument/definition", {"textDocument": {"uri": URI}, "position": mpos}),
        req(21, "textDocument/hover", {"textDocument": {"uri": URI}, "position": mpos}),
        req(22, "textDocument/references",
            {"textDocument": {"uri": URI}, "position": mpos,
             "context": {"includeDeclaration": True}}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    dv = (by_id(msgs, 20) or {}).get("result")
    if not dv or "uri" not in dv:
        failures.append("definition(strmod.str_len) returned no Location")
    elif dv["uri"] != DEP_STRING_URI:
        failures.append(f"definition(strmod.str_len) uri is not the dep decl: {dv['uri']} != {DEP_STRING_URI}")

    hv = (by_id(msgs, 21) or {}).get("result")
    if not hv or "contents" not in hv:
        failures.append("hover(strmod.str_len) returned no contents")
    else:
        hval = hv["contents"].get("value", "")
        if "str_len" not in hval:
            failures.append("hover(strmod.str_len) value does not mention 'str_len'")
        if "fun" not in hval:
            failures.append(f"hover(strmod.str_len) value does not render a signature: {hval!r}")

    rv = (by_id(msgs, 22) or {}).get("result")
    if not isinstance(rv, list):
        failures.append("references(strmod.str_len) result is not an array")
    else:
        uris = [e.get("uri", "") for e in rv]
        if DEP_STRING_URI not in uris:
            failures.append(f"references(strmod.str_len) has no canonical dep decl location (got {sorted(set(uris))})")
        if not any(u == URI for u in uris):
            failures.append("references(strmod.str_len) has no in-buffer use-site")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def type_value_scenario():
    """definition on a qualified type member (`strmod.str`, the type_resolved
    path) and a qualified value member (`bln.true`) — distinct from the function
    member's expr_resolved path."""
    tpos = _member_pos("strmod.str)")  # the `str` type in `s: strmod.str)`
    vpos = _member_pos("bln.true")
    if tpos is None:
        return ["strmod.str type member not found in fixture-alias app.mach"]
    if vpos is None:
        return ["bln.true value member not found in fixture-alias app.mach"]
    text = open(APP).read()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(URI, text),
        req(30, "textDocument/definition", {"textDocument": {"uri": URI}, "position": tpos}),
        req(31, "textDocument/definition", {"textDocument": {"uri": URI}, "position": vpos}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    tv = (by_id(msgs, 30) or {}).get("result")
    if not tv or "uri" not in tv:
        failures.append("definition(strmod.str type member) returned no Location")
    elif tv["uri"] != DEP_STRING_URI:
        failures.append(f"definition(strmod.str type member) uri is not the dep decl: {tv['uri']} != {DEP_STRING_URI}")

    vv = (by_id(msgs, 31) or {}).get("result")
    if not vv or "uri" not in vv:
        failures.append("definition(bln.true value member) returned no Location")
    elif vv["uri"] != DEP_BOOL_URI:
        failures.append(f"definition(bln.true value member) uri is not the dep decl: {vv['uri']} != {DEP_BOOL_URI}")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def run():
    """drive the aliased-import scenarios; return a list of failure strings."""
    if not os.path.exists(APP):
        return [f"fixture not found at {APP}"]
    return member_scenario() + type_value_scenario()


if __name__ == "__main__":
    standalone("alias", run)
