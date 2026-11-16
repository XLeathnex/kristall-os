// SPDX-License-Identifier: GPL-3.0-or-later
// Our own sheet for a new protected Wi-Fi network: the password field, Cancel / Join. The helper
// creates the connection (NetworkManager); a refused password is said plainly and the field stays
// for another try; nothing with a wrong password is kept.
import QtQuick
import qs.core
import qs.services

Column {
    id: pp
    property string scheme: Theme.scheme
    property var cc: null
    readonly property var net: cc && cc.passwordNetwork ? cc.passwordNetwork : ({ name: "", security: "wpa-psk" })
    property string status: ""          // "" | "connecting" | "wrong" | "failed"
    property bool showPassword: false
    width: PanelMetrics.ccInner
    spacing: 10

    readonly property bool unsupported: net.security === "unsupported"

    function join() {
        if (field.text.length < 8 && net.security !== "none") {
            status = "short";
            return;
        }
        status = "connecting";
        PanelsHelper.request("wifi.connect", { ssid: net.name, password: field.text, security: net.security }, r => {
            if (!r.ok)
                pp.status = "failed";
        });
    }
    Connections {
        target: PanelsHelper
        function onWifi(ev) {
            if (ev.ssid !== pp.net.name)
                return;
            if (ev.state === "connected")
                pp.cc.openPage("wifi");
            else if (ev.state === "failed")
                pp.status = ev.reason === "password" ? "wrong" : "failed";
        }
    }
    Component.onCompleted: Qt.callLater(() => field.input.forceActiveFocus())

    CcHeader {
        title: pp.net.name
        scheme: pp.scheme
        onBack: pp.cc.back()
    }
    KText {
        width: parent.width
        leftPadding: 6
        rightPadding: 6
        text: pp.unsupported ? Strings.t("panels.wifi.unsupported") : Strings.t("panels.wifi.passwordPrompt", { name: pp.net.name })
        textStyle: "callout"
        wrapMode: Text.WordWrap
        lineHeightMode: Text.ProportionalHeight
        lineHeight: 1.0
        scheme: pp.scheme
    }
    KTextField {
        id: field
        objectName: "cc.wifi.password"
        visible: !pp.unsupported
        x: 6
        width: parent.width - 12
        password: !pp.showPassword
        placeholder: Strings.t("panels.wifi.password")
        scheme: pp.scheme
        enabled: pp.status !== "connecting"
        onAccepted: pp.join()
        onEscaped: pp.cc.back()
        onTextChanged: if (pp.status === "wrong" || pp.status === "short") pp.status = ""
    }
    Row {
        visible: !pp.unsupported
        x: 6
        spacing: 8
        KToggle { id: show; scheme: pp.scheme; label: Strings.t("panels.wifi.showPassword"); scale: 0.8; checked: pp.showPassword; onToggled: on => pp.showPassword = on }
        KText { anchors.verticalCenter: parent.verticalCenter; text: Strings.t("panels.wifi.showPassword"); textStyle: "subheadline"; scheme: pp.scheme }
    }
    KText {
        visible: pp.status !== ""
        width: parent.width
        leftPadding: 6
        rightPadding: 6
        text: pp.status === "connecting" ? Strings.t("panels.wifi.connecting")
              : pp.status === "wrong" ? Strings.t("panels.wifi.wrongPassword")
              : pp.status === "short" ? Strings.t("panels.wifi.shortPassword")
              : Strings.t("panels.wifi.failed")
        textStyle: "subheadline"
        level: pp.status === "connecting" ? "secondaryLabel" : "label"
        color: pp.status === "connecting" ? Theme.color(pp.scheme, "secondaryLabel") : Theme.color(pp.scheme, "destructive")
        wrapMode: Text.WordWrap
        lineHeightMode: Text.ProportionalHeight
        lineHeight: 1.0
        scheme: pp.scheme
    }
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 6
        spacing: 8
        KButton {
            objectName: "cc.wifi.cancel"
            text: Strings.t("common.cancel")
            scheme: pp.scheme
            onClicked: pp.cc.back()
        }
        KButton {
            objectName: pp.unsupported ? "cc.wifi.settingsButton" : "cc.wifi.join"
            text: pp.unsupported ? Strings.t("panels.wifi.settings") + Strings.t("common.ellipsis") : Strings.t("panels.wifi.join")
            variant: "accent"
            scheme: pp.scheme
            enabled: pp.unsupported || (field.text.length > 0 && pp.status !== "connecting")
            onClicked: {
                if (pp.unsupported) {
                    pp.cc.closeRequested();
                    Session.openSystemSettings("kcm_networkmanagement");
                } else {
                    pp.join();
                }
            }
        }
    }
    Item { width: 1; height: 2 }
}
