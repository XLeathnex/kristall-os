// SPDX-License-Identifier: GPL-3.0-or-later
// A row in an expanded Control Center module (networks, devices, outputs, options): a 26-px
// circle with a symbol (accent when `on`), title, optional subtitle, trailing symbol or check.
import QtQuick
import qs.core

Item {
    id: ir
    property string icon: ""
    property string title: ""
    property string subtitle: ""
    property bool on: false
    property bool circle: true
    property bool checked: false
    property string trailingIcon: ""
    property string scheme: Theme.scheme
    signal activated()

    implicitWidth: PanelMetrics.ccInner
    implicitHeight: subtitle !== "" ? 40 : 34
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.ListItem
    Accessible.name: title + (subtitle !== "" ? ", " + subtitle : "")
    Accessible.checked: checked || on
    Keys.onReturnPressed: activated()
    Keys.onSpacePressed: activated()
    function activate() { activated(); }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.listRow
        color: hover.hovered && ir.enabled ? Theme.color(ir.scheme, "hover") : "transparent"
    }
    Rectangle {
        id: badge
        visible: ir.icon !== ""
        x: 6
        anchors.verticalCenter: parent.verticalCenter
        width: 26; height: 26; radius: 13
        color: !ir.circle ? "transparent" : ir.on ? Theme.accentFor(ir.scheme) : Theme.color(ir.scheme, "fillStrong")
        KIcon {
            anchors.centerIn: parent
            size: 14
            name: ir.icon
            color: ir.on && ir.circle ? Theme.accentContent : Theme.color(ir.scheme, "label")
        }
    }
    Column {
        anchors.verticalCenter: parent.verticalCenter
        x: badge.visible ? 40 : 10
        width: ir.width - x - 34
        KText { width: parent.width; text: ir.title; textStyle: "body"; elide: Text.ElideRight; scheme: ir.scheme }
        KText {
            visible: ir.subtitle !== ""
            width: parent.width
            text: ir.subtitle
            textStyle: "subheadline"
            level: "secondaryLabel"
            elide: Text.ElideRight
            scheme: ir.scheme
        }
    }
    KIcon {
        visible: ir.checked || ir.trailingIcon !== ""
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        size: 14
        name: ir.checked ? "bold/check" : ir.trailingIcon
        color: ir.checked ? Theme.accentFor(ir.scheme) : Theme.color(ir.scheme, "secondaryLabel")
    }
    KFocusRing { targetRadius: Theme.radius.listRow; scheme: ir.scheme }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: { ir.forceActiveFocus(Qt.MouseFocusReason); ir.activated(); } }
}
