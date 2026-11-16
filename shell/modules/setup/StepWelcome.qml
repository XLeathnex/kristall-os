// SPDX-License-Identifier: GPL-3.0-or-later
// The welcome moment: our own crystal, one word, one promise, one button. It appears once
// (the crystal settles, the words fade in) and then is still.
import QtQuick
import qs.core
import qs.services

Item {
    id: w
    property var ctl: null
    property string scheme: Theme.scheme
    readonly property bool dark: scheme === "dark"
    property real shown: 0
    Component.onCompleted: shown = 1
    Behavior on shown { NumberAnimation { duration: Theme.reduceMotion ? 300 : 1100; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }

    Column {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -24
        spacing: 0
        width: Math.min(640, w.width - 64)

        Item {
            width: parent.width
            height: 232
            // halo behind the crystal
            Rectangle {
                anchors.centerIn: crystal
                width: 300
                height: 300
                radius: 150
                color: w.dark ? Qt.rgba(0.45, 0.42, 1.0, 0.10) : Qt.rgba(1, 1, 1, 0.55)
                opacity: w.shown
            }
            Crystal {
                id: crystal
                size: 176
                dark: w.dark
                anchors.horizontalCenter: parent.horizontalCenter
                y: 24 + (Theme.reduceMotion ? 0 : (1 - w.shown) * 28)
                opacity: w.shown
                scale: Theme.reduceMotion ? 1 : 0.92 + 0.08 * w.shown
            }
        }
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: Strings.t("setup.welcome.title")
            font.family: Theme.displayFamily
            font.pixelSize: 64
            font.weight: Font.DemiBold
            font.letterSpacing: -1.6
            lineHeight: 1.0
            scheme: w.scheme
            opacity: Math.max(0, w.shown * 1.4 - 0.4)
        }
        Item { width: 1; height: 14 }
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: Strings.t("setup.welcome.subtitle")
            textStyle: "title2"
            level: "secondaryLabel"
            scheme: w.scheme
            opacity: Math.max(0, w.shown * 1.6 - 0.6)
        }
        Item { width: 1; height: 40 }
        KButton {
            id: startButton
            objectName: "setup.welcome.start"
            anchors.horizontalCenter: parent.horizontalCenter
            text: Strings.t("setup.welcome.start")
            variant: "accent"
            size: "large"
            minWidth: 200
            scheme: w.scheme
            opacity: Math.max(0, w.shown * 2 - 1)
            onClicked: w.ctl.next()
        }
        Item { width: 1; height: 14 }
        KButton {
            objectName: "setup.welcome.later"
            anchors.horizontalCenter: parent.horizontalCenter
            text: Strings.t("setup.welcome.later")
            variant: "plain"
            size: "small"
            scheme: w.scheme
            opacity: Math.max(0, w.shown * 2 - 1)
            onClicked: w.ctl.skipAll()
        }
        Item { width: 1; height: 6 }
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: Strings.t("setup.welcome.laterNote")
            textStyle: "caption1"
            level: "tertiaryLabel"
            scheme: w.scheme
            opacity: Math.max(0, w.shown * 2 - 1)
        }
    }
    function primary() { ctl.next(); }
}
