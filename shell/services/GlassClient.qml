// SPDX-License-Identifier: GPL-3.0-or-later
// Client for glass.sock (docs/contracts/glass.md). Adopted from kwin/glass/demo/GlassClient.qml
// (the reference client); shell-core owns this copy. Changes from the reference:
//  * tracks `bound` per surface so a surface with windows:0 falls back (contract §7.4)
//  * remembers the last legibility scheme per surface/shape (late-created shapes get it)
//  * the retry timer only runs while disconnected
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    // true while the effect is present and in state "active"; when false, draw fallbacks
    property bool active: false
    property string state: "absent"     // absent | active | disabled | failed
    property string theme: "light"      // effective theme reported by the effect
    property string quality: ""
    property real glass: 0.3
    property bool reduceTransparency: false
    property var boundWindows: ({})     // surface key -> windows count
    property var schemes: ({})          // "surface/shape" -> "light" | "dark"

    signal legibility(string surface, string shape, string scheme, real luminance)
    signal bound(string surface, int windows)

    readonly property string socketPath: {
        const env = Quickshell.env("KRISTALL_GLASS_SOCKET");
        return env ? env : Quickshell.env("XDG_RUNTIME_DIR") + "/kristall/glass.sock";
    }

    property var _surfaces: ({})        // key -> { match, shapes (JSON string), sync }
    property var _dirty: ({})
    property bool _flushQueued: false
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

    function bind(key, match) {
        _surfaces[key] = { match: match, shapes: _surfaces[key] ? _surfaces[key].shapes : "[]", sync: "immediate" };
        if (sock.connected)
            _send({ op: "bind", surface: key, match: match });
        _markDirty(key);
    }

    // shapesJson: JSON text of the full shape array; equal text is not resent
    function setShapes(key, shapesJson, sync) {
        const s = _surfaces[key];
        if (!s || s.shapes === shapesJson)
            return;
        s.shapes = shapesJson;
        s.sync = sync || "immediate";
        _markDirty(key);
    }

    function unbind(key) {
        if (!_surfaces[key])
            return;
        delete _surfaces[key];
        if (sock.connected)
            _send({ op: "unbind", surface: key });
    }

    function isBound(key) {
        return (boundWindows[key] || 0) > 0;
    }

    function _markDirty(key) {
        _dirty[key] = true;
        if (!_flushQueued) {
            _flushQueued = true;
            Qt.callLater(_flush);
        }
    }

    function _flush() {
        _flushQueued = false;
        if (!sock.connected)
            return;
        for (const key in _dirty) {
            const s = _surfaces[key];
            if (s)
                sock.write('{"op":"shapes","surface":' + JSON.stringify(key) + ',"sync":"' + s.sync + '","shapes":' + s.shapes + '}\n');
        }
        _dirty = {};
        sock.flush();
    }

    function _send(obj) {
        sock.write(JSON.stringify(obj) + "\n");
        sock.flush();
    }

    function _lost() {
        active = false;
        state = "absent";
        boundWindows = {};
        if (!retry.running)
            retry.start();
    }

    function _handle(line) {
        let ev;
        try {
            ev = JSON.parse(line);
        } catch (e) {
            return;
        }
        switch (ev.event) {
        case "hello":
        case "state":
            root.state = ev.state;
            root.active = ev.state === "active";
            if (ev.theme)
                root.theme = ev.theme;
            if (ev.quality)
                root.quality = ev.quality;
            if (ev.glass !== undefined)
                root.glass = ev.glass;
            if (ev.reduceTransparency !== undefined)
                root.reduceTransparency = ev.reduceTransparency;
            break;
        case "legibility": {
            const s = Object.assign({}, root.schemes);
            s[ev.surface + "/" + ev.shape] = ev.scheme;
            root.schemes = s;
            root.legibility(ev.surface, ev.shape, ev.scheme, ev.luminance);
            break;
        }
        case "bound": {
            const b = Object.assign({}, root.boundWindows);
            b[ev.surface] = ev.windows;
            root.boundWindows = b;
            root.bound(ev.surface, ev.windows);
            break;
        }
        case "error":
            console.warn("glass:", ev.code, ev.message, ev.surface || "");
            break;
        }
    }

    Socket {
        id: sock
        path: root.socketPath
        connected: false
        onConnectedChanged: {
            if (connected) {
                retry.stop();
                root._backoff = 250;
                root._send({ op: "hello", client: "kristall-shell" });
                for (const key in root._surfaces) {
                    root._send({ op: "bind", surface: key, match: root._surfaces[key].match });
                    root._markDirty(key);
                }
            } else {
                root._lost();
            }
        }
        onError: root._lost()
        parser: SplitParser {
            onRead: data => root._handle(data)
        }
    }

    // reconnect with backoff 0.25 s .. 5 s; only runs while disconnected
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
