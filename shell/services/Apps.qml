// SPDX-License-Identifier: GPL-3.0-or-later
// The default-apps manifest (docs/contracts/apps.md) and app identity: display names for
// window app ids, desktop entries, launching. The manifest is static (/usr), read once.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    readonly property string manifestPath: Quickshell.env("KRISTALL_APPS_MANIFEST") || "/usr/share/kristall/apps/apps.json"
    property var apps: []              // manifest entries (schema 1)
    property var _byDesktop: ({})      // "org.kde.dolphin" -> entry

    function _norm(id) {
        return (id || "").replace(/\.desktop$/, "").toLowerCase();
    }

    // manifest entry for an app id / desktop id, or null
    function entry(appId) {
        return _byDesktop[_norm(appId)] || null;
    }

    function byId(kristallId) {
        for (const a of apps)
            if (a.id === kristallId)
                return a;
        return null;
    }

    function desktopEntry(appId) {
        if (!appId)
            return null;
        return DesktopEntries.byId(appId) || DesktopEntries.heuristicLookup(appId);
    }

    // Name shown for an app: our manifest name in the system language, else the desktop entry's
    // Name, else the app id made readable.
    function displayName(appId) {
        const e = entry(appId);
        if (e)
            return Strings.pick(e.name);
        const d = desktopEntry(appId);
        if (d && d.name)
            return d.name;
        const tail = (appId || "").split(".").pop();
        return tail ? tail.charAt(0).toUpperCase() + tail.slice(1) : "";
    }

    function launch(appIdOrDesktopId) {
        const d = desktopEntry(_norm(appIdOrDesktopId));
        if (d) {
            d.execute();
            return true;
        }
        Quickshell.execDetached(["gtk-launch", _norm(appIdOrDesktopId)]);
        return false;
    }

    function launchKristall(kristallId) {
        const a = byId(kristallId);
        return a ? launch(a.desktop_id) : false;
    }

    FileView {
        path: root.manifestPath
        printErrors: false
        onLoaded: {
            try {
                const m = JSON.parse(text());
                root.apps = m.apps || [];
                const map = {};
                for (const a of root.apps)
                    map[root._norm(a.desktop_id)] = a;
                root._byDesktop = map;
            } catch (e) {
                console.warn("apps: invalid manifest", root.manifestPath, e);
            }
        }
    }
}
