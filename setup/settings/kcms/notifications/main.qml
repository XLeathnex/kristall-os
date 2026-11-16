// SPDX-License-Identifier: GPL-3.0-or-later
// Notifications & Focus: Do Not Disturb (`panels.focus.until`: 0 off, -1 on, > now until then)
// and the apps whose banners are silenced (`panels.mutedApps`) — the panels module's keys.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    readonly property real until: Number(Lang.setting("panels.focus.until", 0))
    readonly property bool dnd: until === -1 || until > Date.now()
    readonly property var muted: Lang.setting("panels.mutedApps", []) || []

    Kirigami.FormLayout {
        QQC2.Switch {
            objectName: "notifications.dnd"
            Kirigami.FormData.label: Lang.t("Nicht stören:", "Do Not Disturb:")
            checked: page.dnd
            text: page.dnd ? (page.until > 0 ? Lang.t("An bis ", "On until ") + new Date(page.until).toLocaleTimeString(Qt.locale(), Locale.ShortFormat) : Lang.t("An", "On"))
                           : Lang.t("Aus", "Off")
            onToggled: Settings.set("panels.focus.until", checked ? -1 : 0)
        }
        RowLayout {
            QQC2.Button { text: Lang.t("1 Stunde", "For 1 hour"); onClicked: Settings.set("panels.focus.until", Date.now() + 3600 * 1000) }
            QQC2.Button {
                text: Lang.t("Bis morgen früh", "Until tomorrow morning")
                onClicked: { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(7, 0, 0, 0); Settings.set("panels.focus.until", d.getTime()); }
            }
        }
        Note { text: Lang.t("Während „Nicht stören“ erscheinen keine Mitteilungen auf dem Bildschirm; du findest sie in der Mitteilungszentrale. Dringende Mitteilungen kommen trotzdem.",
                            "While Do Not Disturb is on, nothing pops up; you find everything in Notification Centre. Urgent notifications still come through.") }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Stummgeschaltete Apps", "Silenced Apps") }
        QQC2.Label {
            visible: page.muted.length === 0
            text: Lang.t("Keine. Eine App stummschalten: rechte Maustaste auf eine ihrer Mitteilungen.", "None. To silence an app, right-click one of its notifications.")
            wrapMode: Text.WordWrap
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        }
        Repeater {
            model: page.muted
            RowLayout {
                required property string modelData
                QQC2.Label { text: modelData; Layout.minimumWidth: Kirigami.Units.gridUnit * 12 }
                QQC2.Button {
                    text: Lang.t("Wieder erlauben", "Allow Again")
                    onClicked: Settings.set("panels.mutedApps", page.muted.filter(a => a !== modelData))
                }
            }
        }
    }
}
