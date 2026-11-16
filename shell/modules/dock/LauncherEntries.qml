// SPDX-License-Identifier: GPL-3.0-or-later
// Badges and progress apps publish through the Unity launcher API (session bus), via one small
// helper process that sleeps in its main loop until an app sends an update.
import QtQuick
import Quickshell
import Quickshell.Io
import "common"

Scope {
    id: entries
    property var byKey: ({})       // app key -> {count, countVisible, progress, progressVisible, urgent}
    readonly property string helper: Quickshell.env("KRISTALL_DOCK_LAUNCHER_HELPER") || (Quickshell.shellDir + "/modules/dock/helper/kristall-dock-launcher-entries")
    property int _backoff: 2000

    function _apply(m) {
        if (!m.app)
            return;
        const key = AppCatalog.keyForAppId(m.app);
        const b = Object.assign({}, byKey);
        if (m.gone)
            delete b[key];
        else
            b[key] = m;
        byKey = b;
    }

    Process {
        id: proc
        command: [entries.helper]
        running: true
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => {
                try {
                    entries._apply(JSON.parse(line));
                } catch (e) {
                    console.info("dock: launcher helper said", line);
                }
            }
        }
        onExited: code => {
            if (entries._backoff <= 60000) {
                console.info("dock: launcher-entry helper exited (" + code + "), restarting");
                retry.start();
            }
        }
    }
    Timer {
        id: retry
        interval: entries._backoff
        onTriggered: {
            entries._backoff *= 2;
            proc.running = true;
        }
    }
}
