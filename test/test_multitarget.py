#!/usr/bin/env python3
"""multi-target union coverage (#58): a module imported only under a non-default
target's `$if` gate is still in the workspace graph, so references reach its
use-sites. fixture-multitarget's `winonly` is imported by `main` only under the
windows target; with `build_project_union` the linux-host server still sees
winonly's use of `common.shared`, which a default-target-only build would omit."""
import os

from harness import LiveServer, req, notify, did_open, pos, file_uri, standalone, REPO

MT = os.path.join(REPO, "test", "fixture-multitarget")
COMMON = os.path.join(MT, "src", "common.mach")

# common.mach line 4: `pub fun shared() i64 {` — decl `shared` at col 8.
DECL = pos(4, 8)


def run():
    """drive the multi-target union scenario; return a list of failure strings."""
    if not os.path.exists(COMMON):
        return [f"fixture-multitarget not found at {MT}"]
    common_uri = file_uri(COMMON)
    failures = []
    srv = LiveServer()
    try:
        srv.send(req(1, "initialize", {"capabilities": {}}))
        srv.recv_id(1)
        srv.send(notify("initialized"))
        srv.send(did_open(common_uri, open(COMMON).read()))

        srv.send(req(20, "textDocument/references",
                     {"textDocument": {"uri": common_uri}, "position": DECL,
                      "context": {"includeDeclaration": True}}))
        res = (srv.recv_id(20) or {}).get("result")
        if not isinstance(res, list):
            failures.append("references(shared) result is not an array")
        else:
            uris = {r.get("uri", "") for r in res}
            if not any(u.endswith("winonly.mach") for u in uris):
                failures.append(
                    "references(shared) missing the windows-only use-site "
                    f"(winonly.mach); got {sorted(uris)} — the union did not "
                    "cover the non-default target")
            if not any(u.endswith("main.mach") for u in uris):
                failures.append(
                    f"references(shared) missing the main.mach use-site; got {sorted(uris)}")

        srv.send(req(2, "shutdown", None))
        srv.send(notify("exit"))
    finally:
        srv.close()
    return failures


if __name__ == "__main__":
    standalone("multitarget", run)
