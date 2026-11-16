// SPDX-License-Identifier: GPL-3.0-or-later
// Dock & Menu Bar: the Dock's size, magnification and hiding (`dock.*`, the dock module's keys)
// and what the menu bar shows (`bar.*`, shell-core's keys). Live.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    function flag(path, def) { return Lang.setting(path, def) === true; }

    Kirigami.FormLayout {
        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Dock" }
        RowLayout {
            Kirigami.FormData.label: Lang.t("Größe:", "Size:")
            QQC2.Label { text: Lang.t("Klein", "Small") }
            QQC2.Slider {
                objectName: "dock.size"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 12
                from: 32; to: 80; stepSize: 2
                value: Number(Lang.setting("dock.size", 48))
                onMoved: Settings.set("dock.size", Math.round(value))
            }
            QQC2.Label { text: Lang.t("Groß", "Large") }
        }
        QQC2.CheckBox {
            objectName: "dock.magnification"
            Kirigami.FormData.label: Lang.t("Vergrößerung:", "Magnification:")
            text: Lang.t("Symbole unter dem Zeiger vergrößern", "Enlarge icons under the pointer")
            checked: page.flag("dock.magnification", true)
            onToggled: Settings.set("dock.magnification", checked)
        }
        RowLayout {
            enabled: page.flag("dock.magnification", true)
            QQC2.Label { text: Lang.t("Wenig", "Less") }
            QQC2.Slider {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 12
                from: Number(Lang.setting("dock.size", 48)) + 8; to: 128; stepSize: 2
                value: Number(Lang.setting("dock.magnifiedSize", 76))
                onMoved: Settings.set("dock.magnifiedSize", Math.round(value))
            }
            QQC2.Label { text: Lang.t("Viel", "More") }
        }
        QQC2.CheckBox {
            objectName: "dock.autoHide"
            text: Lang.t("Dock automatisch ein- und ausblenden", "Automatically hide and show the Dock")
            checked: page.flag("dock.autoHide", false)
            onToggled: Settings.set("dock.autoHide", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Fenster in das App-Symbol ablegen", "Minimise windows into the app's icon")
            checked: page.flag("dock.minimizeToApp", false)
            onToggled: Settings.set("dock.minimizeToApp", checked)
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Menüleiste", "Menu Bar") }
        QQC2.CheckBox {
            objectName: "bar.dimWhenMaximized"
            Kirigami.FormData.label: Lang.t("Menüleiste:", "Menu bar:")
            text: Lang.t("Abdunkeln, wenn ein Fenster den Bildschirm füllt", "Dim when a window fills the screen")
            checked: page.flag("bar.dimWhenMaximized", true)
            onToggled: Settings.set("bar.dimWhenMaximized", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Assistent in der Menüleiste zeigen", "Show the assistant in the menu bar")
            checked: page.flag("bar.showAssistant", true)
            onToggled: Settings.set("bar.showAssistant", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Kontrollzentrum in der Menüleiste zeigen", "Show Control Center in the menu bar")
            checked: page.flag("bar.showControlCenter", true)
            onToggled: Settings.set("bar.showControlCenter", checked)
        }
        QQC2.CheckBox {
            objectName: "bar.showBatteryPercentage"
            text: Lang.t("Batterie in Prozent zeigen", "Show battery percentage")
            checked: page.flag("bar.showBatteryPercentage", false)
            onToggled: Settings.set("bar.showBatteryPercentage", checked)
        }
        QQC2.CheckBox {
            Kirigami.FormData.label: Lang.t("Uhr:", "Clock:")
            text: Lang.t("Datum zeigen", "Show the date")
            checked: page.flag("bar.showDate", true)
            onToggled: Settings.set("bar.showDate", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Wochentag zeigen", "Show the day of the week")
            checked: page.flag("bar.showDayOfWeek", true)
            onToggled: Settings.set("bar.showDayOfWeek", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Sekunden zeigen", "Show seconds")
            checked: page.flag("bar.showSeconds", false)
            onToggled: Settings.set("bar.showSeconds", checked)
        }
        QQC2.ComboBox {
            implicitContentWidthPolicy: QQC2.ComboBox.WidestText
            Kirigami.FormData.label: Lang.t("Zeitformat:", "Time format:")
            model: [Lang.t("Wie die Region", "Like the region"), Lang.t("24 Stunden", "24-hour"), Lang.t("12 Stunden", "12-hour")]
            readonly property var values: ["auto", "24h", "12h"]
            currentIndex: Math.max(0, values.indexOf(String(Lang.setting("bar.clock", "auto"))))
            onActivated: i => Settings.set("bar.clock", values[i])
        }
    }
}
