// SPDX-License-Identifier: GPL-3.0-or-later
// Mac keyboard shortcuts (`keyboard.macShortcuts`, published for the menus as
// `keyboard.commandKey`): the owner's own keys, labelled as printed, with their Mac roles; a
// tiny "try it" — press Command-C (the key beside the space bar + C) and see what arrived.
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    icon: "command"
    title: Strings.t("setup.keyboard.title")
    subtitle: Strings.t("setup.keyboard.subtitle")
    cardWidth: 620
    implicitHeight: col.implicitHeight

    readonly property bool mac: ctl ? ctl.macKeys : true
    readonly property var kb: ctl ? ctl.helper.keyboard : null
    readonly property bool working: kb !== null && kb.active === true
    property string tried: ""          // "" | mac | pc
    property bool litCmd: false
    property bool litC: false

    function setMac(on) {
        ctl.put("keyboard.macShortcuts", on);
        ctl.put("keyboard.commandKey", on ? "ctrl" : "");
        tried = "";
    }
    function primary() {
        setMac(mac);          // Continue confirms the choice shown (the default: Mac shortcuts)
        ctl.next();
    }
    function keyPressed(ev) {
        // what the window received tells which way the keys are working right now
        if (ev.key === Qt.Key_Control || ev.key === Qt.Key_Alt || ev.key === Qt.Key_Meta) {
            litCmd = true;
            return false;
        }
        if (ev.key === Qt.Key_C) {
            litC = true;
            if (ev.modifiers & Qt.ControlModifier)
                tried = st.mac ? "mac" : "pc";
            else if (ev.modifiers & Qt.AltModifier)
                tried = "alt";
            release.restart();
            return true;
        }
        return false;
    }
    Timer { id: release; interval: 450; onTriggered: { st.litCmd = false; st.litC = false; } }

    Column {
        id: col
        width: parent.width
        spacing: 18
        Row {          // the owner's bottom-left keys, as printed, and what they do
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            Keycap { legend: "Strg"; glyph: st.mac ? "⌃" : ""; role: st.mac ? Strings.t("setup.keyboard.control") : ""; scheme: st.scheme }
            Keycap { legend: "Win"; glyph: st.mac ? "⌥" : ""; role: st.mac ? Strings.t("setup.keyboard.option") : ""; scheme: st.scheme }
            Keycap { legend: "Alt"; glyph: st.mac ? "⌘" : ""; role: st.mac ? Strings.t("setup.keyboard.command") : ""; lit: st.litCmd; scheme: st.scheme }
            Keycap { legend: ""; keyWidth: 150; scheme: st.scheme }
            Keycap { legend: "C"; lit: st.litC; scheme: st.scheme }
        }
        KSegmented {
            id: seg
            objectName: "setup.keyboard.choice"
            anchors.horizontalCenter: parent.horizontalCenter
            width: 420
            model: [Strings.t("setup.keyboard.yes"), Strings.t("setup.keyboard.no")]
            currentIndex: st.mac ? 0 : 1
            scheme: st.scheme
            onActivated: i => st.setMac(i === 0)
        }
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: st.mac ? Strings.t("setup.keyboard.yesNote") : Strings.t("setup.keyboard.noNote")
            textStyle: "callout"
            level: "secondaryLabel"
            scheme: st.scheme
        }
        Rectangle {          // try it
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width, tryText.implicitWidth + 40)
            height: 40
            radius: 20
            color: st.tried === "mac" || st.tried === "pc" ? Qt.rgba(Theme.color(st.scheme, "success").r, Theme.color(st.scheme, "success").g, Theme.color(st.scheme, "success").b, 0.16) : Theme.color(st.scheme, "fill")
            KText {
                id: tryText
                objectName: "setup.keyboard.try"
                anchors.centerIn: parent
                text: st.mac && !st.working && st.kb !== null ? Strings.t("setup.keyboard.unavailable")
                      : st.tried === "mac" ? "✓ " + Strings.t("setup.keyboard.tryOk")
                      : st.tried === "pc" ? "✓ " + Strings.t("setup.keyboard.tryPc")
                      : Strings.t("setup.keyboard.try", { keys: st.mac ? "Alt + C" : "Strg + C" })
                textStyle: "callout"
                emphasized: st.tried !== ""
                scheme: st.scheme
            }
        }
    }
}
