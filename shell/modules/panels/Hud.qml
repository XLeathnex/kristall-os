// SPDX-License-Identifier: GPL-3.0-or-later
// Heads-up display for the volume, brightness and keyboard-backlight keys (macOS 26/27: a small
// glass module at the top right under the menu bar, title and a capsule level with the symbol in
// it). Other on-screen displays Plasma announces (keyboard layout, power mode …) show as a line of
// text in the same place. Shown for 1.5 s after the last change, then it fades.
// Surface: namespace "kristall-hud", Overlay, no input, no keyboard; exists only while shown.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services

PanelWindow {
    id: hudWindow
    property var hud: null
    signal finished()
    readonly property string screenName: screen ? screen.name : ""
    readonly property int pad: PanelMetrics.shadowPad
    readonly property string kind: hud ? hud.kind : "volume"

    Component.onDestruction: PanelsRegistry.remove("hud:" + hudWindow.screenName, hudWindow)
    onScreenNameChanged: PanelsRegistry.add("hud:" + screenName, hudWindow)
    Item { Component.onCompleted: PanelsRegistry.add("hud:" + hudWindow.screenName, hudWindow) }

    WlrLayershell.namespace: "kristall-hud"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; right: true }
    implicitWidth: PanelMetrics.hudWidth + PanelMetrics.ccEdge + pad
    implicitHeight: Theme.size.bar + PanelMetrics.ccTop + PanelMetrics.hudHeight + pad
    color: "transparent"
    mask: Region {}

    // live values, so holding a key moves the level smoothly
    readonly property real level: {
        switch (kind) {
        case "volume": return Audio.available ? (Audio.muted ? 0 : Audio.volume) : (hud ? hud.value : 0);
        case "brightness": return Hw.hasBacklight ? Hw.brightness : (hud ? hud.value : 0);
        case "kbd": return Hw.hasKbdLight ? Hw.kbdLevel : (hud ? hud.value : 0);
        default: return hud ? Math.max(0, hud.value) : 0;
        }
    }
    readonly property string title: {
        switch (kind) {
        case "volume": return Audio.muted ? Strings.t("panels.hud.muted") : (Audio.deviceName || Strings.t("panels.hud.volume"));
        case "brightness": return Strings.t("panels.display");
        case "kbd": return Strings.t("panels.kbd");
        case "mic": return Strings.t("panels.hud.microphone");
        default: return hud ? hud.text : "";
        }
    }
    readonly property string symbol: {
        switch (kind) {
        case "volume": return Audio.muted || level <= 0 ? "fill/speaker-simple-slash" : level < 0.34 ? "fill/speaker-simple-none" : level < 0.67 ? "fill/speaker-simple-low" : "fill/speaker-simple-high";
        case "brightness": return "fill/sun";
        case "kbd": return "fill/keyboard";
        case "mic": return level <= 0 ? "fill/microphone-slash" : "fill/microphone";
        }
        return "fill/info";
    }

    property real fade: 0
    Behavior on fade { NumberAnimation { duration: Theme.duration(hudWindow.fade > 0.5 ? "medium" : "short", true); easing.type: Easing.InOutQuad } }
    onFadeChanged: if (fade <= 0.001 && !life.running) finished()
    Component.onCompleted: { fade = 1; life.restart(); }
    onHudChanged: if (hud) { fade = 1; life.restart(); }
    Timer {
        id: life
        interval: PanelMetrics.hudTimeout
        onTriggered: hudWindow.fade = 0
    }

    GlassSurface {
        id: glassSurface
        key: "hud-" + hudWindow.screenName
        layerNamespace: "kristall-hud"
        output: hudWindow.screenName
    }
    GlassShape {
        id: shape
        objectName: "hud"
        shapeId: "hud"
        surface: glassSurface
        role: "hud"
        x: hudWindow.pad
        y: Theme.size.bar + PanelMetrics.ccTop
        width: PanelMetrics.hudWidth
        height: hudWindow.kind === "text" ? 52 : PanelMetrics.hudHeight
        glassOpacity: hudWindow.fade
        opacity: 1

        Item {
            anchors.fill: parent
            opacity: hudWindow.fade
            KText {
                id: titleText
                visible: hudWindow.kind !== "text"
                x: 16; y: 10
                width: parent.width - 32
                text: hudWindow.title
                textStyle: "subheadline"
                emphasized: true
                elide: Text.ElideRight
                scheme: shape.scheme
            }
            // the level: Control Center's capsule, not interactive
            Rectangle {
                visible: hudWindow.kind !== "text"
                x: 16
                y: 32
                width: parent.width - 32
                height: Theme.size.capsuleSlider
                radius: height / 2
                color: Theme.color(shape.scheme, "fillStrong")
                clip: true
                Rectangle {
                    height: parent.height
                    radius: height / 2
                    width: parent.height + (parent.width - parent.height) * Math.max(0, Math.min(1, hudWindow.level))
                    color: "#FFFFFF"
                    opacity: shape.scheme === "dark" ? 0.92 : 1
                    Behavior on width { NumberAnimation { duration: Theme.duration("short"); easing.type: Easing.OutQuad } }
                }
                KIcon {
                    x: (parent.height - size) / 2
                    anchors.verticalCenter: parent.verticalCenter
                    size: 14
                    name: hudWindow.symbol
                    color: "#3A3A3C"
                }
            }
            Row {
                visible: hudWindow.kind === "text"
                anchors.centerIn: parent
                spacing: 10
                KIcon { anchors.verticalCenter: parent.verticalCenter; size: 18; name: hudWindow.symbol; color: shape.textColor }
                KText { anchors.verticalCenter: parent.verticalCenter; text: hudWindow.title; textStyle: "hudValue"; scheme: shape.scheme }
            }
        }
    }
}
