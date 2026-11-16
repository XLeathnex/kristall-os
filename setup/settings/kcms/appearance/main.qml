// SPDX-License-Identifier: GPL-3.0-or-later
// Appearance: light / dark / automatic, accent colour, the Liquid Glass slider, wallpaper and
// display size — the same settings the Setup Assistant asked about, changed live.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kristall.settings

KCM.SimpleKCM {
    id: page
    Component.onCompleted: System.registerTestRoot(page)
    readonly property string helper: System.env("KRISTALL_SETUP_HELPER", "kristall-setup-helper")
    readonly property string theme: Lang.setting("appearance.theme", "auto")
    readonly property string accent: Lang.setting("appearance.accent", "blue")
    readonly property real glass: Number(Lang.setting("appearance.glass", 0.3))
    readonly property var accents: [["blue", "#007AFF", "Blau", "Blue"], ["purple", "#AF52DE", "Lila", "Purple"], ["pink", "#FF2D55", "Rosa", "Pink"],
                                   ["red", "#FF3B30", "Rot", "Red"], ["orange", "#FF9500", "Orange", "Orange"], ["yellow", "#FFCC00", "Gelb", "Yellow"],
                                   ["green", "#28CD41", "Grün", "Green"], ["graphite", "#8E8E93", "Graphit", "Graphite"]]
    property var output: displays.result && displays.result.outputs && displays.result.outputs.length > 0 ? displays.result.outputs[0] : null
    property var walls: wallpapers.result && wallpapers.result.wallpapers ? wallpapers.result.wallpapers : []

    JsonProcess { id: displays; program: page.helper; arguments: ["displays"]; Component.onCompleted: start() }
    JsonProcess { id: setScale; program: page.helper; onFinished: displays.start() }
    JsonProcess { id: wallpapers; program: page.helper; arguments: ["wallpapers"]; Component.onCompleted: start() }
    FileDialog {
        id: pickWallpaper
        title: Lang.t("Eigenes Bild wählen", "Choose a Picture")
        nameFilters: [Lang.t("Bilder (*.jpg *.jpeg *.png *.webp)", "Pictures (*.jpg *.jpeg *.png *.webp)")]
        onAccepted: System.launch(["plasma-apply-wallpaperimage", selectedFile.toString().replace("file://", "")])
    }

    Kirigami.FormLayout {
        RowLayout {
            Kirigami.FormData.label: Lang.t("Darstellung:", "Appearance:")
            spacing: Kirigami.Units.largeSpacing
            Repeater {
                model: [["light", "Hell", "Light"], ["dark", "Dunkel", "Dark"], ["auto", "Automatisch", "Auto"]]
                QQC2.RadioButton {
                    required property var modelData
                    objectName: "appearance.theme." + modelData[0]
                    text: Lang.t(modelData[1], modelData[2])
                    checked: page.theme === modelData[0]
                    onToggled: if (checked) Settings.set("appearance.theme", modelData[0])
                }
            }
        }
        Note { text: Lang.t("„Automatisch“ ist tagsüber hell und nachts dunkel.", "“Auto” is light during the day and dark at night.") }

        RowLayout {
            Kirigami.FormData.label: Lang.t("Akzentfarbe:", "Accent colour:")
            spacing: Kirigami.Units.smallSpacing * 2
            Repeater {
                model: page.accents
                QQC2.AbstractButton {
                    required property var modelData
                    objectName: "appearance.accent." + modelData[0]
                    implicitWidth: Kirigami.Units.gridUnit * 1.3
                    implicitHeight: implicitWidth
                    QQC2.ToolTip.text: Lang.t(modelData[2], modelData[3])
                    QQC2.ToolTip.visible: hovered
                    Accessible.name: Lang.t(modelData[2], modelData[3])
                    onClicked: Settings.set("appearance.accent", modelData[0])
                    contentItem: Item {}
                    background: Rectangle {
                        radius: width / 2
                        color: modelData[1]
                        border.width: 1
                        border.color: Qt.rgba(0, 0, 0, 0.15)
                        Rectangle {
                            anchors.centerIn: parent
                            visible: page.accent === modelData[0]
                            width: parent.width * 0.36
                            height: width
                            radius: width / 2
                            color: "white"
                        }
                    }
                }
            }
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Glas", "Glass") }
        RowLayout {
            Kirigami.FormData.label: Lang.t("Glas:", "Glass:")
            QQC2.Label { text: Lang.t("Klar", "Clear") }
            QQC2.Slider {
                objectName: "appearance.glass"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 14
                from: 0; to: 1; stepSize: 0.05
                value: page.glass
                onMoved: Settings.set("appearance.glass", Math.round(value * 100) / 100)
            }
            QQC2.Label { text: Lang.t("Getönt", "Tinted") }
        }
        Note { text: Lang.t("Wie viel vom Schreibtisch durch Menüs, Dock und Panels scheint. Mehr Tönung macht Text leichter lesbar.",
                            "How much of the desktop shines through menus, the Dock and panels. More tint makes text easier to read.") }
        QQC2.CheckBox {
            objectName: "appearance.reduceTransparency"
            text: Lang.t("Transparenz reduzieren", "Reduce transparency")
            checked: Lang.setting("appearance.reduceTransparency", false) === true
            onToggled: Settings.set("appearance.reduceTransparency", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Kontrast erhöhen", "Increase contrast")
            checked: Lang.setting("accessibility.increaseContrast", false) === true
            onToggled: Settings.set("accessibility.increaseContrast", checked)
        }
        QQC2.CheckBox {
            text: Lang.t("Bewegungen reduzieren", "Reduce motion")
            checked: Lang.setting("accessibility.reduceMotion", false) === true
            onToggled: Settings.set("accessibility.reduceMotion", checked)
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Hintergrundbild", "Wallpaper") }
        Flow {
            Kirigami.FormData.label: Lang.t("Hintergrundbild:", "Wallpaper:")
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
            spacing: Kirigami.Units.smallSpacing * 2
            Repeater {
                model: page.walls.slice(0, 8)
                QQC2.AbstractButton {
                    required property var modelData
                    implicitWidth: Kirigami.Units.gridUnit * 6
                    implicitHeight: Kirigami.Units.gridUnit * 3.75
                    Accessible.name: modelData.name
                    QQC2.ToolTip.text: modelData.name
                    QQC2.ToolTip.visible: hovered
                    onClicked: System.launch(["plasma-apply-wallpaperimage", modelData.path])
                    contentItem: Image { source: "file://" + modelData.preview; fillMode: Image.PreserveAspectCrop; sourceSize.width: 240; asynchronous: true }
                    background: Rectangle { color: Kirigami.Theme.alternateBackgroundColor; radius: 6 }
                }
            }
        }
        QQC2.Button {
            text: Lang.t("Eigenes Bild …", "Your Own Picture…")
            onClicked: pickWallpaper.open()
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: Lang.t("Anzeigegröße", "Display Size") }
        RowLayout {
            Kirigami.FormData.label: Lang.t("Anzeigegröße:", "Display size:")
            visible: page.output !== null && page.output.choices.length > 1
            QQC2.Label { text: Lang.t("Größerer Text", "Larger Text") }
            QQC2.Slider {
                id: sizeSlider
                objectName: "appearance.displaySize"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 12
                from: 0
                to: page.output ? page.output.choices.length - 1 : 0
                stepSize: 1
                snapMode: QQC2.Slider.SnapAlways
                value: {
                    if (!page.output)
                        return 0;
                    let best = 0, d = 99;
                    page.output.choices.forEach((c, i) => { const x = Math.abs(c.scale - page.output.scale); if (x < d) { d = x; best = i; } });
                    return best;
                }
                onPressedChanged: if (!pressed) apply()
                Keys.onReleased: apply()
                function apply() {
                    const c = page.output.choices[Math.round(value)];
                    if (c && Math.abs(c.scale - page.output.scale) > 0.001)
                        setScale.run(["display-scale", page.output.name, String(c.scale)]);
                }
            }
            QQC2.Label { text: Lang.t("Mehr Platz", "More Space") }
        }
        Note {
            visible: page.output !== null
            text: Lang.t("Andere Bildschirme stellst du unter „Anzeige & Bildschirm“ ein.", "Other screens are set up under “Display & Monitor”.")
        }
    }
}
