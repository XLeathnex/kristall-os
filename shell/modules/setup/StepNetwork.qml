// SPDX-License-Identifier: GPL-3.0-or-later
// Getting online (shown only when the computer is offline): the Wi-Fi networks around, known and
// open ones join at once, a new protected one asks for its password in our own sheet. Scans only
// while this step is on screen. Continue always works — nothing in the setup needs the internet.
import QtQuick
import Quickshell
import Quickshell.Networking as QsNet
import qs.core
import qs.services

StepBase {
    id: st
    icon: "wifi-high"
    title: Strings.t("setup.network.title")
    subtitle: Network.connected ? Strings.t("setup.network.online") : Strings.t("setup.network.subtitle")
    primaryText: Network.connected ? Strings.t("setup.continue") : Strings.t("setup.skip")
    implicitHeight: Math.max(column.implicitHeight, 300)

    property var asking: null          // {name, security} while the password sheet is shown
    property string status: ""         // "" | connecting | wrong | short | failed
    Component.onCompleted: if (Network.wifiDevice) Network.wifiDevice.scannerEnabled = true
    Component.onDestruction: if (Network.wifiDevice) Network.wifiDevice.scannerEnabled = false

    readonly property var networks: {
        const d = Network.wifiDevice;
        if (!d || !d.networks || !Network.wifiEnabled)
            return [];
        const list = d.networks.values.filter(n => n.name && n.name !== "");
        list.sort((a, b) => (b.connected - a.connected) || (b.known - a.known) || (b.signalStrength - a.signalStrength) || a.name.localeCompare(b.name));
        return list.slice(0, 8);
    }
    function secured(n) {
        return n.security !== QsNet.WifiSecurityType.Open && n.security !== QsNet.WifiSecurityType.Owe;
    }
    function securityKey(n) {
        const s = n.security;
        if (!secured(n))
            return "none";
        if (s === QsNet.WifiSecurityType.Sae)
            return "sae";
        if (s === QsNet.WifiSecurityType.Wpa2Eap || s === QsNet.WifiSecurityType.WpaEap || s === QsNet.WifiSecurityType.Wpa3SuiteB192
            || s === QsNet.WifiSecurityType.Leap || s === QsNet.WifiSecurityType.DynamicWep || s === QsNet.WifiSecurityType.StaticWep)
            return "unsupported";
        return "wpa-psk";
    }
    function bars(s) {
        return s > 0.66 ? "bold/wifi-high" : s > 0.33 ? "bold/wifi-medium" : s > 0.05 ? "bold/wifi-low" : "bold/wifi-none";
    }
    function choose(n) {
        if (n.connected || n.stateChanging)
            return;
        const sec = securityKey(n);
        if (n.known || sec === "none") {
            n.connect();
            return;
        }
        status = "";
        asking = { name: n.name, security: sec };
        Qt.callLater(() => { if (field.visible) field.input.forceActiveFocus(); });
    }
    function join() {
        if (asking.security !== "none" && field.text.length < 8) {
            status = "short";
            return;
        }
        status = "connecting";
        const ssid = asking.name;
        ctl.helper.run([ctl.helper.tool, "wifi-connect", ssid, asking.security], r => {
            if (!st.asking || st.asking.name !== ssid)
                return;
            if (r.ok) {
                st.asking = null;
                st.status = "";
            } else {
                st.status = r.error === "password" ? "wrong" : "failed";
            }
        }, { stdin: field.text });
    }
    function keyPressed(ev) {
        if (asking && ev.key === Qt.Key_Escape) {
            asking = null;
            return true;
        }
        return false;
    }
    function primary() {
        if (asking && asking.security !== "unsupported" && !Network.connected) {
            join();
            return;
        }
        ctl.next();
    }

    Column {
        id: column
        width: parent.width
        spacing: 6
        visible: st.asking === null

        KText {
            visible: !Network.hasWifi
            width: parent.width
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            text: Strings.t("setup.network.noWifi")
            scheme: st.scheme
        }
        Column {
            visible: Network.hasWifi && !Network.wifiEnabled
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 12
            KText { anchors.horizontalCenter: parent.horizontalCenter; text: Strings.t("setup.network.off"); scheme: st.scheme }
            KButton {
                objectName: "setup.network.turnOn"
                anchors.horizontalCenter: parent.horizontalCenter
                text: Strings.t("setup.network.turnOn")
                scheme: st.scheme
                onClicked: Network.setWifiEnabled(true)
            }
        }
        KText {
            visible: Network.hasWifi && Network.wifiEnabled && st.networks.length === 0
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: Strings.t("setup.network.searching")
            level: "secondaryLabel"
            scheme: st.scheme
        }
        Rectangle {          // the list, as a rounded group (like a settings list on the Mac)
            visible: st.networks.length > 0
            width: parent.width
            height: list.implicitHeight + 8
            radius: 14
            color: Theme.color(st.scheme, "fill")
            Column {
                id: list
                y: 4
                width: parent.width
                Repeater {
                    model: ScriptModel { values: st.networks }
                    KListRow {
                        required property var modelData
                        objectName: "setup.wifi:" + modelData.name
                        width: list.width - 8
                        x: 4
                        icon: st.bars(modelData.signalStrength)
                        title: modelData.name
                        detail: modelData.stateChanging || modelData.state === QsNet.NetworkState.Connecting ? Strings.t("setup.network.connecting")
                                : modelData.connected ? Strings.t("setup.network.connected")
                                : modelData.known ? Strings.t("setup.network.known") : ""
                        scheme: st.scheme
                        onActivated: st.choose(modelData)
                        KIcon {
                            visible: st.secured(modelData)
                            anchors.verticalCenter: parent.verticalCenter
                            name: "fill/lock-simple"
                            size: 13
                            color: Theme.color(st.scheme, "secondaryLabel")
                        }
                    }
                }
            }
        }
    }

    // our own password sheet
    Column {
        id: sheet
        visible: st.asking !== null
        width: parent.width
        spacing: 12
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: st.asking ? Strings.t("setup.network.password.title", { name: st.asking.name }) : ""
            textStyle: "title3"
            emphasized: true
            scheme: st.scheme
        }
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: st.asking && st.asking.security === "unsupported" ? Strings.t("setup.network.unsupported") : Strings.t("setup.network.password.text")
            level: "secondaryLabel"
            scheme: st.scheme
        }
        KTextField {
            id: field
            objectName: "setup.wifi.password"
            visible: st.asking !== null && st.asking.security !== "unsupported"
            anchors.horizontalCenter: parent.horizontalCenter
            width: 320
            password: !showToggle.checked
            placeholder: Strings.t("setup.network.password.field")
            enabled: st.status !== "connecting"
            scheme: st.scheme
            onAccepted: st.join()
            onEscaped: st.asking = null
            onTextChanged: if (st.status === "wrong" || st.status === "short") st.status = ""
        }
        Row {
            visible: field.visible
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            KToggle {
                id: showToggle
                property bool on: false
                checked: on
                scale: 0.8
                scheme: st.scheme
                label: Strings.t("setup.network.password.show")
                onToggled: v => on = v
            }
            KText { anchors.verticalCenter: parent.verticalCenter; text: Strings.t("setup.network.password.show"); textStyle: "subheadline"; scheme: st.scheme }
        }
        KText {
            visible: st.status !== ""
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: st.status === "connecting" ? Strings.t("setup.network.connecting")
                  : st.status === "wrong" ? Strings.t("setup.network.password.wrong")
                  : st.status === "short" ? Strings.t("setup.network.password.short")
                  : Strings.t("setup.network.password.failed")
            color: st.status === "connecting" ? Theme.color(st.scheme, "secondaryLabel") : Theme.color(st.scheme, "destructive")
            textStyle: "callout"
            scheme: st.scheme
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            KButton {
                objectName: "setup.wifi.cancel"
                text: Strings.t("common.cancel")
                scheme: st.scheme
                onClicked: st.asking = null
            }
            KButton {
                objectName: "setup.wifi.join"
                visible: field.visible
                text: Strings.t("setup.network.password.join")
                variant: "accent"
                enabled: st.status !== "connecting"
                scheme: st.scheme
                onClicked: st.join()
            }
        }
    }
}
