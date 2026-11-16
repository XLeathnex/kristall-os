// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Notifications
import qs.services


// The desktop's notification service (org.freedesktop.Notifications through Quickshell's
// NotificationServer) and everything the panels show of it: the history grouped by app (newest
// first), the banners on screen, Do Not Disturb, per-app muting. The history is kept in
// $XDG_RUNTIME_DIR/kristall/panels-notifications.json so it survives a shell restart within the
// session (the runtime directory ends with the session).
//
// Who decides what appears as a banner (macOS behaviour): nothing while the screen is locked;
// with Do Not Disturb, while the front window on that output is full screen, or for a muted app,
// only critical ("time-sensitive") notifications; nothing while Notification Centre is open (new
// ones go straight into it). Everything except transient notifications stays in the history.
Singleton {
    id: root

    property var entries: []           // NotifEntry, newest first
    property var banners: []           // NotifEntry shown as banners now, newest first
    property int revision: 0
    property int _serial: 1
    property bool centerOpen: false    // set by the module: Notification Centre is open somewhere
    property string bannerOutput: ""   // output banners appear on (set by the module)
    readonly property int maxHistory: 100

    // ---- Do Not Disturb ("Nicht stören"): until a time (ms since epoch), -1 = until switched off
    readonly property real dndUntil: Number(Settings.get("panels.focus.until", 0)) || 0
    property real _now: Date.now()
    onDndUntilChanged: _now = Date.now()
    readonly property bool dnd: dndUntil === -1 || dndUntil > _now
    function setDnd(until) {
        Settings.set("panels.focus.until", until);
    }
    Timer {
        // one shot at the end of the chosen period (no periodic wake-up)
        running: root.dndUntil > 0 && root.dndUntil > root._now
        interval: Math.max(1000, Math.min(2147483000, root.dndUntil - root._now))
        onTriggered: {
            root._now = Date.now();
            if (root.dndUntil > 0 && root.dndUntil <= root._now)
                root.setDnd(0);
        }
    }

    // ---- muted apps (banners off, still collected in Notification Centre)
    readonly property var mutedApps: Settings.get("panels.mutedApps", []) || []
    function isMuted(appKey) {
        return mutedApps.indexOf(appKey) >= 0;
    }
    function setMuted(appKey, muted) {
        const list = mutedApps.filter(k => k !== appKey);
        if (muted)
            list.push(appKey);
        Settings.set("panels.mutedApps", list);
    }

    // ---- groups for Notification Centre: [{key, name, icon, entries: [newest first]}], newest group first
    readonly property var groups: {
        revision;
        const order = [];
        const map = {};
        for (const e of entries) {
            if (e.isTransient)
                continue;
            if (!map[e.appKey]) {
                map[e.appKey] = { key: e.appKey, name: e.displayName, icon: e.iconSource, entries: [] };
                order.push(map[e.appKey]);
            }
            map[e.appKey].entries.push(e);
        }
        return order;
    }
    function group(key) {
        for (const g of groups)
            if (g.key === key)
                return g;
        return { key: key, name: "", icon: "", entries: [] };
    }
    readonly property int count: groups.reduce((n, g) => n + g.entries.length, 0)

    // ---- the server ----------------------------------------------------------------------------
    // Recreated when the name was taken by someone else and becomes free again (session start
    // order, a Plasma fallback panel that held it for a while).
    property bool _serverWanted: true
    LazyLoader {
        id: serverLoader
        active: root._serverWanted
        NotificationServer {
            keepOnReload: true
            persistenceSupported: true
            bodySupported: true
            bodyMarkupSupported: false
            bodyHyperlinksSupported: false
            bodyImagesSupported: false
            actionsSupported: true
            actionIconsSupported: false
            imageSupported: true
            inlineReplySupported: true
            onNotification: n => root._incoming(n)
        }
    }
    Connections {
        target: PanelsHelper
        function onNotifyOwnerChanged() {
            const o = PanelsHelper.notifyOwner;
            if (!o.owned && root._serverWanted && root._lostName) {
                console.info("kristall-panels: notification service is free again, claiming it");
                root._lostName = false;
                root._serverWanted = false;
                Qt.callLater(() => root._serverWanted = true);
            } else if (o.owned && !o.mine) {
                console.info("kristall-panels: org.freedesktop.Notifications is owned by pid", o.pid);
                root._lostName = true;
            }
        }
    }
    property bool _lostName: false

    property Component _entryComp: Component { NotifEntry {} }

    function _find(serverId) {
        for (const e of entries)
            if (e.n && e.serverId === serverId)
                return e;
        return null;
    }

    function _incoming(n) {
        n.tracked = true;
        let e = _find(n.id);
        const replaced = e !== null;
        const before = e ? (e.summary + "\n" + e.body) : "";
        if (!e) {
            e = _entryComp.createObject(root, { key: _serial++, n: n, time: Date.now() });
            e.sync();
            entries = [e].concat(entries);
        } else {
            e.n = n;
            e.sync();
            e.time = Date.now();
            entries = [e].concat(entries.filter(x => x !== e));
        }
        _trim();
        revision++;
        // a replacement that only moves a progress bar updates in place without a new banner
        const onlyProgress = replaced && before === e.summary + "\n" + e.body;
        if (banners.indexOf(e) >= 0)
            bannerUpdated(e);
        else if (!onlyProgress && _wantsBanner(e))
            _showBanner(e);
        _save();
    }
    signal bannerUpdated(var entry)

    function _wantsBanner(e) {
        if (PanelsHelper.locked)
            return false;
        if (centerOpen)
            return false;
        if (e.critical)
            return true;
        if (dnd || isMuted(e.appKey))
            return false;
        const front = Bridge.frontWindow;
        if (front && front.fullscreen && !front.minimized && (bannerOutput === "" || front.output === bannerOutput))
            return false;
        return true;
    }

    function _showBanner(e) {
        let b = banners.filter(x => x !== e);
        // the Mac stacks banners of one app: the newest one stands for the group
        b = b.filter(x => x.appKey !== e.appKey);
        banners = [e].concat(b).slice(0, PanelMetrics.bannerMax);
    }
    // number of other banners of the same app the newest one stands for (drawn as a stack)
    function stackedBehind(e) {
        revision;
        let n = 0;
        for (const x of entries)
            if (x !== e && x.appKey === e.appKey && x.time > Date.now() - 10 * 60 * 1000 && !x.isTransient)
                n++;
        return Math.min(n, 2);
    }

    function hideBanner(e) {
        if (banners.indexOf(e) >= 0)
            banners = banners.filter(x => x !== e);
        if (e.isTransient)
            remove(e);
    }
    function hideAllBanners() {
        for (const e of banners.slice())
            hideBanner(e);
    }

    // removes one notification (the app is told it was dismissed)
    function remove(e) {
        if (!e)
            return;
        banners = banners.filter(x => x !== e);
        entries = entries.filter(x => x !== e);
        const n = e.n;
        e.n = null;
        if (n)
            n.dismiss();
        e.destroy();
        revision++;
        _save();
    }
    function clearGroup(appKey) {
        for (const e of entries.filter(x => x.appKey === appKey))
            remove(e);
    }
    function clearAll() {
        for (const e of entries.slice())
            remove(e);
    }

    // the app (or its expiry) closed it
    function _closed(e, reason) {
        e.n = null;
        if (reason === NotificationCloseReason.CloseRequested || e.isTransient) {
            // the app took it back (e.g. the message was read elsewhere): it disappears everywhere
            banners = banners.filter(x => x !== e);
            entries = entries.filter(x => x !== e);
            Qt.callLater(() => e.destroy());
            revision++;
            _save();
        } else {
            revision++;
        }
    }

    function _trim() {
        if (entries.length <= maxHistory)
            return;
        const keep = entries.slice(0, maxHistory);
        for (const e of entries.slice(maxHistory)) {
            const n = e.n;
            e.n = null;
            if (n)
                n.dismiss();
            e.destroy();
        }
        entries = keep;
    }

    // ---- what a click does: the app's default action, and its window comes forward ---------------
    function activate(e) {
        const invoked = e.hasDefault && e.invoke("default");
        const win = windowFor(e);
        if (win)
            Bridge.call("window.activate", { id: win.id }, null);
        else if (!invoked && e.desktopEntry !== "")
            Apps.launch(e.desktopEntry);
        if (!e.resident)
            remove(e);
        else
            hideBanner(e);
    }
    function invokeAction(e, id) {
        e.invoke(id);
        const win = windowFor(e);
        if (win)
            Bridge.call("window.activate", { id: win.id }, null);
        if (!e.resident)
            remove(e);
    }
    function reply(e, text) {
        if (e.n && text !== "")
            e.n.sendInlineReply(text);
        remove(e);
    }

    // the app's top-most normal window: by sender pid, else desktop entry = app id, else app name
    function windowFor(e) {
        const ws = Bridge.windows;
        const order = Bridge.stacking.length ? Bridge.stacking : Object.keys(ws);
        const want = e.desktopEntry.replace(/\.desktop$/, "").toLowerCase();
        const name = e.appName.toLowerCase();
        const tests = [
            w => e.senderPid > 0 && w.pid === e.senderPid,
            w => want !== "" && (w.appId || "").toLowerCase() === want,
            w => want !== "" && want.split(".").pop() === (w.appId || "").toLowerCase().split(".").pop(),
            w => name !== "" && ((w.appId || "").toLowerCase() === name || (w.appId || "").toLowerCase().split(".").pop() === name)
        ];
        for (const t of tests) {
            for (let i = order.length - 1; i >= 0; --i) {
                const w = ws[order[i]];
                if (w && w.normal && t(w))
                    return w;
            }
        }
        return null;
    }

    // ---- persistence for the session -----------------------------------------------------------
    readonly property string historyPath: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/kristall/panels-notifications.json"
    property bool _loaded: false
    FileView {
        id: store
        path: root.historyPath
        blockLoading: true
        printErrors: false
        atomicWrites: true
    }
    function _save() {
        if (_loaded)
            Qt.callLater(_write);
    }
    function _write() {
        const data = { version: 1, entries: entries.filter(e => !e.isTransient).map(e => e.snapshot()) };
        store.setText(JSON.stringify(data));
    }
    Component.onCompleted: {
        try {
            const t = store.text();
            if (t) {
                const d = JSON.parse(t);
                const list = [];
                for (const s of (d.entries || [])) {
                    const e = _entryComp.createObject(root, s);
                    _serial = Math.max(_serial, (s.key || 0) + 1);
                    list.push(e);
                }
                entries = list;
                revision++;
            }
        } catch (err) {
            console.info("kristall-panels: no notification history to restore");
        }
        _loaded = true;
    }
}
