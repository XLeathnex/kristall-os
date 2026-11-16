# SPDX-License-Identifier: GPL-3.0-or-later
"""Stand-in for the assistant daemon's socket: records what a tool client sends (with
timestamps) and can broadcast turn events, following docs/contracts/assistant-ipc.md."""
from __future__ import annotations

import json
import os
import socket
import threading
import time


class MockDaemon:
    def __init__(self, path: str):
        self.path = path
        self.received: list[tuple[float, dict]] = []
        self._srv = None
        self._clients: list[socket.socket] = []
        self.seq = 0

    def start(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(4)
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self):
        if self._srv:
            self._srv.close()
            self._srv = None
        for c in self._clients:
            try:
                c.close()
            except OSError:
                pass

    def _accept(self):
        while self._srv:
            try:
                c, _ = self._srv.accept()
            except OSError:
                return
            self._clients.append(c)
            self.broadcast({"type": "hello", "protocol": 1, "daemon": "kristall-assistant", "version": "mock", "demo": False}, [c])
            self.broadcast({"type": "snapshot", "state": "acting", "turn": {"turn_id": "t1"}, "account": {},
                            "pending_permissions": [], "agent_cursor": None,
                            "assistant": {"name": "Kristall", "language": "de", "input_mode": "voice"},
                            "voice": {"input": True, "output": True, "live_transcript": True}}, [c])
            threading.Thread(target=self._read, args=(c,), daemon=True).start()

    def _read(self, c):
        buf = b""
        while True:
            try:
                d = c.recv(65536)
            except OSError:
                return
            if not d:
                return
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    self.received.append((time.monotonic(), json.loads(line)))
                except ValueError:
                    pass

    def broadcast(self, ev: dict, to=None):
        self.seq += 1
        ev = dict(ev, seq=self.seq, ts=int(time.time() * 1000))
        for c in (to or list(self._clients)):
            try:
                c.sendall((json.dumps(ev) + "\n").encode())
            except OSError:
                pass

    def cursor_events(self):
        return [(t, m) for t, m in self.received if m.get("type") == "agent_cursor"]
