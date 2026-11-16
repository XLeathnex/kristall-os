# SPDX-License-Identifier: GPL-3.0-or-later
"""Connection to the assistant daemon (`assistant.sock`, docs/contracts/assistant-ipc.md).

Used to publish ``agent_cursor`` and ``tool_activity`` requests (role ``tool``), and to learn
when a turn starts and ends so the cursor can leave and the agent session can close as soon as
the work is over.  Never blocks a tool call: if the daemon is not there, events are dropped.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Callable

from . import log


def socket_path() -> str:
    p = os.environ.get("KRISTALL_ASSISTANT_SOCKET")
    if p:
        return p
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(run, "kristall", "assistant.sock")


class Link:
    def __init__(self, path: str | None = None, name: str = "hands"):
        self.path = path or socket_path()
        self.name = name
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._next_try = 0.0
        self._backoff = 0.2
        self.turn_id: str | None = None
        self.language = ""
        self.on_turn_finished: Callable[[str | None, str], None] | None = None
        self.on_turn_started: Callable[[str | None], None] | None = None
        self.sent: list[dict] = []      # tests: record of everything sent
        self.record = False

    def _connect(self) -> bool:
        if self._sock is not None:
            return True
        now = time.monotonic()
        if now < self._next_try:
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(self.path)
            s.settimeout(0.5)
            s.sendall((json.dumps({"type": "hello", "client": self.name, "role": "tool"}) + "\n").encode())
        except OSError:
            s.close()
            self._next_try = now + self._backoff
            self._backoff = min(self._backoff * 2, 5.0)
            return False
        self._backoff = 0.2
        self._sock = s
        threading.Thread(target=self._read_loop, args=(s,), name="assistant-link", daemon=True).start()
        return True

    def _read_loop(self, s: socket.socket) -> None:
        buf = b""
        s.settimeout(None)
        try:
            while True:
                data = s.recv(65536)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    self._event(ev)
        except OSError:
            pass
        with self._lock:
            if self._sock is s:
                self._sock = None

    def _event(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "snapshot":
            turn = ev.get("turn") or {}
            self.turn_id = turn.get("turn_id")
            self.language = ((ev.get("assistant") or {}).get("language")) or self.language
        elif t == "turn_started":
            self.turn_id = ev.get("turn_id")
            if self.on_turn_started:
                self.on_turn_started(self.turn_id)
        elif t == "turn_finished":
            tid = ev.get("turn_id")
            if self.on_turn_finished:
                try:
                    self.on_turn_finished(tid, str(ev.get("outcome", "")))
                except Exception:
                    log.exception("turn_finished handler failed")
            self.turn_id = None

    def send(self, msg: dict) -> bool:
        if self.record:
            self.sent.append(dict(msg, _t=time.monotonic()))
        with self._lock:
            if not self._connect():
                return False
            try:
                self._sock.sendall((json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                return True
            except OSError:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
                return False

    def cursor(self, **fields) -> bool:
        return self.send({"type": "agent_cursor", **{k: v for k, v in fields.items() if v is not None}})

    def activity(self, text, status: str = "running", activity_id: str | None = None) -> bool:
        msg = {"type": "tool_activity", "text": text, "status": status}
        if activity_id:
            msg["activity_id"] = activity_id
        return self.send(msg)

    def close(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
