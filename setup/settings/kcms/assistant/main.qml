// SPDX-License-Identifier: GPL-3.0-or-later
// Assistant: sign-in status (sign in through the Setup Assistant's sheet, sign out), name, voice,
// language, how to call it, the light around the screen, what it may do without asking (the
// "always allow" grants, reviewable and revocable) and reading app contents (accessibility).
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    readonly property string accountTool: System.env("KRISTALL_ASSISTANT_ACCOUNT", "kristall-assistant-account")
    property string status: ""
    property bool confirmSignOut: false
    readonly property string name: String(Lang.setting("assistant.name", "Kristall"))
    readonly property bool mac: Lang.setting("keyboard.macShortcuts", true) === true
    readonly property var grants: perms.data && perms.data.always ? perms.data.always : ({})
    readonly property var grantKeys: Object.keys(grants)

    JsonProcess {
        id: account
        program: page.accountTool
        onLine: o => { if (o && o.status && typeof o.status === "object") page.status = o.status.status || page.status; else if (o && o.event === "status") page.status = o.status || page.status; }
        onFinished: (c, r) => { if (r && r.status) page.status = r.status.status || page.status; }
        Component.onCompleted: run(["status"])
    }
    // the daemon re-checks too; re-read when the owner comes back from signing in
    Timer { id: recheck; interval: 2500; onTriggered: account.run(["status"]) }
    JsonFile { id: perms; path: System.env("XDG_CONFIG_HOME", System.homeDir() + "/.config") + "/kristall/assistant/permissions.json" }

    readonly property var categories: ({
        "files.modify": ["Deine Dateien ändern", "Change your files"], "files.delete": ["Dateien endgültig löschen", "Delete files permanently"],
        "system.config": ["Systemeinstellungen ändern", "Change system configuration"], "processes.stop": ["Programme beenden", "Quit programs"],
        "system.power": ["Ausschalten, neu starten, abmelden", "Shut down, restart, log out"], "apps.install": ["Apps installieren oder entfernen", "Install or remove apps"],
        "shell.run": ["Befehle ausführen", "Run commands"], "tool.use": ["Werkzeuge benutzen", "Use tools"]
    })
    function grantLabel(k) {
        const base = k.split(":")[0];
        const c = categories[base];
        const label = c ? Lang.t(c[0], c[1]) : (grants[k] && grants[k].label ? Lang.pick(grants[k].label) : k);
        return k.indexOf(":") > 0 && base === "shell.run" ? label + " (" + k.split(":")[1] + ")" : label;
    }
    function revoke(k) {
        const d = JSON.parse(JSON.stringify(perms.data || { version: 1, always: {} }));
        delete d.always[k];
        perms.write(d);
    }

    Kirigami.FormLayout {
        RowLayout {
            Kirigami.FormData.label: Lang.t("Claude-Konto:", "Claude account:")
            QQC2.Label {
                objectName: "assistant.account"
                text: page.status === "ready" ? Lang.t("Angemeldet", "Signed in")
                      : page.status === "" ? "…"
                      : page.status === "cli_missing" ? Lang.t("Noch nicht eingerichtet", "Not set up yet")
                      : Lang.t("Nicht angemeldet", "Not signed in")
            }
            QQC2.Button {
                objectName: "assistant.signin"
                visible: page.status !== "ready" && page.status !== ""
                text: Lang.t("Mit Claude anmelden …", "Sign In with Claude…")
                highlighted: true
                onClicked: { System.launch([System.env("KRISTALL_SHELLCTL", "kristall-shellctl"), "setup", "claude-signin", "settings"]); recheck.start(); }
            }
            QQC2.Button {
                objectName: "assistant.signout"
                visible: page.status === "ready" && !page.confirmSignOut
                text: Lang.t("Abmelden …", "Sign Out…")
                onClicked: page.confirmSignOut = true
            }
        }
        RowLayout {
            visible: page.confirmSignOut
            QQC2.Label { text: Lang.t(page.name + " kann danach nicht antworten, bis du dich wieder anmeldest.", page.name + " can't answer until you sign in again.") }
            QQC2.Button { objectName: "assistant.signoutConfirm"; text: Lang.t("Abmelden", "Sign Out"); onClicked: { page.confirmSignOut = false; account.run(["logout"]); } }
            QQC2.Button { text: Lang.t("Abbrechen", "Cancel"); onClicked: page.confirmSignOut = false }
        }
        Note { text: Lang.t(page.name + " nutzt dein eigenes Claude-Konto. Was du fragst und was " + page.name + " sich ansieht, geht über dein Konto an Anthropic; deine Stimme bleibt auf diesem Computer.",
                            page.name + " uses your own Claude account. What you ask and what " + page.name + " looks at goes to Anthropic through your account; your voice stays on this computer.") }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Name und Stimme", "Name and Voice") }
        QQC2.TextField {
            objectName: "assistant.name"
            Kirigami.FormData.label: Lang.t("Name:", "Name:")
            text: page.name
            onEditingFinished: if (text.trim() !== "" && text.trim() !== page.name) Settings.set("assistant.name", text.trim().slice(0, 40))
        }
        QQC2.ComboBox {
            implicitContentWidthPolicy: QQC2.ComboBox.WidestText
            objectName: "assistant.language"
            Kirigami.FormData.label: Lang.t("Sprache:", "Language:")
            model: ["Deutsch", "English"]
            currentIndex: Lang.setting("assistant.language", "de") === "en" ? 1 : 0
            onActivated: i => Settings.set("assistant.language", i === 1 ? "en" : "de")
        }
        QQC2.ComboBox {
            implicitContentWidthPolicy: QQC2.ComboBox.WidestText
            objectName: "assistant.speak"
            Kirigami.FormData.label: Lang.t("Antworten vorlesen:", "Read answers aloud:")
            readonly property var values: ["always", "voice_only", "never"]
            model: [Lang.t("Immer", "Always"), Lang.t("Wenn ich spreche", "When I speak"), Lang.t("Nie", "Never")]
            currentIndex: Math.max(0, values.indexOf(String(Lang.setting("assistant.speak_replies", "voice_only"))))
            onActivated: i => Settings.set("assistant.speak_replies", values[i])
        }
        RowLayout {
            Kirigami.FormData.label: Lang.t("Sprechtempo:", "Speaking rate:")
            QQC2.Label { text: Lang.t("Langsamer", "Slower") }
            QQC2.Slider {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                from: 0.6; to: 1.6; stepSize: 0.1
                value: Number(Lang.setting("assistant.speaking_rate", 1.0))
                onMoved: Settings.set("assistant.speaking_rate", Math.round(value * 10) / 10)
            }
            QQC2.Label { text: Lang.t("Schneller", "Faster") }
        }
        RowLayout {
            Kirigami.FormData.label: Lang.t("Rufen mit:", "Call with:")
            QQC2.Label { text: page.mac ? Lang.t("⌥ Leertaste (Win + Leertaste)", "⌥ Space (Win + Space)") : Lang.t("Alt + Leertaste", "Alt + Space") }
            QQC2.Button { text: Lang.t("Ändern …", "Change…"); onClicked: System.launch(["systemsettings", "kcm_keys"]) }
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Leuchten", "Light") }
        QQC2.CheckBox {
            Kirigami.FormData.label: Lang.t("Bildschirmrand:", "Screen edge:")
            text: Lang.t("Leuchtet, während " + page.name + " zuhört oder arbeitet", "Glows while " + page.name + " listens or works")
            checked: Lang.setting("assistant.ui.light.enabled", true) === true
            onToggled: Settings.set("assistant.ui.light.enabled", checked)
        }
        RowLayout {
            enabled: Lang.setting("assistant.ui.light.enabled", true) === true
            QQC2.Label { text: Lang.t("Dezent", "Subtle") }
            QQC2.Slider {
                objectName: "assistant.lightIntensity"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                from: 0.2; to: 1.0; stepSize: 0.05
                value: Number(Lang.setting("assistant.ui.light.intensity", 0.8))
                onMoved: Settings.set("assistant.ui.light.intensity", Math.round(value * 100) / 100)
            }
            QQC2.Label { text: Lang.t("Kräftig", "Bright") }
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Was " + page.name + " darf", "What " + page.name + " May Do") }
        Note {
            Kirigami.FormData.label: ""
            text: Lang.t("Ohne zu fragen: Dinge ansehen und lesen, Apps und Dateien öffnen, Lautstärke und Helligkeit ändern, neue Dateien anlegen, in den Papierkorb legen. Vor allem anderen fragt " + page.name + " – Senden, Kaufen, Passwörter und Administratorrechte immer.",
                         "Without asking: look and read, open apps and files, change volume and brightness, create new files, move to the trash. For everything else " + page.name + " asks — sending, buying, passwords and administrator rights always.")
        }
        QQC2.Label {
            Kirigami.FormData.label: Lang.t("Immer erlaubt:", "Always allowed:")
            visible: page.grantKeys.length === 0
            text: Lang.t("Nichts – " + page.name + " fragt jedes Mal.", "Nothing — " + page.name + " asks every time.")
        }
        Repeater {
            model: page.grantKeys
            RowLayout {
                required property string modelData
                required property int index
                Kirigami.FormData.label: index === 0 ? Lang.t("Immer erlaubt:", "Always allowed:") : ""
                QQC2.Label { text: page.grantLabel(modelData); Layout.minimumWidth: Kirigami.Units.gridUnit * 12 }
                QQC2.Button {
                    objectName: "assistant.revoke." + modelData
                    text: Lang.t("Wieder fragen", "Ask Again")
                    onClicked: page.revoke(modelData)
                }
            }
        }
        QQC2.ComboBox {
            implicitContentWidthPolicy: QQC2.ComboBox.WidestText
            objectName: "assistant.accessibility"
            Kirigami.FormData.label: Lang.t("Inhalte von Apps lesen:", "Read app contents:")
            readonly property var values: ["on_demand", "always", "off"]
            model: [Lang.t("Nur wenn nötig (empfohlen)", "Only when needed (recommended)"), Lang.t("Immer bereit", "Always ready"), Lang.t("Nie", "Never")]
            currentIndex: Math.max(0, values.indexOf(String(Lang.setting("assistant.hands.accessibility", "on_demand"))))
            onActivated: i => Settings.set("assistant.hands.accessibility", values[i])
        }
        Note {
            text: Lang.t("So kann " + page.name + " Knöpfe und Texte in Apps direkt erkennen, statt nur auf den Bildschirm zu schauen. „Nie“ macht manche Aufgaben langsamer oder unmöglich.",
                         "This lets " + page.name + " recognise buttons and text in apps directly instead of only looking at the screen. “Never” makes some tasks slower or impossible.")
        }
    }
}
