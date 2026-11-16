// SPDX-License-Identifier: GPL-3.0-or-later
// The assistant's face in the panel: a small cut crystal. Two gradient facets turn against each
// other around a bright four-pointed spark (our assistant symbol). Listening and speaking: it
// swells with the voice level; thinking: the facets spin; acting: they turn slowly; idle: still.
// Animations run only while the state asks for them.
import QtQuick
import qs.core

Item {
    id: orb
    property string mode: "idle"         // idle listening transcribing thinking acting speaking error
    property real level: 0
    property string scheme: Theme.scheme
    property real size: 32
    implicitWidth: size
    implicitHeight: size

    readonly property bool still: Theme.reduceMotion
    readonly property bool spinning: !still && (mode === "thinking" || mode === "transcribing" || mode === "acting")
    readonly property real swell: still ? 0 : ((mode === "listening" || mode === "speaking") ? level : 0)
    readonly property var colors: mode === "error" ? ["#FFC15A", "#FF7A4D", "#FF5C7A"]
                                 : mode === "speaking" ? ["#D9B8FF", "#FF8FC9", "#8A7CFF"]
                                 : mode === "acting" ? ["#6FE6D6", "#3F7DFF", "#6B5BFF"]
                                 : ["#9BF4FF", "#5C8DFF", "#B58CFF"]

    property real spin: 0
    NumberAnimation on spin {
        running: orb.spinning
        from: 0
        to: 360
        duration: orb.mode === "acting" ? 5200 : 1700
        loops: Animation.Infinite
    }
    property real s: 1 + 0.22 * swell
    Behavior on s { NumberAnimation { duration: 90 } }

    Item {
        anchors.centerIn: parent
        width: orb.size
        height: orb.size
        scale: orb.s

        // soft halo behind
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 1.28
            height: width
            radius: width / 2
            color: Qt.alpha(orb.colors[0], orb.scheme === "dark" ? 0.20 : 0.28)
            opacity: 0.4 + 0.6 * orb.swell
        }
        // body
        Rectangle {
            id: body
            anchors.fill: parent
            radius: width / 2
            rotation: orb.spin
            gradient: Gradient {
                GradientStop { position: 0.0; color: orb.colors[0] }
                GradientStop { position: 0.55; color: orb.colors[1] }
                GradientStop { position: 1.0; color: orb.colors[2] }
            }
        }
        // second facet, turning the other way
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.86
            height: width
            radius: width / 2
            rotation: -orb.spin * 1.6 + 45
            opacity: 0.55
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.75) }
                GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.0) }
                GradientStop { position: 1.0; color: Qt.alpha(orb.colors[2], 0.6) }
            }
        }
        // rim
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.55)
        }
        KIcon {
            anchors.centerIn: parent
            size: Math.round(orb.size * 0.56)
            name: "kristall/assistant"
            color: "#FFFFFF"
        }
    }
}
