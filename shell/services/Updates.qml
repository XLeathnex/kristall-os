// SPDX-License-Identifier: GPL-3.0-or-later
// System update status (docs/contracts/update.md), pushed by the helper whenever
// /var/lib/kristall/update/state.json changes (inotify). Read-only here.
pragma Singleton
import QtQuick
import Quickshell

Singleton {
    id: root

    property var status: ({ schema: 1, state: "unknown" })
    readonly property string state: status.state || "unknown"
    readonly property bool restartRequired: state === "restart-required" || state === "rollback-queued"
    readonly property string stagedVersion: status.staged ? (status.staged.version || "") : ""

    function refresh() { Helper.request("update.refresh", {}); }
    Component.onCompleted: if (Helper.last.update) status = Helper.last.update.status

    Connections {
        target: Helper
        function onEvent(ev) {
            if (ev.event === "update" && ev.status)
                root.status = ev.status;
        }
    }
}
