// SPDX-License-Identifier: GPL-3.0-or-later
// Light / dark / automatic and the accent colour. Applied the moment it is chosen
// (`appearance.theme`, `appearance.accent`): the menu bar, Dock and this card change at once.
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    icon: "circle-half"
    title: Strings.t("setup.appearance.title")
    subtitle: Strings.t("setup.appearance.subtitle")
    side: "left"
    cardWidth: 560
    implicitHeight: col.implicitHeight

    readonly property string theme: ctl ? ctl.value("appearance.theme", "auto") : "auto"
    readonly property string accent: ctl ? ctl.value("appearance.accent", "blue") : "blue"
    readonly property var themes: ["light", "dark", "auto"]
    readonly property var accents: ["blue", "purple", "pink", "red", "orange", "yellow", "green", "graphite"]

    function keyPressed(ev) {
        if (ev.key === Qt.Key_Left || ev.key === Qt.Key_Right) {
            const i = themes.indexOf(theme) + (ev.key === Qt.Key_Left ? -1 : 1);
            if (i >= 0 && i < themes.length)
                ctl.put("appearance.theme", themes[i]);
            return true;
        }
        return false;
    }

    Column {
        id: col
        width: parent.width
        spacing: 24
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 18
            Repeater {
                model: st.themes
                ChoiceTile {
                    required property string modelData
                    objectName: "setup.theme." + modelData
                    selected: st.theme === modelData
                    label: Strings.t("setup.appearance." + modelData)
                    note: modelData === "auto" ? Strings.t("setup.appearance.autoNote") : ""
                    scheme: st.scheme
                    previewWidth: 128
                    previewHeight: 82
                    MiniDesktop {
                        anchors.fill: parent
                        dark: modelData === "dark"
                        split: modelData === "auto"
                    }
                    onChosen: st.ctl.put("appearance.theme", modelData)
                }
            }
        }
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 10
            KText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Strings.t("setup.appearance.accent")
                textStyle: "callout"
                emphasized: true
                scheme: st.scheme
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 12
                Repeater {
                    model: st.accents
                    Item {
                        id: dot
                        required property string modelData
                        objectName: "setup.accent." + modelData
                        width: 26
                        height: 26
                        activeFocusOnTab: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData
                        Accessible.checked: st.accent === modelData
                        Keys.onSpacePressed: st.ctl.put("appearance.accent", modelData)
                        Rectangle {
                            anchors.centerIn: parent
                            width: 26
                            height: 26
                            radius: 13
                            color: Theme.accents[dot.modelData] ? Theme.accents[dot.modelData][st.scheme === "dark" ? "dark" : "light"] : "#888"
                            border.width: 1
                            border.color: Qt.rgba(0, 0, 0, 0.12)
                        }
                        Rectangle {        // selected: a white dot inside, like the Mac
                            anchors.centerIn: parent
                            visible: st.accent === dot.modelData
                            width: 9
                            height: 9
                            radius: 4.5
                            color: "#FFFFFF"
                        }
                        KFocusRing { targetRadius: 13; scheme: st.scheme }
                        TapHandler { onTapped: { dot.forceActiveFocus(Qt.MouseFocusReason); st.ctl.put("appearance.accent", dot.modelData); } }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                    }
                }
            }
            KText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: ({
                    blue: Strings.pick({ de: "Blau", en: "Blue" }), purple: Strings.pick({ de: "Lila", en: "Purple" }),
                    pink: Strings.pick({ de: "Rosa", en: "Pink" }), red: Strings.pick({ de: "Rot", en: "Red" }),
                    orange: Strings.pick({ de: "Orange", en: "Orange" }), yellow: Strings.pick({ de: "Gelb", en: "Yellow" }),
                    green: Strings.pick({ de: "Grün", en: "Green" }), graphite: Strings.pick({ de: "Graphit", en: "Graphite" })
                })[st.accent] || ""
                textStyle: "caption1"
                level: "secondaryLabel"
                scheme: st.scheme
            }
        }
    }
}
