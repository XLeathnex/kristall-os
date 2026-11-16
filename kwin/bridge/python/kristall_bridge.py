# SPDX-License-Identifier: GPL-3.0-or-later
"""Client for kristall-bridge (docs/contracts/bridge.md). Standard library only.

    from kristall_bridge import Bridge
    with Bridge(client="hands") as b:
        print(b.call("window.list"))
        with b.agent_session("Opening the settings") as agent:
            agent.click(400, 300)
            agent.text("Schöne Grüße")
        shot = b.call("screenshot", target="desktop", maxWidth=1440, excludeShell=True)

Thread safety: one Bridge per thread. Events received while waiting for a reply are queued and
returned by next_event()/wait_event().
"""
from __future__ import annotations

import collections
import itertools
import json
import os
import select
import socket
import time

__all__ = ["Bridge", "BridgeError", "AgentSession", "default_socket_path", "connect_with_retry"]

MAX_LINE = 1 << 20


class BridgeError(Exception):
    """An error reply: .code is one of invalid, not_found, busy, unsupported, denied, internal."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def default_socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "kristall", "bridge.sock")


class Bridge:
    def __init__(self, path=None, client="python", timeout=10.0, hello=True):
        self.path = path or default_socket_path()
        self.timeout = timeout
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
        self._sock.settimeout(timeout)
        self._sock.connect(self.path)
        self._buf = b""
        self._ids = itertools.count(1)
        self._events = collections.deque()
        self._replies = {}
        self.info = self.call("hello", client=client, version=1) if hello else None

    # -- lifecycle
    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def fileno(self):
        return self._sock.fileno()

    @property
    def capabilities(self):
        return set((self.info or {}).get("capabilities", []))

    # -- wire
    def send(self, obj):
        data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self._sock.sendall(data)

    def _read_some(self, timeout):
        r, _, _ = select.select([self._sock], [], [], max(0.0, timeout))
        if not r:
            return False
        data = self._sock.recv(1 << 20)
        if not data:
            raise ConnectionError("bridge closed the connection")
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            msg = json.loads(line)
            if "event" in msg:
                self._events.append(msg)
            else:
                self._replies[_key(msg.get("id"))] = msg
        if len(self._buf) > MAX_LINE + 1:
            raise ConnectionError("bridge sent an over-long line")
        return True

    def request(self, method, params=None, timeout=None):
        """Sends a request and returns the raw reply object (with "result" or "error")."""
        rid = next(self._ids)
        self.send({"id": rid, "method": method, "params": params or {}})
        end = time.monotonic() + (self.timeout if timeout is None else timeout)
        while _key(rid) not in self._replies:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"no reply to {method} within the timeout")
            self._read_some(left)
        return self._replies.pop(_key(rid))

    def call(self, method, timeout=None, **params):
        reply = self.request(method, params, timeout=timeout)
        if "error" in reply:
            err = reply["error"] or {}
            raise BridgeError(err.get("code", "internal"), err.get("message", ""))
        return reply.get("result", {})

    # -- events
    def subscribe(self, *topics):
        return self.call("subscribe", events=list(topics))

    def next_event(self, timeout=0.0):
        end = time.monotonic() + timeout
        while not self._events:
            left = end - time.monotonic()
            if left <= 0 or not self._read_some(left):
                if not self._events:
                    return None
        return self._events.popleft()

    def wait_event(self, match, timeout=5.0):
        """Returns the first queued or arriving event for which match(event) is true (or whose
        name equals match, if it is a string); other events stay queued."""
        if isinstance(match, str):
            name = match
            match = lambda e: e.get("event") == name  # noqa: E731
        end = time.monotonic() + timeout
        while True:
            for i, ev in enumerate(self._events):
                if match(ev):
                    del self._events[i]
                    return ev
            left = end - time.monotonic()
            if left <= 0:
                return None
            self._read_some(left)

    def drain_events(self, timeout=0.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self._read_some(end - time.monotonic()):
                break
        out = list(self._events)
        self._events.clear()
        return out

    # -- agent
    def agent_session(self, label):
        return AgentSession(self, label)


class AgentSession:
    """Context manager around agent.begin / agent.end."""

    def __init__(self, bridge, label):
        self.bridge = bridge
        self.label = label
        self.token = None

    def __enter__(self):
        self.token = self.bridge.call("agent.begin", label=self.label)["session"]
        return self

    def __exit__(self, *exc):
        try:
            self.bridge.call("agent.end", session=self.token)
        except (BridgeError, OSError, TimeoutError):
            pass

    def pointer(self, type, x=None, y=None, **kw):
        params = {"session": self.token, "type": type, **kw}
        if x is not None:
            params["x"], params["y"] = x, y
        return self.bridge.call("agent.pointer", **params)

    def move(self, x, y, **kw):
        return self.pointer("move", x, y, **kw)

    def click(self, x, y, button="left", count=1, **kw):
        return self.pointer("click", x, y, button=button, count=count, **kw)

    def down(self, x, y, button="left", **kw):
        return self.pointer("down", x, y, button=button, **kw)

    def up(self, x=None, y=None, button="left", **kw):
        return self.pointer("up", x, y, button=button, **kw)

    def scroll(self, x, y, dx=0, dy=0, **kw):
        return self.pointer("scroll", x, y, dx=dx, dy=dy, **kw)

    def drag(self, from_xy, to_xy, button="left", duration_ms=300, **kw):
        return self.bridge.call("agent.drag", session=self.token, button=button, durationMs=duration_ms,
                                timeout=max(10.0, duration_ms / 1000 + 5),
                                **{"from": {"x": from_xy[0], "y": from_xy[1]}, "to": {"x": to_xy[0], "y": to_xy[1]}}, **kw)

    def key(self, keys, window_id=None, restore_focus=True):
        params = {"session": self.token, "keys": keys, "restoreFocus": restore_focus}
        if window_id:
            params["windowId"] = window_id
        return self.bridge.call("agent.key", **params)

    def text(self, text, window_id=None, restore_focus=True, paths=None):
        params = {"session": self.token, "text": text, "restoreFocus": restore_focus}
        if window_id:
            params["windowId"] = window_id
        if paths:
            params["paths"] = list(paths)
        return self.bridge.call("agent.text", timeout=max(10.0, len(text) / 200), **params)


def connect_with_retry(client="python", path=None, attempts=8, first_delay=0.1):
    """The bridge may not be up yet (or KWin restarted): retry with exponential backoff."""
    delay = first_delay
    last = None
    for _ in range(attempts):
        try:
            return Bridge(path=path, client=client)
        except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError) as e:
            last = e
            time.sleep(delay)
            delay = min(delay * 2, 5.0)
    raise last


def _key(rid):
    return json.dumps(rid)
