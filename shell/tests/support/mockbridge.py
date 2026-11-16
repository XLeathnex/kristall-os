#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mock of the compositor bridge (docs/contracts/bridge.md) for shell tests and development.

Speaks the bridge protocol on a Unix socket (default $XDG_RUNTIME_DIR/kristall/bridge.sock,
or --socket PATH): hello (with privileged/locked), subscribe (windows/active/stacking/outputs/
desktops snapshots then deltas; "menus" and "agent" accepted; unknown topic -> invalid), window.*
methods (they change the mock state and emit the events the real bridge would; setIconGeometry is
recorded), window.list (stacking order), cursor.get. Window objects carry the contract's additions
(type, parentId, xwayland, content, namespace for layer surfaces). Privileged methods (agent.*,
screenshot) return `unsupported`; agent.pointer/agent.state events can be emitted from the control
socket so an assistant-cursor overlay can be developed against the mock.
Not modelled: the D-Bus side of "menus" (the mock does not own org.kde.kappmenuview), popups.

Scripting: a control socket at <socket>.ctl takes one JSON command per line and answers one line:
  {"cmd":"open","window":{"id":"w1","appId":"org.kde.kate","title":"…", …}}   (missing fields get defaults)
  {"cmd":"close","id":"w1"}            {"cmd":"activate","id":"w1"|null}
  {"cmd":"set","id":"w1","changes":{"maximized":true}}   (any window fields)
  {"cmd":"menu","id":"w1","service":":1.42","path":"/MenuBar/1"}  ({"service":null} detaches)
  {"cmd":"outputs","outputs":[{"name":"Virtual-0",…}]}
  {"cmd":"agentPointer","x":…,"y":…,"type":"click","button":"left"}   (emits agent.pointer)
  {"cmd":"agentState","active":true,"label":"…"}                        (emits agent.state)
  {"cmd":"state"}  -> {"windows":[…],"active":…,"stacking":[…],"iconGeometry":{…},"menuClients":n}
  {"cmd":"calls"}  -> methods clients called, in order (then cleared)
