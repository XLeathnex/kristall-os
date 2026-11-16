// SPDX-License-Identifier: GPL-3.0-or-later
// The lock screen clock in the macOS 26/27 arrangement: the date in a small line above a very
// large time, centred near the top of the screen (design.md §3 clockLarge: Inter Display 96 px,
// weight 600, tracking −2). Updates once a minute (a single-shot timer aimed at the next minute,
// no polling).
import QtQuick

Column {
    id: clock
    spacing: -6

    readonly property bool de: Qt.locale().name.substring(0, 2) === "de"
    property date now: new Date()

    Timer {
        id: tick
        repeat: false
        running: true
        interval: 60000 - (Date.now() % 60000) + 50
        onTriggered: {
            clock.now = new Date();
            interval = 60000 - (Date.now() % 60000) + 50;
            start();
        }
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        color: Qt.rgba(1, 1, 1, 0.88)
        font.family: "Inter"
        font.pixelSize: 22
        font.weight: Font.DemiBold
        font.letterSpacing: -0.3
        renderType: Text.NativeRendering
        text: clock.de
            ? clock.now.toLocaleDateString(Qt.locale("de_DE"), "dddd, d. MMMM")
            : clock.now.toLocaleDateString(Qt.locale(), "dddd, MMMM d")
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        color: Qt.rgba(1, 1, 1, 0.92)
        font.family: "Inter Display"
        font.pixelSize: 96
        font.weight: Font.DemiBold
        font.letterSpacing: -2.0
        font.features: { "tnum": 1 }
        renderType: Text.NativeRendering
        text: clock.now.toLocaleTimeString(Qt.locale(), clock.de || Qt.locale().timeFormat(Locale.ShortFormat).indexOf("AP") < 0 ? "H:mm" : "h:mm")
    }
}
