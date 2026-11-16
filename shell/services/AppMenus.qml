// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell


// Application menus over DBusMenu (com.canonical.dbusmenu), mirrored by the helper as JSON trees.
// track(key, service, path) starts mirroring (the bar uses key "app" for the front window);
// trees[key] is the latest layout: {id, children:[{id, type, label, enabled, toggle, checked,
// shortcut:[[mods…,key]], children?}]}. Updates arrive as the app changes its menus.
Singleton {
    id: root

    property var trees: ({})
    property var sources: ({})       // key -> "service path"
    property int revision: 0
    // the front window's menu is mirrored under the key "app" (the bar shows it)
    readonly property var frontMenu: Bridge.frontWindow && Bridge.frontWindow.menu ? Bridge.frontWindow.menu : null
    onFrontMenuChanged: {
        if (frontMenu && frontMenu.service && frontMenu.path)
            track("app", frontMenu.service, frontMenu.path);
        else
            untrack("app");
    }

    signal layoutChanged(string key)
    signal failed(string key, string error)

    function track(key, service, path) {
        const id = service + " " + path;
        if (sources[key] === id)
            return;
        const s = Object.assign({}, sources);
        s[key] = id;
        sources = s;
        const t = Object.assign({}, trees);
        delete t[key];
        trees = t;
        revision++;
        Helper.request("menu.open", { key: key, service: service, path: path });
    }

    function untrack(key) {
        if (!sources[key])
            return;
        const s = Object.assign({}, sources);
        delete s[key];
        sources = s;
        const t = Object.assign({}, trees);
        delete t[key];
        trees = t;
        revision++;
        Helper.request("menu.close", { key: key });
    }

    function node(key, id) {
        const root_ = trees[key];
        if (!root_)
            return null;
        if (!id)
            return root_;
        const stack = [root_];
        while (stack.length) {
            const n = stack.pop();
            if (n.id === id)
                return n;
            for (const c of n.children || [])
                stack.push(c);
        }
        return null;
    }

    // find the first item whose label matches `re` (e.g. the app's own "About …" entry)
    function findItem(key, re) {
        const r = trees[key];
        if (!r)
            return null;
        const stack = (r.children || []).slice().reverse();
        while (stack.length) {
            const n = stack.pop();
            if (n.type === "item" && !n.children && re.test(n.label || ""))
                return n;
            for (const c of (n.children || []).slice().reverse())
                stack.push(c);
        }
        return null;
    }

    function activate(key, id) { Helper.request("menu.event", { key: key, item: id, kind: "clicked" }); }
    function aboutToShow(key, id) {
        Helper.request("menu.aboutToShow", { key: key, item: id });
        Helper.request("menu.event", { key: key, item: id, kind: "opened" });
    }
    function hidden(key, id) { Helper.request("menu.event", { key: key, item: id, kind: "closed" }); }

    Connections {
        target: Helper
        function onEvent(ev) {
            if (ev.event === "menu.layout" && root.sources[ev.key]) {
                const t = Object.assign({}, root.trees);
                t[ev.key] = ev.menu;
                root.trees = t;
                root.revision++;
                root.layoutChanged(ev.key);
            } else if (ev.event === "menu.error" && root.sources[ev.key]) {
                root.failed(ev.key, ev.error);
            }
        }
        function onReadyChanged() {
            // helper restarted: re-open every tracked menu
            if (!Helper.ready)
                return;
            for (const key in root.sources) {
                const parts = root.sources[key].split(" ");
                Helper.request("menu.open", { key: key, service: parts[0], path: parts[1] });
            }
        }
    }
}
