// SPDX-License-Identifier: GPL-3.0-or-later
// Battery & Energy (docs/contracts/power.md): the mode (Automatic, Quiet, Balanced, Performance),
// the battery, a charge limit where the hardware has one, and the doctor report as a readable
// health check with a one-click "Save Report".
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    readonly property string tool: System.env("KRISTALL_POWER_CMD", "kristall-power")
    property var st: null
    readonly property var daemon: powerFile.data
    readonly property bool auto: daemon ? (daemon.automatic && !daemon.manual) : Lang.setting("power.automatic", true) === true
    readonly property string mode: st ? String(st.mode || "") : ""
    readonly property var battery: st ? st.battery : null
    readonly property var limit: st ? st.charge_limit : null
    readonly property int chargeLimit: Number(Lang.setting("power.chargeLimit", 100))
    property var report: null
    property string savedTo: ""
    property string reportDir: System.runtimeDir() + "/kristall/doctor-" + Date.now()

    JsonProcess { id: status; program: page.tool; arguments: ["status", "--json"]; onFinished: (c, r) => { if (r) page.st = r; } Component.onCompleted: start() }
    JsonProcess { id: setMode; program: page.tool; onFinished: status.start() }
    JsonProcess {
        id: doctor
        program: page.tool
        onFinished: (c, r) => page.report = r && r.kind === "kristall-power-doctor" ? r : (c === 0 ? { summary: null, levers: [] } : null)
    }
    JsonFile { id: powerFile; path: System.runtimeDir() + "/kristall/power.json"; onDataChanged: status.start() }

    function modeName(m) {
        return ({ quiet: Lang.t("Leise", "Quiet"), balanced: Lang.t("Ausgewogen", "Balanced"), performance: Lang.t("Leistung", "Performance") })[m] || m;
    }
    function leverText(l) {
        const names = {
            "epp": Lang.t("Prozessor-Sparmodus", "Processor power saving"), "charge-limit": Lang.t("Ladegrenze", "Charge limit"),
            "pcie-aspm": Lang.t("Stromsparen der Geräte", "Device power saving"), "platform-profile": Lang.t("Lüfterprofil des Herstellers", "Maker's fan profile"),
            "zram": Lang.t("Komprimierter Arbeitsspeicher", "Compressed memory"), "deep-idle": Lang.t("Tiefschlaf im Leerlauf", "Deep sleep when idle"),
            "turbo": "Turbo", "refresh-rate": Lang.t("Bildwiederholrate", "Refresh rate"), "glass-quality": Lang.t("Glas-Qualität", "Glass quality"),
            "automatic-mode": Lang.t("Automatischer Modus", "Automatic mode"), "wifi-power-save": Lang.t("WLAN-Stromsparen", "Wi-Fi power saving")
        };
        return names[l.lever] || l.lever;
    }
    function statusText(s) {
        return ({ applied: Lang.t("aktiv", "active"), unsupported: Lang.t("nicht vorhanden", "not available"), locked: Lang.t("vom Hersteller festgelegt", "set by the maker"),
                  failed: Lang.t("fehlgeschlagen", "failed"), warning: Lang.t("Hinweis", "note"), unknown: Lang.t("unbekannt", "unknown"),
                  skipped: Lang.t("übersprungen", "skipped") })[s] || s;
    }
    function saveReport() {
        const name = Lang.t("Kristall-Bericht-", "Kristall-Report-") + System.today() + ".json";
        const dest = System.desktopDir() + "/" + name;
        if (System.copyFile(page.reportDir + "/doctor.json", dest))
            page.savedTo = dest;
    }

    Kirigami.FormLayout {
        QQC2.ComboBox {
            implicitContentWidthPolicy: QQC2.ComboBox.WidestText
            id: modeBox
            objectName: "energy.mode"
            Kirigami.FormData.label: Lang.t("Energiemodus:", "Energy mode:")
            readonly property var values: ["auto", "quiet", "balanced", "performance"]
            model: [Lang.t("Automatisch", "Automatic"), modeName("quiet"), modeName("balanced"), modeName("performance")]
            currentIndex: page.auto ? 0 : Math.max(0, values.indexOf(page.mode === "power-saver" ? "quiet" : page.mode))
            onActivated: i => setMode.run(["mode", values[i]])
        }
        Note {
            text: page.auto ? Lang.t("Wählt selbst: leise im Akkubetrieb, volle Leistung, wenn ein Spiel oder Blender sie braucht. Gerade: ",
                                     "Chooses by itself: quiet on battery, full power when a game or Blender needs it. Right now: ") + page.modeName(page.mode) + "."
                            : Lang.t("Du hast selbst gewählt. „Automatisch“ übernimmt wieder, wenn du es auswählst oder dich neu anmeldest.",
                                     "You chose yourself. “Automatic” takes over again when you pick it or log in again.")
        }
        QQC2.CheckBox {
            Kirigami.FormData.label: Lang.t("Im Akkubetrieb:", "On battery:")
            text: Lang.t("Bildschirm etwas abdunkeln", "Slightly dim the display")
            checked: Lang.setting("power.dimOnBattery", true) === true
            onToggled: Settings.set("power.dimOnBattery", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Bildwiederholrate senken (spart Strom)", "Lower the refresh rate (saves power)")
            checked: Lang.setting("power.batteryRefreshRate", "auto") === "auto"
            onToggled: Settings.set("power.batteryRefreshRate", checked ? "auto" : "max")
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Batterie", "Battery") }
        QQC2.Label {
            objectName: "energy.battery"
            Kirigami.FormData.label: Lang.t("Zustand:", "Condition:")
            visible: page.battery !== null && page.battery !== undefined
            text: page.battery ? page.battery.percent + " %" + (page.battery.health_percent ? Lang.t(" · Kapazität ", " · capacity ") + Math.round(page.battery.health_percent) + Lang.t(" % des Neuzustands", " % of new") : "") : ""
        }
        QQC2.Switch {
            objectName: "energy.limit"
            Kirigami.FormData.label: Lang.t("Batterie schonen:", "Protect battery:")
            visible: page.limit !== null && page.limit !== undefined && page.limit.supported === true
            text: Lang.t("Laden bei 80 % beenden", "Stop charging at 80 %")
            checked: page.chargeLimit < 100
            onToggled: Settings.set("power.chargeLimit", checked ? 80 : 100)
        }
        Note {
            visible: page.limit !== null && page.limit !== undefined && page.limit.supported === true
            text: Lang.t("Gut, wenn der Laptop meistens am Netz hängt. Vor einer langen Reise ausschalten.", "Good if the laptop is plugged in most of the time. Turn it off before a long trip.")
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Gesundheitscheck", "Health Check") }
        RowLayout {
            Kirigami.FormData.label: Lang.t("Energie-Check:", "Energy check:")
            QQC2.Button {
                objectName: "energy.check"
                text: Lang.t("Jetzt prüfen", "Check Now")
                enabled: !doctor.running
                onClicked: { page.savedTo = ""; page.report = null; doctor.run(["doctor", "--json", "--out", page.reportDir]); }
            }
            QQC2.BusyIndicator { visible: doctor.running; running: visible }
        }
        QQC2.Label {
            objectName: "energy.summary"
            visible: page.report !== null
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
            wrapMode: Text.WordWrap
            font.weight: Font.DemiBold
            text: page.report && page.report.summary ? Lang.pick(page.report.summary) : Lang.t("Der Check ist fertig.", "The check is done.")
        }
        Repeater {
            model: page.report ? (page.report.levers || []).slice(0, 12) : []
            RowLayout {
                required property var modelData
                Kirigami.Icon {
                    implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth
                    source: modelData.status === "applied" ? "checkmark" : (modelData.status === "warning" || modelData.status === "failed") ? "dialog-warning" : "dialog-information"
                }
                QQC2.Label { text: page.leverText(modelData) + ": " + page.statusText(modelData.status) }
            }
        }
        RowLayout {
            visible: page.report !== null
            QQC2.Button {
                objectName: "energy.save"
                text: Lang.t("Bericht sichern", "Save Report")
                icon.name: "document-save"
                onClicked: page.saveReport()
            }
            QQC2.Button {
                visible: page.savedTo !== ""
                text: Lang.t("Im Dateimanager zeigen", "Show in Files")
                onClicked: System.showInFiles(page.savedTo)
            }
        }
        QQC2.Label {
            objectName: "energy.saved"
            visible: page.savedTo !== ""
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
            wrapMode: Text.WordWrap
            text: Lang.t("Gesichert auf dem Schreibtisch: ", "Saved to the desktop: ") + page.savedTo.split("/").pop()
        }
    }
}
