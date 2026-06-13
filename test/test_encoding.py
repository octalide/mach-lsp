#!/usr/bin/env python3
"""UTF-16 position-encoding round-trip over a buffer with a multibyte character.

the LSP `character` field is UTF-16 code units; the compiler core is byte-
oriented. this asserts the conversion at the boundary (#65): a request position
at a UTF-16 column lands on the right byte (inbound), and a reported range's
column is in UTF-16 units, not bytes (outbound).

the buffer puts an EM DASH (U+2014, 3 UTF-8 bytes / 1 UTF-16 unit) in a string
literal before a `g()` call on the same line, so that call's byte column (38)
and UTF-16 column (36) differ. the fixture is sent as raw UTF-8 (not \\uXXXX
escaped), matching how editor clients deliver non-ASCII text."""
import json
import os

from harness import req, notify, pos, by_id, drive, standalone

EM = "—"  # em dash: 3 UTF-8 bytes, 1 UTF-16 code unit
# line 0: g's declaration (ASCII). line 1: a string holding the em dash, then a
# g() call whose `g` sits at UTF-16 col 36 but byte col 38.
SRC = (
    "fun g() i64 { ret 0; }\n"
    f'fun f() i64 {{ val s: str = "{EM}"; ret g(); }}\n'
)
URI = "file:///enc.mach"

G_U16_COL = 36   # UTF-16 column of the g() call on line 1
G_BYTE_COL = 38  # its byte column — what a byte-oriented server would wrongly emit


def did_open_raw(uri, text):
    """a didOpen frame whose body is raw UTF-8 (ensure_ascii=False)."""
    obj = {"jsonrpc": "2.0", "method": "textDocument/didOpen",
           "params": {"textDocument": {"uri": uri, "languageId": "mach", "version": 1, "text": text}}}
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def run():
    """drive the encoding round-trip; return a list of failure strings."""
    frames = [
        req(1, "initialize", {"capabilities": {}}),
        notify("initialized"),
        did_open_raw(URI, SRC),
        # inbound: a definition request at the g() call's UTF-16 column must
        # resolve to g's decl on line 0 — only possible if char 36 maps to byte 38.
        req(20, "textDocument/definition",
            {"textDocument": {"uri": URI}, "position": pos(1, G_U16_COL)}),
        # outbound: references on g's decl reports the line-1 use-site; its column
        # must be the UTF-16 value (36), not the byte value (38).
        req(30, "textDocument/references",
            {"textDocument": {"uri": URI}, "position": pos(0, 4),
             "context": {"includeDeclaration": True}}),
        req(2, "shutdown", None),
        notify("exit"),
    ]
    code, msgs = drive(frames)

    failures = []

    # inbound: definition lands on g's decl (line 0)
    dv = (by_id(msgs, 20) or {}).get("result")
    loc = dv[0] if isinstance(dv, list) and dv else dv
    if not loc or "range" not in loc:
        failures.append(
            f"definition at UTF-16 col {G_U16_COL} returned no Location "
            "(inbound UTF-16->byte conversion failed)")
    elif loc["range"]["start"]["line"] != 0:
        failures.append(
            f"definition landed on line {loc['range']['start']['line']}, expected 0 (g's decl)")

    # outbound: the line-1 use-site is reported at the UTF-16 column, not the byte column
    rv = (by_id(msgs, 30) or {}).get("result")
    if not isinstance(rv, list):
        failures.append("references result is not an array")
    else:
        cols = {r["range"]["start"]["character"] for r in rv
                if r["range"]["start"]["line"] == 1}
        if G_U16_COL not in cols:
            hint = " (byte column leaked)" if G_BYTE_COL in cols else ""
            failures.append(
                f"references use-site on line 1 at cols {sorted(cols)}, "
                f"expected UTF-16 col {G_U16_COL}{hint}")

    if code != 0:
        failures.append("non-zero exit code after clean shutdown")

    return failures


if __name__ == "__main__":
    standalone("encoding", run)
