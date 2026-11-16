// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: win
    WlrLayershell.namespace: "kristall-demo-bar"
    WlrLayershell.layer: WlrLayer.Top
    anchors { top: true; left: true; right: true }
    implicitHeight: 40
    exclusiveZone: 34
    color: "transparent"

    GlassSurface {
        id: glassSurface
        key: "bar-" + win.screen.name
        layerNamespace: "kristall-demo-bar"
        output: win.screen.name
        shapes: [strip]
    }

    GlassShape {
        id: strip
        shapeId: "strip"
        surface: glassSurface
        x: 8; y: 6
        width: parent.width - 16; height: 28
        radius: 10
        Row {
            anchors.verticalCenter: parent.verticalCenter
            x: 14
            spacing: 18
            Text { text: qsTr("Files"); font.family: "Inter"; font.pixelSize: 13; font.weight: Font.Bold; color: strip.textColor }
            Repeater {
                model: [qsTr("File"), qsTr("Edit"), qsTr("View"), qsTr("Go"), qsTr("Window"), qsTr("Help")]
                Text { required property string modelData; text: modelData; font.family: "Inter"; font.pixelSize: 13; color: strip.textColor }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 14
            text: "Mo 16. Nov  09:41"
            font.family: "Inter"; font.pixelSize: 13; font.weight: Font.Medium
            color: strip.textColor
        }
    }
}
