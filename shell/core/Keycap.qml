// SPDX-License-Identifier: GPL-3.0-or-later
// A key as printed on the owner's keyboard (its legend), with the Mac name and glyph under it
// when it plays a Mac role. Drawn, not an image: a raised rounded key in the current scheme.
import QtQuick

Item {
    id: cap
    property string legend: ""
    property string glyph: ""          // ⌘ ⌥ ⌃ shown on the key's corner
    property string role: ""           // "Befehl" / "Command" under the key
    property bool lit: false           // highlighted (pressed in the "try it" moment)
    property string scheme: Theme.scheme
    property real keyWidth: Math.max(44, legendText.implicitWidth + 24)
    implicitWidth: Math.max(keyWidth, roleText.implicitWidth)
    implicitHeight: 44 + (role !== "" ? 6 + roleText.implicitHeight : 0)

    Rectangle {          // the key's lower edge (gives it depth)
        id: base
        anchors.horizontalCenter: parent.horizontalCenter
        width: cap.keyWidth
        height: 44
        radius: 8
        color: cap.scheme === "dark" ? Qt.rgba(0, 0, 0, 0.45) : Qt.rgba(0, 0, 0, 0.16)
    }
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        width: cap.keyWidth
        height: 41
        radius: 8
        color: cap.lit ? Theme.accentFor(cap.scheme) : (cap.scheme === "dark" ? "#3A3A3C" : "#FFFFFF")
        border.width: 1
        border.color: Theme.color(cap.scheme, "border")
        Behavior on color { ColorAnimation { duration: Theme.duration("micro", true) } }
        KText {
            id: legendText
            anchors.centerIn: parent
            text: cap.legend
            textStyle: "body"
            emphasized: true
            color: cap.lit ? "#FFFFFF" : Theme.color(cap.scheme, "label")
            scheme: cap.scheme
        }
        KText {
            visible: cap.glyph !== ""
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 4
            text: cap.glyph
            textStyle: "caption1"
            color: cap.lit ? "#FFFFFF" : Theme.color(cap.scheme, "secondaryLabel")
            scheme: cap.scheme
        }
    }
    KText {
        id: roleText
        visible: cap.role !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        y: 44 + 6
        text: cap.role
        textStyle: "caption1"
        level: "secondaryLabel"
        scheme: cap.scheme
    }
}
