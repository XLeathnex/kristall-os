// SPDX-License-Identifier: GPL-3.0-or-later
// The welcome's own artwork (not a photo, not Apple's): a calm sky of soft light with large,
// faint crystal facets — light and dark variants. Drawn once; nothing here animates by itself.
import QtQuick
import QtQuick.Shapes

Item {
    id: bd
    property bool dark: false

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: bd.dark ? "#0A0F24" : "#EEF4FF" }
            GradientStop { position: 0.55; color: bd.dark ? "#141238" : "#F3EEFF" }
            GradientStop { position: 1.0; color: bd.dark ? "#1E0F2E" : "#FFF3F6" }
        }
    }
    // soft glows
    Repeater {
        model: [
            { x: 0.18, y: 0.22, r: 0.42, c: bd.dark ? "#3355FF" : "#9CC2FF", a: bd.dark ? 0.30 : 0.55 },
            { x: 0.82, y: 0.30, r: 0.38, c: bd.dark ? "#8A3FFF" : "#D7B8FF", a: bd.dark ? 0.26 : 0.55 },
            { x: 0.60, y: 0.92, r: 0.46, c: bd.dark ? "#FF4F8B" : "#FFC7D9", a: bd.dark ? 0.16 : 0.50 }
        ]
        Shape {
            required property var modelData
            anchors.fill: parent
            readonly property real rad: Math.max(bd.width, bd.height) * modelData.r
            ShapePath {
                strokeWidth: 0
                strokeColor: "transparent"
                fillGradient: RadialGradient {
                    centerX: bd.width * modelData.x
                    centerY: bd.height * modelData.y
                    centerRadius: rad
                    focalX: centerX
                    focalY: centerY
                    GradientStop { position: 0.0; color: Qt.rgba(Qt.color(modelData.c).r, Qt.color(modelData.c).g, Qt.color(modelData.c).b, modelData.a) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
                PathRectangle { x: 0; y: 0; width: bd.width; height: bd.height }
            }
        }
    }
    // large faint facets crossing the sky
    Shape {
        anchors.fill: parent
        opacity: bd.dark ? 0.10 : 0.22
        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillColor: "#FFFFFF"
            startX: bd.width * 0.0
            startY: bd.height * 0.72
            PathLine { x: bd.width * 0.34; y: bd.height * 0.30 }
            PathLine { x: bd.width * 0.46; y: bd.height * 1.0 }
            PathLine { x: 0; y: bd.height }
            PathLine { x: 0; y: bd.height * 0.72 }
        }
        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillColor: "#FFFFFF"
            startX: bd.width * 0.70
            startY: 0
            PathLine { x: bd.width; y: 0 }
            PathLine { x: bd.width; y: bd.height * 0.55 }
            PathLine { x: bd.width * 0.84; y: bd.height * 0.40 }
            PathLine { x: bd.width * 0.70; y: 0 }
        }
    }
    Shape {
        anchors.fill: parent
        opacity: bd.dark ? 0.06 : 0.14
        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillColor: bd.dark ? "#B9A6FF" : "#7FA7FF"
            startX: bd.width * 0.34
            startY: bd.height * 0.30
            PathLine { x: bd.width * 0.58; y: bd.height * 0.62 }
            PathLine { x: bd.width * 0.46; y: bd.height }
            PathLine { x: bd.width * 0.34; y: bd.height * 0.30 }
        }
        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillColor: bd.dark ? "#FF9EC4" : "#C9A6FF"
            startX: bd.width * 0.84
            startY: bd.height * 0.40
            PathLine { x: bd.width; y: bd.height * 0.55 }
            PathLine { x: bd.width; y: bd.height }
            PathLine { x: bd.width * 0.74; y: bd.height }
            PathLine { x: bd.width * 0.84; y: bd.height * 0.40 }
        }
    }
}
