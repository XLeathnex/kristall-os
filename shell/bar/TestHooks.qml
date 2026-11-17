// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC (loaded when KRISTALL_SHELL_TEST=1): drives the bar and menus the way pointer
// and keyboard input would (the headless compositor has no input devices) and reports state.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.core
import qs.services
import Quickshell.Services.SystemTray

Scope {
    id: hooks
    function bar(output) {
        return BarRegistry.bars[output] || BarRegistry.bars[Object.keys(BarRegistry.bars)[0]];
    }
    // every ShellBus request as it arrived (kristall-shellctl argument passing)
    property var requests: []
    Connections {
        target: ShellBus
        function onRequested(target, action, arg, output) {
            hooks.requests = hooks.requests.concat([{ target: target, action: action, arg: arg, output: output }]).slice(-20);
        }
    }
    // a KToggle bound to a setting, on its own surface at (100, 100) (binding-safety test)
    property bool toggleTest: false
    LazyLoader {
        active: hooks.toggleTest
        PanelWindow {
            screen: Quickshell.screens[0]
            WlrLayershell.namespace: "kristall-test"
            WlrLayershell.layer: WlrLayer.Overlay
            exclusionMode: ExclusionMode.Ignore
            anchors { top: true; left: true }
            margins { top: 100; left: 100 }
            implicitWidth: 120
            implicitHeight: 64
            color: Theme.color(Theme.scheme, "window")
            KToggle {
                id: boundToggle
                objectName: "test.toggle"
                x: 20; y: 20
                checked: Settings.get("bar.showBatteryPercentage", false) === true
                onToggled: on => Settings.set("bar.showBatteryPercentage", on)
                Component.onCompleted: hooks.testToggle = boundToggle
            }
        }
    }
    property var testToggle: null
    IpcHandler {
        target: "test"
        // a static menu with two submenus at (x, y) of the first output (safe-triangle tests)
        function openTestMenu(x: real, y: real): string {
            const scr = Quickshell.screens[0].name;
            Menus.open({ screen: scr, rect: { x: x, y: y, w: 1, h: 1 }, owner: "test:menu", source: Menus.list([
                { label: "Erstes", children: [1, 2, 3, 4, 5, 6].map(i => ({ label: "Eins " + i, action: () => {} })) },
                { label: "Zweites", action: () => {} },
                { label: "Drittes", action: () => {} },
                { label: "Viertes", children: [1, 2, 3].map(i => ({ label: "Vier " + i, action: () => {} })) },
                { label: "Fünftes", action: () => {} }
            ]) });
            return "ok";
        }
        function menuState(): string {
            const host = Menus.hosts[Quickshell.screens[0].name];
            if (!host || !host.open)
                return JSON.stringify(null);
            const levels = [];
            for (let i = 0; i < host.levelModel.count; ++i) {
                const p = host.panelAt(i);
                levels.push({ anchorRow: host._levels[i] ? host._levels[i].anchorRow : -1, current: p ? p.currentIndex : -1,
                              x: p ? p.x : 0, y: p ? p.y : 0, w: p ? p.width : 0, h: p ? p.height : 0,
                              rows: p ? p.entries.map((e, k) => p.rowRect(k)) : [] });
            }
            return JSON.stringify(levels);
        }
        // a pointer path over the open menu ("x,y;x,y;…"), delivered as consecutive motion events
        function hoverPath(points: string): string {
            const host = Menus.hosts[Quickshell.screens[0].name];
            for (const pt of points.split(";").map(p => p.split(",").map(Number)))
                if (host && pt.length === 2)
                    host.pointerMove(pt[0], pt[1], false);
            return "ok";
        }
        function hover(x: real, y: real): string {
            const host = Menus.hosts[Quickshell.screens[0].name];
            if (host)
                host.pointerMove(x, y, false);
            return "ok";
        }
        function toggleTest(on: bool): string {
            hooks.toggleTest = on;
            return "ok";
        }
        function toggleState(): string {
            const t = hooks.testToggle;
            return JSON.stringify(t ? { checked: t.checked, shown: t.shownChecked, setting: Settings.get("bar.showBatteryPercentage", false) } : null);
        }
        function lastRequests(): string {
            return JSON.stringify(hooks.requests);
        }
        function openMenu(index: int, output: string): string {
            const b = hooks.bar(output);
            if (!b)
                return "no bar";
            b.tracker.openAt(index, true);
            return "ok";
        }
        // press on bar item `index`, drag to (x, y) and release there (output coordinates)
        function pressDragRelease(index: int, x: real, y: real, output: string): string {
            const b = hooks.bar(output);
            const list = b.ordered();
            if (index < 0 || index >= list.length)
                return "no item";
            list[index].openMenu(false);
            Menus.dragMove(b.screenName, x, y);
            return Menus.dragRelease(b.screenName, x, y) ? "activated" : "released";
        }
        // how a one-chord DBusMenu shortcut ("Control+Shift+N" for [["Control","Shift","N"]]) is shown
        function shortcutText(chord: string): string {
            return Theme.shortcutText([chord.split("+")]);
        }
        // a click or touchpad tap on a title: press and release in the same instant, before the
        // menu's surface is configured (a tap delivers both at once)
        function quickClick(index: int, output: string): string {
            const b = hooks.bar(output);
            const list = b.ordered();
            if (index < 0 || index >= list.length)
                return "no item";
            const it = list[index];
            const p = it.mapToItem(null, it.width / 2, it.height / 2);
            it.openMenu(false);
            return Menus.dragRelease(b.screenName, p.x, p.y) ? "activated" : "released";
        }
        // press-and-drag in three steps, as the input would arrive: press on bar item, move, release
        function press(index: int, output: string): string {
            const b = hooks.bar(output);
            const list = b.ordered();
            if (index < 0 || index >= list.length)
                return "no item";
            list[index].openMenu(false);
            return "ok";
        }
        function release(x: real, y: real, output: string): string {
            const b = hooks.bar(output);
            return Menus.dragRelease(b.screenName, x, y) ? "activated" : "released";
        }
        function pointer(x: real, y: real, output: string): string {
            const b = hooks.bar(output);
            Menus.dragMove(b.screenName, x, y);
            return "ok";
        }
        function key(name: string, output: string): string {
            const b = hooks.bar(output);
            const host = Menus.hosts[b.screenName];
            if (!host)
                return "no host";
            const keys = { down: Qt.Key_Down, up: Qt.Key_Up, left: Qt.Key_Left, right: Qt.Key_Right, return: Qt.Key_Return, escape: Qt.Key_Escape };
            const ev = { key: keys[name] !== undefined ? keys[name] : 0, text: keys[name] !== undefined ? "" : name, accepted: false };
            host.key(ev);
            return ev.accepted ? "ok" : "ignored";
        }
        function close(): string {
            Menus.close("test");
            return "ok";
        }
        function itemRects(output: string): string {
            try {
                const b = hooks.bar(output);
                return JSON.stringify(b.ordered().map(x => { const p = x.mapToItem(null, 0, 0); return { owner: x.owner, text: x.text, x: p.x, w: x.width }; }));
            } catch (e) {
                console.warn("test.itemRects:", e);
                return "[]";
            }
        }
        // the app name the bar shows for a window's app id (Apps.displayName)
        function appName(appId: string): string {
            return Apps.displayName(appId);
        }
        // a window title as the owner reads it (Apps.windowTitle: product names → our names)
        function windowTitle(title: string): string {
            return Apps.windowTitle(title);
        }
        function state(output: string): string {
            const b = hooks.bar(output);
            const host = b ? Menus.hosts[b.screenName] : null;
            const levels = [];
            if (host) {
                for (let i = 0; i < host.levelModel.count; ++i) {
                    const p = host.panelAt(i);
                    if (p)
                        levels.push({ x: p.x, y: p.y, w: p.width, h: p.height, selected: p.currentIndex, scheme: p.scheme,
                                      items: p.entries.map(e => (e.type || "item") === "item" ? (e.label + (e.enabled === false ? " [disabled]" : "") + (e.checked ? " [x]" : "") + (e.shortcut ? " {" + e.shortcut + "}" : "") + ((e.sub || e.children) ? " >" : "")) : "-" + (e.type || "")) });
                }
            }
            return JSON.stringify({
                menu: Menus.current ? Menus.current.owner : null,
                levels: levels,
                bar: b ? { appName: b.appName, titles: b.ordered().map(x => x.text || x.owner), dimmed: b.dimmed, scheme: b.scheme,
                           reveal: { strip: b.revealAllowed && !b.revealed, revealed: b.revealed, slideY: b.slideY, gameLike: b.gameLike, fullscreen: b.fullscreenWin !== null },
                           glassDrawn: GlassClient.isBound("bar-" + b.screenName) && GlassClient.active } : null,
                theme: Theme.scheme, glass: GlassClient.state, bridge: Bridge.connected, activeId: Bridge.activeId,
                power: { battery: Power.hasBattery, percent: Power.percent, mode: Power.mode, onBattery: Power.onBattery },
                audio: { available: Audio.available, volume: Audio.volume, muted: Audio.muted },
                network: { available: Network.available, wifi: Network.hasWifi, connected: Network.connected, name: Network.wifiName, bars: Network.wifiBars, enabled: Network.wifiEnabled },
                bluetooth: { available: BluetoothStatus.available, enabled: BluetoothStatus.enabled },
                update: Updates.state, clock: Clock.barText(Clock.date), lang: Strings.lang,
                appMenu: AppMenus.sources.app || null,
                accent: Theme.accent.toString(), reduceMotion: Theme.reduceMotion, glassLevel: Theme.glassLevel,
                tray: SystemTray.items.values.map(i => ({ id: i.id, title: i.title, hasMenu: i.hasMenu }))
            });
        }
    }
}
