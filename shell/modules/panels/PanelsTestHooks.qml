// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC target "panelstest" (loaded when KRISTALL_SHELL_TEST=1): reports the panels'
// state and finds controls by objectName to operate them the way a click or drag would, and
// reports their rectangles on the output so tests can use real pointer and keyboard input too.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import Quickshell.Networking as QsNet
import qs.core
import qs.services

Scope {
    id: hooks
    property var module: null

    function find(item, name) {
        if (!item)
            return null;
        if (item.objectName === name && item.visible !== false)
            return item;
        const kids = item.children || [];
        for (let i = 0; i < kids.length; ++i) {
            const r = find(kids[i], name);
            if (r)
                return r;
        }
        return null;
    }
    function names(item, out, onlyVisible) {
        if (!item)
            return out;
        if (onlyVisible && item.visible === false)
            return out;
        if (item.objectName && item.objectName.indexOf(".") > 0 || (item.objectName || "").indexOf(":") > 0)
            out.push(item.objectName);
        const kids = item.children || [];
        for (let i = 0; i < kids.length; ++i)
            names(kids[i], out, onlyVisible);
        return out;
    }
    function findAny(name) {
        const ws = PanelsRegistry.windows;
        for (const k in ws) {
            const it = find(ws[k].contentItem, name);
            if (it)
                return { item: it, win: ws[k] };
        }
        return null;
    }
    function rectOf(hit) {
        const p = hit.item.mapToItem(null, 0, 0);
        const w = hit.win;
        // CC and Notification Centre cover the output; banners and HUD are anchored top right
        const ox = w.anchors.left ? 0 : w.screen.width - w.width;
        return { x: ox + p.x, y: p.y, w: hit.item.width, h: hit.item.height };
    }

    IpcHandler {
        target: "panelstest"

        function state(): string {
            const ws = PanelsRegistry.windows;
            const out = { windows: Object.keys(ws) };
            const m = hooks.module;
            out.ccOutput = m ? m.ccOutput : "";
            out.ncOutput = m ? m.ncOutput : "";
            for (const k in ws) {
                if (k.startsWith("cc:")) {
                    const w = ws[k];
                    out.cc = { page: w.page, open: w.open, t: w.t, scheme: w.scheme, controls: hooks.names(w.contentItem, [], true),
                               height: w.target.height, width: w.target.width };
                }
                if (k.startsWith("nc:"))
                    out.nc = { open: ws[k].open, controls: hooks.names(ws[k].contentItem, [], true) };
                if (k.startsWith("hud:")) {
                    const h = ws[k];
                    out.hud = { kind: h.kind, level: h.level, title: h.title, fade: h.fade, symbol: h.symbol };
                }
                if (k.startsWith("banners:"))
                    out.bannerWindow = { output: k.split(":")[1], keyboard: ws[k].replying };
            }
            out.banners = Notifs.banners.map(e => ({ key: e.key, app: e.displayName, appKey: e.appKey, summary: e.summary, body: e.body,
                                                      progress: e.progress, actions: e.actions, critical: e.critical, image: e.image,
                                                      icon: e.iconSource, stacked: Notifs.stackedBehind(e), live: e.live, reply: e.hasReply }));
            out.notifications = { count: Notifs.count, dnd: Notifs.dnd, dndUntil: Notifs.dndUntil, muted: Notifs.mutedApps,
                                  groups: Notifs.groups.map(g => ({ key: g.key, name: g.name, count: g.entries.length,
                                                                    summaries: g.entries.map(e => e.summary) })) };
            out.hw = { backlight: Hw.hasBacklight, brightness: Hw.brightness, kbd: Hw.hasKbdLight, kbdLevel: Hw.kbdLevel,
                       night: PanelsHelper.night, nightOn: Hw.nightLightOn, locked: PanelsHelper.locked,
                       sinks: Hw.sinks.map(s => Hw.sinkName(s)), defaultSink: Pipewire.defaultAudioSink ? Hw.sinkName(Pipewire.defaultAudioSink) : "",
                       micInUse: Hw.micInUse, micUser: Hw.micUser,
                       networks: Hw.networks.map(n => ({ name: n.name, strength: n.signalStrength, connected: n.connected, known: n.known, secured: Hw.secured(n), security: QsNet.WifiSecurityType.toString(n.security) })),
                       bt: Hw.btDevices.map(d => ({ name: d.name || d.deviceName, connected: d.connected, battery: d.batteryAvailable ? d.battery : -1 })),
                       btAvailable: BluetoothStatus.available, btEnabled: BluetoothStatus.enabled,
                       wifiEnabled: Network.wifiEnabled, wifiName: Network.wifiName, hasWifi: Network.hasWifi, netAvailable: Network.available };
            out.audio = { available: Audio.available, volume: Audio.volume, muted: Audio.muted, device: Audio.deviceName };
            out.media = { available: Media.available, title: Media.title, artist: Media.artist, playing: Media.playing, app: Media.appName };
            out.power = { battery: Power.hasBattery, percent: Power.percent, mode: Power.mode, selected: PanelsUtil.selectedMode, summary: PanelsUtil.energySummary(), chosenText: PanelsUtil.chosenModeText() };
            out.helper = { ready: PanelsHelper.ready, notifyOwner: PanelsHelper.notifyOwner };
            out.theme = Theme.scheme;
            out.open = ShellBus.open;
            return JSON.stringify(out);
        }

        // operate a control as a click would
        function click(name: string): string {
            const h = hooks.findAny(name);
            if (!h)
                return "missing";
            const it = h.item;
            if (typeof it.activate === "function")
                it.activate();
            else if (typeof it._activate === "function")
                it._activate();
            else if (typeof it.flip === "function")
                it.flip();
            else if (typeof it.activated === "function")
                it.activated();
            else if (typeof it.clicked === "function")
                it.clicked();
            else
                return "not clickable";
            return "ok";
        }
        function slide(name: string, value: real): string {
            const h = hooks.findAny(name);
            if (!h || typeof h.item.setValue !== "function")
                return "missing";
            h.item.setValue(value);
            return "ok";
        }
        // the value the control shows right now
        function shown(name: string): string {
            const h = hooks.findAny(name);
            if (!h)
                return "missing";
            const it = h.item;
            return JSON.stringify({ shown: it.shown !== undefined ? it.shown : it.value, checked: it.checked, on: it.on, index: it.currentIndex });
        }
        // texts under the named control that do not fit (elided or cut after the last line)
        function truncated(name: string): string {
            const h = hooks.findAny(name);
            if (!h)
                return "missing";
            const out = [];
            const walk = it => {
                if (!it || it.visible === false)
                    return;
                if (it.truncated === true)
                    out.push(it.text);
                for (const k of (it.children || []))
                    walk(k);
            };
            walk(h.item);
            return JSON.stringify(out);
        }
        function segment(name: string, index: int): string {
            const h = hooks.findAny(name);
            if (!h || typeof h.item.select !== "function")
                return "missing";
            h.item.select(index);
            return "ok";
        }
        function type(name: string, text: string): string {
            const h = hooks.findAny(name);
            if (!h)
                return "missing";
            h.item.text = text;
            return "ok";
        }
        function accept(name: string): string {
            const h = hooks.findAny(name);
            if (!h)
                return "missing";
            h.item.accepted();
            return "ok";
        }
        function rect(name: string): string {
            const h = hooks.findAny(name);
            return h ? JSON.stringify(hooks.rectOf(h)) : "null";
        }
        function controls(): string {
            const out = {};
            const ws = PanelsRegistry.windows;
            for (const k in ws)
                out[k] = hooks.names(ws[k].contentItem, [], true);
            return JSON.stringify(out);
        }
        function page(name: string): string {
            const ws = PanelsRegistry.windows;
            for (const k in ws)
                if (k.startsWith("cc:")) {
                    ws[k].openPage(name);
                    return "ok";
                }
            return "no cc";
        }
        function pressEscape(): string {
            const ws = PanelsRegistry.windows;
            for (const k in ws) {
                if (k.startsWith("cc:")) {
                    if (ws[k].page !== "main")
                        ws[k].back();
                    else
                        ws[k].closeRequested();
                    return "cc";
                }
                if (k.startsWith("nc:")) {
                    ws[k].closeRequested();
                    return "nc";
                }
            }
            return "none";
        }
        function hud(kind: string, percent: int): string {
            hooks.module.hudFor(kind, percent, "", "");
            return "ok";
        }
        function hideBanners(): string {
            Notifs.hideAllBanners();
            return "ok";
        }
        function notifSet(key: int, field: string, value: string): string {
            for (const e of Notifs.entries)
                if (e.key === key) {
                    if (field === "activate")
                        Notifs.activate(e);
                    else if (field === "remove")
                        Notifs.remove(e);
                    else if (field === "action")
                        Notifs.invokeAction(e, value);
                    else if (field === "reply")
                        Notifs.reply(e, value);
                    else if (field === "mute")
                        Notifs.setMuted(e.appKey, value === "true");
                    else if (field === "menu") {
                        for (const k in PanelsRegistry.windows) {
                            const c = hooks.find(PanelsRegistry.windows[k].contentItem, (k.startsWith("nc:") ? "nc:" : "banner:") + key);
                            if (c) {
                                PanelsMenus.cardMenu(c, k.split(":")[1]);
                                return "ok";
                            }
                        }
                        return "no card";
                    }
                    return "ok";
                }
            return "missing";
        }
        function clearAll(): string {
            Notifs.clearAll();
            return "ok";
        }
    }
}
