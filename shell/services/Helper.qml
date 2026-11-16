// SPDX-License-Identifier: GPL-3.0-or-later
// The shell's single long-lived helper process (helper/kristall-shell-helper), JSON lines over
// stdin/stdout. Services use request()/the event signal; nobody else starts processes for queries.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    property bool ready: false
    property var last: ({})             // last event of each kind, for services created later
    signal event(var ev)

    readonly property string path: Quickshell.env("KRISTALL_SHELL_HELPER") || (Quickshell.shellDir + "/helper/kristall-shell-helper")
    property int _nextId: 1
    property var _callbacks: ({})
    property var _queue: []
    property int _backoff: 500

    // op: string, params: object, cb: optional function(reply)
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
            console.warn("kristall-shell-helper: bad line", line);
            return;
        }
        if (m.event === "ready") {
            ready = true;
            _backoff = 500;
            const q = _queue;
            _queue = [];
            for (const l of q)
                proc.write(l);
        }
        if (m.id !== undefined && m.event === undefined) {
            const cb = _callbacks[m.id];
            delete _callbacks[m.id];
            if (cb)
                cb(m);
            return;
        }
        if (m.event) {
            const l = Object.assign({}, last);
            l[m.event] = m;
            last = l;
        }
        root.event(m);
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
            console.warn("kristall-shell-helper exited with", code, "- restarting in", root._backoff, "ms");
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