CLI: mockbridge.py serve [--socket P] | mockbridge.py ctl P '<json>'
Python: MockBridge(path).start() in a thread; .open(...), .set(...), etc.
"""
import json
import os
import selectors
import socket
import sys
import threading

DEFAULT_WINDOW = {
    "appId": "", "title": "", "pid": 0, "x": 0, "y": 30, "w": 800, "h": 600, "output": "Virtual-0",
    "desktops": [1], "allDesktops": False, "active": False, "minimized": False, "maximized": False,
    "fullscreen": False, "keepAbove": False, "demandsAttention": False, "normal": True,
    "skipTaskbar": False, "skipSwitcher": False, "closeable": True, "minimizable": True,
    "maximizable": True, "icon": "", "menu": None,
    # contract additions
    "type": "normal", "parentId": None, "xwayland": False, "content": None,
}
TOPICS = {"windows", "active", "stacking", "outputs", "desktops", "agent", "menus"}


class MockBridge:
    def __init__(self, path, outputs=None):
        self.path = path
        self.ctl_path = path + ".ctl"
        self.windows = {}
        self.order = []
        self.active = None
        self.outputs = outputs or [{"name": "Virtual-0", "x": 0, "y": 0, "w": 1280, "h": 800, "scale": 1.0,
                                    "refresh": 60.0, "internal": True, "primary": True}]
        self.clients = {}   # sock -> {"buf": b"", "topics": set()}
        self.calls = []
        self.icon_geometry = {}
        self.lock = threading.RLock()
        self.sel = selectors.DefaultSelector()
        self._stop = False

    # ---- state changes (also used by the control socket) ----------------------------------------
    def emit(self, topic, event, data):
        line = (json.dumps({"event": event, "data": data}) + "\n").encode()
        for s, c in list(self.clients.items()):
            if topic in c["topics"]:
                self._send(s, line)

    def open(self, win):
        with self.lock:
            w = dict(DEFAULT_WINDOW)
            w.update(win)
            if w["content"] is None:   # client area inside a 30-px server-side title bar
                w["content"] = {"x": w["x"], "y": w["y"] + 30, "w": w["w"], "h": max(0, w["h"] - 30)}
            if w["type"] != "normal" and "normal" not in win:
                w["normal"] = False
            self.windows[w["id"]] = w
            self.order.append(w["id"])
            self.emit("windows", "window.added", {"window": w})
            self.emit("stacking", "stacking.changed", {"order": list(self.order)})
            if win.get("active", True):
                self.activate(w["id"])
            return w

    def close(self, wid):
        with self.lock:
            if wid not in self.windows:
                return False
            del self.windows[wid]
            self.order.remove(wid)
            self.emit("windows", "window.removed", {"id": wid})
            self.emit("stacking", "stacking.changed", {"order": list(self.order)})
            if self.active == wid:
                rest = [i for i in self.order if not self.windows[i]["minimized"]]
                self.activate(rest[-1] if rest else None)
            return True

    def set(self, wid, changes):
        with self.lock:
            w = self.windows.get(wid)
            if not w:
                return False
            real = {k: v for k, v in changes.items() if w.get(k) != v}
            if not real:
                return True
            w.update(real)
            self.emit("windows", "window.changed", {"id": wid, "changes": real})
            return True

    def activate(self, wid):
        with self.lock:
            if self.active == wid:
                return
            if self.active in self.windows:
                self.set(self.active, {"active": False})
            self.active = wid
            if wid is not None:
                self.set(wid, {"active": True, "minimized": False})
                self.order.remove(wid)
                self.order.append(wid)
                self.emit("stacking", "stacking.changed", {"order": list(self.order)})
            self.emit("active", "active.changed", {"id": wid})

    # ---- protocol ---------------------------------------------------------------------------------
    def _send(self, s, data):
        try:
            s.sendall(data)
        except OSError:
            self._drop(s)

    def _drop(self, s):
        if s in self.clients:
            del self.clients[s]
            try:
                self.sel.unregister(s)
            except Exception:
                pass
            s.close()

    def handle(self, s, req):
        rid, method, p = req.get("id"), req.get("method"), req.get("params") or {}
        self.calls.append({"method": method, "params": p})

        def ok(result=None):
            self._send(s, (json.dumps({"id": rid, "result": result or {}}) + "\n").encode())

        def err(code, msg):
            self._send(s, (json.dumps({"id": rid, "error": {"code": code, "message": msg}}) + "\n").encode())

        with self.lock:
            if method == "hello":
                return ok({"version": 1, "kwin": "mock", "capabilities": ["windows", "menus", "iconGeometry"],
                           "privileged": False, "locked": False})
            if method == "subscribe":
                topics = set(p.get("events") or [])
                if topics - TOPICS:
                    return err("invalid", "unknown topic " + ", ".join(sorted(topics - TOPICS)))
                self.clients[s]["topics"] |= topics
                ok()
                if "windows" in topics:
                    self._send(s, (json.dumps({"event": "windows.snapshot", "data": {"windows": list(self.windows.values())}}) + "\n").encode())
                if "active" in topics:
                    self._send(s, (json.dumps({"event": "active.changed", "data": {"id": self.active}}) + "\n").encode())
                if "stacking" in topics:
                    self._send(s, (json.dumps({"event": "stacking.changed", "data": {"order": list(self.order)}}) + "\n").encode())
                if "outputs" in topics:
                    self._send(s, (json.dumps({"event": "outputs.changed", "data": {"outputs": self.outputs}}) + "\n").encode())
                if "desktops" in topics:
                    self._send(s, (json.dumps({"event": "desktops.changed", "data": {"current": 1, "count": 1, "names": ["Desktop 1"]}}) + "\n").encode())
                return
            if method == "window.list":   # stacking order, bottom to top
                return ok({"windows": [self.windows[i] for i in self.order]})
            if method == "cursor.get":
                return ok({"x": 0, "y": 0})
            if method and (method.startswith("agent.") or method == "screenshot"):
                return err("unsupported", "mock bridge")
            if method and method.startswith("window."):
                wid = p.get("id")
                if wid not in self.windows:
                    return err("not_found", "no window " + str(wid))
                if method == "window.activate":
                    self.activate(wid)
                elif method == "window.close":
                    self.close(wid)
                elif method == "window.setMinimized":
                    self.set(wid, {"minimized": bool(p.get("value"))})
                    if p.get("value") and self.active == wid:
                        rest = [i for i in self.order if not self.windows[i]["minimized"]]
                        self.activate(rest[-1] if rest else None)
                elif method == "window.setMaximized":
                    self.set(wid, {"maximized": bool(p.get("value"))})
                elif method == "window.setFullscreen":
                    self.set(wid, {"fullscreen": bool(p.get("value"))})
                elif method == "window.setGeometry":
                    self.set(wid, {k: p[k] for k in ("x", "y", "w", "h") if k in p})
                elif method == "window.setIconGeometry":
                    self.icon_geometry[wid] = None if not p.get("w") or not p.get("h") else {k: p.get(k) for k in ("x", "y", "w", "h")}
                elif method in ("window.toDesktop", "window.toOutput"):
                    pass
                else:
                    return err("invalid", "unknown method " + method)
                return ok()
            if method in ("workspace.showDesktop", "effect.toggle", "desktop.set"):
                return ok()
            return err("invalid", "unknown method " + str(method))

    def control(self, cmd):
        c = cmd.get("cmd")
        if c == "open":
            return self.open(cmd["window"])
        if c == "close":
            return self.close(cmd["id"])
        if c == "activate":
            self.activate(cmd.get("id"))
            return True
        if c == "set":
            return self.set(cmd["id"], cmd.get("changes") or {})
        if c == "menu":
            m = None if not cmd.get("service") else {"service": cmd["service"], "path": cmd["path"]}
            return self.set(cmd["id"], {"menu": m})
        if c == "outputs":
            self.outputs = cmd["outputs"]
            self.emit("outputs", "outputs.changed", {"outputs": self.outputs})
            return True
        if c == "state":
            return {"windows": list(self.windows.values()), "active": self.active, "stacking": self.order,
                    "clients": len(self.clients), "iconGeometry": self.icon_geometry,
                    "menuClients": sum(1 for c in self.clients.values() if "menus" in c["topics"])}
        if c == "agentPointer":   # what the assistant's cursor overlay would receive
            self.emit("agent", "agent.pointer", {k: cmd.get(k) for k in ("x", "y", "type", "button")})
            return True
        if c == "agentState":
            self.emit("agent", "agent.state", {"active": bool(cmd.get("active")), "label": cmd.get("label", "")})
            return True
        if c == "calls":
            out, self.calls = self.calls, []
            return out
        return {"error": "unknown cmd"}

    # ---- server loop --------------------------------------------------------------------------------
    def _listen(self, path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        os.chmod(path, 0o600)
        srv.listen(16)
        srv.setblocking(False)
        return srv

    def serve(self):
        srv = self._listen(self.path)
        ctl = self._listen(self.ctl_path)
        self.sel.register(srv, selectors.EVENT_READ, "srv")
        self.sel.register(ctl, selectors.EVENT_READ, "ctl")
        ctl_clients = {}
        while not self._stop:
            for key, _ in self.sel.select(0.5):
                s = key.fileobj
                if key.data == "srv":
                    c, _ = s.accept()
                    self.clients[c] = {"buf": b"", "topics": set()}
                    self.sel.register(c, selectors.EVENT_READ, "client")
                elif key.data == "ctl":
                    c, _ = s.accept()
                    ctl_clients[c] = b""
                    self.sel.register(c, selectors.EVENT_READ, "ctlclient")
                else:
                    try:
                        data = s.recv(65536)
                    except OSError:
                        data = b""
                    if key.data == "client":
                        if not data:
                            self._drop(s)
                            continue
                        c = self.clients[s]
                        c["buf"] += data
                        while b"\n" in c["buf"]:
                            line, c["buf"] = c["buf"].split(b"\n", 1)
                            if line.strip():
                                try:
                                    self.handle(s, json.loads(line))
                                except ValueError:
                                    self._send(s, b'{"id":null,"error":{"code":"invalid","message":"bad json"}}\n')
                            if s not in self.clients:
                                break
                    else:
                        if not data:
                            self.sel.unregister(s)
                            s.close()
                            ctl_clients.pop(s, None)
                            continue
                        ctl_clients[s] += data
                        while b"\n" in ctl_clients[s]:
                            line, ctl_clients[s] = ctl_clients[s].split(b"\n", 1)
                            with self.lock:
                                try:
                                    res = self.control(json.loads(line))
                                except Exception as e:  # noqa: BLE001
                                    res = {"error": str(e)}
                            s.sendall((json.dumps(res) + "\n").encode())

    def start(self):
        t = threading.Thread(target=self.serve, daemon=True)
        t.start()
        return self

    def stop(self):
        self._stop = True


def ctl(path, cmd):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path + ".ctl" if not path.endswith(".ctl") else path)
    s.sendall((json.dumps(cmd) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        d = s.recv(65536)
        if not d:
            break
        buf += d
    s.close()
    return json.loads(buf.split(b"\n", 1)[0])


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "ctl":
        print(json.dumps(ctl(sys.argv[2], json.loads(sys.argv[3]))))
    else:
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "kristall", "bridge.sock")
        if "--socket" in sys.argv:
            path = sys.argv[sys.argv.index("--socket") + 1]
        print("mock bridge on", path, flush=True)
        MockBridge(path).serve()
