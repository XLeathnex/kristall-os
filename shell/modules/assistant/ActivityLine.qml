// SPDX-License-Identifier: GPL-3.0-or-later
// One line saying what the assistant is doing right now, in the owner's language (the daemon's
// bilingual `activity.text`; never a tool name), with a quiet indicator: three dots that breathe
// while it runs, a check when done, a cross when it failed.
import QtQuick
import qs.core
import qs.services

Item {
    id: line
    property var activity: null
    property string scheme: Theme.scheme
    property string fallbackText: ""
    readonly property bool running: activity !== null && activity.status === "running"
    readonly property string text: activity ? (Strings.pick(activity.text) || fallbackText) : fallbackText
    implicitHeight: Math.max(18, label.implicitHeight)
    implicitWidth: 18 + label.implicitWidth

    Item {
        id: indicator
        width: 14
        height: 14
        anchors.verticalCenter: label.verticalCenter

        Row {
            id: dots
            visible: line.running || line.activity === null
            anchors.centerIn: parent
            spacing: 2.5
            Repeater {
                model: 3
                Rectangle {
                    required property int index
                    width: 3.5
                    height: 3.5
                    radius: 1.75
                    color: Theme.accentFor(line.scheme)
                    property real phase: 0
                    opacity: 0.35 + 0.65 * phase
                    SequentialAnimation on phase {
                        running: dots.visible && !Theme.reduceMotion
                        loops: Animation.Infinite
                        PauseAnimation { duration: index * 160 }
                        NumberAnimation { from: 0; to: 1; duration: 380; easing.type: Easing.InOutSine }
                        NumberAnimation { from: 1; to: 0; duration: 380; easing.type: Easing.InOutSine }
                        PauseAnimation { duration: (2 - index) * 160 }
                    }
                }
            }
        }
        KIcon {
            visible: !dots.visible
            anchors.centerIn: parent
            size: 13
            name: line.activity && line.activity.status === "failed" ? "bold/x" : "bold/check"
            color: line.activity && line.activity.status === "failed" ? Theme.color(line.scheme, "secondaryLabel") : Theme.color(line.scheme, "success")
        }
    }
    KText {
        id: label
        x: 20
        width: line.width - x
        text: line.text
        textStyle: "callout"
        scheme: line.scheme
        level: line.running ? "label" : "secondaryLabel"
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
    }
}
