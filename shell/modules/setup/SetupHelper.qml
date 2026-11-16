// SPDX-License-Identifier: GPL-3.0-or-later
// Runs the commands behind the Setup Assistant — kristall-setup-helper (displays, touchpads,
// Wi-Fi with a password, about), kristall-power, kristall-apps — one process per call, JSON
// lines on stdout, the last line the result. Watches the files other components publish
// (apps installation progress, the keyboard plugin's status) with inotify; nothing polls.
import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: h
    readonly property string tool: Quickshell.env("KRISTALL_SETUP_HELPER") || "kristall-setup-helper"
    readonly property string powerTool: Quickshell.env("KRISTALL_POWER_CMD") || "kristall-power"
    readonly property string runtime: Quickshell.env("XDG_RUNTIME_DIR") || "/tmp"

    property var touchpads: []
    property var displays: []
    property var power: null           // kristall-power status --json
    property var apps: null            // /var/lib/kristall/apps/status.json
    property var keyboard: null        // $XDG_RUNTIME_DIR/kristall/keyboard.json

    // run(argv, cb(result, events), {stdin, onEvent})
    function run(argv, cb, opts) {
        const p = runner.createObject(h, { command: argv, callback: cb || null, opts: opts || {} });
        p.running = true;
        return p;
    }

    function refresh() {
        run([tool, "touchpads"], r => h.touchpads = r && r.touchpads ? r.touchpads : []);
        run([tool, "displays"], r => h.displays = r && r.outputs ? r.outputs : []);
        run([powerTool, "status", "--json"], (r, ev, raw) => h.power = raw);
        appsFile.reload();
        kbFile.reload();
    }

    property Component runner: Component {
        Process {
            id: p
            property var callback: null
            property var opts: ({})
            property var events: []
            property var last: null
            stdinEnabled: opts.stdin !== undefined
            stdout: SplitParser {
                onRead: line => {
                    let m = null;
                    try {
                        m = JSON.parse(line);
                    } catch (e) {
                        return;
                    }
                    if (m && m.event === "result") {
                        p.last = m;
                    } else {
                        p.events.push(m);
                        if (p.opts.onEvent)
                            p.opts.onEvent(m);
                        if (!m.event)
                            p.last = m;       // tools that print one JSON object (kristall-power)
                    }
                }
            }
            onStarted: if (opts.stdin !== undefined) { write(opts.stdin + "\n"); }
            onExited: code => {
                if (p.callback)
                    p.callback(p.last && p.last.event === "result" ? p.last : (code === 0 ? { ok: true } : { ok: false, code: code }), p.events, p.last);
                p.destroy();
            }
        }
    }

    FileView {
        id: appsFile
        path: Quickshell.env("KRISTALL_APPS_STATUS") || "/var/lib/kristall/apps/status.json"
        printErrors: false
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                h.apps = JSON.parse(text());
            } catch (e) {
                h.apps = null;
            }
        }
        onLoadFailed: h.apps = null
    }
    FileView {
        id: kbFile
        path: h.runtime + "/kristall/keyboard.json"
        printErrors: false
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                h.keyboard = JSON.parse(text());
            } catch (e) {
                h.keyboard = null;
            }
        }
        onLoadFailed: h.keyboard = null
    }
}
