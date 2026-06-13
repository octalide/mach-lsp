#!/usr/bin/env python3
"""dep-graph invalidation scenarios: a project root's loaded graph is a snapshot,
so editing one of its sources on disk must not keep serving stale positions. each
scenario copies test/fixture-ws to a scratch dir, resolves a cross-file symbol
(its declaration lives in lib.mach, reached from app.mach's `use`), then shifts
that declaration down on disk and confirms the next resolve serves the new line —
once via a `workspace/didChangeWatchedFiles` notification (the primary trigger),
once via the manifest-mtime fallback for clients that do not deliver watch
notifications. a third scenario covers failed-load recovery: a broken manifest
must not pin the failure for the session — fixing it on disk retries the load."""
import os
import shutil
import tempfile

from harness import LiveServer, req, notify, did_open, pos, file_uri, standalone, REPO

WS = os.path.join(REPO, "test", "fixture-ws")

# fixture-ws/src/app.mach line 6: `ret shared(1) + shared(2) + LIMIT;` use at col 8.
# fixture-ws/src/lib.mach  line 4: `pub fun shared(x: i64) i64 {` decl at col 8.
APP_USE = pos(6, 8)
DECL_LINE = 4
SHIFT = 3


def _scratch_project():
    """copy fixture-ws into a fresh temp dir; return (dir, app path, lib path)."""
    tmp = tempfile.mkdtemp(prefix="mls-inval-")
    dst = os.path.join(tmp, "ws")
    shutil.copytree(WS, dst)
    return dst, os.path.join(dst, "src", "app.mach"), os.path.join(dst, "src", "lib.mach")


def _definition_line(srv, app_uri, rid):
    """request definition on the `shared` use-site and return (uri, line)."""
    srv.send(req(rid, "textDocument/definition",
                 {"textDocument": {"uri": app_uri}, "position": APP_USE}))
    res = (srv.recv_id(rid) or {}).get("result")
    if not res or "uri" not in res:
        return None, None
    return res["uri"], res.get("range", {}).get("start", {}).get("line")


def _shift_decl(lib_path):
    """prepend blank lines to lib.mach, moving the `shared` decl down by SHIFT."""
    text = open(lib_path).read()
    with open(lib_path, "w") as f:
        f.write("\n" * SHIFT + text)


def watched_files_trigger():
    """edit a dep source on disk and fire didChangeWatchedFiles: the next
    definition must serve the shifted declaration line, proving the root reloaded."""
    proj, app, lib = _scratch_project()
    app_uri = file_uri(app)
    lib_uri = file_uri(lib)
    failures = []
    srv = LiveServer()
    try:
        srv.send(req(1, "initialize", {"capabilities": {}}))
        srv.recv_id(1)
        srv.send(notify("initialized"))
        srv.send(did_open(app_uri, open(app).read()))

        uri1, line1 = _definition_line(srv, app_uri, 20)
        if uri1 != lib_uri or line1 != DECL_LINE:
            failures.append(f"definition(shared) before edit: uri {uri1} line {line1}, expected {lib_uri} line {DECL_LINE}")

        _shift_decl(lib)
        srv.send(notify("workspace/didChangeWatchedFiles",
                        {"changes": [{"uri": lib_uri, "type": 2}]}))

        uri2, line2 = _definition_line(srv, app_uri, 21)
        if uri2 != lib_uri or line2 != DECL_LINE + SHIFT:
            failures.append(f"definition(shared) after didChangeWatchedFiles: uri {uri2} line {line2}, expected {lib_uri} line {DECL_LINE + SHIFT}")

        srv.send(req(2, "shutdown", None))
        srv.send(notify("exit"))
    finally:
        srv.close()
        shutil.rmtree(proj, ignore_errors=True)
    return failures


def mtime_fallback_trigger():
    """without any watch notification, a manifest mtime bump must reload the
    graph (the conservative fallback), picking up a concurrent dep-source edit."""
    proj, app, lib = _scratch_project()
    app_uri = file_uri(app)
    lib_uri = file_uri(lib)
    manifest = os.path.join(proj, "mach.toml")
    failures = []
    srv = LiveServer()
    try:
        srv.send(req(1, "initialize", {"capabilities": {}}))
        srv.recv_id(1)
        srv.send(notify("initialized"))
        srv.send(did_open(app_uri, open(app).read()))

        uri1, line1 = _definition_line(srv, app_uri, 20)
        if uri1 != lib_uri or line1 != DECL_LINE:
            failures.append(f"definition(shared) before edit: uri {uri1} line {line1}, expected {lib_uri} line {DECL_LINE}")

        _shift_decl(lib)
        # bump the manifest mtime well past the load-time snapshot (mtime is
        # second-granular, so a same-second rewrite would not register).
        future = os.path.getmtime(manifest) + 1000
        os.utime(manifest, (future, future))

        uri2, line2 = _definition_line(srv, app_uri, 21)
        if uri2 != lib_uri or line2 != DECL_LINE + SHIFT:
            failures.append(f"definition(shared) after mtime bump: uri {uri2} line {line2}, expected {lib_uri} line {DECL_LINE + SHIFT}")

        srv.send(req(2, "shutdown", None))
        srv.send(notify("exit"))
    finally:
        srv.close()
        shutil.rmtree(proj, ignore_errors=True)
    return failures


