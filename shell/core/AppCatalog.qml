// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import qs.services
import "fuzzy.js" as Fuzzy

// Shared by the Dock, Search, Apps and the switcher (shell-apps): every installed app (desktop
// entries, live: a new or removed .desktop file updates it without a restart) joined with the
// Kristall app manifest, matching of windows to apps, the Mac's click semantics (launch, bring
// forward, restore), Hide/Quit, and what the owner actually opens (learned ranking).
// Learned data: $XDG_DATA_HOME/kristall/shell-apps/usage.json, written only after a launch.
Singleton {
    id: root

    // ---- the catalogue -----------------------------------------------------------------------
    property var apps: []              // visible apps, sorted by display name
    property var byKey: ({})           // key (desktop id without .desktop) -> record (visible or not)
    property int revision: 0
    property bool ready: false

    // record: {key, entry, name, nameDe, nameEn, iconName, kristallId, category, flatpak, noDisplay,
    //          comment, prepared}
    function _category(entry, manifest) {
        if (manifest && manifest.category)
            return manifest.category;
        const c = String(entry.categories || "").split(/[;,\s]+/);
        const has = x => c.indexOf(x) >= 0;
        if (has("Game"))
            return "games";
        if (has("Development") || has("IDE"))
            return "developer";
        if (has("Graphics") || has("3DGraphics") || has("Photography"))
            return "graphics";
        if (has("AudioVideo") || has("Audio") || has("Video") || has("Music") || has("Player"))
            return "media";
        if (has("Network") || has("WebBrowser") || has("Email") || has("Chat") || has("InstantMessaging"))
            return "internet";
        if (has("Office") || has("WordProcessor") || has("Spreadsheet") || has("TextEditor"))
            return "productivity";
        if (has("Settings") || has("System") || has("FileManager") || has("PackageManager"))
            return "system";
        return "utilities";
    }
    function _flatpakId(entry) {
        const ex = String(entry.execString || "");
        const m = ex.match(/flatpak['"]?\s+run\s+(.*)$/);
        if (!m)
            return "";
        for (const tok of m[1].split(/\s+/)) {
            if (tok.startsWith("-") || tok === "")
                continue;
            if (/^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2,}$/.test(tok))
                return tok;
            break;
        }
        return "";
    }
    function _list(v) {
        if (!v)
            return [];
        if (typeof v === "string")
            return v.split(/[;,]/).map(s => s.trim()).filter(s => s !== "");
        const out = [];
        for (let i = 0; i < v.length; ++i)
            out.push(String(v[i]));
        return out;
    }

    function rebuild() {
        _iconCache = {};
        const entries = DesktopEntries.applications.values;
        const map = {};
        const visible = [];
        for (const e of entries) {
            if (!e || !e.id)
                continue;
            const key = e.id.replace(/\.desktop$/, "");
            const man = Apps.entry(key);
            const nameDe = man ? man.name.de : "";
            const nameEn = man ? man.name.en : "";
            const name = man ? Strings.pick(man.name) : (e.name || key);
            const kw = _list(e.keywords).join(" ");
            const fields = [
                { text: name, weight: 1.0 },
                { text: nameDe, weight: 1.0 },
                { text: nameEn, weight: 1.0 },
                { text: man ? e.name : "", weight: 0.95 },       // the app's own name ("Dolphin")
                { text: e.genericName, weight: 0.75 },
                { text: kw, weight: 0.7 },
                { text: key.split(".").pop(), weight: 0.6 }
            ];
            const rec = {
                key: key, entry: e, name: name, nameDe: nameDe, nameEn: nameEn,
                iconName: e.icon || "", kristallId: man ? man.id : "", manifest: man,
                category: _category(e, man), flatpak: _flatpakId(e),
                noDisplay: e.noDisplay === true || (man !== null && man.show_in_apps === false),
                comment: e.comment || "", prepared: Fuzzy.prepare(fields)
            };
            map[key] = rec;
            map[key.toLowerCase()] = rec;
            if (!rec.noDisplay)
                visible.push(rec);
        }
        visible.sort((a, b) => a.name.localeCompare(b.name, Strings.lang));
        byKey = map;
        apps = visible;
        _keyCache = {};
        revision++;
        ready = entries.length > 0;
    }
    Connections {
        target: DesktopEntries
        function onApplicationsChanged() { Qt.callLater(root.rebuild); }
    }
    Connections {
        target: Apps
        function onAppsChanged() { Qt.callLater(root.rebuild); }
    }
    Component.onCompleted: rebuild()

    // ---- icons -------------------------------------------------------------------------------
    function iconUrl(nameOrPath) {
        const n = nameOrPath || "";
        if (n.startsWith("/"))
            return "file://" + n;
        if (n !== "" && Quickshell.hasThemeIcon(n))
            return Quickshell.iconPath(n);
        return Quickshell.iconPath("application-x-executable", true) || "";
    }
    // icon URLs looked up once per app (theme lookups are file-system work; Search asks per keystroke)
    property var _iconCache: ({})
    function iconFor(key) {
        const c = _iconCache[key];
        if (c !== undefined)
            return c;
        const r = byKey[key];
        const u = iconUrl(r ? r.iconName : "");
        _iconCache[key] = u;
        return u;
    }

    // ---- windows <-> apps ----------------------------------------------------------------------
    property var _keyCache: ({})
    // window app ids that are another name of a listed app
    readonly property var appAliases: ({ "kdesystemsettings": "systemsettings", "org.kde.systemsettings": "systemsettings" })
    function _program(exec) {
        const first = String(exec || "").trim().split(/\s+/)[0] || "";
        return first.split("/").pop();
    }
    // the app key of a window's app id ("org.kde.dolphin", "firefox", a WM class …)
    function keyForAppId(appId) {
        if (!appId)
            return "";
        const c = _keyCache[appId];
        if (c !== undefined)
            return c;
        let k = "";
        const lower = appId.toLowerCase();
        if (appAliases[lower] && byKey[appAliases[lower]])
            k = appAliases[lower];          // another name of a listed app (checked first)
        else if (byKey[appId])
            k = byKey[appId].key;
        else if (byKey[lower])
            k = byKey[lower].key;
        if (k === "") {
            for (const key in byKey) {
                const r = byKey[key];
                const sc = String(r.entry.startupClass || "").toLowerCase();
                if (sc !== "" && sc === lower) {
                    k = r.key;
                    break;
                }
            }
        }
        if (k === "") {
            const d = DesktopEntries.heuristicLookup(appId);
            if (d && d.id) {
                k = d.id.replace(/\.desktop$/, "");
                // a hidden helper entry of a listed app (e.g. kdesystemsettings.desktop, which System
                // Settings uses when it is opened on one page) belongs to that app: same program
                if (!byKey[k] && d.noDisplay) {
                    const prog = _program(d.execString);
                    for (const key in byKey)
                        if (prog !== "" && _program(byKey[key].entry.execString) === prog) {
                            k = key;
                            break;
                        }
                }
            }
        }
        if (k === "")
            k = "window:" + appId;
        _keyCache[appId] = k;
        return k;
    }

    // app windows the Dock and switcher care about: normal, not skipping the taskbar
    function isAppWindow(w) {
        return w && w.normal && !w.skipTaskbar && (w.type === undefined || w.type === "normal" || w.type === "dialog" && !w.parentId);
    }
    // key -> [windows], in stacking order (bottom first)
    readonly property var running: {
        Bridge.revision;
        const out = {};
        const order = Bridge.stacking;
        const seen = {};
        const add = w => {
            if (!isAppWindow(w) || seen[w.id])
                return;
            seen[w.id] = true;
            const k = keyForAppId(w.appId);
            (out[k] = out[k] || []).push(w);
        };
        for (const id of order)
            add(Bridge.windows[id]);
        for (const id in Bridge.windows)
            add(Bridge.windows[id]);
        return out;
    }
    function windowsOf(key) {
        return running[key] || [];
    }
    function isRunning(key) {
        return (running[key] || []).length > 0;
    }
    readonly property string frontKey: Bridge.frontWindow ? keyForAppId(Bridge.frontWindow.appId) : ""

    // display name and icon for any key (also for windows without a desktop entry)
    function displayName(key) {
        const r = byKey[key];
        if (r)
            return r.name;
        if (key.startsWith("window:"))
            return Apps.displayName(key.substring(7));
        return Apps.displayName(key);
    }
    function iconForKey(key) {
        const r = byKey[key];
        if (r)
            return iconUrl(r.iconName);
        const ws = windowsOf(key);
        return iconUrl(ws.length && ws[0].icon && ws[0].icon !== "wayland" ? ws[0].icon : "");
    }

    // ---- hide (Mac: the app's windows disappear, no minimised tiles) ---------------------------------
    property var hiddenIds: ({})       // window id -> true
    function _setHidden(id, on) {
        const h = Object.assign({}, hiddenIds);
        if (on)
            h[id] = true;
        else
            delete h[id];
        hiddenIds = h;
    }
    Connections {
        target: Bridge
        function onWindowChanged(id, changes) {
            if (changes.minimized === false && root.hiddenIds[id])
                root._setHidden(id, false);
            if (changes.minimized === true)
                root._minimizedAt[id] = Date.now();
        }
        function onWindowRemoved(id) {
            if (root.hiddenIds[id])
                root._setHidden(id, false);
            delete root._minimizedAt[id];
        }
    }
    property var _minimizedAt: ({})
    // the Dock publishes where each app's icon rests (global logical rect): Hide flows there
    property var dockRects: ({})
    function hide(key) {
        const r = dockRects[key];
        for (const w of windowsOf(key)) {
            if (!w.minimized) {
                _setHidden(w.id, true);
                if (r)
                    Bridge.call("window.setIconGeometry", { id: w.id, x: r.x, y: r.y, w: r.w, h: r.h });
                Bridge.call("window.setMinimized", { id: w.id, value: true });
            }
        }
    }
    function hideOthers(key) {
        for (const k in running)
            if (k !== key)
                hide(k);
    }
    function isHidden(key) {
        const ws = windowsOf(key);
        return ws.length > 0 && ws.every(w => w.minimized && hiddenIds[w.id]);
    }
    function quit(key) {
        for (const w of windowsOf(key))
            Bridge.call("window.close", { id: w.id });
    }

    // ---- launching and activating (the Mac's Dock click) ---------------------------------------
    signal launched(string key)
    signal activated(string key)

    function launch(key) {
        const r = byKey[key];
        if (!r)
            return false;
        r.entry.execute();
        noteUse(key, "");
        launched(key);
        return true;
    }
    // Not running → launch. Running → bring all its windows forward (front-most last); hidden →
    // show them again; only minimised windows → restore the most recently minimised one.
    function activate(key) {
        const ws = windowsOf(key);
        if (ws.length === 0)
            return launch(key);
        noteUse(key, "");
        const hidden = ws.filter(w => w.minimized && hiddenIds[w.id]);
        const shown = ws.filter(w => !w.minimized);
        if (hidden.length > 0) {
            for (const w of hidden) {
                _setHidden(w.id, false);
                Bridge.call("window.activate", { id: w.id });
            }
        } else if (shown.length === 0) {
            const last = ws.slice().sort((a, b) => (_minimizedAt[b.id] || 0) - (_minimizedAt[a.id] || 0))[0];
            Bridge.call("window.activate", { id: last.id });
        } else {
            for (const w of shown)        // bottom first: the app's top window ends up active
                Bridge.call("window.activate", { id: w.id });
        }
        activated(key);
        return true;
    }
    function activateWindow(id) {
        const w = Bridge.windows[id];
        if (!w)
            return;
        if (hiddenIds[id])
            _setHidden(id, false);
        Bridge.call("window.activate", { id: id });
    }

    // ---- kept in the Dock (`dock.pinned`; shared by the Dock and the Apps grid) --------------------
    // default = the manifest's Dock order with the Apps tile second (the Mac's Launchpad position)
    readonly property string appsTileId: "kristall:apps"
    readonly property var defaultPinned: {
        const docked = Apps.apps.filter(a => typeof a.dock === "number" && a.show_in_apps !== false)
                                .sort((a, b) => a.dock - b.dock).map(a => a.id);
        docked.splice(Math.min(1, docked.length), 0, appsTileId);
        return docked;
    }
    property var _pinnedOverride: null     // our own write, until the settings file reflects it
    readonly property var _pinnedSetting: Settings.get("dock.pinned", null)
    on_PinnedSettingChanged: _pinnedOverride = null
    readonly property var pinnedIds: {
        const p = _pinnedOverride !== null ? _pinnedOverride : _pinnedSetting;
        return Array.isArray(p) ? p : defaultPinned;
    }
    // stored id → app key ("files" → "org.kde.dolphin"; "desktop:org.kde.kate" → "org.kde.kate")
    function keyOfPinned(id) {
        if (id === appsTileId)
            return "";
        if (id.startsWith("desktop:"))
            return id.substring(8);
        const a = Apps.byId(id);
        return a ? a.desktop_id.replace(/\.desktop$/, "") : id;
    }
    // app key → the id we store (the manifest id when the app is in the manifest)
    function pinIdOf(key) {
        const r = byKey[key];
        if (r && r.kristallId)
            return r.kristallId;
        const m = Apps.entry(key);
        return m ? m.id : "desktop:" + key;
    }
    function isPinned(key) {
        return pinnedIds.some(id => keyOfPinned(id) === key);
    }
    function storePinned(list) {
        _pinnedOverride = list;
        Settings.set("dock.pinned", list);
    }
    function pin(key, index) {
        const list = pinnedIds.filter(id => keyOfPinned(id) !== key);
        const at = index === undefined || index < 0 ? list.length : Math.min(index, list.length);
        list.splice(at, 0, pinIdOf(key));
        storePinned(list);
    }
    function unpin(key) {
        storePinned(pinnedIds.filter(id => keyOfPinned(id) !== key));
    }

    // ---- what the owner opens (ranking) --------------------------------------------------------
    readonly property string usagePath: (Quickshell.env("XDG_DATA_HOME") || (Quickshell.env("HOME") + "/.local/share")) + "/kristall/shell-apps/usage.json"
    property var usage: ({})           // key -> {n: count, t: last ms}
    property var picks: ({})           // normalised query -> {key: count}
    function noteUse(key, queryText) {
        const u = Object.assign({}, usage);
        const old = u[key] || { n: 0, t: 0 };
        u[key] = { n: old.n + 1, t: Date.now() };
        usage = u;
        const q = Fuzzy.norm(queryText || "");
        if (q !== "") {
            const p = Object.assign({}, picks);
            const m = Object.assign({}, p[q] || {});
            m[key] = (m[key] || 0) + 1;
            p[q] = m;
            const ks = Object.keys(p);
            if (ks.length > 400)
                delete p[ks[0]];
            picks = p;
        }
        saveTimer.restart();
    }
    // remember that the owner chose `key` after typing `queryText` (Search learns from it)
    function notePick(key, queryText) {
        const q = Fuzzy.norm(queryText || "");
        if (q === "")
            return;
        const p = Object.assign({}, picks);
        const m = Object.assign({}, p[q] || {});
        m[key] = (m[key] || 0) + 1;
        p[q] = m;
        const ks = Object.keys(p);
        if (ks.length > 400)
            delete p[ks[0]];
        picks = p;
        saveTimer.restart();
    }
    // 0 … ~250: often and recently used apps rank higher
    function usageBoost(key) {
        const u = usage[key];
        if (!u)
            return 0;
        const days = (Date.now() - u.t) / 86400000;
        const recency = days < 1 ? 1 : days < 7 ? 0.8 : days < 30 ? 0.5 : 0.25;
        return Math.min(180, 45 * Math.log2(1 + u.n)) * recency;
    }
    // what the owner chose before after typing this (or a longer text starting with it)
    function pickBoost(key, q) {
        let b = 0;
        const exact = picks[q];
        if (exact && exact[key])
            b = Math.max(b, Math.min(400, 260 + 40 * exact[key]));
        if (b === 0 && q.length >= 1) {
            for (const k in picks)
                if (k.length > q.length && k.startsWith(q) && picks[k][key])
                    b = Math.max(b, 180);
        }
        return b;
    }
    FileView {
        id: usageFile
        path: root.usagePath
        printErrors: false
        atomicWrites: true
        onLoaded: {
            try {
                const d = JSON.parse(text());
                root.usage = d.usage || {};
                root.picks = d.picks || {};
            } catch (e) {
                console.info("shell-apps: usage file unreadable, starting fresh");
            }
        }
    }
    property bool _dirMade: false
    Timer {
        id: saveTimer
        interval: 1500
        onTriggered: {
            if (!root._dirMade) {
                root._dirMade = true;
                Quickshell.execDetached(["mkdir", "-p", root.usagePath.substring(0, root.usagePath.lastIndexOf("/"))]);
                restart();
                return;
            }
            usageFile.setText(JSON.stringify({ schema: 1, usage: root.usage, picks: root.picks }));
        }
    }

    // ---- search ---------------------------------------------------------------------------------
    // [{rec, score}] best first; `limit` results. Synchronous and cheap (pre-normalised entries).
    function search(text, limit) {
        const qq = Fuzzy.query(text);
        if (qq.q === "")
            return [];
        // learned choices for this text, looked up once per keystroke
        const boost = {};
        for (const k in picks) {
            if (k === qq.q) {
                for (const key in picks[k])
                    boost[key] = Math.max(boost[key] || 0, Math.min(400, 260 + 40 * picks[k][key]));
            } else if (k.length > qq.q.length && k.startsWith(qq.q)) {
                for (const key in picks[k])
                    boost[key] = Math.max(boost[key] || 0, 180);
            }
        }
        // with a limit (every keystroke of Search): keep only the best `limit` in a small sorted
        // array — no object per match, no sort of hundreds of hits (≤ 2 ms per keystroke)
        const list = apps;
        if (limit) {
            const top = [];                 // [{rec, score, order}] best first
            let floor = 0;
            for (let i = 0; i < list.length; ++i) {
                const r = list[i];
                const s = Fuzzy.score(r.prepared, qq.q, qq.w, qq.c);
                if (s <= 0)
                    continue;
                const sc = s + (usage[r.key] ? usageBoost(r.key) : 0) + (boost[r.key] || 0);
                if (top.length >= limit && sc <= floor)
                    continue;               // ties keep catalogue order: the earlier one stays
                let k = top.length;
                while (k > 0 && top[k - 1].score < sc)
                    --k;
                top.splice(k, 0, { rec: r, score: sc, order: i });
                if (top.length > limit)
                    top.pop();
                floor = top.length >= limit ? top[top.length - 1].score : 0;
            }
            return top;
        }
        const out = [];
        for (let i = 0; i < list.length; ++i) {
            const r = list[i];
            const s = Fuzzy.score(r.prepared, qq.q, qq.w, qq.c);
            if (s <= 0)
                continue;
            out.push({ rec: r, score: s + (usage[r.key] ? usageBoost(r.key) : 0) + (boost[r.key] || 0), order: i });
        }
        out.sort((a, b) => b.score - a.score || a.order - b.order);
        return out;
    }
}
