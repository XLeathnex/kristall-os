// SPDX-License-Identifier: GPL-3.0-or-later
// A small activity indicator (eight fading spokes, like the Mac's) — turns only while `running`
// (a long operation is in progress), never while idle.
import QtQuick

Item {
    id: sp
    property bool running: false
    property string scheme: Theme.scheme
    width: 20
    height: 20
    Repeater {
        model: 8
        Rectangle {
            required property int index
            x: sp.width / 2 - 1
            y: 1
            width: 2
            height: 5
            radius: 1
            color: Theme.color(sp.scheme, "label")
            opacity: 0.18 + 0.82 * ((index + 8 - Math.floor(sp.phase)) % 8) / 7
            transform: Rotation { origin.x: 1; origin.y: sp.height / 2 - 1; angle: index * 45 }
        }
    }
    // one turn per 0.8 s, only while an operation the owner started is running; then it stops
    property real phase: 0
    NumberAnimation on phase {
        from: 0
        to: 8
        duration: 800
        loops: Animation.Infinite
        running: sp.running && sp.visible
    }
}
