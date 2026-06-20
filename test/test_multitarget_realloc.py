#!/usr/bin/env python3
"""multi-target union realloc regression (#91 / mach#1540): loading a real
multi-target project drove the compiler's `walk_comptime_if_union` through a
use-after-realloc and segfaulted the server. the crash needed all three: union
mode (multiple `[target.*]`), 2+ taken `$if` branches diverging on OS *and* arch,
and an earlier taken branch importing enough modules to cross the compiler's
INITIAL_MODULE_CAP (16) and realloc `p.modules` mid-walk.

fixture-multitarget-realloc reproduces it: three targets (linux x86_64, windows
x86_64, linux aarch64), a windows branch importing 24 leaf modules (the realloc)
and a linux branch importing one more (`lx`, deref'd post-realloc). opening
main.mach triggers the union build; pre-fix mach this segfaults the server. the
test asserts the server survives the load and that a cross-module request reaches
`lx`, which the union loads only via the linux branch."""
import os

from harness import LiveServer, req, notify, did_open, pos, file_uri, standalone, REPO

RT = os.path.join(REPO, "test", "fixture-multitarget-realloc")
MAIN = os.path.join(RT, "src", "main.mach")
LX = os.path.join(RT, "src", "lx.mach")

# lx.mach: `pub fun lxval()` is the 4th line (3 comment lines above it), so the
# 0-based decl `lxval` is at line 3, col 8.
LXVAL = pos(3, 8)


def run():
    """drive the realloc union scenario; return a list of failure strings."""
    if not os.path.exists(MAIN):
        return [f"fixture-multitarget-realloc not found at {RT}"]
    main_uri = file_uri(MAIN)
    lx_uri = file_uri(LX)
    root_uri = file_uri(RT)
    failures = []
    srv = LiveServer()
    try:
        srv.send(req(1, "initialize",
                     {"rootUri": root_uri,
                      "workspaceFolders": [{"uri": root_uri, "name": "rtfix"}],
                      "capabilities": {}}))
        if srv.recv_id(1) is None:
            return ["server did not answer initialize (crashed during startup?)"]
        srv.send(notify("initialized"))

        # opening both documents; the union build is lazy, so the realloc walk
        # fires on the first feature request below, not on didOpen.
        srv.send(did_open(main_uri, open(MAIN).read()))
        srv.send(did_open(lx_uri, open(LX).read()))

        # references on lx's decl drives the union load (lx is reachable only via
        # the linux branch). pre-fix the walk segfaults here mid-request, so no
        # response arrives; a sane array proves the union loaded lx and survived.
        srv.send(req(20, "textDocument/references",
                     {"textDocument": {"uri": lx_uri}, "position": LXVAL,
                      "context": {"includeDeclaration": True}}))
        res = srv.recv_id(20)
        if res is None:
            # the server died during the union load — don't send into the dead
            # pipe; close() below surfaces the signal.
            failures.append(
                "no response to references(lxval) — the server died during the "
                "multi-target union load (the #91/mach#1540 realloc crash)")
            return failures
        result = res.get("result")
        if not isinstance(result, list):
            failures.append("references(lxval) result is not an array")
        elif not any(r.get("uri", "").endswith("lx.mach") for r in result):
            failures.append(
                "references(lxval) missing lx.mach's own decl — the union did "
                f"not load the linux-branch leaf; got {sorted(r.get('uri','') for r in result)}")

        # a second request the server can only answer if it is still alive after
        # the load — the liveness assertion the bare didOpen cannot make.
        srv.send(req(21, "textDocument/hover",
                     {"textDocument": {"uri": lx_uri}, "position": LXVAL}))
        if srv.recv_id(21) is None:
            failures.append(
                "no response to a follow-up request — the server is not alive "
                "after the multi-target union load")
            return failures

        srv.send(req(2, "shutdown", None))
        srv.send(notify("exit"))
    finally:
        code = srv.close()
        # a clean shutdown exits 0; a signal kill (SIGSEGV) surfaces as a negative
        # return code, so flag it even if a response slipped through.
        if code is not None and code < 0:
            failures.append(f"server exited on signal {-code} (SIGSEGV=11 is the #91 crash)")
    return failures


if __name__ == "__main__":
    standalone("multitarget-realloc", run)
