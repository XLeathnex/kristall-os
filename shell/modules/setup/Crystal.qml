// SPDX-License-Identifier: GPL-3.0-or-later
// The Kristall mark drawn large: the same four facets as icons/kristall/mark.svg (a quartz point,
// shell/tools/gen-mark.py), each filled with its own gradient so the crystal catches the light.
// Static; it moves only when the welcome appears (and not at all with Reduce Motion).
import QtQuick
import QtQuick.Shapes

Item {
    id: c
    property real size: 200
    property bool dark: false
    implicitWidth: size
    implicitHeight: size
    readonly property real u: size / 24

    // facet polygons in the mark's 24-unit box
    readonly property var facets: [
        { pts: [[11.05, 1.41], [5.97, 5.74], [11.05, 8.58]], a: "#FFFFFF", b: "#9DC4FF", o: 1.0 },
        { pts: [[12.95, 1.41], [12.95, 8.58], [18.03, 5.74]], a: "#E9DCFF", b: "#8E7CF0", o: 0.95 },
        { pts: [[5.20, 7.49], [5.20, 17.00], [11.05, 22.51], [11.05, 10.76]], a: "#CFE3FF", b: "#3E7BFA", o: 0.95 },
        { pts: [[12.95, 10.76], [12.95, 22.51], [18.80, 17.00], [18.80, 7.49]], a: "#B9A6FF", b: "#5B3FD9", o: 0.9 }
    ]

    Repeater {
        model: c.facets
        Shape {
            required property var modelData
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            opacity: modelData.o
            ShapePath {
                strokeWidth: 0
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: modelData.pts[0][0] * c.u
                    y1: 0
                    x2: modelData.pts[modelData.pts.length - 1][0] * c.u
                    y2: c.size
                    GradientStop { position: 0.0; color: modelData.a }
                    GradientStop { position: 1.0; color: modelData.b }
                }
                startX: modelData.pts[0][0] * c.u
                startY: modelData.pts[0][1] * c.u
                PathPolyline {
                    path: modelData.pts.concat([modelData.pts[0]]).map(p => Qt.point(p[0] * c.u, p[1] * c.u))
                }
            }
        }
    }
}
