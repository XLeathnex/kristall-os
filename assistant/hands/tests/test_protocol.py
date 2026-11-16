# SPDX-License-Identifier: GPL-3.0-or-later
"""MCP conformance: initialize/version negotiation, tools/list, tools/call, errors, ping during a
running call, cancellation (no response for a cancelled request), and the real executable."""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from support.env import HANDS
from kristall_hands.mcp import Server
from kristall_hands.tooling import Registry, Result


class Pipe(io.RawIOBase):
    """A blocking line pipe usable as the server's stdin."""

    def __init__(self):
        self.r, self.w = os.pipe()
        self.f = os.fdopen(self.r, "rb")

    def send(self, obj):
        os.write(self.w, (json.dumps(obj) + "\n").encode() if not isinstance(obj, bytes) else obj)

    def close_write(self):
        os.close(self.w)


class Collector(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.lines = []
        self.cv = threading.Condition()

    def write(self, b):
        with self.cv:
            for line in bytes(b).splitlines():
                if line.strip():
                    self.lines.append((time.monotonic(), json.loads(line)))
            self.cv.notify_all()
        return len(b)

    def flush(self):
        pass

    def wait_for(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                for t, m in self.lines:
                    if pred(m):
                        return m
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self.cv.wait(left)


class InProcess(unittest.TestCase):
    def setUp(self):
        reg = Registry()
        self.slow_cancelled = threading.Event()

        @reg.tool("fast", "fast tool", {"n": {"type": "integer", "minimum": 0}}, ["n"])
        def fast(ctx, n):
            return Result.text(f"n={n}")

        @reg.tool("slow", "slow tool")
        def slow(ctx):
            try:
                ctx.sleep(5)
            finally:
                if ctx.cancelled:
                    self.slow_cancelled.set()
            return Result.text("finished")

        @reg.tool("boom", "crashes")
        def boom(ctx):
            raise ZeroDivisionError

        self.inp = Pipe()
        self.out = Collector()
        self.cancels = []
        self.srv = Server(reg, name="t", version="1", instructions="hi", stdin=self.inp.f, stdout=self.out,
                          on_cancel=lambda: self.cancels.append(1))
        self.th = threading.Thread(target=self.srv.serve, daemon=True)
        self.th.start()

    def tearDown(self):
        try:
            self.inp.close_write()
        except OSError:
            pass
        self.th.join(2)

    def rpc(self, rid, method, params=None):
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.inp.send(msg)
        return self.out.wait_for(lambda m: m.get("id") == rid)

    def test_lifecycle_and_errors(self):
        r = self.rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "c", "version": "0"}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["instructions"], "hi")
        self.assertIn("tools", r["result"]["capabilities"])
        r = self.rpc(2, "initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(r["result"]["protocolVersion"], "2025-11-25")
        self.inp.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = self.rpc(3, "tools/list", {})
        self.assertEqual([t["name"] for t in r["result"]["tools"]], ["fast", "slow", "boom"])
        self.assertEqual(r["result"]["tools"][0]["inputSchema"]["type"], "object")
        r = self.rpc(4, "tools/call", {"name": "fast", "arguments": {"n": 3}})
        self.assertEqual(r["result"]["content"][0]["text"], "n=3")
        self.assertNotIn("isError", r["result"])
        r = self.rpc(5, "tools/call", {"name": "fast", "arguments": {"n": -1}})
        self.assertTrue(r["result"]["isError"])
        r = self.rpc(6, "tools/call", {"name": "fast", "arguments": {"n": 1, "x": 2}})
        self.assertTrue(r["result"]["isError"])
        r = self.rpc(61, "tools/call", {"name": "fast", "arguments": {"n": 2, "intent": "x", "risk": "send"}})
        self.assertNotIn("isError", r["result"])          # intent/risk are accepted on every tool
        r = self.rpc(7, "tools/call", {"name": "nope", "arguments": {}})
        self.assertEqual(r["error"]["code"], -32602)
        r = self.rpc(8, "no/such", {})
        self.assertEqual(r["error"]["code"], -32601)
        r = self.rpc(9, "tools/call", {"name": "boom", "arguments": {}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("internal error", r["result"]["content"][0]["text"])
        self.inp.send(b"{not json\n")
        r = self.out.wait_for(lambda m: m.get("error", {}).get("code") == -32700)
        self.assertIsNotNone(r)
        self.inp.send({"jsonrpc": "1.0", "id": 10, "method": "ping"})
        r = self.out.wait_for(lambda m: m.get("id") == 10)
        self.assertEqual(r["error"]["code"], -32600)
        self.assertEqual(self.rpc(11, "ping")["result"], {})

    def test_ping_during_call_and_cancel(self):
        self.rpc(1, "initialize", {"protocolVersion": "2025-06-18"})
        self.inp.send({"jsonrpc": "2.0", "id": 20, "method": "tools/call", "params": {"name": "slow", "arguments": {}}})
        time.sleep(0.1)
        t0 = time.monotonic()
        self.assertEqual(self.rpc(21, "ping")["result"], {})
        self.assertLess(time.monotonic() - t0, 0.5)            # the reader stays responsive
        self.inp.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 20, "reason": "user"}})
        self.assertTrue(self.slow_cancelled.wait(2))
        r = self.rpc(22, "tools/call", {"name": "fast", "arguments": {"n": 1}})   # worker is free again
        self.assertEqual(r["result"]["content"][0]["text"], "n=1")
        self.assertIsNone(self.out.wait_for(lambda m: m.get("id") == 20, timeout=0.3))   # no response
        self.assertEqual(self.cancels, [1])


class RealExecutable(unittest.TestCase):
    def test_stdio(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, XDG_RUNTIME_DIR=td, XDG_DATA_HOME=td, KRISTALL_HANDS_LOG_STDERR="1",
                       PYTHONPATH=HANDS)
            p = subprocess.Popen([sys.executable, "-m", "kristall_hands"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=env, cwd=HANDS)

            def rpc(rid, method, params):
                p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n").encode())
                p.stdin.flush()
                return json.loads(p.stdout.readline())
            t0 = time.monotonic()
            r = rpc(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
            startup = time.monotonic() - t0
            self.assertEqual(r["result"]["serverInfo"]["name"], "kristall-hands")
            self.assertIn("<screen-content-", r["result"]["instructions"])
            r = rpc(2, "tools/list", {})
            tools = r["result"]["tools"]
            self.assertEqual(len(tools), 30)
            size = len(json.dumps(tools))
            r = rpc(3, "tools/call", {"name": "timer", "arguments": {"action": "list"}})
            self.assertIn("No timers", r["result"]["content"][0]["text"])
            r = rpc(4, "tools/call", {"name": "list_windows", "arguments": {}})
            self.assertTrue(r["result"]["isError"])
            p.stdin.close()
            self.assertEqual(p.wait(5), 0)
            print(f"\n   real server: initialize answered after {startup * 1000:.0f} ms; tools/list = {size} chars "
                  f"(~{size // 4} tokens, estimate)")


if __name__ == "__main__":
    unittest.main()
