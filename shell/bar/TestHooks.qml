// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC (loaded when KRISTALL_SHELL_TEST=1): drives the bar and menus the way pointer
// and keyboard input would (the headless compositor has no input devices) and reports state.
import QtQuick
import Quickshell
import Quickshell.Io
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
    IpcHandler {
        target: "test"
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
