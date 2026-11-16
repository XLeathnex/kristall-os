// SPDX-License-Identifier: GPL-3.0-or-later
// The design-system gallery: every component in every state, on live glass over the wallpaper.
// Open with `kristall-shellctl gallery toggle` (or KRISTALL_SHELL_GALLERY=1). Close with Esc.
// Later agents: this is the reference for how components look and are used.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services
import qs.bar

PanelWindow {
    id: win
    readonly property string screenName: screen ? screen.name : ""
    WlrLayershell.namespace: "kristall-gallery"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
    exclusionMode: ExclusionMode.Normal
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"

    GlassSurface {
        id: gs
        key: "gallery-" + win.screenName
        layerNamespace: "kristall-gallery"
        output: win.screenName
    }

    Item {
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: ShellBus.request("gallery", "hide")
    }

    // ---- reusable section card --------------------------------------------------------------------
    component Card: GlassShape {
        id: card
        property string title: ""
        default property alias body: inner.data
        role: "panel"
        surface: gs
        width: 420
        height: inner.childrenRect.height + 56
        KText {
            x: 20; y: 14
            text: card.title
            textStyle: "headline"
            scheme: card.scheme
        }
        Item {
            id: inner
            x: 20; y: 42
            width: card.width - 40
        }
    }
    component Caption: KText {
        textStyle: "caption1"
        level: "secondaryLabel"
    }

    Flow {
        x: 28; y: 20
        width: win.width - 56
        spacing: 20

        // ---- title --------------------------------------------------------------------------------
        Item {
            width: parent.width
            height: 54
            KText { text: Strings.t("gallery.title"); textStyle: "largeTitle"; emphasized: true; color: "#FFFFFF"; style: Text.Raised; styleColor: "#40000000" }
            KText { y: 32; text: Strings.t("gallery.subtitle") + " · " + Theme.scheme + " · glass " + Theme.glassLevel.toFixed(2) + " · effect " + GlassClient.state; textStyle: "callout"; color: "#FFFFFF"; style: Text.Raised; styleColor: "#40000000" }
        }

        // ---- buttons -------------------------------------------------------------------------------
        Card {
            id: buttons
            shapeId: "buttons"
            title: Strings.t("gallery.buttons")
            Column {
                spacing: 10
                Repeater {
                    model: ["fill", "accent", "plain", "destructive"]
                    Row {
                        required property string modelData
                        spacing: 8
                        KButton { text: modelData; variant: modelData; scheme: buttons.scheme }
                        KButton { text: "hover"; variant: modelData; showState: "hover"; scheme: buttons.scheme }
                        KButton { text: "pressed"; variant: modelData; showState: "pressed"; scheme: buttons.scheme }
                        KButton { text: "off"; variant: modelData; enabled: false; scheme: buttons.scheme }
                    }
                }
                Row {
                    spacing: 8
                    KButton { text: "Small"; size: "small"; scheme: buttons.scheme }
                    KButton { text: "Regular"; showState: "focus"; scheme: buttons.scheme }
                    KButton { text: "Large"; size: "large"; variant: "accent"; scheme: buttons.scheme }
                    KButton { icon: "bold/plus"; scheme: buttons.scheme }
                    KButton { icon: "fill/wifi-high"; checkable: true; checked: true; scheme: buttons.scheme }
                }
                Caption { text: "fill · accent · plain · destructive; hover, pressed, disabled, focus ring; icon toggle (on)"; scheme: buttons.scheme }
            }
        }

        // ---- toggles, sliders, segments -------------------------------------------------------------
        Card {
            id: controls
            shapeId: "controls"
            title: Strings.t("gallery.controls")
            Column {
                spacing: 12
                Row {
                    spacing: 14
                    KToggle { checked: false; scheme: controls.scheme }
                    KToggle { checked: true; scheme: controls.scheme }
                    KToggle { checked: true; showState: "pressed"; scheme: controls.scheme }
                    KToggle { checked: false; showState: "focus"; scheme: controls.scheme }
                    KToggle { checked: true; enabled: false; scheme: controls.scheme }
                }
                KSlider { width: 360; value: 0.35; scheme: controls.scheme }
                KSlider { width: 360; value: 0.7; showState: "focus"; scheme: controls.scheme }
                KSlider { width: 360; value: 0.5; enabled: false; scheme: controls.scheme }
                KCapsuleSlider { width: 360; value: 0.62; icon: "fill/speaker-simple-high"; scheme: controls.scheme }
                KCapsuleSlider { width: 360; value: 0.2; icon: "fill/sun"; scheme: controls.scheme }
                KSegmented { width: 360; model: ["Hell", "Dunkel", "Automatisch"]; currentIndex: 1; scheme: controls.scheme }
                KSegmented { width: 360; model: ["Leise", "Ausgewogen", "Leistung"]; currentIndex: 0; enabled: false; scheme: controls.scheme }
            }
        }

        // ---- fields and lists -------------------------------------------------------------------------
        Card {
            id: fields
            shapeId: "fields"
            title: Strings.t("gallery.fields") + " · " + Strings.t("gallery.list")
            Column {
                spacing: 10
                KTextField { width: 360; placeholder: "Name"; scheme: fields.scheme }
                KTextField { width: 360; text: "Kristall"; showState: "focus"; scheme: fields.scheme }
                KTextField { width: 360; search: true; placeholder: "Suchen oder fragen"; scheme: fields.scheme }
                KTextField { width: 360; search: true; text: "Blender"; scheme: fields.scheme }
                KTextField { width: 360; text: "disabled"; enabled: false; scheme: fields.scheme }
                KSeparator { width: 360; scheme: fields.scheme }
                Column {
                    width: 360
                    KListRow { width: parent.width; title: "WLAN"; icon: "fill/wifi-high"; detail: "Zuhause"; chevron: true; scheme: fields.scheme }
                    KListRow { width: parent.width; title: "Bluetooth"; icon: "bold/bluetooth"; showState: "hover"; scheme: fields.scheme
                        KToggle { checked: true; scheme: fields.scheme } }
                    KListRow { width: parent.width; title: "Ausgewählt"; icon: "fill/star"; selected: true; scheme: fields.scheme }
                    KListRow { width: parent.width; title: "Blender"; subtitle: "Grafik · 4,2 GB"; icon: "fill/cube"; scheme: fields.scheme }
                    KListRow { width: parent.width; title: "Nicht verfügbar"; icon: "fill/prohibit"; enabled: false; scheme: fields.scheme }
                }
            }
        }

        // ---- menus (rendered in place, the same panels the menu host uses) ---------------------------
        Item {
            width: 420
            height: menuA.height + 30
            KMenuPanel {
                id: menuA
                level: 0
                surface: gs
                currentIndex: 3
                src: Menus.list([
                    { type: "header", label: "Darstellung" },
                    { label: "Als Symbole", toggle: "checkmark", checked: true, shortcut: Theme.shortcutText([["Super", "1"]]) },
                    { label: "Als Liste", toggle: "checkmark", shortcut: Theme.shortcutText([["Super", "2"]]) },
                    { label: "Sortieren nach", children: [{ label: "Name" }] },
                    { type: "separator" },
                    { label: "Neuer Ordner", shortcut: Theme.shortcutText([["Super", "Shift", "N"]]) },
                    { label: "Umbenennen", enabled: false },
                    { label: "In den Papierkorb legen", shortcut: Theme.shortcutText([["Super", "BackSpace"]]) }
                ])
            }
            KMenuPanel {
                id: menuB
                level: 1
                surface: gs
                x: menuA.width + Theme.size.submenuGap
                y: menuA.rowRect(3).y - Theme.size.menuPaddingV
                currentIndex: 1
                src: Menus.list([
                    { label: "Name", toggle: "radio", checked: true },
                    { label: "Art" },
                    { label: "Änderungsdatum" },
                    { label: "Größe" }
                ])
            }
        }

        // ---- type scale -----------------------------------------------------------------------------
        Card {
            id: typeCard
            shapeId: "type"
            title: Strings.t("gallery.type")
            Column {
                spacing: 2
                Repeater {
                    model: ["largeTitle", "title1", "title2", "title3", "headline", "body", "callout", "subheadline", "footnote", "caption1", "caption2"]
                    Row {
                        required property string modelData
                        spacing: 10
                        KText { width: 92; text: modelData; textStyle: "caption1"; level: "secondaryLabel"; scheme: typeCard.scheme; anchors.verticalCenter: parent.verticalCenter }
                        KText {
                            text: Theme.type[modelData].size + "/" + Theme.type[modelData].line + " Größe Kristall 0123"
                            textStyle: modelData
                            scheme: typeCard.scheme
                        }
                    }
                }
            }
        }

        // ---- materials ---------------------------------------------------------------------------------
        Item {
            width: 420
            height: 330
            KText { text: Strings.t("gallery.materials"); textStyle: "headline"; color: "#FFFFFF"; style: Text.Raised; styleColor: "#40000000" }
            GlassShape { id: mBar; shapeId: "m-bar"; surface: gs; role: "bar"; y: 28; width: 420; height: Theme.size.bar
                KText { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "bar"; scheme: mBar.scheme } }
            GlassShape { id: mMenu; shapeId: "m-menu"; surface: gs; role: "menu"; y: 66; width: 130; height: 110
                KText { x: 12; y: 10; text: "menu"; scheme: mMenu.scheme } }
            GlassShape { id: mPanel; shapeId: "m-panel"; surface: gs; role: "panel"; x: 145; y: 66; width: 130; height: 110
                KText { x: 14; y: 12; text: "panel"; scheme: mPanel.scheme } }
            GlassShape { id: mHud; shapeId: "m-hud"; surface: gs; role: "hud"; x: 290; y: 66; width: 130; height: 110
                KText { x: 14; y: 12; text: "hud"; scheme: mHud.scheme } }
            GlassShape { id: mControl; shapeId: "m-control"; surface: gs; role: "control"; y: 192; width: 130; height: 36
                KText { anchors.centerIn: parent; text: "control"; scheme: mControl.scheme } }
            GlassShape { id: mTip; shapeId: "m-tooltip"; surface: gs; role: "tooltip"; x: 145; y: 196; width: 90; height: 26
                KText { anchors.centerIn: parent; text: "tooltip"; textStyle: "callout"; scheme: mTip.scheme } }
            GlassShape { id: mMedia; shapeId: "m-media"; surface: gs; role: "media"; x: 290; y: 192; width: 130; height: 36
                KText { anchors.centerIn: parent; text: "media (clear)"; scheme: mMedia.scheme } }
            Row {
                y: 246
                spacing: 8
                KButton { text: "Glass"; variant: "glass"; glassSurface: gs; shapeId: "g1" }
                KButton { icon: "kristall/assistant"; variant: "glass"; glassSurface: gs; shapeId: "g2" }
                KButton { text: "Accent"; variant: "accent" }
            }
            KText { y: 290; width: 420; wrapMode: Text.WordWrap; text: "Without the effect every shape draws the fallback fill (Reduce Transparency: opaque)."; textStyle: "caption1"; color: "#FFFFFF"; style: Text.Raised; styleColor: "#60000000" }
        }

        // ---- colours and symbols ------------------------------------------------------------------------
        Card {
            id: colors
            shapeId: "colors"
            title: Strings.t("gallery.colors") + " · " + Strings.t("gallery.symbols")
            Column {
                spacing: 10
                Row {
                    spacing: 8
                    Repeater {
                        model: Object.keys(Theme.accents)
                        Column {
                            required property string modelData
                            spacing: 2
                            Rectangle { width: 40; height: 24; radius: 12; color: Theme.accents[modelData][colors.scheme] }
                            KText { text: modelData; textStyle: "caption2"; level: "secondaryLabel"; scheme: colors.scheme }
                        }
                    }
                }
                Row {
                    spacing: 12
                    Repeater {
                        model: ["label", "secondaryLabel", "tertiaryLabel", "quaternaryLabel"]
                        KText { required property string modelData; text: modelData; level: modelData; textStyle: "callout"; scheme: colors.scheme }
                    }
                }
                Row {
                    spacing: 14
                    KIcon { name: "kristall/mark"; size: 16; scheme: colors.scheme }
                    KIcon { name: "bold/wifi-high"; scheme: colors.scheme }
                    KIcon { name: "bold/wifi-medium"; scheme: colors.scheme }
                    KIcon { name: "wifi-slash"; scheme: colors.scheme }
                    KIcon { name: "fill/speaker-simple-high"; scheme: colors.scheme }
                    KIcon { name: "fill/speaker-simple-slash"; scheme: colors.scheme }
                    KIcon { name: "kristall/control-center"; scheme: colors.scheme }
                    KIcon { name: "kristall/assistant"; scheme: colors.scheme }
                    KIcon { name: "bold/bluetooth"; scheme: colors.scheme }
                    KIcon { name: "magnifying-glass"; scheme: colors.scheme }
                }
                Row {
                    spacing: 14
                    Repeater {
                        model: [1.0, 0.55, 0.08]
                        BatteryGlyph { required property real modelData; level: modelData; scheme: colors.scheme }
                    }
                    BatteryGlyph { level: 0.4; charging: true; scheme: colors.scheme }
                }
                KScrollArea {
                    width: 360; height: 60
                    scheme: colors.scheme
                    contentHeight: 200
                    Column {
                        Repeater { model: 8; KText { required property int index; text: "Scroll area row " + (index + 1); scheme: colors.scheme } }
                    }
                }
            }
        }
    }
}
