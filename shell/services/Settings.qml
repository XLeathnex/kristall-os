// SPDX-License-Identifier: GPL-3.0-or-later
// The shared settings file (docs/contracts/settings.md), live. Reads through one long-lived
// `kristall-settings watch --full --initial`; writes with `kristall-settings set`.
// Values the shell needs have the same defaults as shell/image/settings.json so the shell
// still renders sensibly if the tool is missing (fail soft).
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    property var data: ({})
    property bool loaded: false
    readonly property string tool: Quickshell.env("KRISTALL_SETTINGS_CMD") || "kristall-settings"

    // Fallbacks = shell/image/settings.json (keep in sync; tests compare them).
    readonly property var fallback: ({
        appearance: { theme: "auto", glass: 0.3, accent: "blue", glassQuality: "auto", reduceTransparency: false },
        accessibility: { reduceMotion: false, increaseContrast: false },
        bar: { showSeconds: false, showDate: true, showDayOfWeek: true, showBatteryPercentage: false, clock: "auto",
               dimWhenMaximized: true, showAssistant: true, showControlCenter: true }
    })

    function _lookup(obj, parts) {
        let o = obj;
        for (const p of parts) {
            if (o === null || o === undefined || typeof o !== "object" || !(p in o))
                return undefined;
            o = o[p];
        }
        return o;
    }

    // get("appearance.glass", 0.3): effective value, else the shell's fallback, else `def`
    function get(path, def) {
        const parts = path.split(".");
        let v = _lookup(data, parts);
        if (v === undefined || v === null)
            v = _lookup(fallback, parts);
        return (v === undefined || v === null) ? def : v;
    }

    function set(path, value) {
        Quickshell.execDetached([tool, "set", path, JSON.stringify(value)]);
    }

    Process {
        id: watch
        command: [root.tool, "watch", "--full", "--initial"]
        running: true
        stdout: SplitParser {
            onRead: line => {
                try {
                    const m = JSON.parse(line);
                    if (m.settings !== undefined) {
                        root.data = m.settings;
                        root.loaded = true;
                    }
                } catch (e) {
                    console.warn("settings: bad line from kristall-settings:", line);
                }
            }
        }
        onExited: code => {
            console.warn("kristall-settings watch exited (" + code + "); retrying");
            retry.start();
        }
    }
    Timer {
        id: retry
        interval: 3000
        onTriggered: watch.running = true
    }
}
