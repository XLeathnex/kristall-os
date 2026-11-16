// SPDX-License-Identifier: GPL-3.0-or-later
// The assistant's name, its first language and when it reads answers aloud
// (`assistant.name`, `assistant.language`, `assistant.speak_replies`).
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    icon: "user-sound"
    title: Strings.t("setup.voice.title")
    subtitle: Strings.t("setup.voice.subtitle")
    cardWidth: 600
    implicitHeight: col.implicitHeight

    readonly property var speakModes: ["always", "voice_only", "never"]
    readonly property string lang: ctl ? ctl.value("assistant.language", "de") : "de"
    readonly property string speak: ctl ? ctl.value("assistant.speak_replies", "voice_only") : "voice_only"

    function saveName() {
        const n = nameField.text.trim();
        if (n !== "" && n !== ctl.value("assistant.name", "Kristall"))
            ctl.put("assistant.name", n.slice(0, 40));
    }
    function primary() {
        saveName();
        ctl.next();
    }
    onCtlChanged: if (ctl) nameField.text = ctl.assistantName

    component Line: Rectangle {
        id: line
        property string scheme: Theme.scheme
        property alias label: lbl.text
        default property alias control: holder.data
        width: parent ? parent.width : 0
        height: 52
        radius: 0
        color: "transparent"
        KText { id: lbl; x: 16; anchors.verticalCenter: parent.verticalCenter; scheme: line.scheme }
        Item { id: holder; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; width: childrenRect.width; height: childrenRect.height }
    }

    Column {
        id: col
        width: parent.width
        spacing: 0
        Rectangle {
            width: parent.width
            height: lines.height
            radius: 14
            color: Theme.color(st.scheme, "fill")
            Column {
                id: lines
                width: parent.width
                Line {
                    scheme: st.scheme
                    label: Strings.t("setup.voice.name")
                    KTextField {
                        id: nameField
                        objectName: "setup.voice.name"
                        width: 220
                        scheme: st.scheme
                        onAccepted: st.saveName()
                        input.onActiveFocusChanged: if (!input.activeFocus) st.saveName()
                    }
                }
                KSeparator { x: 16; width: parent.width - 32; scheme: st.scheme }
                Line {
                    scheme: st.scheme
                    label: Strings.t("setup.voice.language")
                    KSegmented {
                        objectName: "setup.voice.language"
                        width: 220
                        model: ["Deutsch", "English"]
                        currentIndex: st.lang === "en" ? 1 : 0
                        scheme: st.scheme
                        onActivated: i => st.ctl.put("assistant.language", i === 1 ? "en" : "de")
                    }
                }
                KSeparator { x: 16; width: parent.width - 32; scheme: st.scheme }
                Line {
                    scheme: st.scheme
                    label: Strings.t("setup.voice.speak")
                    KSegmented {
                        objectName: "setup.voice.speak"
                        width: 340
                        model: st.speakModes.map(m => Strings.t("setup.voice.speak." + m))
                        currentIndex: st.speakModes.indexOf(st.speak)
                        scheme: st.scheme
                        onActivated: i => st.ctl.put("assistant.speak_replies", st.speakModes[i])
                    }
                }
            }
        }
        Item { width: 1; height: 16 }
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: Strings.t("setup.voice.call", { name: st.ctl ? st.ctl.assistantName : "Kristall", keys: st.ctl ? st.ctl.keysFor("assistant") : "" })
            textStyle: "callout"
            level: "secondaryLabel"
            scheme: st.scheme
        }
    }
}
