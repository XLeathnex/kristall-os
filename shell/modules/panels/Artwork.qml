// SPDX-License-Identifier: GPL-3.0-or-later
// Album art (the player's art URL) in a rounded square, with a calm music symbol while there is
// none or it cannot be loaded.
import QtQuick
import qs.core

Item {
    id: art
    property string source: ""
    property string scheme: Theme.scheme
    property real radius: 10
    implicitWidth: 52
    implicitHeight: 52

    Rectangle {
        anchors.fill: parent
        radius: art.radius
        color: Theme.color(art.scheme, "fillStrong")
        visible: img.status !== Image.Ready
        KIcon {
            anchors.centerIn: parent
            size: Math.round(art.width * 0.42)
            name: "fill/music-notes"
            color: Theme.color(art.scheme, "secondaryLabel")
        }
    }
    RoundedImage {
        id: img
        anchors.fill: parent
        radius: art.radius
        source: art.source
    }
}
