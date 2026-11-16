// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall log-out / restart / shut-down confirmation, in the Mac's manner: one small alert in
// the middle of the screen ("Do you want to shut down your computer now?"), the countdown
// sentence below it, Cancel and the action as two capsule buttons (the action is the default).
// Loaded by Logout.qml (the wrapper the overlay build writes), which forwards these signals to
// Plasma's logout greeter and falls back to plasma-desktop's own dialog if this file fails.
// Context properties used: sdtype, ShutdownType, canLogout, softwareUpdatePending.
import QtQuick
import QtQuick.Window

Item {
    id: root

    signal logoutRequested()
    signal haltRequested()
    signal haltUpdateRequested()
    signal suspendRequested(int spdMethod)
    signal rebootRequested()
    signal rebootRequested2(int opt)
    signal rebootUpdateRequested()
    signal cancelRequested()
    signal lockScreenRequested()
    signal cancelSoftwareUpdateRequested()

    function sleepRequested() { root.suspendRequested(2); }
    function hibernateRequested() { root.suspendRequested(4); }

    readonly property bool de: Qt.locale().name.substring(0, 2) === "de"
    function t(de, en) { return root.de ? de : en; }

    readonly property bool updates: typeof softwareUpdatePending !== "undefined" && softwareUpdatePending
    readonly property int type: sdtype
    readonly property bool choose: type === ShutdownType.ShutdownTypeDefault
    readonly property bool isReboot: type === ShutdownType.ShutdownTypeReboot
    readonly property bool isHalt: type === ShutdownType.ShutdownTypeHalt

    property int remaining: 60

    function act() {
        if (root.isReboot) {
            root.updates ? root.rebootUpdateRequested() : root.rebootRequested();
        } else if (root.isHalt) {
            root.updates ? root.haltUpdateRequested() : root.haltRequested();
        } else {
            root.logoutRequested();
        }
    }

    // colours from the session's colour scheme (light or dark)
    SystemPalette { id: palette; colorGroup: SystemPalette.Active }
    readonly property bool dark: (palette.window.r * 0.299 + palette.window.g * 0.587 + palette.window.b * 0.114) < 0.5
    readonly property color label: dark ? "#F2F2F7" : "#1D1D1F"
    readonly property color secondary: dark ? Qt.rgba(1, 1, 1, 0.55) : Qt.rgba(0, 0, 0, 0.5)
    readonly property color accent: palette.highlight
    readonly property color material: dark ? Qt.rgba(0.118, 0.118, 0.125, 0.90) : Qt.rgba(0.965, 0.965, 0.973, 0.90)

    // one-second countdown while the dialog is open (stops with the dialog)
    Timer {
        interval: 1000
        repeat: true
        running: !root.choose && root.remaining > 0
        onTriggered: {
            root.remaining -= 1;
            if (root.remaining <= 0) {
                root.act();
            }
        }
    }

    Keys.onEscapePressed: root.cancelRequested()
    Keys.onReturnPressed: root.choose ? root.haltRequested() : root.act()
    Keys.onEnterPressed: root.choose ? root.haltRequested() : root.act()
    focus: true
    Component.onCompleted: forceActiveFocus()

    // a light veil, not a black-out: the desktop stays visible as on the Mac
    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: 0.18
    }
    MouseArea {
        anchors.fill: parent
        onClicked: root.cancelRequested()
    }

    Rectangle {
        id: card
        width: 300
        height: column.implicitHeight + 40
        anchors.centerIn: parent
        radius: 26
        color: root.material
        border.width: 1
        border.color: root.dark ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(0, 0, 0, 0.10)
        opacity: 0
        scale: 0.96
        Component.onCompleted: { opacity = 1; scale = 1; }
        Behavior on opacity { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 250; easing.bezierCurve: [0.2, 0.9, 0.25, 1, 1, 1] } }

        MouseArea { anchors.fill: parent }   // clicks on the card do not cancel

        Column {
            id: column
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
            spacing: 10

            Image {
                anchors.horizontalCenter: parent.horizontalCenter
                // the Kristall mark, white on the dark card, dark on the light one
                source: root.dark ? "mark.png" : "mark-dark.png"
                width: 56; height: 56
                sourceSize.width: 112; sourceSize.height: 112
                smooth: true
                opacity: 0.92
            }

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: root.label
                font.pixelSize: 13
                font.weight: Font.Bold
                text: root.choose ? root.t("Möchtest du deinen Computer jetzt ausschalten, neu starten oder dich abmelden?",
                                           "Do you want to shut down, restart or log out now?")
                    : root.isReboot ? root.t("Möchtest du deinen Computer jetzt neu starten?", "Are you sure you want to restart your computer now?")
                    : root.isHalt ? root.t("Möchtest du deinen Computer jetzt ausschalten?", "Are you sure you want to shut down your computer now?")
                    : root.t("Möchtest du dich wirklich abmelden und alle Programme beenden?", "Are you sure you want to quit all apps and log out now?")
            }

            Text {
                width: parent.width
                visible: !root.choose
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: root.secondary
                font.pixelSize: 11
                font.features: { "tnum": 1 }
                text: {
                    const s = root.remaining;
                    const upd = root.updates && (root.isReboot || root.isHalt)
                        ? root.t("Updates werden dabei installiert. ", "Updates will be installed. ") : "";
                    if (root.isReboot)
                        return upd + root.t(`Wenn du nichts unternimmst, wird der Computer in ${s} Sekunden automatisch neu gestartet.`,
                                            `If you do nothing, the computer will restart automatically in ${s} seconds.`);
                    if (root.isHalt)
                        return upd + root.t(`Wenn du nichts unternimmst, wird der Computer in ${s} Sekunden automatisch ausgeschaltet.`,
                                            `If you do nothing, the computer will shut down automatically in ${s} seconds.`);
                    return root.t(`Wenn du nichts unternimmst, wirst du in ${s} Sekunden automatisch abgemeldet.`,
                                  `If you do nothing, you will be logged out automatically in ${s} seconds.`);
                }
            }

            Item { width: 1; height: 4 }

            // buttons: side by side for one action, stacked for the choice
            Grid {
                width: parent.width
                columns: root.choose ? 1 : 2
                spacing: 8
                Repeater {
                    model: root.choose
                        ? [{ k: "halt", p: true }, { k: "reboot", p: false }, { k: "logout", p: false }, { k: "cancel", p: false }]
                        : [{ k: "cancel", p: false }, { k: "act", p: true }]
                    delegate: Rectangle {
                        required property var modelData
                        width: root.choose ? column.width : (column.width - 8) / 2
                        height: 28
                        radius: 14
                        color: modelData.p ? root.accent
                             : (mouse.pressed ? (root.dark ? Qt.rgba(1, 1, 1, 0.28) : Qt.rgba(0, 0, 0, 0.18))
                                              : (root.dark ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(0, 0, 0, 0.08)))
                        opacity: mouse.pressed && modelData.p ? 0.85 : 1
                        visible: modelData.k !== "logout" || canLogout
                        Text {
                            anchors.centerIn: parent
                            color: modelData.p ? "#FFFFFF" : root.label
                            font.pixelSize: 13
                            font.weight: modelData.p ? Font.DemiBold : Font.Normal
                            text: {
                                switch (modelData.k) {
                                case "cancel": return root.t("Abbrechen", "Cancel");
                                case "halt": return root.t("Ausschalten", "Shut Down");
                                case "reboot": return root.t("Neustart", "Restart");
                                case "logout": return root.t("Abmelden", "Log Out");
                                default:
                                    return root.isReboot ? root.t("Neustart", "Restart")
                                         : root.isHalt ? root.t("Ausschalten", "Shut Down")
                                         : root.t("Abmelden", "Log Out");
                                }
                            }
                        }
                        MouseArea {
                            id: mouse
                            anchors.fill: parent
                            onClicked: {
                                switch (parent.modelData.k) {
                                case "cancel": root.cancelRequested(); break;
                                case "halt": root.updates ? root.haltUpdateRequested() : root.haltRequested(); break;
                                case "reboot": root.updates ? root.rebootUpdateRequested() : root.rebootRequested(); break;
                                case "logout": root.logoutRequested(); break;
                                default: root.act();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
