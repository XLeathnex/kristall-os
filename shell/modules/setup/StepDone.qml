// SPDX-License-Identifier: GPL-3.0-or-later
// The closing screen: three things worth knowing (Search, the assistant, Settings) while the
// default apps finish installing in the background (progress from the apps contract).
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    readonly property string name: ctl ? ctl.assistantName : "Kristall"
    icon: "check-circle"
    title: Strings.t("setup.finish.title")
    subtitle: Strings.t("setup.finish.subtitle")
    cardWidth: 600
    implicitHeight: col.implicitHeight
    primaryText: Strings.t("setup.finish.start")
    showBack: true

    readonly property var apps: ctl ? ctl.helper.apps : null
    readonly property string appsState: apps ? String(apps.state || "") : ""
    readonly property int total: apps ? Number(apps.total || 0) : 0
    readonly property int doneN: apps ? Number(apps.done || 0) : 0
    function primary() { ctl.finish(); }

    Column {
        id: col
        width: parent.width
        spacing: 16
        Repeater {
            model: [
                { icon: "magnifying-glass", key: "search", keys: st.ctl ? st.ctl.keysFor("search") : "" },
                { icon: "kristall/assistant", key: "assistant", keys: st.ctl ? st.ctl.keysFor("assistant") : "" },
                { icon: "gear", key: "settings", keys: "" }
            ]
            Row {
                required property var modelData
                width: col.width
                spacing: 16
                Rectangle {
                    width: 44
                    height: 44
                    radius: 12
                    color: Theme.color(st.scheme, "fill")
                    KIcon { anchors.centerIn: parent; name: modelData.icon; size: 22; color: Theme.accentFor(st.scheme) }
                }
                Column {
                    width: col.width - 60
                    spacing: 2
                    anchors.verticalCenter: parent.verticalCenter
                    KText { text: Strings.t("setup.finish." + modelData.key + ".title"); emphasized: true; scheme: st.scheme || Theme.scheme }
                    KText {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: Strings.t("setup.finish." + modelData.key + ".text", { keys: modelData.keys, name: st.name, icon: "✦" })
                        textStyle: "callout"
                        level: "secondaryLabel"
                        scheme: st.scheme || Theme.scheme
                    }
                }
            }
        }
        Item { width: 1; height: 4 }
        // the apps installing in the background
        Column {
            width: parent.width
            spacing: 6
            visible: st.apps !== null && st.appsState !== "not-started"
            KText {
                objectName: "setup.finish.apps"
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: st.appsState === "done" ? Strings.t("setup.finish.apps.done")
                      : st.appsState === "waiting-for-network" ? Strings.t("setup.finish.apps.waiting")
                      : st.appsState === "error" ? Strings.t("setup.finish.apps.someFailed")
                      : Strings.t("setup.finish.apps.installing", { done: st.doneN, total: st.total })
                textStyle: "caption1"
                level: "secondaryLabel"
                scheme: st.scheme || Theme.scheme
            }
            Rectangle {
                visible: st.appsState === "installing" && st.total > 0
                anchors.horizontalCenter: parent.horizontalCenter
                width: 260
                height: 4
                radius: 2
                color: Theme.color(st.scheme, "trackOff")
                Rectangle {
                    width: parent.width * Math.min(1, st.total > 0 ? st.doneN / st.total : 0)
                    height: parent.height
                    radius: 2
                    color: Theme.accentFor(st.scheme)
                    Behavior on width { NumberAnimation { duration: Theme.duration("long") } }
                }
            }
        }
    }
}
