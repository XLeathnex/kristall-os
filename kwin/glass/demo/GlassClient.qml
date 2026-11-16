// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall glass: reference QML client for glass.sock (docs/contracts/glass.md).
// One connection per shell process. Remembers every bound surface and its last shapes and
// replays them after a reconnect, so callers never deal with the socket's lifecycle.
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

    // Coalesce: at most one "shapes" message per surface per event-loop turn.
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
            if (ev.theme) root.theme = ev.theme;
            if (ev.quality) root.quality = ev.quality;
            if (ev.glass !== undefined) root.glass = ev.glass;
            if (ev.reduceTransparency !== undefined) root.reduceTransparency = ev.reduceTransparency;
            break;
        case "legibility":
            root.legibility(ev.surface, ev.shape, ev.scheme, ev.luminance);
            break;
        case "bound":
            root.bound(ev.surface, ev.windows);
            break;
        case "error":
            console.warn("glass:", ev.code, ev.message, ev.surface || "");
            break;
        }
    }

    Socket {
        id: sock
        path: root.socketPath
        connected: true
        onConnectedChanged: {
            if (connected) {
                root._backoff = 250;
                root._send({ op: "hello", client: "kristall-shell" });
                for (const key in root._surfaces) {
                    root._send({ op: "bind", surface: key, match: root._surfaces[key].match });
                    root._markDirty(key);
                }
            } else {
                root.active = false;
                root.state = "absent";
                retry.start();
            }
        }
        onError: {
            root.active = false;
            root.state = "absent";
            retry.start();
        }
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
            sock.connected = false;
            sock.connected = true;
        }
    }
}
