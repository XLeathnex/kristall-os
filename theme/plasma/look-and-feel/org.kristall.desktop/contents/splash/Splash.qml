// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall login splash (KSplash). Shown between the login screen and the desktop: the default
// wallpaper, blurred like on the login screen, with a thin progress bar where the password field
// was — so the hand-over login → desktop reads as one continuous image coming into focus.
// KSplash drives `stage` (1…6) and closes the window when the desktop is ready.
import QtQuick

Rectangle {
    id: root
    color: "#000000"

    property int stage

    // Plasma's splash runs with the session's colour scheme; pick the matching background.
    SystemPalette { id: palette; colorGroup: SystemPalette.Active }
    readonly property bool dark: (palette.window.r * 0.299 + palette.window.g * 0.587 + palette.window.b * 0.114) < 0.5

    Image {
        id: background
        anchors.fill: parent
        source: root.dark ? "images/background-dark.jpg" : "images/background-light.jpg"
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
        smooth: true
        opacity: 0
        NumberAnimation on opacity { to: 1; duration: 250; easing.type: Easing.OutCubic }
    }

    Rectangle {
        id: track
        width: 200
        height: 4
        radius: 2
        anchors.horizontalCenter: parent.horizontalCenter
        y: Math.round(parent.height * 0.62)
        color: root.dark ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(0, 0, 0, 0.16)

        Rectangle {
            height: parent.height
            radius: parent.radius
            color: root.dark ? "#F2F2F7" : "#1D1D1F"
            width: Math.max(parent.height, parent.width * Math.min(1, root.stage / 6))
            Behavior on width { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
        }
    }
}
