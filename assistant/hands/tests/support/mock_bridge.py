# SPDX-License-Identifier: GPL-3.0-or-later
"""A mock of kristall-bridge written from docs/contracts/bridge.md, for hands' tests.

It keeps a model of outputs (with a scale), windows, and coloured "markers" (rectangles in
logical coordinates) from which screenshots are rendered exactly as the contract describes:
image px per logical px = output scale × the downscale needed to fit maxWidth/maxHeight.
Every request is recorded with a timestamp so tests can check what hands sent and when.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time

from . import png


class MockBridge:
    def __init__(self, path: str, *, width=1800, height=1125, scale=1.6, capabilities=None, shots_dir=None):
        self.path = path
        self.outputs = [{"name": "eDP-1", "x": 0, "y": 0, "w": width, "h": height, "scale": scale,
                         "refresh": 120.0, "internal": True, "primary": True}]
        self.capabilities = capabilities if capabilities is not None else \
            ["windows", "menus", "iconGeometry", "agentInput", "agentText", "screenshot"]
        self.windows: list[dict] = []
        self.markers: list[tuple[tuple[float, float, float, float], tuple[int, int, int]]] = []
        self.calls: list[tuple[float, str, dict]] = []
        self.session: str | None = None
        self.session_conn = None
        self.locked = False
        self.busy_next = 0
        self.deny_privileged = False
        self.shots_dir = shots_dir or os.path.join(os.path.dirname(path), "shots")
        self._srv = None
        self._conns: list[socket.socket] = []
        self._subs: dict[socket.socket, set] = {}
        self._lock = threading.Lock()
        self.on_call = None     # hook(method, params) -> optional result override

    # ------------------------------------------------------------------ model helpers
    def add_window(self, wid, app, title, x, y, w, h, *, active=False, pid=4242, **kw):
        win = {"id": wid, "appId": app, "title": title, "pid": pid, "x": x, "y": y, "w": w, "h": h,
               "output": "eDP-1", "desktops": [1], "allDesktops": False, "active": active, "minimized": False,
               "maximized": False, "fullscreen": False, "keepAbove": False, "demandsAttention": False,
               "normal": True, "skipTaskbar": False, "skipSwitcher": False, "closeable": True,
               "minimizable": True, "maximizable": True, "icon": app, "menu": None}
        win.update(kw)
        if active:
            for o in self.windows:
                o["active"] = False
        self.windows.append(win)
        return win

    def win(self, wid):
        return next((w for w in self.windows if w["id"] == wid), None)

    def methods(self):
        return [m for _, m, _ in self.calls]

    def last(self, method):
        for t, m, p in reversed(self.calls):
            if m == method:
                return p
        return None

    # ------------------------------------------------------------------ server
    def start(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        os.chmod(self.path, 0o600)
        self._srv.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self):
        if self._srv:
            self._srv.close()
            self._srv = None
        for c in list(self._conns):
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _accept(self):
        while self._srv:
            try:
                c, _ = self._srv.accept()
            except OSError:
                return
            self._conns.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _send(self, c, obj):
        with self._lock:
            try:
                c.sendall((json.dumps(obj) + "\n").encode())
            except OSError:
                pass

    def emit(self, topic, event, data):
        for c, topics in list(self._subs.items()):
            if topic in topics:
                self._send(c, {"event": event, "data": data})

    def escape(self):
        """The owner presses Escape while a session is active."""
        if self.session:
            self.session = None
            self.emit("agent", "agent.state", {"active": False, "label": "cancelled"})

    def _serve(self, c):
        buf = b""
        while True:
            try:
                d = c.recv(65536)
            except OSError:
                break
            if not d:
                break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    req = json.loads(line)
                except ValueError:
                    self._send(c, {"id": None, "error": {"code": "invalid", "message": "bad json"}})
                    continue
                rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
                self.calls.append((time.monotonic(), method, params))
                try:
                    res = self._handle(c, method, params)
                    self._send(c, {"id": rid, "result": res})
                except BridgeErr as e:
                    self._send(c, {"id": rid, "error": {"code": e.code, "message": e.msg}})
        if self.session_conn is c:
            self.session = None
            self.session_conn = None
        self._subs.pop(c, None)

    def _handle(self, c, method, p):
        if self.on_call:
            r = self.on_call(method, p)
            if r is not None:
                if isinstance(r, BridgeErr):
                    raise r
                return r
        privileged = method.startswith("agent.") or method == "screenshot"
        if privileged and (self.locked or self.deny_privileged):
            raise BridgeErr("denied", "locked" if self.locked else "not a kristall binary")
        if method == "hello":
            return {"version": 1, "kwin": "6.8.3-mock", "capabilities": self.capabilities,
                    "privileged": not self.deny_privileged, "locked": self.locked}
        if method == "subscribe":
            topics = set(p.get("events") or [])
            self._subs[c] = topics
            if "outputs" in topics:
                threading.Timer(0.01, lambda: self._send(c, {"event": "outputs.changed", "data": {"outputs": self.outputs}})).start()
            if "agent" in topics:
                threading.Timer(0.01, lambda: self._send(c, {"event": "agent.state", "data": {"active": bool(self.session), "label": ""}})).start()
            return {}
        if method == "window.list":
            return {"windows": json.loads(json.dumps(self.windows))}
        if method.startswith("window."):
            w = self.win(p.get("id"))
            if w is None:
                raise BridgeErr("not_found", "no such window")
            if method == "window.activate":
                for o in self.windows:
                    o["active"] = o is w
                w["minimized"] = False
            elif method == "window.close":
                self.windows.remove(w)
            elif method == "window.setMinimized":
                w["minimized"] = bool(p.get("value"))
            elif method == "window.setMaximized":
                w["maximized"] = bool(p.get("value"))
            elif method == "window.setFullscreen":
                w["fullscreen"] = bool(p.get("value"))
            elif method == "window.setGeometry":
                w.update({k: p[k] for k in ("x", "y", "w", "h")})
            return {}
        if method == "cursor.get":
            return {"x": 10, "y": 10}
        if method == "agent.begin":
            if self.session:
                raise BridgeErr("busy", "session active")
            self.session = "tok-%d" % len(self.calls)
            self.session_conn = c
            self.emit("agent", "agent.state", {"active": True, "label": p.get("label", "")})
            return {"session": self.session}
        if method == "agent.end":
            if p.get("session") == self.session:
                self.session = None
                self.emit("agent", "agent.state", {"active": False, "label": "ended"})
            return {}
        if method in ("agent.pointer", "agent.drag", "agent.key", "agent.text"):
            if p.get("session") != self.session or not self.session:
                raise BridgeErr("denied", "wrong or expired session token")
            if method in ("agent.pointer", "agent.drag") and self.busy_next > 0:
                self.busy_next -= 1
                time.sleep(0.05)
                raise BridgeErr("busy", "owner is dragging")
            if method == "agent.pointer":
                w = self.window_at(p.get("x"), p.get("y"))
                if w and p.get("type") == "click":
                    for o in self.windows:
                        o["active"] = o is w
                return {"target": {"windowId": w["id"] if w else None, "appId": w["appId"] if w else ""}}
            return {}
        if method == "screenshot":
            return self.screenshot(p)
        raise BridgeErr("invalid", f"unknown method {method}")

    def window_at(self, x, y):
        hits = [w for w in self.windows if not w["minimized"] and w["x"] <= x <= w["x"] + w["w"] and w["y"] <= y <= w["y"] + w["h"]]
        act = [w for w in hits if w["active"]]
        return act[0] if act else (hits[-1] if hits else None)

    # ------------------------------------------------------------------ screenshots
    def screenshot(self, p):
        t = p.get("target", "desktop")
        o = self.outputs[0]
        if t == "desktop":
            rx, ry, rw, rh = o["x"], o["y"], o["w"], o["h"]
        elif isinstance(t, dict) and "window" in t:
            w = self.win(t["window"])
            if not w:
                raise BridgeErr("not_found", "no such window")
            rx, ry, rw, rh = w["x"], w["y"], w["w"], w["h"]
        elif isinstance(t, dict) and "region" in t:
            r = t["region"]
            rx, ry, rw, rh = r["x"], r["y"], r["w"], r["h"]
        elif isinstance(t, dict) and "output" in t:
            rx, ry, rw, rh = o["x"], o["y"], o["w"], o["h"]
        else:
            raise BridgeErr("invalid", "bad target")
        s = o["scale"]
        nw, nh = rw * s, rh * s
        f = 1.0
        mw, mh = p.get("maxWidth") or 0, p.get("maxHeight") or 0
        if mw > 0:
            f = min(f, mw / nw)
        if mh > 0:
            f = min(f, mh / nh)
        iw, ih = max(1, int(round(nw * f))), max(1, int(round(nh * f)))
        sx, sy = iw / rw, ih / rh
        bg = bytes([40, 44, 52])
        rows = []
        for y in range(ih):
            ly = ry + (y + 0.5) / sy
            row = bytearray(bg * iw)
            for (mx, my, mw_, mh_), col in self.markers:
                if my <= ly < my + mh_:
                    x0 = max(0, int((mx - rx) * sx + 0.5))
                    x1 = min(iw, int((mx + mw_ - rx) * sx + 0.5))
                    if x1 > x0:
                        row[x0 * 3:x1 * 3] = bytes(col) * (x1 - x0)
            rows.append(bytes(row))
        data = png.encode(iw, ih, b"".join(rows))
        os.makedirs(self.shots_dir, mode=0o700, exist_ok=True)
        path = os.path.join(self.shots_dir, f"shot-{len(self.calls)}.png")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return {"path": path, "width": iw, "height": ih, "originX": rx, "originY": ry, "scaleX": sx, "scaleY": sy}


class BridgeErr(Exception):
    def __init__(self, code, msg=""):
        super().__init__(code)
        self.code, self.msg = code, msg
