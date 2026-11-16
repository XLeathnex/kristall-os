// SPDX-License-Identifier: GPL-3.0-or-later
// The battery symbol: 25×12 rounded body with a terminal nub, filled to the charge level
// (red at ≤ 10 %, green while charging), a bolt while charging. Drawn, not an icon, so the level
// is exact.
import QtQuick
import qs.core

Item {
    id: g
    property real level: 1            // 0..1
    property bool charging: false
    property bool plugged: false
    property string scheme: Theme.scheme
    readonly property color ink: Theme.color(scheme, "label")
    implicitWidth: 27
    implicitHeight: 12
    readonly property real px: 1 / Math.max(1, Window.window ? Window.window.devicePixelRatio : 1)

    Rectangle {
        id: body
        width: 24.5; height: 12
        radius: 3.5
        color: "transparent"
        border.width: 1
        border.color: Qt.alpha(g.ink, 0.45)
        Rectangle {
            x: 2; y: 2
            height: parent.height - 4
            width: Math.max(1.5, (parent.width - 4) * Math.max(0, Math.min(1, g.level)))
            radius: 1.8
            color: g.charging ? Theme.color(g.scheme, "success") : g.level <= 0.10 ? Theme.color(g.scheme, "destructive") : g.ink
        }
    }
    Rectangle {
        x: body.width + 0.5
        anchors.verticalCenter: body.verticalCenter
        width: 1.5; height: 4
        radius: 0.75
        color: Qt.alpha(g.ink, 0.45)
    }
    KIcon {
        visible: g.charging || g.plugged
        anchors.centerIn: body
        size: 11
        name: g.charging ? "fill/lightning" : "fill/plug"
        color: g.scheme === "dark" ? "#000000" : "#FFFFFF"
    }
}
