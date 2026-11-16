// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Bluetooth
import Quickshell.Networking as QsNet
import Quickshell.Services.Pipewire
import qs.services


// What Control Center controls beyond the shell's summary services (qs.services Audio, Network,
// BluetoothStatus, Power): the Wi-Fi network list, Bluetooth devices, audio outputs and who
// records from the microphone, display and keyboard backlight, Night Light. Values are pushed by
// their services; writes from sliders are coalesced to one per frame.
Singleton {
    id: root

    // ---- Wi-Fi ---------------------------------------------------------------------------------
    property bool wifiScanning: false           // true while the Wi-Fi list is on screen
    onWifiScanningChanged: if (Network.wifiDevice) Network.wifiDevice.scannerEnabled = wifiScanning
    readonly property var networks: {
        const d = Network.wifiDevice;
        if (!d || !d.networks || !Network.wifiEnabled)
            return [];
        const list = d.networks.values.filter(n => n.name && n.name !== "");
        list.sort((a, b) => (b.connected - a.connected) || (b.known - a.known) || (b.signalStrength - a.signalStrength) || a.name.localeCompare(b.name));
        return list;
    }
    function bars(strength) {
        return strength > 0.66 ? 3 : strength > 0.33 ? 2 : strength > 0.05 ? 1 : 0;
    }
    function wifiIcon(strength) {
        const b = bars(strength);
        return b === 3 ? "bold/wifi-high" : b === 2 ? "bold/wifi-medium" : b === 1 ? "bold/wifi-low" : "bold/wifi-none";
    }
    function secured(net) {
        return net.security !== QsNet.WifiSecurityType.Open && net.security !== QsNet.WifiSecurityType.Owe;
    }
    // what our password sheet can join: personal WPA/WPA2/WPA3 (and an unknown one, most likely
    // WPA2); enterprise and WEP networks go to the Wi-Fi settings
    function securityKey(net) {
        const s = net.security;
        if (!secured(net))
            return "none";
        if (s === QsNet.WifiSecurityType.Sae)
            return "sae";
        if (s === QsNet.WifiSecurityType.Wpa2Eap || s === QsNet.WifiSecurityType.WpaEap || s === QsNet.WifiSecurityType.Wpa3SuiteB192
            || s === QsNet.WifiSecurityType.Leap || s === QsNet.WifiSecurityType.DynamicWep || s === QsNet.WifiSecurityType.StaticWep)
            return "unsupported";
        return "wpa-psk";
    }

    // ---- Bluetooth -----------------------------------------------------------------------------
    readonly property var btDevices: {
        const a = BluetoothStatus.adapter;
        if (!a || !a.devices || !BluetoothStatus.enabled)
            return [];
        const list = a.devices.values.filter(d => d.paired || d.bonded || d.connected);
        list.sort((x, y) => (y.connected - x.connected) || (x.name || x.deviceName).localeCompare(y.name || y.deviceName));
        return list;
    }
    function btIcon(dev) {
        const i = dev.icon || "";
        if (i.indexOf("headset") >= 0 || i.indexOf("headphone") >= 0 || i.indexOf("audio") >= 0)
            return "headphones";
        if (i.indexOf("mouse") >= 0)
            return "mouse";
        if (i.indexOf("keyboard") >= 0)
            return "keyboard";
        if (i.indexOf("phone") >= 0)
            return "device-mobile";
        if (i.indexOf("gaming") >= 0 || i.indexOf("joystick") >= 0)
            return "game-controller";
        if (i.indexOf("computer") >= 0)
            return "laptop";
        return "bluetooth";
    }

    // ---- audio outputs and microphone use ------------------------------------------------------
    readonly property var nodes: Pipewire.ready && Pipewire.nodes ? Pipewire.nodes.values : []
    readonly property var sinks: nodes.filter(n => n.audio !== null && n.isSink && !n.isStream)
    readonly property var recorders: nodes.filter(n => n.audio !== null && n.isStream && (n.type & PwNodeType.AudioInStream) === PwNodeType.AudioInStream
                                                       && !String((n.properties || {})["stream.monitor"] || "").length)
    readonly property bool micInUse: recorders.length > 0
    readonly property string micUser: {
        if (!micInUse)
            return "";
        const p = recorders[0].properties || {};
        return p["application.name"] || recorders[0].description || recorders[0].name || "";
    }
    // (recording streams are not bound — binding them costs a PipeWire round trip per stream and
    // is not needed: a stream's name is the recording app's name for PipeWire and Pulse clients)
    function sinkName(n) {
        return n.description || n.nickname || n.name;
    }
    function selectSink(n) {
        Pipewire.preferredDefaultAudioSink = n;
    }
    PwObjectTracker {
        objects: root.sinks
    }

    // ---- display / keyboard backlight, Night Light (helper) ------------------------------------
    readonly property bool hasBacklight: PanelsHelper.brightness.available === true
    readonly property real brightness: hasBacklight ? PanelsHelper.brightness.value / Math.max(1, PanelsHelper.brightness.max) : 0
    readonly property bool hasKbdLight: PanelsHelper.kbd.available === true
    readonly property real kbdLevel: hasKbdLight ? PanelsHelper.kbd.value / Math.max(1, PanelsHelper.kbd.max) : 0
    readonly property bool hasNightLight: PanelsHelper.night.available === true
    readonly property bool nightLightOn: hasNightLight && PanelsHelper.night.enabled === true && PanelsHelper.night.inhibited !== true

    property real _pendingBrightness: -1
    property real _pendingKbd: -1
    function setBrightness(f) {
        _pendingBrightness = Math.max(0, Math.min(1, f));
        Qt.callLater(_flush);
    }
    function setKbd(f) {
        _pendingKbd = Math.max(0, Math.min(1, f));
        Qt.callLater(_flush);
    }
    function _flush() {
        if (_pendingBrightness >= 0 && hasBacklight) {
            // never all the way to black from the slider (the Mac keeps the screen readable)
            const max = PanelsHelper.brightness.max;
            PanelsHelper.request("brightness.set", { value: Math.max(Math.round(max * 0.01), 1, Math.round(_pendingBrightness * max)) });
        }
        if (_pendingKbd >= 0 && hasKbdLight)
            PanelsHelper.request("kbd.set", { value: Math.round(_pendingKbd * PanelsHelper.kbd.max) });
        _pendingBrightness = -1;
        _pendingKbd = -1;
    }
    function setNightLight(on) {
        PanelsHelper.request("nightlight.set", { on: on });
    }
}
