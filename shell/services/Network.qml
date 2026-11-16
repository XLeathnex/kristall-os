// SPDX-License-Identifier: GPL-3.0-or-later
// Network summary from NetworkManager (Quickshell's native Networking service): connected?,
// Wi-Fi present/enabled, current network name and strength. Never scans by itself.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Networking

Singleton {
    id: root

    readonly property bool available: Networking.backend === NetworkBackendType.NetworkManager
    readonly property var devices: Networking.devices ? Networking.devices.values : []
    readonly property var wifiDevice: {
        for (const d of devices)
            if (d.type === DeviceType.Wifi)
                return d;
        return null;
    }
    readonly property bool hasWifi: wifiDevice !== null
    readonly property bool wifiEnabled: Networking.wifiEnabled
    readonly property var wifiNetwork: {
        if (!wifiDevice || !wifiDevice.networks)
            return null;
        for (const n of wifiDevice.networks.values)
            if (n.connected)
                return n;
        return null;
    }
    readonly property bool wifiConnected: wifiNetwork !== null
    readonly property string wifiName: wifiNetwork ? wifiNetwork.name : ""
    readonly property real wifiStrength: wifiNetwork ? wifiNetwork.signalStrength : 0   // 0..1
    readonly property bool wiredConnected: {
        for (const d of devices)
            if (d.type !== DeviceType.Wifi && d.connected)
                return true;
        return false;
    }
    readonly property bool connected: wifiConnected || wiredConnected
    // 0 = none, 1..3 bars
    readonly property int wifiBars: !wifiConnected ? 0 : wifiStrength > 0.66 ? 3 : wifiStrength > 0.33 ? 2 : 1

    function setWifiEnabled(on) {
        Networking.wifiEnabled = on;
    }
}
