# SPDX-License-Identifier: GPL-3.0-or-later
"""Client for the compositor bridge (docs/contracts/bridge.md).

One persistent connection, opened on first use: the agent session lives on it (the bridge ends
a session when its connection closes) and so does the ``agent`` event topic that reports the
owner pressing Escape.  Window lists are fetched on demand (``window.list``) rather than
subscribed, so moving a window does not wake this process.
"""
from __future__ import annotations

import itertools
import json
import os
import socket
import threading
import time
from typing import Any, Callable

from . import log

MAX_LINE = 1 << 20


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def socket_path() -> str:
    p = os.environ.get("KRISTALL_BRIDGE_SOCKET")
    if p:
        return p
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(run, "kristall", "bridge.sock")


class Bridge:
    def __init__(self, path: str | None = None, client: str = "kristall-hands"):
        self.path = path or socket_path()
        self.client = client
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()          # connect / send
        self._cond = threading.Condition()
        self._replies: dict[Any, dict] = {}
        self._ids = itertools.count(1)
        self._reader: threading.Thread | None = None
        self.capabilities: set[str] = set()
        self.privileged: bool | None = None     # hello.privileged (None: older bridge without the field)
        self.kwin = ""
        self.outputs: list[dict] = []
        self.session: str | None = None
        self.session_label = ""
        self.on_agent_state: Callable[[dict], None] | None = None
        self._last_fail = 0.0
        self.denied = False
        self._outputs_seen = threading.Event()

    # ------------------------------------------------------------------ connection
    def connected(self) -> bool:
        return self._sock is not None

    def ensure(self) -> bool:
        """Connect (if needed).  Returns False when the bridge is not running."""
        if self._sock is not None:
            return True
        with self._lock:
            if self._sock is not None:
                return True
            if time.monotonic() - self._last_fail < 2.0:
                return False
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect(self.path)
                s.settimeout(None)
            except OSError as e:
                s.close()
                self._last_fail = time.monotonic()
                log.debug("bridge not reachable at %s: %s", self.path, e)
                return False
            self._sock = s
            self._reader = threading.Thread(target=self._read_loop, args=(s,), name="bridge-reader", daemon=True)
            self._reader.start()
        try:
            hello = self.request("hello", {"client": self.client, "version": 1}, timeout=3.0)
            self.capabilities = set(hello.get("capabilities") or [])
            self.kwin = str(hello.get("kwin", ""))
            self.privileged = hello.get("privileged") if isinstance(hello.get("privileged"), bool) else None
            self.request("subscribe", {"events": ["agent", "outputs"]}, timeout=3.0)
            # the snapshot of the outputs topic follows the reply immediately
            self._outputs_seen.wait(0.5)
            log.info("bridge connected (kwin %s, capabilities %s)", self.kwin, sorted(self.capabilities))
        except BridgeError as e:
            log.warning("bridge handshake failed: %s", e)
            self.close()
            self._last_fail = time.monotonic()
            return False
        return True

    def close(self) -> None:
        s, self._sock = self._sock, None
        self.session = None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
        with self._cond:
            self._cond.notify_all()

    def _read_loop(self, s: socket.socket) -> None:
        buf = b""
        try:
            while True:
                data = s.recv(65536)
                if not data:
                    break
                buf += data
                if len(buf) > 4 * MAX_LINE:
                    log.warning("bridge sent an over-long line; dropping connection")
                    break
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    self._dispatch(msg)
        except OSError:
            pass
        if self._sock is s:
            log.info("bridge connection closed")
            self._sock = None
            self.session = None
            if self.on_agent_state:
                try:
                    self.on_agent_state({"active": False, "label": "disconnected"})
                except Exception:
                    log.exception("agent state callback failed")
        with self._cond:
            self._cond.notify_all()

    def _dispatch(self, msg: dict) -> None:
        if "event" in msg:
            ev, data = msg.get("event"), msg.get("data") or {}
            if ev == "outputs.changed":
                self.outputs = list(data.get("outputs") or [])
                self._outputs_seen.set()
            elif ev == "agent.state":
                if not data.get("active"):
                    self.session = None
                if self.on_agent_state:
                    try:
                        self.on_agent_state(data)
                    except Exception:
                        log.exception("agent state callback failed")
            return
        if "id" in msg:
            with self._cond:
                self._replies[msg["id"]] = msg
                self._cond.notify_all()

    def request(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        s = self._sock
        if s is None:
            raise BridgeError("unavailable", "bridge not connected")
        rid = next(self._ids)
        line = json.dumps({"id": rid, "method": method, "params": params or {}}, ensure_ascii=False,
                          separators=(",", ":")) + "\n"
        with self._lock:
            try:
                s.sendall(line.encode("utf-8"))
            except OSError as e:
                self.close()
                raise BridgeError("unavailable", str(e))
        end = time.monotonic() + timeout
        with self._cond:
            while rid not in self._replies:
                if self._sock is not s:
                    raise BridgeError("unavailable", "bridge connection closed")
                left = end - time.monotonic()
                if left <= 0:
                    raise BridgeError("timeout", f"no reply to {method}")
                self._cond.wait(left)
            msg = self._replies.pop(rid)
        if "error" in msg:
            err = msg["error"] or {}
            code = str(err.get("code", "internal"))
            if code == "denied":
                self.denied = True
            raise BridgeError(code, str(err.get("message", "")))
        return msg.get("result") or {}

    # ------------------------------------------------------------------ helpers
    def has(self, cap: str) -> bool:
        return cap in self.capabilities

    def windows(self) -> list[dict]:
        return list(self.request("window.list", {}).get("windows") or [])

    def begin(self, label: str) -> str:
        if self.session:
            return self.session
        r = self.request("agent.begin", {"label": label[:80]})
        self.session = r.get("session")
        self.session_label = label
        return self.session or ""

    def end(self) -> None:
        sess, self.session = self.session, None
        if sess and self._sock is not None:
            try:
                self.request("agent.end", {"session": sess}, timeout=2.0)
            except BridgeError:
                pass
