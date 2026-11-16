// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: win
    WlrLayershell.namespace: "kristall-demo-panel"
    WlrLayershell.layer: WlrLayer.Top
    anchors { top: true; right: true }
    margins { top: 44; right: 10 }
    implicitWidth: 340
    implicitHeight: 300
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"

    GlassSurface {
        id: glassSurface
        key: "panel"
        layerNamespace: "kristall-demo-panel"
        shapes: [panel]
    }

    GlassShape {
        id: panel
        shapeId: "panel"
        surface: glassSurface
        anchors.fill: parent
        anchors.margins: 6
        radius: 26
        smoothing: 0.6

        Column {
            x: 20; y: 18
            spacing: 10
            width: parent.width - 40
            Text { text: qsTr("Notifications"); font.family: "Inter"; font.pixelSize: 17; font.weight: Font.Bold; color: panel.textColor }
            Text { text: qsTr("Liquid Glass is computed live from the screen behind it."); wrapMode: Text.WordWrap; width: parent.width; font.family: "Inter"; font.pixelSize: 13; color: panel.textColor }
            Text { text: qsTr("Text switches colour when the effect reports a legibility change."); wrapMode: Text.WordWrap; width: parent.width; font.family: "Inter"; font.pixelSize: 13; color: panel.textColor; opacity: 0.75 }
            Item { width: 1; height: 8 }
            Repeater {
                model: [0.65, 0.4]
                Rectangle {
                    required property real modelData
                    width: parent.width; height: 26; radius: 13
                    color: panel.scheme === "light" ? Qt.rgba(0, 0, 0, 0.10) : Qt.rgba(1, 1, 1, 0.16)
                    Rectangle { width: parent.width * parent.modelData; height: parent.height; radius: 13; color: "#ffffff"; opacity: 0.92 }
                }
            }
        }
    }
}
