// SPDX-License-Identifier: GPL-3.0-or-later
// An honest privacy note: what stays on the laptop, what goes to Anthropic, and that the
// assistant asks before acting.
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    readonly property string name: ctl ? ctl.assistantName : "Kristall"
    icon: "shield-check"
    title: Strings.t("setup.privacy.title")
    subtitle: Strings.t("setup.privacy.subtitle")
    cardWidth: 600
    implicitHeight: col.implicitHeight

    Column {
        id: col
        width: parent.width
        spacing: 18
        Repeater {
            model: [
                { icon: "fill/house", key: "local" },
                { icon: "fill/cloud", key: "claude" },
                { icon: "fill/hand-palm", key: "ask" }
            ]
            Row {
                required property var modelData
                width: col.width
                spacing: 16
                Rectangle {
                    width: 40
                    height: 40
                    radius: 20
                    color: Qt.rgba(Theme.accentFor(st.scheme).r, Theme.accentFor(st.scheme).g, Theme.accentFor(st.scheme).b, 0.14)
                    KIcon { anchors.centerIn: parent; name: modelData.icon; size: 20; color: Theme.accentFor(st.scheme) }
                }
                Column {
                    width: col.width - 56
                    spacing: 3
                    KText { text: Strings.t("setup.privacy." + modelData.key + ".title"); emphasized: true; scheme: st.scheme || Theme.scheme }
                    KText {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: Strings.t("setup.privacy." + modelData.key + ".text", { name: st.name })
                        textStyle: "callout"
                        level: "secondaryLabel"
                        scheme: st.scheme || Theme.scheme
                    }
                }
            }
        }
    }
}
