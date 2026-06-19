#!/usr/bin/env python3
"""eager project-load scenarios (#79).

when the client supplies a workspace root at initialize, the server builds that
project's whole import closure once at `initialized` — off the request path —
instead of lazily on the first cross-module feature request, where the long
build would leave the request hanging and the client declaring the server dead.

the build still blocks the single-threaded loop for its full duration; the win
is that it happens once, at startup, wrapped in a liveness signal. these tests
assert that signal (a work-done-progress span when the client supports it, a
single showMessage when it does not) and that the warmed project still serves a
cross-module request correctly. timing is not asserted — only behaviour."""
import os

from harness import (LiveServer, req, notify, did_open, pos, file_uri,
                     standalone, FIXTURE, REPO)

APP = os.path.join(FIXTURE, "src", "app.mach")
URI = file_uri(APP)
ROOT_URI = file_uri(FIXTURE)
DEP_STRING_URI = file_uri(os.path.join(REPO, "dep", "mach-std", "src", "types", "string.mach"))

# app.mach line 10: `    ret str_len(s);` — `str_len` use, name at col 10.
STR_LEN = pos(10, 10)


def _progress(msgs):
    """the $/progress notifications in `msgs`, as a list of (kind, token)."""
    out = []
    for m in msgs:
        if m.get("method") == "$/progress":
            v = m.get("params", {}).get("value", {})
            out.append((v.get("kind"), m.get("params", {}).get("token")))
    return out


def progress_scenario():
    """with window.workDoneProgress, `initialized` creates a progress token and
    emits a begin/end span around the eager load, and the warmed project then
    answers a cross-module definition into the dependency."""
    text = open(APP).read()
    ls = LiveServer()
    ls.send(req(1, "initialize",
                {"rootUri": ROOT_URI, "capabilities": {"window": {"workDoneProgress": True}}}))
    if ls.recv_id(1) is None:
        return ["initialize got no response"]
    ls.send(notify("initialized"))
    ls.send(did_open(URI, text))
    ls.send(req(20, "textDocument/definition",
                {"textDocument": {"uri": URI}, "position": STR_LEN}))
    msgs = ls.collect_until(20)
    ls.send(req(2, "shutdown", None))
    ls.send(notify("exit"))
    code = ls.close()

    failures = []

    create = next((m for m in msgs
                   if m.get("method") == "window/workDoneProgress/create"), None)
    if create is None:
        failures.append("no window/workDoneProgress/create request was sent")
        token = None
    else:
        token = create.get("params", {}).get("token")
        if not token:
            failures.append("workDoneProgress/create carried no token")

    prog = _progress(msgs)
    kinds = [k for k, _ in prog]
    if "begin" not in kinds:
        failures.append(f"no $/progress begin around the eager load (got {kinds})")
    if "end" not in kinds:
        failures.append(f"no $/progress end around the eager load (got {kinds})")
    if token is not None:
        if any(t != token for _, t in prog):
            failures.append(f"a $/progress token did not match the created token {token!r}: {prog}")

    dv = next((m.get("result") for m in msgs if m.get("id") == 20), None)
    if not dv or dv.get("uri") != DEP_STRING_URI:
        failures.append(f"definition(str_len) after eager load did not reach the dep decl: {dv}")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def fallback_scenario():
    """without window.workDoneProgress, the eager load falls back to a single
    showMessage and sends no $/progress; the project is still warmed and serves
    a cross-module definition."""
    text = open(APP).read()
    ls = LiveServer()
    ls.send(req(1, "initialize", {"rootUri": ROOT_URI, "capabilities": {}}))
    if ls.recv_id(1) is None:
        return ["initialize got no response"]
    ls.send(notify("initialized"))
    ls.send(did_open(URI, text))
    ls.send(req(20, "textDocument/definition",
                {"textDocument": {"uri": URI}, "position": STR_LEN}))
    msgs = ls.collect_until(20)
    ls.send(req(2, "shutdown", None))
    ls.send(notify("exit"))
    code = ls.close()

    failures = []

    if _progress(msgs):
        failures.append("a $/progress span was sent without window.workDoneProgress")
    if any(m.get("method") == "window/workDoneProgress/create" for m in msgs):
        failures.append("workDoneProgress/create was sent without the capability")

    show = next((m for m in msgs if m.get("method") == "window/showMessage"), None)
    if show is None:
        failures.append("no showMessage fallback for a progress-less client")
    elif "loading" not in show.get("params", {}).get("message", "").lower():
        failures.append(f"showMessage fallback did not mention loading: {show}")

    dv = next((m.get("result") for m in msgs if m.get("id") == 20), None)
    if not dv or dv.get("uri") != DEP_STRING_URI:
        failures.append(f"definition(str_len) after fallback eager load did not reach the dep decl: {dv}")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def single_file_scenario():
    """no workspace root: the server stays in single-file mode — no eager load,
    no progress span, no showMessage — and a local symbol still resolves."""
    src = "fun lone() i64 { ret 1; }\n"
    uri = "file:///scratch.mach"
    ls = LiveServer()
    ls.send(req(1, "initialize",
                {"capabilities": {"window": {"workDoneProgress": True}}}))
    if ls.recv_id(1) is None:
        return ["initialize got no response"]
    ls.send(notify("initialized"))
    ls.send(did_open(uri, src))
    ls.send(req(20, "textDocument/definition",
                {"textDocument": {"uri": uri}, "position": pos(0, 5)}))
    msgs = ls.collect_until(20)
    ls.send(req(2, "shutdown", None))
    ls.send(notify("exit"))
    code = ls.close()

    failures = []
    if _progress(msgs):
        failures.append("a $/progress span was sent in single-file mode")
    if any(m.get("method") == "window/workDoneProgress/create" for m in msgs):
        failures.append("workDoneProgress/create was sent in single-file mode")
    if any(m.get("method") == "window/showMessage" for m in msgs):
        failures.append("a showMessage was sent in single-file mode")

    dv = next((m.get("result") for m in msgs if m.get("id") == 20), None)
    if not dv or dv.get("uri") != uri:
        failures.append(f"definition(lone) did not resolve locally in single-file mode: {dv}")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")
    return failures


def run():
    """drive the eager-load scenarios; return a list of failure strings."""
    if not os.path.exists(APP):
        return [f"fixture not found at {APP}"]
    failures = []
    failures += progress_scenario()
    failures += fallback_scenario()
    failures += single_file_scenario()
    return failures


if __name__ == "__main__":
    standalone("eager", run)
