// SPDX-License-Identifier: GPL-3.0-or-later
// The menu bar of one output (design.md §8, shell.md §3).
// Left: our mark and its menu · the front app's name (bold) · that app's own menus (DBusMenu via
// the bridge's window.menu) or a minimal menu set. Right: tray (StatusNotifierItem) · battery ·
// Wi-Fi · sound · Control Center · assistant · clock. Glass strip; solid and calmer while the front
// window on this output is maximised (macOS 27). Text colour follows the glass legibility signal.
import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import Quickshell.Services.SystemTray
import qs.core
import qs.services
import qs.bar

PanelWindow {
    id: barWindow
    required property var modelData
    screen: modelData
    readonly property string screenName: screen ? screen.name : ""

    WlrLayershell.namespace: "kristall-bar"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    anchors { top: true; left: true; right: true }
    implicitHeight: Theme.size.bar
    exclusiveZone: Theme.size.bar
    color: "transparent"

    // ---- state ---------------------------------------------------------------------------------
    readonly property var front: Bridge.frontWindow
    readonly property bool frontHere: front !== null && front.output === screenName
    readonly property bool dimmed: Settings.get("bar.dimWhenMaximized", true) && frontHere && !front.minimized && (front.maximized || front.fullscreen)
    readonly property string scheme: dimmed ? Theme.scheme : strip.scheme
    readonly property string appId: front ? front.appId : ""
    readonly property string appName: front ? Apps.displayName(front.appId) : Strings.pick(Apps.byId("files") ? Apps.byId("files").name : { en: "Files", de: "Dateien" })
    readonly property bool hasAppMenu: front !== null && front.menu !== null && front.menu !== undefined && AppMenus.trees.app !== undefined
    // top-level titles of the front app's menu; replaced only when ids/labels change so the
    // title buttons are not rebuilt on every layout update (apps update menus while opening them)
    property var appTitles: []
    function _refreshTitles() {
        const t = hasAppMenu ? AppMenus.trees.app : null;
        const list = (t && t.children ? t.children : []).filter(c => c.type === "item" && c.label !== "")
            .map(c => ({ id: c.id, label: c.label, enabled: c.enabled !== false }));
        if (JSON.stringify(list) !== JSON.stringify(appTitles))
            appTitles = list;
    }
    onHasAppMenuChanged: _refreshTitles()
    Connections {
        target: AppMenus
        function onLayoutChanged(key) { if (key === "app") barWindow._refreshTitles(); }
    }

    Component.onCompleted: BarRegistry.add(screenName, barWindow)
    Component.onDestruction: BarRegistry.remove(screenName, barWindow)

    // ---- menu tracking (press-and-drag across titles, ←/→) -------------------------------------
    property var buttons: []
    function registerButton(b) { buttons = buttons.concat([b]); }
    function unregisterButton(b) { buttons = buttons.filter(x => x !== b); }
    function isVisibleInBar(b) {
        const p = b.mapToItem(null, 0, 0);
        return p.x + b.width <= barWindow.width + 0.5 && (b.parent !== leftClip.contentItem || p.x + b.width <= leftClip.width + 0.5);
    }
    function ordered() {
        return buttons.filter(b => b.trackable).sort((a, b) => a.mapToItem(null, 0, 0).x - b.mapToItem(null, 0, 0).x);
    }
    readonly property QtObject tracker: QtObject {
        readonly property int openIndex: {
            const c = Menus.current;
            if (!c)
                return -1;
            const list = barWindow.ordered();
            for (let i = 0; i < list.length; ++i)
                if (list[i].fullOwner === c.owner)
                    return i;
            return -1;
        }
        function hitTest(x, y) {
            if (y < 0 || y >= Theme.size.bar)
                return -1;
            const list = barWindow.ordered();
            for (let i = 0; i < list.length; ++i) {
                const p = list[i].mapToItem(null, 0, 0);
                if (x >= p.x && x < p.x + list[i].width)
                    return i;
            }
            return -1;
        }
        function openAt(i, keyboard) {
            const list = barWindow.ordered();
            if (i >= 0 && i < list.length)
                list[i].openMenu(keyboard);
        }
        function step(d) {
            const list = barWindow.ordered();
            if (list.length === 0)
                return;
            openAt(((openIndex < 0 ? 0 : openIndex) + d + list.length) % list.length, true);
        }
    }
    function openFirstMenu() {
        const list = ordered();
        if (list.length)
            list[0].openMenu(true);
    }

    // ---- material ------------------------------------------------------------------------------
    GlassSurface {
        id: glassSurface
        key: "bar-" + barWindow.screenName
        layerNamespace: "kristall-bar"
        output: barWindow.screenName
    }
    GlassShape {
        id: strip
        shapeId: "strip"
        surface: glassSurface
        role: "bar"
        anchors.fill: parent
        glassOpacity: barWindow.dimmed ? 0 : 1
        glassEnabled: glassOpacity > 0.001
        Behavior on glassOpacity { NumberAnimation { duration: Theme.duration("barDim", true); easing.type: Easing.InOutQuad } }
    }
    Rectangle {    // the solid, calmer state
        anchors.fill: parent
        color: Theme.color(Theme.scheme, "barSolid")
        opacity: barWindow.dimmed ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.duration("barDim", true); easing.type: Easing.InOutQuad } }
        KSeparator { anchors.bottom: parent.bottom; width: parent.width; scheme: Theme.scheme }
    }

    // ---- left: mark, app name, app menus ---------------------------------------------------------
    Flickable {
        id: leftClip
        x: Theme.size.barEdge
        height: parent.height
        width: Math.max(0, right.x - x - 12)
        interactive: false
        clip: true
        contentWidth: leftRow.width
        opacity: barWindow.dimmed ? 0.88 : 1
        Row {
            id: leftRow
            height: Theme.size.bar
            spacing: Theme.size.barTitleSpacing

            BarButton {
                id: markButton
                bar: barWindow
                owner: "mark"
                padding: Theme.size.barMarkPadding
                accessibleName: Strings.t("bar.mark")
                menuSource: function () { return Menus.list(BarMenus.markMenu()); }
                KIcon {
                    name: "kristall/mark"
                    size: 15
                    scheme: barWindow.scheme
                    color: Theme.color(barWindow.scheme, "label")
                }
            }
            BarButton {
                bar: barWindow
                owner: "app"
                text: barWindow.appName
                bold: true
                menuSource: function () { return Menus.list(BarMenus.appNameMenu(barWindow.front, barWindow.appName)); }
            }
            Repeater {
                model: barWindow.appTitles
                BarButton {
                    required property var modelData
                    required property int index
                    bar: barWindow
                    owner: "title:" + modelData.id
                    text: modelData.label
                    enabled: modelData.enabled !== false
                    menuSource: function () {
                        AppMenus.aboutToShow("app", modelData.id);
                        return { kind: "dbus", key: "app", item: modelData.id };
                    }
                }
            }
            Repeater {
                // minimal menus for apps that export none (and the desktop), plus our Window menu
                model: BarMenus.extraTitles(barWindow.front, barWindow.appTitles)
                BarButton {
                    required property var modelData
                    bar: barWindow
                    owner: "extra:" + modelData.id
                    text: modelData.label
                    menuSource: function () { return Menus.list(BarMenus.extraMenu(modelData.id, barWindow.front)); }
                }
            }
        }
    }

    // ---- right: tray, battery, Wi-Fi, sound, Control Center, assistant, clock -------------------
    Row {
        id: right
        anchors.right: parent.right
        anchors.rightMargin: Theme.size.barEdge
        height: parent.height
        spacing: 0
        opacity: barWindow.dimmed ? 0.88 : 1

        Repeater {
            model: SystemTray.items
            BarButton {
                id: trayButton
                required property var modelData
                bar: barWindow
                owner: "tray:" + modelData.id
                padding: Theme.size.barStatusPadding
                tooltip: modelData.tooltipTitle || modelData.title
                accessibleName: modelData.title
                visible: modelData.status !== Status.Passive
                menuSource: modelData.hasMenu ? function () { return { kind: "qs", handle: trayButton.modelData.menu }; } : null
                menuMinWidth: 200
                rightClickMenu: !modelData.onlyMenu
                onActivated: button => button === Qt.MiddleButton ? modelData.secondaryActivate() : modelData.activate()
                IconImage {
                    implicitSize: Theme.size.barIcon
                    source: trayButton.modelData.icon
                }
            }
        }
        BarButton {
            id: battery
            bar: barWindow
            owner: "status:battery"
            visible: Power.hasBattery
            padding: Theme.size.barStatusPadding
            accessibleName: Strings.t("battery.title") + " " + Power.percent + " %"
            menuSource: function () { return Menus.list(BarMenus.batteryMenu()); }
            menuMinWidth: 250
            Row {
                spacing: 5
                KText {
                    visible: Settings.get("bar.showBatteryPercentage", false)
                    anchors.verticalCenter: parent.verticalCenter
                    text: Power.percent + " %"
                    textStyle: "menuBar"
                    tabular: true
                    scheme: barWindow.scheme
                }
                BatteryGlyph {
                    anchors.verticalCenter: parent.verticalCenter
                    level: Power.percent / 100
                    charging: Power.charging
                    plugged: !Power.onBattery && !Power.charging
                    scheme: barWindow.scheme
                }
            }
        }
        BarButton {
            bar: barWindow
            owner: "status:wifi"
            visible: Network.available && Network.hasWifi
            padding: Theme.size.barStatusPadding
            accessibleName: Strings.t("wifi.title")
            icon: !Network.wifiEnabled ? "wifi-slash" : Network.wifiBars === 3 ? "bold/wifi-high" : Network.wifiBars === 2 ? "bold/wifi-medium" : Network.wifiBars === 1 ? "bold/wifi-low" : "wifi-none"
            menuSource: function () { return Menus.list(BarMenus.wifiMenu()); }
            menuMinWidth: 260
        }
        BarButton {
            bar: barWindow
            owner: "status:sound"
            padding: Theme.size.barStatusPadding
            accessibleName: Strings.t("sound.title")
            icon: !Audio.available || Audio.muted || Audio.volume <= 0 ? "fill/speaker-simple-slash" : Audio.volume < 0.34 ? "fill/speaker-simple-none" : Audio.volume < 0.67 ? "fill/speaker-simple-low" : "fill/speaker-simple-high"
            menuSource: function () { return Menus.list(BarMenus.soundMenu()); }
            menuMinWidth: 280
        }
        BarButton {
            bar: barWindow
            owner: "status:control-center"
            visible: Settings.get("bar.showControlCenter", true)
            padding: Theme.size.barStatusPadding
            icon: "kristall/control-center"
            accessibleName: Strings.t("bar.controlCenter")
            active: ShellBus.isOpen("control-center", barWindow.screenName)
            onClicked: ShellBus.request("panels", "toggle-control-center", "", barWindow.screenName)
        }
        BarButton {
            bar: barWindow
            owner: "status:assistant"
            visible: Settings.get("bar.showAssistant", true)
            padding: Theme.size.barStatusPadding
            icon: "kristall/assistant"
            accessibleName: Strings.t("bar.assistant")
            active: ShellBus.isOpen("assistant", barWindow.screenName)
            onClicked: ShellBus.request("assistant", "invoke", "bar", barWindow.screenName)
        }
        BarButton {
            bar: barWindow
            owner: "status:clock"
            padding: Theme.size.barStatusPadding + 1
            text: Clock.barText(Clock.date)
            accessibleName: Clock.longDate(Clock.date) + " " + text
            active: ShellBus.isOpen("notifications", barWindow.screenName)
            onClicked: ShellBus.request("panels", "toggle-notifications", "", barWindow.screenName)
        }
    }
}
