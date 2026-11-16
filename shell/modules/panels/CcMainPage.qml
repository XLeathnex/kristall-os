// SPDX-License-Identifier: GPL-3.0-or-later
// Control Center's module grid (4 columns of 68 px, macOS 26/27 arrangement):
//   [ Connectivity 2×2 ][ Now Playing 2×2 ]      without a player: [ Focus 2×1 ][ small ][ small ]
//   [ Focus 2×1 ][ small ][ small ]
//   [ Display 4×1 ]  [ Sound 4×1 ]  [ Keyboard 4×1 ]  [ Battery / Energy 4×1 ]
// Hardware that is not there takes its module away; nothing is ever shown broken.
import QtQuick
import Quickshell
import qs.core
import qs.services

Column {
    id: mp
    property string scheme: Theme.scheme
    signal openPage(string page)
    signal closeRequested()
    spacing: PanelMetrics.ccGap

    readonly property bool hasMedia: Media.available
    readonly property bool hasScreenshot: { DesktopEntries.applications; return Apps.desktopEntry("org.kde.spectacle") !== null; }

    // ---- microphone in use (privacy indicator, as on the Mac) --------------------------------------
    Item {
        visible: Hw.micInUse
        width: parent.width
        height: 20
        Rectangle {
            id: dot
            width: 8; height: 8; radius: 4
            x: 6
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.color(mp.scheme, "warning")
        }
        KText {
            x: dot.x + 14
            width: parent.width - x
            anchors.verticalCenter: parent.verticalCenter
            text: Hw.micUser !== "" ? Strings.t("panels.mic.inUse", { app: Hw.micUser }) : Strings.t("panels.mic.inUseAnon")
            textStyle: "subheadline"
            level: "secondaryLabel"
            elide: Text.ElideRight
            scheme: mp.scheme
        }
    }

    // ---- row 1 ---------------------------------------------------------------------------------
    Row {
        spacing: PanelMetrics.ccGap
        CcTile {
            id: conn
            width: PanelMetrics.ccHalf
            height: PanelMetrics.ccHalf
            scheme: mp.scheme
            readonly property bool wifiRow: Network.available && Network.hasWifi
            readonly property bool btRow: BluetoothStatus.available
            readonly property bool wiredRow: Network.available && (Network.wiredConnected || !Network.hasWifi)
            Column {
                x: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                CcConnRow {
                    visible: conn.wifiRow
                    objectBase: "cc.wifi"
                    icon: Network.wifiEnabled ? "bold/wifi-high" : "bold/wifi-slash"
                    title: Strings.t("panels.wifi")
                    subtitle: !Network.wifiEnabled ? Strings.t("panels.off") : Network.wifiConnected ? Network.wifiName : Strings.t("panels.wifi.notConnected")
                    on: Network.wifiEnabled
                    scheme: mp.scheme
                    onToggled: Network.setWifiEnabled(!Network.wifiEnabled)
                    onOpened: mp.openPage("wifi")
                }
                CcConnRow {
                    visible: conn.btRow
                    objectBase: "cc.bt"
                    icon: "bold/bluetooth"
                    title: Strings.t("panels.bt")
                    subtitle: !BluetoothStatus.enabled ? Strings.t("panels.off")
                              : BluetoothStatus.connectedCount === 1 && Hw.btDevices.length ? (Hw.btDevices[0].name || Hw.btDevices[0].deviceName)
                              : BluetoothStatus.connectedCount > 1 ? Strings.tn("panels.bt.nConnected", BluetoothStatus.connectedCount) : Strings.t("panels.on")
                    on: BluetoothStatus.enabled
                    scheme: mp.scheme
                    onToggled: BluetoothStatus.setEnabled(!BluetoothStatus.enabled)
                    onOpened: mp.openPage("bluetooth")
                }
                CcConnRow {
                    visible: conn.wiredRow
                    objectBase: "cc.ethernet"
                    icon: "bold/network"
                    title: Strings.t("panels.ethernet")
                    subtitle: Network.wiredConnected ? Strings.t("panels.ethernet.connected") : Strings.t("panels.ethernet.disconnected")
                    on: Network.wiredConnected
                    switchable: false
                    scheme: mp.scheme
                    onOpened: Session.openSystemSettings("kcm_networkmanagement")
                }
                KText {
                    visible: !conn.wifiRow && !conn.btRow && !conn.wiredRow
                    width: conn.width - 20
                    text: Strings.t("panels.network.none")
                    textStyle: "callout"
                    level: "secondaryLabel"
                    wrapMode: Text.WordWrap
                    lineHeightMode: Text.ProportionalHeight
                    lineHeight: 1.0
                    scheme: mp.scheme
                }
            }
        }
        Loader {
            width: PanelMetrics.ccHalf
            height: PanelMetrics.ccHalf
            sourceComponent: mp.hasMedia ? mediaTile : focusBlock
        }
    }

    // ---- row 2 (with a player: focus and the small tiles move here) ------------------------------
    Loader {
        active: mp.hasMedia
        visible: active
        width: PanelMetrics.ccInner
        height: active ? PanelMetrics.ccCell : 0
        sourceComponent: Row {
            spacing: PanelMetrics.ccGap
            Loader { sourceComponent: focusTile }
            Loader { sourceComponent: smallA }
            Loader { sourceComponent: smallB }
        }
    }

    // ---- sliders ---------------------------------------------------------------------------------
    CcSliderModule {
        id: display
        title: Strings.t("panels.display")
        sliderName: "cc.display"
        icon: "fill/sun"
        value: Hw.brightness
        scheme: mp.scheme
        visible: Hw.hasBacklight
        onMoved: v => Hw.setBrightness(v)
        onOpened: mp.openPage("display")
    }
    // without a backlight (desktop monitor) the Display module keeps the appearance switch
    CcTile {
        visible: !Hw.hasBacklight
        width: PanelMetrics.ccInner
        height: PanelMetrics.ccCell
        scheme: mp.scheme
        KText {
            x: 12; y: 6; height: 20
            text: Strings.t("panels.display")
            textStyle: "subheadline"
            emphasized: true
            scheme: mp.scheme
        }
        KSegmented {
            objectName: "cc.appearance"
            x: 12; y: 32
            width: parent.width - 24
            scheme: mp.scheme
            model: [Strings.t("panels.appearance.light"), Strings.t("panels.appearance.dark"), Strings.t("panels.appearance.auto")]
            id: appearanceSegments
            currentIndex: ["light", "dark", "auto"].indexOf(Settings.get("appearance.theme", "auto"))
            onActivated: i => Settings.set("appearance.theme", ["light", "dark", "auto"][i])
        }
    }
    CcSliderModule {
        id: sound
        title: Strings.t("panels.sound")
        sliderName: "cc.sound"
        visible: Audio.available
        icon: Audio.muted || Audio.volume <= 0 ? "fill/speaker-simple-slash" : Audio.volume < 0.34 ? "fill/speaker-simple-none" : Audio.volume < 0.67 ? "fill/speaker-simple-low" : "fill/speaker-simple-high"
        value: Audio.muted ? 0 : Audio.volume
        scheme: mp.scheme
        onMoved: v => Audio.setVolume(v)
        onOpened: mp.openPage("sound")
        // the speaker symbol inside the slider mutes / unmutes
        MouseArea {
            objectName: "cc.sound.mute"
            width: parent.height
            height: parent.height
            cursorShape: Qt.PointingHandCursor
            onClicked: Audio.setMuted(!Audio.muted)
            function activate() { Audio.setMuted(!Audio.muted); }
        }
    }
    CcTile {
        visible: !Audio.available
        width: PanelMetrics.ccInner
        height: 44
        scheme: mp.scheme
        KText {
            x: 12; anchors.verticalCenter: parent.verticalCenter
            text: Strings.t("panels.sound") + " — " + Strings.t("panels.sound.none")
            textStyle: "callout"
            level: "secondaryLabel"
            scheme: mp.scheme
        }
    }
    CcSliderModule {
        title: Strings.t("panels.kbd")
        sliderName: "cc.kbd"
        visible: Hw.hasKbdLight
        expandable: false
        icon: "fill/keyboard"
        value: Hw.kbdLevel
        scheme: mp.scheme
        onMoved: v => Hw.setKbd(v)
    }

    // ---- battery and energy mode ------------------------------------------------------------------
    CcTile {
        id: energy
        visible: Power.hasBattery || Power.hasPerformance
        width: PanelMetrics.ccInner
        height: 52
        scheme: mp.scheme
        objectName: "cc.energy.open"
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: title.text + ", " + sub.text
        Keys.onReturnPressed: mp.openPage("energy")
        Keys.onSpacePressed: mp.openPage("energy")
        function activate() { mp.openPage("energy"); }
        KIcon {
            id: battIcon
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            size: 22
            name: PanelsUtil.batteryIcon()
            color: Power.hasBattery && Power.percent <= 10 && !Power.charging ? Theme.color(mp.scheme, "destructive") : Theme.color(mp.scheme, "label")
        }
        Column {
            x: battIcon.x + battIcon.width + 10
            width: parent.width - x - 30
            anchors.verticalCenter: parent.verticalCenter
            KText {
                id: title
                width: parent.width
                text: Power.hasBattery ? Strings.t("panels.battery") + "  " + Power.percent + " %" : Strings.t("panels.energy.mode")
                textStyle: "callout"
                emphasized: true
                tabular: true
                scheme: mp.scheme
            }
            KText {
                id: sub
                width: parent.width
                text: PanelsUtil.energySummary()
                textStyle: "subheadline"
                level: "secondaryLabel"
                elide: Text.ElideRight
                scheme: mp.scheme
            }
        }
        KIcon {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            size: 12
            name: "bold/caret-right"
            color: Theme.color(mp.scheme, "secondaryLabel")
        }
        KFocusRing { targetRadius: Theme.radius.panelTile; scheme: mp.scheme }
        TapHandler { onTapped: mp.openPage("energy") }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }

    // ---- pieces placed by the loaders above ----------------------------------------------------------
    Component {
        id: focusTile
        CcTile {
            width: PanelMetrics.ccHalf
            height: PanelMetrics.ccCell
            scheme: mp.scheme
            CcConnRow {
                x: 10
                anchors.verticalCenter: parent.verticalCenter
                objectBase: "cc.focus"
                icon: "fill/moon"
                title: Strings.t("panels.focus")
                subtitle: Notifs.dnd ? Fmt.until(Notifs.dndUntil) : Strings.t("panels.off")
                on: Notifs.dnd
                scheme: mp.scheme
                onToggled: Notifs.setDnd(Notifs.dnd ? 0 : -1)
                onOpened: mp.openPage("focus")
            }
        }
    }
    Component {
        id: smallA
        CcSmallTile {
            visible: mp.hasScreenshot
            buttonName: "cc.screenshot"
            icon: "selection-plus"
            caption: Strings.t("panels.screenshot")
            scheme: mp.scheme
            onClicked: {
                mp.closeRequested();
                // after the panel is gone, so it is not in the picture
                Quickshell.execDetached(["sh", "-c", "sleep 0.4; exec spectacle --region"]);
            }
        }
    }
    Component {
        id: smallB
        CcSmallTile {
            buttonName: Hw.hasNightLight ? "cc.nightlight" : "cc.darkmode"
            icon: Hw.hasNightLight ? "fill/sun-horizon" : "fill/circle-half"
            caption: Hw.hasNightLight ? Strings.t("panels.nightLight") : Strings.t("panels.darkMode")
            on: Hw.hasNightLight ? Hw.nightLightOn : Theme.dark
            scheme: mp.scheme
            onClicked: {
                if (Hw.hasNightLight)
                    Hw.setNightLight(!Hw.nightLightOn);
                else
                    Settings.set("appearance.theme", Theme.dark ? "light" : "dark");
            }
        }
    }
    Component {
        id: focusBlock
        Column {
            spacing: PanelMetrics.ccGap
            Loader { sourceComponent: focusTile }
            Row {
                spacing: PanelMetrics.ccGap
                Loader { sourceComponent: smallA }
                Loader { sourceComponent: smallB }
            }
        }
    }
    Component {
        id: mediaTile
        CcNowPlaying {
            scheme: mp.scheme
            onOpened: mp.openPage("media")
        }
    }
}
