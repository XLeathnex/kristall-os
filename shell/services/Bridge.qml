// SPDX-License-Identifier: GPL-3.0-or-later
// Client for the compositor bridge (docs/contracts/bridge.md): windows, active window, stacking,
// outputs. Reconnects with backoff 0.25 s .. 5 s and rebuilds its state from the snapshot.
// Without the bridge, `connected` is false, `windows` is empty and calls fail with "unavailable".
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    property bool connected: false
    property var capabilities: []
    property bool locked: false         // screen locked when we connected (hello)
    property var windows: ({})          // id -> window object (contract field names)
    property string activeId: ""
    property var stacking: []           // bottom .. top ids
    property var outputs: []
    property int revision: 0            // bumps on every window change (cheap binding trigger)

    readonly property var activeWindow: activeId !== "" && windows[activeId] ? windows[activeId] : null
    // The front application's window, as the menu bar sees it: the last active *normal* window.
    // It survives keyboard focus moving to shell surfaces (our menus take exclusive keyboard focus,
    // KWin then reports no active window) and transient popups; activating the desktop clears it.
    property string frontId: ""
    readonly property var frontWindow: frontId !== "" && windows[frontId] ? windows[frontId] : null
    function _updateFront() {
        if (activeId === "")
            return;                                  // focus went to a layer surface: keep
        const w = windows[activeId];
        if (!w)
            return;
        if (w.normal)
            frontId = activeId;
        else if (w.type === "desktop")
            frontId = "";
    }
    onActiveIdChanged: _updateFront()
    onWindowRemoved: id => { if (id === frontId) frontId = ""; }

    signal windowAdded(var win)
    signal windowRemoved(string id)
    signal windowChanged(string id, var changes)

    readonly property string socketPath: Quickshell.env("KRISTALL_BRIDGE_SOCKET") || (Quickshell.env("XDG_RUNTIME_DIR") + "/kristall/bridge.sock")

    property int _nextId: 1
    property var _pending: ({})
    property int _backoff: 250
    // Connect only while the socket exists (the helper watches it with inotify): no connect
    // attempts, warnings or wake-ups while the compositor plugin is absent. Without the helper we
    // fall back to retrying with backoff 0.25 s .. 5 s (contract).
    property bool socketExists: false
    Connections {
        target: Helper
        function onEvent(ev) {
            if (ev.event !== "socket" || ev.path !== root.socketPath)
                return;
            root.socketExists = ev.exists;
            if (ev.exists && !sock.connected) {
                root._backoff = 250;
                sock.connected = false;
                sock.connected = true;
            }
        }
        function onReadyChanged() {
            if (Helper.ready)
                Helper.request("watch.socket", { path: root.socketPath });
        }
    }
    Component.onCompleted: {
        Helper.request("watch.socket", { path: root.socketPath });
        noHelper.start();
    }
    // the helper did not answer: try the socket the plain way (retry with backoff)
    Timer {
        id: noHelper
        interval: 3000
        onTriggered: if (!Helper.ready && !sock.connected) { sock.connected = false; sock.connected = true; }
    }

    // call(method, params, cb(result, error)) — error is {code, message} or null
    function call(method, params, cb) {
        if (!sock.connected) {
            if (cb)
                cb(null, { code: "unavailable", message: "bridge not connected" });
            return;
        }
        const id = _nextId++;
        if (cb)
            _pending[id] = cb;
        sock.write(JSON.stringify({ id: id, method: method, params: params || {} }) + "\n");
        sock.flush();
    }

    function windowsOfApp(appId) {
        const out = [];
        for (const id in windows)
            if (windows[id].appId === appId && windows[id].normal)
                out.push(windows[id]);
        return out;
    }

    // topmost normal, non-minimised window on `output` (stacking order), or null
    function topWindowOn(output) {
        for (let i = stacking.length - 1; i >= 0; --i) {
            const w = windows[stacking[i]];
            if (w && w.normal && !w.minimized && w.output === output)
                return w;
        }
        return null;
    }

    function _reset() {
        connected = false;
        frontId = "";
        windows = {};
        activeId = "";
        stacking = [];
        revision++;
        for (const id in _pending)
            _pending[id](null, { code: "unavailable", message: "bridge disconnected" });
        _pending = {};
        if (!retry.running)
            retry.start();
    }

    function _event(name, d) {
        switch (name) {
        case "windows.snapshot": {
            const w = {};
            for (const win of d.windows || [])
                w[win.id] = win;
            windows = w;
            revision++;
            if (frontId !== "" && !w[frontId])
                frontId = "";
            _updateFront();
            break;
        }
        case "window.added":
            windows = Object.assign({}, windows, { [d.window.id]: d.window });
            revision++;
            _updateFront();
            windowAdded(d.window);
            break;
        case "window.changed": {
            const w = windows[d.id];
            if (!w)
                return;
            windows = Object.assign({}, windows, { [d.id]: Object.assign({}, w, d.changes) });
            revision++;
            windowChanged(d.id, d.changes);
            break;
        }
        case "window.removed": {
            const nw = Object.assign({}, windows);
            delete nw[d.id];
            windows = nw;
            revision++;
            windowRemoved(d.id);
            break;
        }
        case "active.changed":
            activeId = d.id || "";
            break;
        case "stacking.changed":
            stacking = d.order || [];
            break;
        case "outputs.changed":
            outputs = d.outputs || [];
            break;
        }
    }

    function _handle(line) {
        let m;
        try {
            m = JSON.parse(line);
        } catch (e) {
            console.warn("bridge: bad JSON from server");
            return;
        }
        if (m.event) {
            _event(m.event, m.data || {});
            return;
        }
        const cb = _pending[m.id];
        delete _pending[m.id];
        if (cb)
            cb(m.result !== undefined ? m.result : null, m.error || null);
    }

    Socket {
        id: sock
        path: root.socketPath
        connected: false
        onConnectedChanged: {
            if (connected) {
                retry.stop();
                root._backoff = 250;
                root.call("hello", { client: "kristall-shell", version: 1 }, (r, e) => {
                    if (r) {
                        root.capabilities = r.capabilities || [];
                        root.locked = r.locked === true;
                    }
                });
                // "menus" declares that we display application menus: only while a client is subscribed to
                // it do applications export their menus (bridge contract, topic "menus")
                root.call("subscribe", { events: ["windows", "active", "stacking", "outputs", "menus"] }, (r, e) => {
                    if (e)
                        console.warn("bridge: subscribe failed:", e.code, e.message);
                });
                root.connected = true;
            } else {
                root._reset();
            }
        }
        onError: root._reset()
        parser: SplitParser {
            onRead: data => root._handle(data)
        }
    }

    Timer {
        id: retry
        interval: root._backoff
        onTriggered: {
            root._backoff = Math.min(root._backoff * 2, 5000);
            if (!root.socketExists && Helper.ready)
                return;           // the helper tells us when it appears
            sock.connected = false;
            sock.connected = true;
        }
    }
}
