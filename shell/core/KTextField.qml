// SPDX-License-Identifier: GPL-3.0-or-later
// Text field (28 px, radius 8) or search field (`search: true`: capsule, magnifier, clear button).
// The surface that hosts a focused field needs keyboard focus (layer-shell OnDemand/Exclusive).
import QtQuick

Item {
    id: f
    property alias text: input.text
    property alias input: input
    property string placeholder: ""
    property bool search: false
    property string scheme: Theme.scheme
    property bool password: false
    property string showState: ""     // gallery: "focus"
    signal accepted()
    signal escaped()

    implicitWidth: 220
    implicitHeight: Theme.size.field
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.EditableText
    Accessible.name: placeholder

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: f.search ? height / 2 : Theme.radius.field
        color: Theme.color(f.scheme, "fieldBackground")
        border.width: 1 / Math.max(1, f.Window.window ? f.Window.window.devicePixelRatio : 1)
        border.color: Theme.color(f.scheme, "border")
    }
    KFocusRing { target: f; visible: input.activeFocus || f.showState === "focus"; targetRadius: bg.radius; scheme: f.scheme }
    KIcon {
        id: glass
        visible: f.search
        x: 9
        anchors.verticalCenter: parent.verticalCenter
        size: 14
        name: "magnifying-glass"
        color: Theme.color(f.scheme, "secondaryLabel")
    }
    TextInput {
        id: input
        anchors.verticalCenter: parent.verticalCenter
        x: f.search ? 29 : 9
        width: f.width - x - (clear.visible ? 28 : 9)
        clip: true
        font.family: Theme.fontFamily
        font.pixelSize: Theme.type.body.size
        font.letterSpacing: Theme.type.body.tracking
        color: Theme.color(f.scheme, "label")
        selectionColor: Qt.alpha(Theme.accentFor(f.scheme), 0.35)
        selectedTextColor: Theme.color(f.scheme, "label")
        renderType: Text.NativeRendering
        echoMode: f.password ? TextInput.Password : TextInput.Normal
        selectByMouse: true
        onAccepted: f.accepted()
        Keys.onEscapePressed: f.escaped()
        KText {
            anchors.verticalCenter: parent.verticalCenter
            visible: input.text === "" && !input.preeditText
            text: f.placeholder
            level: "tertiaryLabel"
            scheme: f.scheme
        }
    }
    Rectangle {
        id: clear
        visible: f.search && input.text !== ""
        width: 16; height: 16; radius: 8
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: parent.right
        anchors.rightMargin: 7
        color: Theme.color(f.scheme, "tertiaryLabel")
        KIcon { anchors.centerIn: parent; size: 9; name: "bold/x"; color: f.scheme === "dark" ? "#000000" : "#FFFFFF" }
        TapHandler { onTapped: { input.text = ""; input.forceActiveFocus(); } }
    }
    TapHandler { onTapped: input.forceActiveFocus(Qt.MouseFocusReason) }
    HoverHandler { cursorShape: Qt.IBeamCursor }
}
