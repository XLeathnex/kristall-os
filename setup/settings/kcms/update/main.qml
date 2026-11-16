// SPDX-License-Identifier: GPL-3.0-or-later
// Software Update (docs/contracts/update.md): the state in one sentence, Check Now, Install,
// Restart to finish, and "return to the previous version" with an honest explanation. Live:
// the state file is watched (inotify) and `kristall-update status --json` re-read on change.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    readonly property string tool: System.env("KRISTALL_UPDATE_CMD", "kristall-update")
    property var st: null
    property bool confirming: false
    readonly property string state: st ? String(st.state || "unknown") : "unknown"
    function v(o) { return o && o.version ? o.version : ""; }

    JsonProcess { id: status; program: page.tool; arguments: ["status", "--json"]; onFinished: (c, r) => { if (r) page.st = r; } Component.onCompleted: start() }
    JsonProcess { id: action; program: page.tool; onFinished: (c, r) => { if (r && r.state) page.st = r; status.start(); } }
    JsonFile {
        path: System.env("KRISTALL_UPDATE_STATE_DIR", "/var/lib/kristall/update") + "/state.json"
        onDataChanged: status.start()
    }
    JsonFile {        // the test mock writes its status here (the real tool reads state.json)
        path: System.env("KRISTALL_UPDATE_STATE_DIR", "/var/lib/kristall/update") + "/status.json"
        onDataChanged: status.start()
    }

    ColumnLayout {
        width: Math.min(parent.width, Kirigami.Units.gridUnit * 32)
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.topMargin: Kirigami.Units.gridUnit
            spacing: Kirigami.Units.largeSpacing * 2
            Kirigami.Icon {
                source: page.state === "up-to-date" ? "checkmark" : page.state === "error" ? "dialog-warning" : "system-software-update"
                implicitWidth: Kirigami.Units.iconSizes.huge
                implicitHeight: implicitWidth
            }
            ColumnLayout {
                Kirigami.Heading {
                    objectName: "update.headline"
                    level: 2
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: ({
                        "checking": Lang.t("Suche nach Updates …", "Checking for updates…"),
                        "downloading": Lang.t("Update wird geladen …", "Downloading the update…"),
                        "rolling-back": Lang.t("Vorherige Version wird vorbereitet …", "Preparing the previous version…"),
                        "rollback-queued": Lang.t("Beim nächsten Neustart startet die vorherige Version.", "The previous version starts at the next restart."),
                        "restart-required": Lang.t("Update bereit – Neustart zum Abschließen.", "Update ready – restart to finish."),
                        "update-available": Lang.t("Ein Update ist verfügbar.", "An update is available."),
                        "error": Lang.t("Das letzte Update hat nicht geklappt.", "The last update didn't work."),
                        "up-to-date": Lang.t("Kristall OS ist auf dem neuesten Stand.", "Kristall OS is up to date."),
                        "unknown": Lang.t("Der Update-Status ist gerade nicht bekannt.", "The update status isn't known right now.")
                    })[page.state] || page.state
                }
                QQC2.Label {
                    objectName: "update.detail"
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Kirigami.Theme.disabledTextColor
                    text: page.state === "error" && page.st.last_error ? Lang.pick(page.st.last_error)
                          : page.state === "restart-required" ? Lang.t("Version ", "Version ") + page.v(page.st.staged) + Lang.t(" ist geladen. Deine Apps und Dateien bleiben, wie sie sind.", " is downloaded. Your apps and files stay as they are.")
                          : (page.st && page.st.booted ? Lang.t("Version ", "Version ") + page.v(page.st.booted) : "")
                            + (page.st && page.st.last_check ? Lang.t(" · zuletzt geprüft ", " · last checked ") + new Date(page.st.last_check).toLocaleString(Qt.locale(), Locale.ShortFormat) : "")
                }
            }
        }
        RowLayout {
            spacing: Kirigami.Units.largeSpacing
            QQC2.Button {
                objectName: "update.restart"
                visible: page.state === "restart-required" || page.state === "rollback-queued"
                text: Lang.t("Jetzt neu starten", "Restart Now")
                highlighted: true
                onClicked: action.run(["restart"])
            }
            QQC2.Button {
                objectName: "update.install"
                visible: page.state === "update-available"
                text: Lang.t("Jetzt installieren", "Install Now")
                highlighted: true
                onClicked: action.run(["apply", "--json"])
            }
            QQC2.Button {
                objectName: "update.check"
                visible: page.state !== "checking" && page.state !== "downloading"
                text: page.state === "error" ? Lang.t("Erneut versuchen", "Try Again") : Lang.t("Jetzt suchen", "Check Now")
                enabled: !action.running
                onClicked: action.run(["check", "--json"])
            }
            QQC2.BusyIndicator { visible: action.running || page.state === "checking" || page.state === "downloading"; running: visible }
        }
        Note {
            text: Lang.t("Updates werden im Hintergrund geladen, wenn du online bist und genug Akku hast. Sie werden erst beim nächsten Neustart aktiv – nie mitten in deiner Arbeit.",
                         "Updates download in the background when you're online and have enough battery. They only take effect at the next restart — never in the middle of your work.")
        }

        Kirigami.Separator { Layout.fillWidth: true; Layout.topMargin: Kirigami.Units.gridUnit }
        Kirigami.Heading { level: 3; text: Lang.t("Zur vorherigen Version zurück", "Return to the Previous Version") }
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: page.st !== null && page.st.can_rollback === true
                  ? Lang.t("Wenn seit dem letzten Update etwas nicht mehr richtig funktioniert, kannst du zur vorherigen Version (" + page.v(page.st.rollback) + ") zurückkehren. Sie startet beim nächsten Neustart. Deine Dateien, Apps und Einstellungen bleiben erhalten. Dafür ist dein Passwort nötig.",
                           "If something stopped working since the last update, you can return to the previous version (" + page.v(page.st.rollback) + "). It starts at the next restart. Your files, apps and settings are kept. Your password is needed for this.")
                  : Lang.t("Es gibt noch keine vorherige Version, zu der du zurückkehren könntest.", "There is no previous version to return to yet.")
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.confirming
            type: Kirigami.MessageType.Warning
            text: Lang.t("Beim nächsten Neustart startet Version " + page.v(page.st ? page.st.rollback : null) + ". Bis dahin kannst du es rückgängig machen. Dein Passwort wird gleich abgefragt.",
                         "Version " + page.v(page.st ? page.st.rollback : null) + " starts at the next restart. You can undo this until then. You'll be asked for your password.")
        }
        RowLayout {
            visible: page.confirming
            QQC2.Button { objectName: "update.rollbackConfirm"; text: Lang.t("Zurückkehren", "Return"); highlighted: true; onClicked: { page.confirming = false; action.run(["rollback", "--json"]); } }
            QQC2.Button { objectName: "update.rollbackAbort"; text: Lang.t("Abbrechen", "Cancel"); onClicked: page.confirming = false }
        }
        RowLayout {
            QQC2.Button {
                objectName: "update.rollback"
                visible: page.st !== null && page.st.can_rollback === true && page.st.rollback_queued !== true && !page.confirming
                text: Lang.t("Zur vorherigen Version zurück …", "Return to Previous Version…")
                onClicked: page.confirming = true
            }
            QQC2.Button {
                objectName: "update.rollbackCancel"
                enabled: !page.confirming
                visible: page.st !== null && page.st.rollback_queued === true
                text: Lang.t("Doch nicht zurückkehren", "Don't Return After All")
                onClicked: action.run(["rollback", "--cancel", "--json"])
            }
        }
    }
}
