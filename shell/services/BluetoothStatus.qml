// SPDX-License-Identifier: GPL-3.0-or-later
// Bluetooth on/off (BlueZ through Quickshell's native service). No adapter => available false.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Bluetooth

Singleton {
    id: root

    readonly property var adapter: Bluetooth.defaultAdapter
    readonly property bool available: adapter !== null
    readonly property bool enabled: available && adapter.enabled
    readonly property int connectedCount: {
        if (!available || !adapter.devices)
            return 0;
        let n = 0;
        for (const d of adapter.devices.values)
            if (d.connected)
                n++;
        return n;
    }

    function setEnabled(on) {
        if (available)
            adapter.enabled = on;
    }
}
