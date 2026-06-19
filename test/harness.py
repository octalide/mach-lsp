#!/usr/bin/env python3
"""shared JSON-RPC stdio harness for the mach-lsp test suite.

every test drives the built server over stdin/stdout with framed JSON-RPC and
asserts on the parsed responses. this module owns the base-protocol framing,
the message reader, the request/notification builders, and the binary path so
no scenario duplicates them.
"""
import json
import os
import select
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the server binary, per mach.toml's out = "out/{target}/{profile}/bin/{name}".
# the native target dir is "linux" and the default profile is "debug"; override
# with MLS_TARGET / MLS_PROFILE / MLS_BIN for another build.
TARGET = os.environ.get("MLS_TARGET", "linux")
PROFILE = os.environ.get("MLS_PROFILE", "debug")
BIN = os.environ.get("MLS_BIN", os.path.join(REPO, "out", TARGET, PROFILE, "bin", "mls"))

FIXTURE = os.path.join(REPO, "test", "fixture")


def frame(obj):
    """encode a JSON-RPC object as a Content-Length framed message."""
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def req(id, method, params=None):
    """a framed request with an id."""
    return frame({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


def notify(method, params=None):
    """a framed notification (no id)."""
    return frame({"jsonrpc": "2.0", "method": method, "params": params or {}})


def pos(line, ch):
    """a 0-based LSP position object."""
    return {"line": line, "character": ch}


def did_open(uri, text):
    """a textDocument/didOpen notification for `uri`."""
    return notify("textDocument/didOpen",
                  {"textDocument": {"uri": uri, "languageId": "mach", "version": 1, "text": text}})


def read_messages(data):
    """parse a stream of Content-Length framed JSON-RPC messages."""
    msgs = []
    i = 0
    while i < len(data):
        hdr_end = data.find(b"\r\n\r\n", i)
        if hdr_end < 0:
            break
        header = data[i:hdr_end].decode(errors="replace")
        clen = None
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                clen = int(line.split(":", 1)[1].strip())
        if clen is None:
            break
        bstart = hdr_end + 4
        msgs.append(json.loads(data[bstart:bstart + clen].decode()))
        i = bstart + clen
    return msgs


def drive(frames, timeout=180):
    """run the server with the given framed input, return (returncode, messages).

    raises FileNotFoundError with a build hint when the binary is missing.
    """
    if not os.path.exists(BIN):
        raise FileNotFoundError(f"server binary not found at {BIN} — run `mach build` first")
    proc = subprocess.run([BIN], input=b"".join(frames),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return proc.returncode, read_messages(proc.stdout)


def by_id(msgs, i):
    """the response message with id `i`, or None."""
    return next((m for m in msgs if m.get("id") == i), None)


def file_uri(path):
    """a file:// URI for an absolute filesystem path."""
    return "file://" + os.path.abspath(path)


def standalone(name, run):
    """run one scenario module standalone: print failures, report, exit non-zero on failure."""
    fails = run()
    for f in fails:
        print("  -", f)
    print(f"{name}:", "FAILED" if fails else "PASSED")
    sys.exit(1 if fails else 0)


class LiveServer:
    """an interactive server session: send frames and read responses as they
    arrive, so a scenario can act between requests (e.g. edit a file on disk and
    fire a watched-files change before the next request). reads are bounded by a
    timeout via select, so a misbehaving server cannot hang the suite."""

    def __init__(self):
        if not os.path.exists(BIN):
            raise FileNotFoundError(f"server binary not found at {BIN} — run `mach build` first")
        self.proc = subprocess.Popen([BIN], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.buf = b""

    def send(self, frame):
        """write one framed message to the server's stdin."""
        self.proc.stdin.write(frame)
        self.proc.stdin.flush()

    def _pop(self):
        """parse and remove one complete framed message from the buffer, or None."""
        hdr_end = self.buf.find(b"\r\n\r\n")
        if hdr_end < 0:
            return None
        header = self.buf[:hdr_end].decode(errors="replace")
        clen = None
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                clen = int(line.split(":", 1)[1].strip())
        if clen is None:
            return None
        bstart = hdr_end + 4
        if len(self.buf) < bstart + clen:
            return None
        msg = json.loads(self.buf[bstart:bstart + clen].decode())
        self.buf = self.buf[bstart + clen:]
        return msg

    def recv_id(self, want_id, timeout=60):
        """read messages until the response with id `want_id` arrives (draining
        any notifications), or None on timeout."""
        deadline = time.time() + timeout
        while True:
            msg = self._pop()
            if msg is not None:
                if msg.get("id") == want_id:
                    return msg
                continue
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            r, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not r:
                return None
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                return None
            self.buf += chunk

    def collect_until(self, want_id, timeout=60):
        """read and return every message up to and including the response with id
        `want_id` — server-initiated requests ($/progress, workDoneProgress/create)
        and notifications included, in arrival order — or the messages seen so far
        on timeout. lets a scenario observe what the server emits around a request
        rather than discarding it like recv_id."""
        out = []
        deadline = time.time() + timeout
        while True:
            msg = self._pop()
            if msg is not None:
                out.append(msg)
                if msg.get("id") == want_id:
                    return out
                continue
            remaining = deadline - time.time()
            if remaining <= 0:
                return out
            r, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not r:
                return out
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                return out
            self.buf += chunk

    def close(self, timeout=10):
        """close stdin and wait for the server to exit; returns the exit code."""
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait()
