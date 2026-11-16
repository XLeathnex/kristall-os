// SPDX-License-Identifier: GPL-3.0-or-later
// Mac Keyboard: the key beside the space bar acts as Command (`keyboard.macShortcuts`, with
// `keyboard.commandKey` published for the menus), what it does, whether it is working right now
// (the plugin's status file), and the apps that get ordinary PC keys.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    readonly property bool mac: Lang.setting("keyboard.macShortcuts", true) === true
    readonly property var pass: Lang.setting("keyboard.passthroughApps", []) || []
    JsonFile { id: status; path: System.runtimeDir() + "/kristall/keyboard.json" }
    readonly property var st: status.data

    Kirigami.FormLayout {
        QQC2.Switch {
            objectName: "keyboard.mac"
            Kirigami.FormData.label: Lang.t("Mac-Kurzbefehle:", "Mac shortcuts:")
            text: Lang.t("Die Alt-Taste neben der Leertaste wirkt als Befehlstaste (⌘)", "The Alt key beside the space bar acts as Command (⌘)")
            checked: page.mac
            onToggled: { Settings.set("keyboard.macShortcuts", checked); Settings.set("keyboard.commandKey", checked ? "ctrl" : ""); }
        }
        Kirigami.InlineMessage {
            objectName: "keyboard.status"
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 28
            visible: page.mac && page.st !== null && page.st !== undefined && !page.st.active
            type: Kirigami.MessageType.Warning
            text: Lang.t("Die Mac-Kurzbefehle sind gerade nicht aktiv, deine Tasten funktionieren deshalb wie auf jedem PC. Ein Neustart hilft meistens.",
                         "Mac shortcuts aren't active right now, so your keys work like on any PC. Restarting usually helps.")
        }
        GridLayout {
            Kirigami.FormData.label: Lang.t("So funktioniert es:", "How it works:")
            visible: page.mac
            columns: 2
            columnSpacing: Kirigami.Units.largeSpacing * 2
            Repeater {
                model: [
                    ["Alt + C / V / X / Z", "Kopieren, Einsetzen, Ausschneiden, Widerrufen", "Copy, paste, cut, undo"],
                    ["Alt + Leertaste", "Suche", "Search"],
                    ["Alt + Tab", "Zwischen Apps wechseln", "Switch between apps"],
                    ["Alt + Q / W", "App beenden / Fenster schließen", "Quit app / close window"],
                    ["Alt + ⇧ + 3 / 4 / 5", "Bildschirmfoto: alles / Bereich / Werkzeug", "Screenshot: screen / area / tool"],
                    ["Alt + ← / →", "Zeilenanfang / -ende", "Start / end of line"],
                    ["Win + ← / →", "Wortweise bewegen", "Move by word"],
                    ["Win + Leertaste", "Assistent", "Assistant"],
                    ["Strg + C (Terminal)", "Programm abbrechen", "Interrupt the program"]
                ]
                Repeater {
                    required property var modelData
                    model: 2
                    QQC2.Label {
                        required property int index
                        text: index === 0 ? modelData[0] : Lang.t(modelData[1], modelData[2])
                        font.weight: index === 0 ? Font.DemiBold : Font.Normal
                    }
                }
            }
        }
        Note { text: Lang.t("Alle Zeichen auf deinen Tasten (auch @ € { } [ ] mit AltGr) tippen weiter genau wie aufgedruckt.",
                            "Every character on your keys (including @ € { } [ ] with AltGr) still types exactly as printed.") }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Apps mit PC-Tasten", "Apps with PC Keys") }
        Note {
            Kirigami.FormData.label: ""
            text: Lang.t("Spiele, Windows-Programme (z. B. Roblox Studio), virtuelle Computer und Fernzugriffe bekommen immer ganz normale PC-Tasten. Weitere Apps kannst du hier hinzufügen.",
                         "Games, Windows programs (e.g. Roblox Studio), virtual machines and remote desktops always get ordinary PC keys. You can add more apps here.")
        }
        Repeater {
            model: page.pass
            RowLayout {
                required property string modelData
                QQC2.Label { text: modelData; Layout.minimumWidth: Kirigami.Units.gridUnit * 12 }
                QQC2.Button { text: Lang.t("Entfernen", "Remove"); onClicked: Settings.set("keyboard.passthroughApps", page.pass.filter(a => a !== modelData)) }
            }
        }
        RowLayout {
            QQC2.TextField {
                id: addField
                objectName: "keyboard.addApp"
                placeholderText: Lang.t("App-Kennung, z. B. org.example.Spiel", "App id, e.g. org.example.Game")
                Layout.preferredWidth: Kirigami.Units.gridUnit * 14
                onAccepted: addButton.clicked()
            }
            QQC2.Button {
                id: addButton
                text: Lang.t("Hinzufügen", "Add")
                enabled: addField.text.trim() !== ""
                onClicked: { Settings.set("keyboard.passthroughApps", page.pass.concat([addField.text.trim().toLowerCase()])); addField.text = ""; }
            }
        }
        Kirigami.Separator { Kirigami.FormData.isSection: true }
        RowLayout {
            Kirigami.FormData.label: Lang.t("Mehr:", "More:")
            QQC2.Button { text: Lang.t("Tastaturbelegung …", "Keyboard Layout…"); onClicked: System.launch(["systemsettings", "kcm_keyboard"]) }
            QQC2.Button { text: Lang.t("Tastenkürzel …", "Shortcuts…"); onClicked: System.launch(["systemsettings", "kcm_keys"]) }
        }
    }
}
