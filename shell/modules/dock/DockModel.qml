// SPDX-License-Identifier: GPL-3.0-or-later
// What the Dock shows, in order: kept apps (`dock.pinned`, default = the app manifest's Dock order
// with the Apps tile second, like the Mac's Launchpad/Apps position), running apps that are not
// kept (in the order they started), a separator, minimised windows (unless `dock.minimizeToApp`),
// Downloads and the Trash. Entries: {id, kind: app|apps|sep|window|downloads|trash, key, windowId,
// pinned, running, launching}.
import QtQuick
import qs.core
import Quickshell
import qs.services

QtObject {
    id: model

    readonly property string appsTileId: AppCatalog.appsTileId
    readonly property var pinnedIds: AppCatalog.pinnedIds
    function keyOf(id) { return AppCatalog.keyOfPinned(id); }
    function idOf(key) { return AppCatalog.pinIdOf(key); }
    function isPinned(key) { return AppCatalog.isPinned(key); }
    function pin(key, index) { AppCatalog.pin(key, index); }
    function unpin(key) { AppCatalog.unpin(key); }
    function unpinId(id) { AppCatalog.storePinned(pinnedIds.filter(x => x !== id)); }
    // move the kept item `id` (stored id) to position `index` among the kept items
    function moveTo(id, index) {
        const list = pinnedIds.filter(x => x !== id);
        list.splice(Math.max(0, Math.min(index, list.length)), 0, id);
        AppCatalog.storePinned(list);
    }

    // ---- running, launching ---------------------------------------------------------------------
    property var _runOrder: []
    property var launching: ({})            // key -> ms; apps that bounce until their first window
    readonly property var running: AppCatalog.running
    onRunningChanged: {
        const keys = Object.keys(running);
        let order = _runOrder.filter(k => running[k] !== undefined);
        for (const k of keys)
            if (order.indexOf(k) < 0)
                order.push(k);
        if (JSON.stringify(order) !== JSON.stringify(_runOrder))
            _runOrder = order;
        let changed = false;
        const l = Object.assign({}, launching);
        for (const k in l)
            if (running[k]) {
                delete l[k];
                changed = true;
            }
        if (changed)
            launching = l;
    }
    function noteLaunch(key) {
        if (AppCatalog.isRunning(key))
            return;
        const l = Object.assign({}, launching);
        l[key] = Date.now();
        launching = l;
        launchTimeout.restart();
    }
    property Timer launchTimeout: Timer {
        interval: 15000
        onTriggered: {
            const l = {};
            const now = Date.now();
            for (const k in model.launching)
                if (now - model.launching[k] < 14000)
                    l[k] = model.launching[k];
            model.launching = l;
            if (Object.keys(l).length)
                restart();
        }
    }
    property Connections _launches: Connections {
        target: AppCatalog
        function onLaunched(key) { model.noteLaunch(key); }
    }

    // ---- minimised windows ------------------------------------------------------------------------
    readonly property bool minimizeToApp: Settings.get("dock.minimizeToApp", false) === true
    readonly property var minimized: {
        if (minimizeToApp)
            return [];
        const out = [];
        for (const k in running)
            for (const w of running[k])
                if (w.minimized && !AppCatalog.hiddenIds[w.id])
                    out.push(w);
        const at = AppCatalog._minimizedAt;
        out.sort((a, b) => (at[a.id] || 0) - (at[b.id] || 0));
        return out;
    }

    // ---- the list ---------------------------------------------------------------------------------
    readonly property var entries: {
        AppCatalog.revision;
        const out = [];
        const seen = {};
        for (const id of pinnedIds) {
            if (id === appsTileId) {
                out.push({ id: "apps", kind: "apps", key: "", pinned: true, pinId: id });
                continue;
            }
            const key = keyOf(id);
            if (seen[key])
                continue;
            const installed = AppCatalog.byKey[key] !== undefined;
            if (!installed && !running[key])
                continue;       // not installed (yet): not shown (apps contract)
            seen[key] = true;
            out.push({ id: "app:" + key, kind: "app", key: key, pinned: true, pinId: id });
        }
        const extra = _runOrder.concat(Object.keys(launching).filter(k => _runOrder.indexOf(k) < 0));
        for (const key of extra) {
            if (seen[key])
                continue;
            seen[key] = true;
            out.push({ id: "app:" + key, kind: "app", key: key, pinned: false, pinId: "" });
        }
        out.push({ id: "sep", kind: "sep", key: "" });
        for (const w of minimized)
            out.push({ id: "win:" + w.id, kind: "window", key: AppCatalog.keyForAppId(w.appId), windowId: w.id });
        out.push({ id: "downloads", kind: "downloads", key: "" });
        out.push({ id: "trash", kind: "trash", key: "" });
        return out;
    }
}
