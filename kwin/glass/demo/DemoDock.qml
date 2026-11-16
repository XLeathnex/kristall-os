// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: win
    WlrLayershell.namespace: "kristall-demo-dock"
    WlrLayershell.layer: WlrLayer.Top
    anchors { bottom: true }
    implicitWidth: 760
    implicitHeight: 130
    exclusiveZone: 84
    color: "transparent"

    readonly property var icons: ["#ff6b5e", "#ffb340", "#34c759", "#30b0c7", "#0a84ff", "#5e5ce6", "#bf5af2", "#ff375f", "#8e8e93"]
    property real hoverX: -1000
    readonly property real base: 52

    function magnify(cx) {
        if (hoverX < -500) return 1.0;
        const d = Math.abs(cx - hoverX);
        return 1.0 + 0.55 * Math.max(0, 1 - d / 140);
    }

    GlassSurface {
        id: glassSurface
        key: "dock-" + win.screen.name
        layerNamespace: "kristall-demo-dock"
        output: win.screen.name
        shapes: [capsule]
    }

    GlassShape {
        id: capsule
        shapeId: "dock"
        surface: glassSurface
        kind: "rect"
        radius: 24
        smoothing: 0.6
        height: 68
        width: iconsRow.width + 24
        x: (parent.width - width) / 2
        y: parent.height - height - 8
        pointerActive: hover.hovered
        pointer: hover.point.position
        Behavior on width { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

        HoverHandler { id: hover }
    }

    Row {
        id: iconsRow
        spacing: 8
        anchors.horizontalCenter: capsule.horizontalCenter
        anchors.bottom: capsule.bottom
        anchors.bottomMargin: 8
        Repeater {
            model: win.icons
            Rectangle {
                required property string modelData
                required property int index
                readonly property real s: win.magnify(iconsRow.x + x + width / 2)
                width: win.base * s
                height: win.base * s
                radius: width * 0.23
                color: modelData
                Behavior on width { NumberAnimation { duration: 90 } }
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width * 0.42; height: width; radius: width / 2
                    color: Qt.rgba(1, 1, 1, 0.85)
                }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        onPositionChanged: mouse => win.hoverX = mouse.x
        onExited: win.hoverX = -1000
        acceptedButtons: Qt.NoButton
    }
}