def broken_manifest_recovers():
    """a root whose manifest fails to parse must not stay bricked for the whole
    session on a non-watch client: once the manifest is fixed on disk (mtime
    bumped past the failure snapshot), the next request retries the load and
    cross-module resolution comes back."""
    proj, app, lib = _scratch_project()
    app_uri = file_uri(app)
    lib_uri = file_uri(lib)
    manifest = os.path.join(proj, "mach.toml")
    good = open(manifest).read()
    with open(manifest, "w") as f:
        f.write("this is [ not a manifest\n")
    failures = []
    srv = LiveServer()
    try:
        srv.send(req(1, "initialize", {"capabilities": {}}))
        srv.recv_id(1)
        srv.send(notify("initialized"))
        srv.send(did_open(app_uri, open(app).read()))

        # broken manifest: the load fails, `shared` stays unresolved single-file
        uri1, _ = _definition_line(srv, app_uri, 20)
        if uri1 == lib_uri:
            failures.append("definition(shared) resolved cross-module despite a broken manifest")

        with open(manifest, "w") as f:
            f.write(good)
        future = os.path.getmtime(manifest) + 1000
        os.utime(manifest, (future, future))

        uri2, line2 = _definition_line(srv, app_uri, 21)
        if uri2 != lib_uri or line2 != DECL_LINE:
            failures.append(f"definition(shared) after manifest fix: uri {uri2} line {line2}, expected {lib_uri} line {DECL_LINE}")

        srv.send(req(2, "shutdown", None))
        srv.send(notify("exit"))
    finally:
        srv.close()
        shutil.rmtree(proj, ignore_errors=True)
    return failures


def reload_rebinds_cached_resolve():
    """a buffer resolve cached before its root reloads must not be served stale.
    the other scenarios only shift a declaration's line, which leaves its DeclId
    intact — so a stale cached cross-module resolve would still read the right
    declaration off the live (reloaded) graph and pass. here the dep is rewritten
    to REORDER its declarations, moving `shared`'s DeclId as well as its line: a
    stale cached resolve carries `shared`'s old DeclId and would now resolve to a
    different declaration entirely, while a fresh re-resolve lands on `shared`'s
    new line. asserting the new line proves the cache entry did not survive the
    reload as a stale hit."""
    proj, app, lib = _scratch_project()
    app_uri = file_uri(app)
    lib_uri = file_uri(lib)
    failures = []
    srv = LiveServer()
    try:
        srv.send(req(1, "initialize", {"capabilities": {}}))
        srv.recv_id(1)
        srv.send(notify("initialized"))
        srv.send(did_open(app_uri, open(app).read()))

        # warm the cache: this resolve of app is cached against the current build
        uri1, line1 = _definition_line(srv, app_uri, 30)
        if uri1 != lib_uri or line1 != DECL_LINE:
            failures.append(f"definition(shared) before reload: uri {uri1} line {line1}, expected {lib_uri} line {DECL_LINE}")

        new_lib = (
            "# lib: reordered so shared's declaration id and line both move; a\n"
            "# cached cross-module resolve served stale would point elsewhere.\n"
            "pub val LIMIT: i64 = 10;\n"
            "\n"
            "\n"
            "pub fun shared(x: i64) i64 {\n"
            "    ret x;\n"
            "}\n"
        )
        with open(lib, "w") as f:
            f.write(new_lib)
        want_line = new_lib.splitlines().index("pub fun shared(x: i64) i64 {")
        srv.send(notify("workspace/didChangeWatchedFiles",
                        {"changes": [{"uri": lib_uri, "type": 2}]}))

        uri2, line2 = _definition_line(srv, app_uri, 31)
        if uri2 != lib_uri or line2 != want_line:
            failures.append(f"definition(shared) after reorder reload: uri {uri2} line {line2}, expected {lib_uri} line {want_line} (a stale cached resolve would land elsewhere)")

        srv.send(req(2, "shutdown", None))
        srv.send(notify("exit"))
    finally:
        srv.close()
        shutil.rmtree(proj, ignore_errors=True)
    return failures


def run():
    """drive the invalidation scenarios; return a list of failure strings."""
    if not os.path.exists(os.path.join(WS, "src", "app.mach")):
        return [f"fixture-ws not found at {WS}"]
    failures = []
    failures += watched_files_trigger()
    failures += mtime_fallback_trigger()
    failures += broken_manifest_recovers()
    failures += reload_rebinds_cached_resolve()
    return failures


if __name__ == "__main__":
    standalone("invalidation", run)
