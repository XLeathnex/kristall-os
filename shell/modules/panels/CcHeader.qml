// SPDX-License-Identifier: GPL-3.0-or-later
// Header of an expanded Control Center module: back chevron, title, optional switch on the right.
import QtQuick
import qs.core
import qs.services

Item {
    id: hd
    property string title: ""
    property string scheme: Theme.scheme
    property bool hasToggle: false
    property bool checked: false
    property string toggleName: "toggle"
    signal back()
    signal toggled(bool on)

    implicitWidth: PanelMetrics.ccInner
    implicitHeight: 32

    KButton {
        id: backButton
        objectName: "cc.back"
        anchors.verticalCenter: parent.verticalCenter
        icon: "bold/caret-left"
        variant: "plain"
        size: "small"
        scheme: hd.scheme
        Accessible.name: Strings.t("panels.back")
        onClicked: hd.back()
    }
    KText {
        anchors.verticalCenter: parent.verticalCenter
        x: backButton.width + 6
        width: parent.width - x - (sw.visible ? sw.width + 8 : 0)
        text: hd.title
        textStyle: "title3"
        emphasized: true
        elide: Text.ElideRight
        scheme: hd.scheme
    }
    KToggle {
        id: sw
        objectName: hd.toggleName
        visible: hd.hasToggle
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        scheme: hd.scheme
        label: hd.title
        checked: hd.checked             // core KToggle: shows the request at once, then the real state
        onToggled: on => hd.toggled(on)
    }
}
