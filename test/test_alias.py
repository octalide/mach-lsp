#!/usr/bin/env python3
"""aliased-import member go-to-definition (#75) over test/fixture-alias.

the fixture binds the std string module under an alias (`use strmod:
std.types.string;`) and calls `strmod.str_len(s)`. definition / hover /
references on the member name `str_len` must reach str_len's declaration inside
dep/mach-std, exactly as a directly `use`d symbol does — a module-alias
qualified member is a resolved cross-module reference, not an unresolved field
access."""
import os

from harness import drive, req, notify, did_open, pos, by_id, file_uri, standalone, REPO

FIXTURE = os.path.join(REPO, "test", "fixture-alias")
APP = os.path.join(FIXTURE, "src", "app.mach")
URI = file_uri(APP)

# the canonical URI of str_len's declaring file; the emitted location must match
# it exactly (no '..' segments), or clients cannot correlate it with a buffer.
DEP_STRING_URI = file_uri(os.path.join(REPO, "dep", "mach-std", "src", "types", "string.mach"))


def _member_pos():
    """position of the `str_len` member token in the first code (non-comment)
    `strmod.str_len` occurrence."""
    for i, line in enumerate(open(APP).read().splitlines()):
        if line.lstrip().startswith("#"):
            continue
        c = line.find("strmod.str_len")
        if c >= 0:
            return pos(i, c + len("strmod."))
    return None


def member_scenario():
    """definition / hover / references on the aliased module's member."""
    mpos = _member_pos()
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


def run():
    """drive the aliased-import scenarios; return a list of failure strings."""
    if not os.path.exists(APP):
        return [f"fixture not found at {APP}"]
    return member_scenario()


if __name__ == "__main__":
    standalone("alias", run)
