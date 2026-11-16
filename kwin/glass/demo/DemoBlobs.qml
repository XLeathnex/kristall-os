// SPDX-License-Identifier: GPL-3.0-or-later
// Shapes of one group merge smoothly when they come within `merge` of each other.
// Click to spread or gather them (an animation driven by input, then idle again).
import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: win
    WlrLayershell.namespace: "kristall-demo-blobs"
    WlrLayershell.layer: WlrLayer.Top
    anchors { left: true }
    margins { left: 40 }
    implicitWidth: 420
    implicitHeight: 200
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"

    property real spread: 0   // 0 = merged, 1 = apart

    GlassSurface {
        id: glassSurface
        key: "blobs"
        layerNamespace: "kristall-demo-blobs"
        shapes: [a, b, c]
    }

    GlassShape {
        id: a
        shapeId: "a"; surface: glassSurface; kind: "capsule"; group: "blobs"; merge: 22
        x: 30; y: 60; width: 120; height: 64
    }
    GlassShape {
        id: b
        shapeId: "b"; surface: glassSurface; kind: "capsule"; group: "blobs"; merge: 22
        x: 158 + 60 * win.spread; y: 60; width: 64; height: 64
        tint: "#0a84ff"; tintAmount: 0.45
    }
    GlassShape {
        id: c
        shapeId: "c"; surface: glassSurface; kind: "rect"; radius: 18; group: "blobs"; merge: 22
        x: 230 + 110 * win.spread; y: 40 + 20 * win.spread; width: 104; height: 104
        variant: "clear"
    }
    Behavior on spread { NumberAnimation { duration: 600; easing.type: Easing.InOutCubic } }

    MouseArea {
        anchors.fill: parent
        onClicked: win.spread = win.spread > 0.5 ? 0 : 1
    }
}
