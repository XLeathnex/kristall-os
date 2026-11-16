// SPDX-License-Identifier: GPL-3.0-or-later
// The edge of a glass object that must read as a solid thing (the Dock, Control Center platters):
//  * a hairline of exactly one device pixel on the outline — light on dark appearance, dark on
//    light appearance (design.md §6 "rim"),
//  * just inside it a specular rim one logical pixel wide that is brightest along the top edge and
//    fades towards the bottom, the way light from above catches the top of a glass slab.
// Put it inside (and filling) a GlassShape or any rounded item. It draws only these two lines;
// the glass stays clear. Static: nothing is repainted unless the size or the scheme changes.
import QtQuick
import QtQuick.Shapes

Item {
    id: rim
    property real radius: 12
    property string scheme: Theme.scheme
    property real strength: 1.0            // multiplies both lines (e.g. glass fades)
    property real specular: 1.0            // 0..1 strength of the top highlight
    readonly property real px: 1 / Math.max(1, Window.window ? Window.window.devicePixelRatio : 1)
    readonly property bool dark: scheme === "dark"
    anchors.fill: parent
    visible: strength > 0.001 && width > 2 && height > 2

    // the hairline (one device pixel)
    Rectangle {
        anchors.fill: parent
        radius: rim.radius
        color: "transparent"
        border.width: rim.px
        border.color: Theme.color(rim.scheme, "rim")
        opacity: rim.strength
    }
    // the specular rim: a ring between the hairline and 1 logical px further in, filled with a
    // vertical gradient (white, bright at the top, almost gone at the bottom)
    Shape {
        id: spec
        anchors.fill: parent
        opacity: rim.strength * rim.specular
        preferredRendererType: Shape.CurveRenderer
        readonly property real o: rim.px
        readonly property real i: rim.px + 1
        ShapePath {
            fillRule: ShapePath.OddEvenFill
            strokeWidth: -1
            strokeColor: "transparent"
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: spec.height
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, rim.dark ? 0.62 : 0.95) }
                GradientStop { position: 0.22; color: Qt.rgba(1, 1, 1, rim.dark ? 0.30 : 0.60) }
                GradientStop { position: 0.6; color: Qt.rgba(1, 1, 1, rim.dark ? 0.10 : 0.22) }
                GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, rim.dark ? 0.05 : 0.12) }
            }
            PathRectangle {
                x: spec.o; y: spec.o
                width: spec.width - 2 * spec.o; height: spec.height - 2 * spec.o
                radius: Math.max(0, rim.radius - spec.o)
            }
            PathRectangle {
                x: spec.i; y: spec.i
                width: Math.max(0, spec.width - 2 * spec.i); height: Math.max(0, spec.height - 2 * spec.i)
                radius: Math.max(0, rim.radius - spec.i)
            }
        }
    }
}
