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
        // Wine/Proton windows (Roblox Studio through Vinegar, …) carry the program file as app id
        // ("notepad.exe", "RobloxStudioBeta.exe"): the program, not "Exe"
        const id = String(appId || "").replace(/\.exe$/i, "");
        const tail = id.split(".").pop();
        return tail ? tail.charAt(0).toUpperCase() + tail.slice(1) : "";
    }

    // A window title as the owner should read it: the app's own product name that Qt appends
    // ("Home — Dolphin", "Unbenannt — KWrite") becomes our name ("Home — Dateien"); a title that
    // is only the product name becomes our name. Product names: the manifest's product_names
    // (apps.md). Everything else is returned unchanged.
    readonly property string _titleSep: " \u2014 "
    function windowTitle(title) {
        const t = String(title || "");
        if (t === "")
            return t;
        const cut = t.lastIndexOf(_titleSep);
        const tail = cut >= 0 ? t.substring(cut + _titleSep.length) : t;
        const a = _byProduct[tail];
        if (!a)
            return t;
        const ours = Strings.pick(a.name);
        return cut >= 0 ? t.substring(0, cut) + _titleSep + ours : ours;
    }
    property var _byProduct: ({})      // "Dolphin" -> entry

    // Apps are started outside the shell's own systemd unit: `kstart --application` (KIO) puts each
    // into its own app-<id>@….service, as Plasma does. Started as the shell's children they lived in
    // kristall-shell.service, so a shell crash or restart (Restart=always) killed every app the owner
    // had opened from the Dock, Apps or Search, with their unsaved work (integration walkthrough).
    readonly property string _scoped: 'id="$1"; command -v kstart >/dev/null && exec kstart --application "$id"; '
        + 'exec systemd-run --user --scope --slice=app.slice --collect --quiet -- gtk-launch "$id"'
    function launchDesktopId(desktopId) {
        // case kept (Flatpak ids such as org.vinegarhq.Sober are case-sensitive file names); no
        // ".desktop" suffix: kstart 6.8 then waits instead of returning
        Quickshell.execDetached(["sh", "-c", _scoped, "kristall-launch", String(desktopId || "").replace(/\.desktop$/, "")]);
    }
    // a desktop action (e.g. "New Window") or any other command, in its own transient scope
    function runScoped(command) {
        if (!command || command.length === 0)
            return;
        Quickshell.execDetached(["systemd-run", "--user", "--scope", "--slice=app.slice", "--collect", "--quiet", "--"].concat(command));
    }
    function launch(appIdOrDesktopId) {
        const d = desktopEntry(_norm(appIdOrDesktopId));
        launchDesktopId(d && d.id ? d.id : appIdOrDesktopId);
        return d !== null && d !== undefined;
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
                const products = {};
                for (const a of root.apps) {
                    map[root._norm(a.desktop_id)] = a;
                    for (const p of (a.product_names || []))
                        products[p] = a;
                }
                root._byDesktop = map;
                root._byProduct = products;
            } catch (e) {
                console.warn("apps: invalid manifest", root.manifestPath, e);
            }
        }
    }
}
