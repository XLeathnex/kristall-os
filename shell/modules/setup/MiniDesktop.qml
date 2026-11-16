// SPDX-License-Identifier: GPL-3.0-or-later
// A tiny drawing of the desktop for choice tiles: wallpaper, menu bar, a window, the Dock.
// `split`: left half light, right half dark (Automatic). `zoom` > 1 draws everything bigger
// (display size: larger text), < 1 smaller (more space).
import QtQuick
import qs.core

Item {
    id: md
    property bool dark: false
    property bool split: false
    property real zoom: 1.0
    property color accent: Theme.accentFor(dark ? "dark" : "light")
    property real radius: 10

    component Half: Item {
        id: half
        property bool dk: false
        property real zoom: 1
        property color accent: "#007AFF"
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: dk ? "#1B2347" : "#BFD6FF" }
                GradientStop { position: 1; color: dk ? "#3A1E4F" : "#F4D3E8" }
            }
        }
        Rectangle {        // menu bar
            width: parent.width
            height: Math.round(7 * half.zoom)
            color: dk ? Qt.rgba(0, 0, 0, 0.35) : Qt.rgba(1, 1, 1, 0.55)
        }
        Rectangle {        // a window
            x: Math.round(parent.width * 0.12)
            y: Math.round(parent.height * 0.20)
            width: Math.round(parent.width * 0.60 * Math.min(1.25, half.zoom))
            height: Math.round(parent.height * 0.50 * Math.min(1.25, half.zoom))
            radius: 4
            color: dk ? "#2C2C2E" : "#FFFFFF"
            Row {
                x: 4; y: 4; spacing: 2
                Repeater { model: ["#FF5F57", "#FEBC2E", "#28C840"]; Rectangle { required property string modelData; width: 3 * half.zoom; height: width; radius: width / 2; color: modelData } }
            }
            Column {
                x: 6; y: 6 + 5 * half.zoom; spacing: 3 * half.zoom
                Repeater {
                    model: 3
                    Rectangle { required property int index; width: (index === 0 ? 34 : 26 - index * 4) * half.zoom; height: 2.5 * half.zoom; radius: 1; color: index === 0 ? half.accent : (dk ? Qt.rgba(1, 1, 1, 0.35) : Qt.rgba(0, 0, 0, 0.25)) }
                }
            }
        }
        Rectangle {        // the Dock
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            width: Math.round(parent.width * 0.5 * half.zoom)
            height: Math.round(9 * half.zoom)
            radius: 4
            color: dk ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(1, 1, 1, 0.55)
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: md.radius
        clip: true
        color: "transparent"
        Half { anchors.fill: parent; dk: md.dark && !md.split; zoom: md.zoom; accent: md.accent }
        Item {
            visible: md.split
            x: parent.width / 2
            width: parent.width / 2
            height: parent.height
            clip: true
            Half { x: -parent.x; width: md.width; height: md.height; dk: true; zoom: md.zoom; accent: md.accent }
        }
    }
}
