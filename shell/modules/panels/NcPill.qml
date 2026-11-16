// SPDX-License-Identifier: GPL-3.0-or-later
// A small glass capsule button in Notification Centre (group headers, "Clear All"), legible over
// any wallpaper. Its glass is switched off while it is not entirely inside the scroll area (the
// compositor's glass is not clipped by the scroll area).
import QtQuick
import qs.core

Item {
    id: pill
    property GlassSurface surface: null
    property string shapeId: "pill"
    property string text: ""
    property string icon: ""
    property Item clipItem: null
    property int layoutRevision: 0
    property real fade: 1
    signal clicked()

    readonly property bool inside: {
        layoutRevision;
        if (!clipItem)
            return true;
        const scrolled = clipItem.flickable ? clipItem.flickable.contentY : 0;   // dependency
        const p = mapToItem(clipItem, 0, 0);
        return p.y + scrolled * 0 >= 0 && p.y + height <= clipItem.height;
    }
    implicitHeight: Theme.size.controlSmall
    implicitWidth: (text !== "" ? label.implicitWidth + 20 : 0) + (icon !== "" ? (text !== "" ? 14 : implicitHeight) : 0)
    opacity: (inside ? 1 : 0) * fade
    activeFocusOnTab: inside
    Accessible.role: Accessible.Button
    Accessible.name: text
    Keys.onReturnPressed: clicked()
    Keys.onSpacePressed: clicked()
    function activate() { clicked(); }

    GlassShape {
        id: shape
        anchors.fill: parent
        shapeId: pill.shapeId
        surface: pill.surface
        role: "control"
        kind: "capsule"
        glassEnabled: pill.inside && pill.visible
        glassOpacity: pill.fade
        pressed: tap.pressed
        pointerActive: hover.hovered
        pointer: hover.point.position
    }
    Row {
        anchors.centerIn: parent
        spacing: 4
        KIcon {
            visible: pill.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            size: 10
            name: pill.icon
            color: Theme.color(shape.scheme, "label")
        }
        KText {
            id: label
            visible: pill.text !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: pill.text
            textStyle: "subheadline"
            emphasized: true
            scheme: shape.scheme
        }
    }
    KFocusRing { targetRadius: pill.height / 2; scheme: shape.scheme }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: tap; onTapped: pill.clicked() }
}
