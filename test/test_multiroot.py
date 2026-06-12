#!/usr/bin/env python3
"""multi-root scenarios: two independent project roots open in one session must
load and resolve independently. test/fixture-ws is a depless two-module project
whose `shared` resolves cross-file within itself; test/fixture depends on the
vendored mach-std and its `str_len` resolves into dep/mach-std. opening both in
one session, each cross-module definition must land in its own project's files
— neither root's graph leaking into the other — and the order of opening must
not matter."""
import os

from harness import drive, req, notify, did_open, pos, by_id, file_uri, standalone, REPO, FIXTURE

WS = os.path.join(REPO, "test", "fixture-ws")
WS_APP = os.path.join(WS, "src", "app.mach")
WS_LIB = os.path.join(WS, "src", "lib.mach")
WS_APP_URI = file_uri(WS_APP)
WS_LIB_URI = file_uri(WS_LIB)

FX_APP = os.path.join(FIXTURE, "src", "app.mach")
FX_APP_URI = file_uri(FX_APP)
DEP_STRING_URI = file_uri(os.path.join(REPO, "dep", "mach-std", "src", "types", "string.mach"))

# fixture-ws/src/app.mach line 6: `ret shared(1) + shared(2) + LIMIT;` use at col 8.
# fixture-ws/src/lib.mach  line 4: `pub fun shared(x: i64) i64 {` decl at col 8.
WS_USE = pos(6, 8)
# fixture/src/app.mach line 10: `    ret str_len(s);` use at col 8 (name at col 10).
FX_USE = pos(10, 10)


def both_resolve_independently(open_ws_first):
    """open both projects in one session; each cross-module definition lands in
    its own project's files regardless of which root was opened first."""
    ws_text = open(WS_APP).read()
    fx_text = open(FX_APP).read()
    opens = [did_open(WS_APP_URI, ws_text), did_open(FX_APP_URI, fx_text)]
    if not open_ws_first:
        opens.reverse()
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        *opens,
        req(20, "textDocument/definition", {"textDocument": {"uri": WS_APP_URI}, "position": WS_USE}),
        req(21, "textDocument/definition", {"textDocument": {"uri": FX_APP_URI}, "position": FX_USE}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)
    order = "ws-first" if open_ws_first else "fixture-first"
    failures = []

    dws = (by_id(msgs, 20) or {}).get("result")
    if not dws or "uri" not in dws:
        failures.append(f"[{order}] definition(shared) returned no Location")
    else:
        if dws["uri"] != WS_LIB_URI:
            failures.append(f"[{order}] definition(shared) landed in {dws['uri']}, expected {WS_LIB_URI}")
        if dws.get("range", {}).get("start", {}).get("line") != 4:
            failures.append(f"[{order}] definition(shared) line {dws.get('range', {}).get('start', {}).get('line')}, expected 4")

    dfx = (by_id(msgs, 21) or {}).get("result")
    if not dfx or "uri" not in dfx:
        failures.append(f"[{order}] definition(str_len) returned no Location")
    elif dfx["uri"] != DEP_STRING_URI:
        failures.append(f"[{order}] definition(str_len) landed in {dfx['uri']}, expected {DEP_STRING_URI}")

    if code != 0:
        failures.append(f"[{order}] non-zero exit code after clean shutdown")
    return failures


def run():
    """drive the multi-root scenarios; return a list of failure strings."""
    if not os.path.exists(WS_APP) or not os.path.exists(FX_APP):
        return ["multi-root fixtures not found"]
    failures = []
    failures += both_resolve_independently(True)
    failures += both_resolve_independently(False)
    return failures


if __name__ == "__main__":
    standalone("multiroot", run)
