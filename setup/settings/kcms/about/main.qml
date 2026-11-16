// SPDX-License-Identifier: GPL-3.0-or-later
// About This Computer: the calm summary — our mark, the OS and its version, the machine's
// processor, memory, graphics and storage. Not a diagnostics dump.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    readonly property string helper: System.env("KRISTALL_SETUP_HELPER", "kristall-setup-helper")
    readonly property var info: sysinfo.result && sysinfo.result.info ? sysinfo.result.info : null
    property var update: null

    JsonProcess { id: sysinfo; program: page.helper; arguments: ["system-info"]; Component.onCompleted: start() }
    JsonProcess {
        id: upd
        program: System.env("KRISTALL_UPDATE_CMD", "kristall-update")
        arguments: ["status", "--json"]
        Component.onCompleted: start()
        onFinished: (code, r) => page.update = r
    }
    readonly property string version: update && update.booted && update.booted.version ? update.booted.version : (info ? info.osVersion : "")

    ColumnLayout {
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width, Kirigami.Units.gridUnit * 30)
        spacing: Kirigami.Units.largeSpacing

        Item { Layout.preferredHeight: Kirigami.Units.gridUnit }
        Crystal {
            Layout.alignment: Qt.AlignHCenter
            size: Kirigami.Units.gridUnit * 7
        }
        Kirigami.Heading {
            objectName: "about.name"
            Layout.alignment: Qt.AlignHCenter
            text: "Kristall OS"
            level: 1
            font.weight: Font.DemiBold
        }
        QQC2.Label {
            objectName: "about.version"
            Layout.alignment: Qt.AlignHCenter
            text: page.version !== "" ? Lang.t("Version ", "Version ") + page.version : ""
            color: Kirigami.Theme.disabledTextColor
        }
        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing }

        Kirigami.FormLayout {
            Layout.alignment: Qt.AlignHCenter
            QQC2.Label {
                visible: page.info !== null && page.info.model !== ""
                Kirigami.FormData.label: Lang.t("Computer:", "Computer:")
                text: page.info ? page.info.model : ""
            }
            QQC2.Label {
                objectName: "about.processor"
                Kirigami.FormData.label: Lang.t("Prozessor:", "Processor:")
                text: page.info ? page.info.processor + (page.info.cores ? Lang.t(" (" + page.info.cores + " Threads)", " (" + page.info.cores + " threads)") : "") : "…"
            }
            QQC2.Label {
                objectName: "about.memory"
                Kirigami.FormData.label: Lang.t("Arbeitsspeicher:", "Memory:")
                text: page.info ? page.info.memoryGB + " GB" : "…"
            }
            QQC2.Label {
                objectName: "about.graphics"
                Kirigami.FormData.label: Lang.t("Grafik:", "Graphics:")
                text: page.info ? (page.info.graphics.length > 0 ? page.info.graphics.join(", ") : Lang.t("Integriert", "Built-in")) : "…"
            }
            QQC2.Label {
                objectName: "about.storage"
                Kirigami.FormData.label: Lang.t("Speicherplatz:", "Storage:")
                text: page.info ? Lang.t(System.formatBytes(page.info.storageFree, "de") + " frei von " + System.formatBytes(page.info.storageTotal, "de"),
                                         System.formatBytes(page.info.storageFree, "en") + " available of " + System.formatBytes(page.info.storageTotal, "en")) : "…"
            }
        }
        Item { Layout.preferredHeight: Kirigami.Units.largeSpacing }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Kirigami.Units.largeSpacing
            QQC2.Button {
                objectName: "about.update"
                text: Lang.t("Softwareupdate …", "Software Update…")
                onClicked: System.launch(["systemsettings", "kcm_kristall_update"])
            }
            QQC2.Button {
                objectName: "about.setup"
                text: Lang.t("Einrichtung erneut öffnen …", "Open Setup Again…")
                onClicked: System.launch([System.env("KRISTALL_SHELLCTL", "kristall-shellctl"), "setup", "start", "welcome"])
            }
        }
        QQC2.Label {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: Kirigami.Units.gridUnit
            text: Lang.t("Freie Software · GPL", "Free software · GPL")
            color: Kirigami.Theme.disabledTextColor
            font: Kirigami.Theme.smallFont
        }
    }
}
