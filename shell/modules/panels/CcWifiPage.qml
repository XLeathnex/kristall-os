// SPDX-License-Identifier: GPL-3.0-or-later
// Expanded Wi-Fi module: switch, the networks around (current first, then known, then others by
// signal), lock for protected ones. Known and open networks connect at once; a new protected one
// asks for its password in our own sheet (CcPasswordPage). Scans only while this is on screen.
import QtQuick
import Quickshell
import Quickshell.Networking as QsNet
import qs.core
import qs.services

Column {
    id: wp
    property string scheme: Theme.scheme
    property var cc: null
    width: PanelMetrics.ccInner
    spacing: 4

    Component.onCompleted: Hw.wifiScanning = true
    Component.onDestruction: Hw.wifiScanning = false

    function choose(net) {
        if (net.connected || net.stateChanging)
            return;
        const sec = Hw.securityKey(net);
        if (net.known || sec === "none") {
            net.connect();
            return;
        }
        cc.passwordNetwork = { name: net.name, security: sec };
        cc.openPage("password");
    }

    CcHeader {
        title: Strings.t("panels.wifi")
        scheme: wp.scheme
        hasToggle: true
        toggleName: "cc.wifi.switch"
        checked: Network.wifiEnabled
        onToggled: on => Network.setWifiEnabled(on)
        onBack: wp.cc.back()
    }
    CcNote {
        visible: !Network.wifiEnabled
        text: Strings.t("panels.wifi.isOff")
        scheme: wp.scheme
    }
    CcSection {
        visible: Network.wifiEnabled
        text: Strings.t("panels.wifi.networks")
        scheme: wp.scheme
    }
    CcNote {
        visible: Network.wifiEnabled && Hw.networks.length === 0
        text: Strings.t("panels.wifi.searching")
        scheme: wp.scheme
    }
    KScrollArea {
        visible: Network.wifiEnabled && Hw.networks.length > 0
        width: parent.width
        height: Math.min(netColumn.implicitHeight, PanelMetrics.ccListMax)
        contentHeight: netColumn.implicitHeight
        scheme: wp.scheme
        Column {
            id: netColumn
            width: PanelMetrics.ccInner
            Repeater {
                model: ScriptModel { values: Hw.networks }
                CcItemRow {
                    required property var modelData
                    objectName: "cc.wifi.net:" + modelData.name
                    width: PanelMetrics.ccInner
                    icon: Hw.wifiIcon(modelData.signalStrength)
                    on: modelData.connected
                    title: modelData.name
                    subtitle: modelData.stateChanging || modelData.state === QsNet.NetworkState.Connecting ? Strings.t("panels.wifi.connecting")
                              : modelData.connected ? Strings.t("panels.wifi.connected")
                              : modelData.known ? Strings.t("panels.wifi.known") : ""
                    trailingIcon: Hw.secured(modelData) ? "fill/lock-simple" : ""
                    scheme: wp.scheme
                    onActivated: wp.choose(modelData)
                }
            }
        }
    }
    CcFooter {
        text: Strings.t("panels.wifi.settings")
        kcm: "kcm_networkmanagement"
        scheme: wp.scheme
        onActivated: wp.cc.closeRequested()
    }
}
