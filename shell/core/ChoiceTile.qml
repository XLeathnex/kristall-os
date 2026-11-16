// SPDX-License-Identifier: GPL-3.0-or-later
// A choice shown as a picture with a label under it (Light / Dark / Automatic, display sizes,
// scrolling). The selection lives with the caller (binding-safe): `chosen()` asks for it.
// Keyboard: Tab focus, Space/Return choose, ←/→ handled by the row.
import QtQuick

Item {
    id: tile
    property bool selected: false
    property string label: ""
    property string note: ""
    property string scheme: Theme.scheme
    property real previewWidth: 132
    property real previewHeight: 84
    property real previewRadius: 10
    default property alias preview: frame.data
    signal chosen()

    implicitWidth: Math.max(previewWidth + 8, labelText.implicitWidth)
    implicitHeight: previewHeight + 8 + 10 + labelText.implicitHeight + (note !== "" ? noteText.implicitHeight + 2 : 0)
    activeFocusOnTab: true
    Accessible.role: Accessible.RadioButton
    Accessible.name: label
    Accessible.checked: selected
    Keys.onSpacePressed: chosen()
    Keys.onReturnPressed: chosen()

    Rectangle {          // selection ring (accent), concentric with the preview
        id: ring
        x: (tile.width - width) / 2
        width: tile.previewWidth + 8
        height: tile.previewHeight + 8
        radius: tile.previewRadius + 4
        color: "transparent"
        border.width: 3
        border.color: tile.selected ? Theme.accentFor(tile.scheme) : (hover.hovered ? Theme.color(tile.scheme, "fillStrong") : "transparent")
        Behavior on border.color { ColorAnimation { duration: Theme.duration("short", true) } }
        KFocusRing { targetRadius: ring.radius; visible: tile.activeFocus; scheme: tile.scheme }
    }
    Item {
        id: frame
        x: ring.x + 4
        y: 4
        width: tile.previewWidth
        height: tile.previewHeight
        clip: true
    }
    Rectangle {          // hairline around the preview
        x: frame.x
        y: frame.y
        width: frame.width
        height: frame.height
        radius: tile.previewRadius
        color: "transparent"
        border.width: 1
        border.color: Theme.color(tile.scheme, "border")
    }
    KText {
        id: labelText
        anchors.horizontalCenter: parent.horizontalCenter
        y: tile.previewHeight + 8 + 10
        text: tile.label
        textStyle: "callout"
        emphasized: tile.selected
        scheme: tile.scheme
    }
    KText {
        id: noteText
        visible: tile.note !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: labelText.bottom
        anchors.topMargin: 2
        width: Math.max(tile.previewWidth + 8, labelText.implicitWidth)
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: tile.note
        textStyle: "caption1"
        level: "secondaryLabel"
        scheme: tile.scheme
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: { tile.forceActiveFocus(Qt.MouseFocusReason); tile.chosen(); } }
}
