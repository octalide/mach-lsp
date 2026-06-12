#!/usr/bin/env python3
"""cross-module scenarios over the fixture project (test/fixture), which depends
on the vendored mach-std. definition / references / hover on a `use`d std symbol
must reach a file:// location inside dep/mach-std, while a local symbol still
resolves in the buffer."""
import os
import sys

from harness import drive, req, notify, did_open, pos, by_id, file_uri, FIXTURE

APP = os.path.join(FIXTURE, "src", "app.mach")
URI = file_uri(APP)

# byte positions in app.mach (0-based):
#   line 6:  `use std.types.string.str_len;`
#   line 9:  `fun length(s: str) usize {`        -> `length` at col 4
#   line 10: `    ret str_len(s);`               -> `str_len` at col 8
#   line 16: `    ret str_len(s) + str_len(s);`  -> two more use-sites
STR_LEN = pos(10, 10)
LOCAL = pos(9, 6)


def run():
    """drive the cross-module scenarios; return a list of failure strings."""
    if not os.path.exists(APP):
        return [f"fixture not found at {APP}"]
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
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    # definition on str_len -> Location inside dep/mach-std's string module
    dv = (by_id(msgs, 20) or {}).get("result")
    if not dv or "uri" not in dv:
        failures.append("definition(str_len) returned no Location")
    else:
        if "dep/mach-std" not in dv["uri"]:
            failures.append(f"definition(str_len) uri is not in dep/mach-std: {dv['uri']}")
        if not dv["uri"].startswith("file://"):
            failures.append(f"definition(str_len) uri is not a file:// URI: {dv['uri']}")
        if "string.mach" not in dv["uri"]:
            failures.append(f"definition(str_len) uri does not name string.mach: {dv['uri']}")

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

    # references on str_len -> the dep decl plus the in-buffer use-sites
    rv = (by_id(msgs, 22) or {}).get("result")
    if not isinstance(rv, list):
        failures.append("references(str_len) result is not an array")
    else:
        if len(rv) < 2:
            failures.append(f"references(str_len) found {len(rv)}, expected >= 2 (decl + use-sites)")
        uris = [e.get("uri", "") for e in rv]
        if not any("dep/mach-std" in u for u in uris):
            failures.append("references(str_len) has no location in dep/mach-std (the decl)")
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

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")

    return failures


if __name__ == "__main__":
    fails = run()
    for f in fails:
        print("  -", f)
    print("crossmodule:", "FAILED" if fails else "PASSED")
    sys.exit(1 if fails else 0)
