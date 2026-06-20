#!/usr/bin/env python3
"""multi-artifact union coverage (#84): a project declaring more than one artifact
(here [bin.app], [lib.core], [bin.tool]) loads cleanly — no "multiple artifacts"
load failure — and the union covers every artifact's closure, not just the
primary's. fixture-multibinary's `toolonly` is reachable only from the secondary
`tool` binary's entry; `app` (the primary artifact) never reaches it. with
`build_project_union` the server still sees toolonly's use of `core.shared`, so
references on `shared` reach a use-site a single-artifact load would omit."""
import os

from harness import LiveServer, req, notify, did_open, pos, file_uri, standalone, REPO

MB = os.path.join(REPO, "test", "fixture-multibinary")
CORE = os.path.join(MB, "src", "core.mach")

# core.mach line 5 (0-based 4): `pub fun shared() i64 {` — decl `shared` at col 8.
DECL = pos(4, 8)


def run():
    """drive the multi-artifact union scenario; return a list of failure strings."""
    if not os.path.exists(CORE):
        return [f"fixture-multibinary not found at {MB}"]
    core_uri = file_uri(CORE)
    failures = []
    srv = LiveServer()
    try:
        srv.send(req(1, "initialize", {"capabilities": {}}))
        srv.recv_id(1)
        srv.send(notify("initialized"))
        srv.send(did_open(core_uri, open(CORE).read()))

        srv.send(req(20, "textDocument/references",
                     {"textDocument": {"uri": core_uri}, "position": DECL,
                      "context": {"includeDeclaration": True}}))
        res = (srv.recv_id(20) or {}).get("result")
        if not isinstance(res, list):
            failures.append("references(shared) result is not an array — the "
                            "multi-artifact project failed to load")
        else:
            uris = {r.get("uri", "") for r in res}
            if not any(u.endswith("toolonly.mach") for u in uris):
                failures.append(
                    "references(shared) missing the non-primary-artifact-only "
                    f"use-site (toolonly.mach); got {sorted(uris)} — the union "
                    "did not cover the secondary `tool` artifact's closure")
            if not any(u.endswith("app.mach") for u in uris):
                failures.append(
                    f"references(shared) missing the primary app.mach use-site; "
                    f"got {sorted(uris)}")

        srv.send(req(2, "shutdown", None))
        srv.send(notify("exit"))
    finally:
        srv.close()
    return failures


if __name__ == "__main__":
    standalone("multibinary", run)
