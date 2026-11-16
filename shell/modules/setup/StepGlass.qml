// SPDX-License-Identifier: GPL-3.0-or-later
// The Liquid Glass slider, from ultra-clear to fully tinted (`appearance.glass`). The card itself,
// the menu bar and the Dock beside it follow while the knob moves.
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    icon: "drop"
    title: Strings.t("setup.glass.title")
    subtitle: Strings.t("setup.glass.subtitle")
    side: "left"
    cardWidth: 560
    implicitHeight: col.implicitHeight

    readonly property real glass: ctl ? Number(ctl.value("appearance.glass", 0.3)) : 0.3

    Column {
        id: col
        width: parent.width
        spacing: 14
        Item { width: 1; height: 8 }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 14
            KIcon { anchors.verticalCenter: parent.verticalCenter; name: "drop-half"; size: 18; color: Theme.color(st.scheme, "secondaryLabel") }
            KSlider {
                id: slider
                objectName: "setup.glass.slider"
                width: 320
                anchors.verticalCenter: parent.verticalCenter
                value: st.glass
                step: 0.1
                scheme: st.scheme
                label: Strings.t("setup.glass.title")
                onMoved: v => st.ctl.put("appearance.glass", Math.round(v * 100) / 100)
            }
            KIcon { anchors.verticalCenter: parent.verticalCenter; name: "fill/drop"; size: 18; color: Theme.color(st.scheme, "secondaryLabel") }
        }
        Item {
            width: 360
            height: 16
            anchors.horizontalCenter: parent.horizontalCenter
            KText { anchors.left: parent.left; text: Strings.t("setup.glass.clear"); textStyle: "caption1"; level: "secondaryLabel"; scheme: st.scheme }
            KText { anchors.right: parent.right; text: Strings.t("setup.glass.tinted"); textStyle: "caption1"; level: "secondaryLabel"; scheme: st.scheme }
        }
        Item { width: 1; height: 6 }
        KText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: Strings.t("setup.glass.note")
            textStyle: "callout"
            level: "secondaryLabel"
            scheme: st.scheme
        }
    }
    function keyPressed(ev) {
        if (ev.key === Qt.Key_Left || ev.key === Qt.Key_Right) {
            const v = Math.max(0, Math.min(1, Math.round((glass + (ev.key === Qt.Key_Left ? -0.1 : 0.1)) * 10) / 10));
            ctl.put("appearance.glass", v);
            return true;
        }
        return false;
    }
}
