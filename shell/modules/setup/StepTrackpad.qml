// SPDX-License-Identifier: GPL-3.0-or-later
// Scrolling direction and tap to click, as a Mac owner expects them by default (natural, on).
// Applied to every touchpad through KWin (which keeps them); shown only when there is one.
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    icon: "hand-tap"
    title: Strings.t("setup.trackpad.title")
    subtitle: Strings.t("setup.trackpad.subtitle")
    cardWidth: 600
    implicitHeight: col.implicitHeight

    readonly property var pad: ctl && ctl.helper.touchpads.length > 0 ? ctl.helper.touchpads[0] : null
    property var natural: null         // the owner's choice; null = Mac default (natural)
    property var tap: null
    readonly property bool naturalShown: natural !== null ? natural : true
    readonly property bool tapShown: tap !== null ? tap : true

    function apply() {
        ctl.helper.run([ctl.helper.tool, "touchpad-set", "--natural", naturalShown ? "on" : "off", "--tap", tapShown ? "on" : "off"],
                       r => { if (r && r.touchpads) ctl.helper.touchpads = r.touchpads; });
    }
    function primary() {
        apply();
        ctl.next();
    }

    component Pad: Item {
        id: padItem
        property bool up: true
        property string scheme: Theme.scheme
        Rectangle {
            anchors.fill: parent
            radius: 10
            color: padItem.scheme === "dark" ? "#3A3A3C" : "#E9E9ED"
            border.width: 1
            border.color: Theme.color(padItem.scheme, "border")
        }
        Column {
            anchors.centerIn: parent
            spacing: 2
            KIcon { anchors.horizontalCenter: parent.horizontalCenter; name: up ? "arrow-up" : "arrow-down"; size: 18; color: Theme.accentFor(padItem.scheme) }
            KIcon { anchors.horizontalCenter: parent.horizontalCenter; name: "hand-pointing"; size: 26; color: Theme.color(padItem.scheme, "label") }
        }
    }

    Column {
        id: col
        width: parent.width
        spacing: 22
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 28
            ChoiceTile {
                objectName: "setup.trackpad.natural"
                selected: st.naturalShown
                label: Strings.t("setup.trackpad.natural")
                note: Strings.t("setup.trackpad.naturalNote")
                scheme: st.scheme
                previewWidth: 150
                previewHeight: 96
                Pad { anchors.fill: parent; up: true; scheme: st.scheme }
                onChosen: { st.natural = true; st.apply(); }
            }
            ChoiceTile {
                objectName: "setup.trackpad.classic"
                selected: !st.naturalShown
                label: Strings.t("setup.trackpad.classic")
                note: Strings.t("setup.trackpad.classicNote")
                scheme: st.scheme
                previewWidth: 150
                previewHeight: 96
                Pad { anchors.fill: parent; up: false; scheme: st.scheme }
                onChosen: { st.natural = false; st.apply(); }
            }
        }
        Rectangle {
            width: parent.width
            height: 56
            radius: 14
            color: Theme.color(st.scheme, "fill")
            Column {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                KText { text: Strings.t("setup.trackpad.tap"); scheme: st.scheme; emphasized: true }
                KText { text: Strings.t("setup.trackpad.tapNote"); textStyle: "caption1"; level: "secondaryLabel"; scheme: st.scheme }
            }
            KToggle {
                objectName: "setup.trackpad.tap"
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                checked: st.tapShown
                label: Strings.t("setup.trackpad.tap")
                scheme: st.scheme
                onToggled: v => { st.tap = v; st.apply(); }
            }
        }
    }
}
