// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io


// The panels module's helper process (helper/kristall-panels-helper), JSON lines over
// stdin/stdout, and the state it reports: display and keyboard backlight (PowerDevil), Night
// Light (KWin), screen lock, the on-screen displays plasmashell announces, who owns the
// notification service. Without the helper (or PowerDevil/KWin) every `available` stays false
// and the matching controls are not shown.
Singleton {
    id: root

    property bool ready: false
    property var brightness: ({ available: false })      // {available, value, max, display, label}
    property var kbd: ({ available: false })             // {available, value, max}
    property var night: ({ available: false })          // {available, enabled, running, inhibited, ours}
    property bool locked: false
    property var notifyOwner: ({ owned: false, mine: false })
    signal osd(var ev)
    signal wifi(var ev)

    readonly property string path: Quickshell.env("KRISTALL_PANELS_HELPER") || (Quickshell.shellDir + "/modules/panels/helper/kristall-panels-helper")
    property int _nextId: 1
    property var _callbacks: ({})
    property var _queue: []
    property int _backoff: 500

    function request(op, params, cb) {
        const msg = Object.assign({ op: op }, params || {});
        if (cb) {
            msg.id = _nextId++;
            _callbacks[msg.id] = cb;
        }
        const line = JSON.stringify(msg) + "\n";
        if (proc.running && ready)
            proc.write(line);
        else
            _queue.push(line);
    }

    function _handle(line) {
        let m;
        try {
            m = JSON.parse(line);
        } catch (e) {
            console.warn("kristall-panels-helper: bad line", line);
            return;
        }
        if (m.id !== undefined && m.event === undefined) {
            const cb = _callbacks[m.id];
            delete _callbacks[m.id];
            if (cb)
                cb(m);
            return;
        }
        switch (m.event) {
        case "ready":
            ready = true;
            _backoff = 500;
            for (const l of _queue)
                proc.write(l);
            _queue = [];
            break;
        case "brightness": brightness = m; break;
        case "kbd": kbd = m; break;
        case "nightlight": night = m; break;
        case "locked": locked = m.locked === true; break;
        case "notifyOwner": notifyOwner = m; break;
        case "osd": root.osd(m); break;
        case "wifi": root.wifi(m); break;
        }
    }

    Process {
        id: proc
        command: [root.path]
        running: true
        stdinEnabled: true
        stdout: SplitParser {
            onRead: data => root._handle(data)
        }
        stderr: SplitParser {
            onRead: data => console.info(data)
        }
        onExited: (code, status) => {
            root.ready = false;
            root.brightness = { available: false };
            root.kbd = { available: false };
            root.night = { available: false };
            console.warn("kristall-panels-helper exited with", code, "- restarting in", root._backoff, "ms");
            restart.start();
        }
    }
    Timer {
        id: restart
        interval: root._backoff
        onTriggered: {
            root._backoff = Math.min(root._backoff * 2, 30000);
            proc.running = true;
        }
    }
}
