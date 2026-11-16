// SPDX-License-Identifier: GPL-3.0-or-later
// The unmistakable "microphone is live" sign: an orange disc with the microphone symbol (the
// colour macOS owners know from the menu-bar privacy dot), a ring that breathes with the input
// level, and the words "Mikrofon an" for screen readers and as a tooltip. Click: done talking.
import QtQuick
import qs.core
import qs.services

Item {
    id: badge
    property real level: 0
    property string scheme: Theme.scheme
    property real tipOriginX: 0           // the surface's offset on its output (tooltips)
    property real tipOriginY: 0
    signal clicked()
    implicitWidth: 28
    implicitHeight: 28
    Accessible.role: Accessible.Indicator
    Accessible.name: Strings.t("assistant.micLive")
    readonly property color orange: Theme.color(scheme, "micOrange")

    Rectangle {
        anchors.centerIn: parent
        width: parent.width + 10 * (Theme.reduceMotion ? 0.4 : badge.level)
        height: width
        radius: width / 2
        color: Qt.alpha(badge.orange, 0.28)
        Behavior on width { NumberAnimation { duration: 80 } }
    }
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: badge.orange
        KIcon {
            anchors.centerIn: parent
            size: 15
            name: "fill/microphone"
            color: "#FFFFFF"
        }
    }
    KTooltip {
        text: Strings.t("assistant.micLive")
        originX: badge.tipOriginX
        originY: badge.tipOriginY
    }
    TapHandler {
        onTapped: badge.clicked()
    }
    HoverHandler {
        cursorShape: Qt.PointingHandCursor
    }
}
