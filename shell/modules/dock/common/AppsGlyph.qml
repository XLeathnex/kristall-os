// SPDX-License-Identifier: GPL-3.0-or-later
// Our own icon for "Apps" (the grid of all apps): a light plate with a 3×3 grid of small
// coloured tiles in the accent palette of design.md §6. Drawn, no external artwork.
import QtQuick
import qs.core
import "squircle.js" as Squircle

Item {
    id: glyph
    property real size: 48
    property real renderSize: size
    property string scheme: Theme.scheme
    readonly property real body: size * 0.82
    readonly property var colors: ["#FF3B30", "#FF9500", "#FFCC00", "#28CD41", "#5AC8FA", "#007AFF", "#AF52DE", "#FF2D55", "#8E8E93"]
    implicitWidth: size
    implicitHeight: size

    Image {
        anchors.centerIn: parent
        width: glyph.body * 104 / 100
        height: width
        source: Squircle.plate(glyph.scheme === "dark")
        sourceSize: Qt.size(Math.ceil(glyph.renderSize * 0.86), Math.ceil(glyph.renderSize * 0.86))
        smooth: true
    }
    Grid {
        anchors.centerIn: parent
        columns: 3
        spacing: glyph.body * 0.07
        Repeater {
            model: 9
            Rectangle {
                required property int index
                width: glyph.body * 0.17
                height: width
                radius: width * 0.3
                color: glyph.colors[index]
            }
        }
    }
}
