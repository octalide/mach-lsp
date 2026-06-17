#!/usr/bin/env python3
"""error-safety scenarios: features that must not crash the server when the
buffer contains a parse error. regression for #79 — completion over a
parse-error buffer previously caused a nil symbol-table deref and killed the
process."""
from harness import drive, req, notify, did_open, pos, by_id, standalone

# a parse error: bare integer `2` as a statement is syntactically invalid
SRC_ERR = "fun f(a: i64) i64 { 2 }\n"
URI = "file:///parse_err.mach"


def run():
    """drive error-safety scenarios; return a list of failure strings."""
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open(URI, SRC_ERR),
        req(10, "textDocument/completion", {"textDocument": {"uri": URI}, "position": pos(0, 20)}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    # server must stay alive: shutdown must receive a reply
    shut = by_id(msgs, 2)
    if shut is None:
        failures.append("server did not reply to shutdown — likely crashed on completion over parse-error buffer")

    # completion must return a result (empty array is fine, error is not)
    cpv = by_id(msgs, 10)
    if cpv is None:
        failures.append("server did not reply to completion over parse-error buffer")
    elif "error" in cpv:
        failures.append(f"completion over parse-error buffer returned an error: {cpv['error']}")
    else:
        result = cpv.get("result")
        if result is None:
            failures.append("completion over parse-error buffer returned null result")
        else:
            items = result.get("items") if isinstance(result, dict) else result
            if items is None:
                failures.append("completion result missing 'items' field")

    if code != 0:
        failures.append(f"server exited with non-zero code {code} after parse-error completion")

    return failures


if __name__ == "__main__":
    standalone("errorsafe", run)
