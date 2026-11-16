// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import qs.core
import qs.services
import "common"

// Context menus of the Dock (macOS 26 arrangement): an app's windows, its desktop actions,
// Options ▸ (Keep in Dock, Show in Files), Show All Windows, Hide, Quit / Open; Downloads (recent
// items, Open in Files); Trash (Open, Empty Trash …); the Dock itself (magnification, size,
// automatic hiding — the owner's Dock settings, no terminal needed).
Singleton {
    id: menus

    function forEntry(e, dock) {
        switch (e.kind) {
        case "app": return appMenu(e, dock);
        case "apps": return appsTileMenu(e, dock);
        case "window": return windowMenu(e, dock);
        case "downloads": return downloadsMenu(dock);
        case "trash": return trashMenu(dock);
        }
        return [];
    }

    function keepItem(e, dock) {
        const kept = e.pinned === true;
        return { label: Strings.t("dock.keepInDock"), toggle: "checkmark", checked: kept,
                 action: () => kept ? dock.dockModel.unpin(e.key) : dock.dockModel.pin(e.key) };
    }

    function appMenu(e, dock) {
        const key = e.key;
        const rec = AppCatalog.byKey[key];
        const ws = AppCatalog.windowsOf(key);
        const items = [];
        // the app's windows (◆ marks minimised ones, a check the front window — as on the Mac)
        for (const w of ws) {
            const front = Bridge.frontId === w.id;
            items.push({ label: (w.minimized ? "◆ " : "") + (w.title || AppCatalog.displayName(key)), toggle: front ? "checkmark" : "", checked: front,
                         action: () => AppCatalog.activateWindow(w.id) });
        }
        if (ws.length)
            items.push({ type: "separator" });
        // the app's own quick actions (desktop entry actions: "New Private Window" …)
        const acts = rec && rec.entry.actions ? rec.entry.actions : [];
        let nActs = 0;
        for (let i = 0; i < acts.length && nActs < 8; ++i) {
            const a = acts[i];
            if (!a || !a.name)
                continue;
            items.push({ label: a.name, action: () => { a.execute(); AppCatalog.noteUse(key, ""); } });
            nActs++;
        }
        if (nActs)
            items.push({ type: "separator" });
        const options = [];
        if (rec)
            options.push(keepItem(e, dock));
        if (rec)
            options.push({ label: Strings.t("dock.showInFiles"), action: () => menus.revealApp(rec) });
        if (options.length)
            items.push({ label: Strings.t("dock.options"), children: options });
        if (ws.length) {
            items.push({ type: "separator" });
            items.push({ label: Strings.t("dock.showAllWindows"), action: () => Bridge.call("effect.toggle", { name: "windowview" }) });
            const hidden = AppCatalog.isHidden(key);
            items.push({ label: hidden ? Strings.t("dock.unhide") : Strings.t("dock.hide"),
                         action: () => hidden ? AppCatalog.activate(key) : AppCatalog.hide(key) });
            items.push({ label: Strings.t("dock.quit"), action: () => AppCatalog.quit(key) });
        } else if (rec) {
            items.push({ type: "separator" });
            items.push({ label: Strings.t("dock.open"), action: () => AppCatalog.launch(key) });
        }
        return items;
    }

    function appsTileMenu(e, dock) {
        return [
            { label: Strings.t("dock.open"), action: () => ShellBus.request("apps", "toggle", "", dock.screenName) },
            { type: "separator" },
            { label: Strings.t("dock.options"), children: [
                { label: Strings.t("dock.keepInDock"), toggle: "checkmark", checked: true, action: () => dock.dockModel.unpinId(e.pinId) }
            ] }
        ];
    }

    function windowMenu(e, dock) {
        const w = Bridge.windows[e.windowId];
        const items = [];
        if (w)
            items.push({ type: "header", label: w.title || AppCatalog.displayName(e.key) });
        items.push({ label: Strings.t("dock.restore"), action: () => AppCatalog.activateWindow(e.windowId) });
        if (w && w.closeable !== false)
            items.push({ label: Strings.t("dock.closeWindow"), action: () => Bridge.call("window.close", { id: e.windowId }) });
        return items;
    }

    function downloadsMenu(dock) {
        const items = [];
        const recent = dock.places.recentDownloads(10);
        if (recent.length) {
            items.push({ type: "header", label: Strings.t("dock.recentDownloads") });
            for (const r of recent)
                items.push({ label: r.name, action: () => dock.places.open(r.path) });
            items.push({ type: "separator" });
        }
        items.push({ label: Strings.t("dock.openInFiles"), action: () => dock.places.open(dock.places.downloads) });
        return items;
    }

    function trashMenu(dock) {
        return [
            { label: Strings.t("dock.open"), action: () => dock.places.openTrash() },
            { type: "separator" },
            { label: Strings.t("dock.emptyTrash") + Strings.t("common.ellipsis"), enabled: dock.places.trashFull,
              action: () => dock.emptyTrashRequested() }
        ];
    }

    // right-click on the Dock's background or separator
    function dockOptions(dock) {
        const s = dock.tileSize;
        const size = (label, v) => ({ label: label, toggle: "radio", checked: Math.abs(s - v) < 3, action: () => Settings.set("dock.size", v) });
        const mag = Settings.get("dock.magnifiedSize", 76) / Math.max(1, s);
        const strength = (label, f) => ({ label: label, toggle: "radio", checked: dock.magnifyOn && Math.abs(mag - f) < 0.12,
                                          action: () => { Settings.set("dock.magnification", true); Settings.set("dock.magnifiedSize", Math.round(s * f)); } });
        return [
            { label: dock.magnifyOn ? Strings.t("dock.magnificationOff") : Strings.t("dock.magnificationOn"),
              action: () => Settings.set("dock.magnification", !dock.magnifyOn) },
            { label: Strings.t("dock.magnification"), children: [
                strength(Strings.t("dock.strength.light"), 1.3), strength(Strings.t("dock.strength.medium"), 1.6), strength(Strings.t("dock.strength.strong"), 2.0)
            ] },
            { label: Strings.t("dock.size"), children: [
                size(Strings.t("dock.size.small"), 40), size(Strings.t("dock.size.medium"), 48), size(Strings.t("dock.size.large"), 60)
            ] },
            { type: "separator" },
            { label: dock.autoHide ? Strings.t("dock.autoHideOff") : Strings.t("dock.autoHideOn"),
              action: () => Settings.set("dock.autoHide", !dock.autoHide) },
            { label: Strings.t("dock.minimizeToApp"), toggle: "checkmark", checked: dock.dockModel.minimizeToApp,
              action: () => Settings.set("dock.minimizeToApp", !dock.dockModel.minimizeToApp) }
        ];
    }

    // Files with the app's desktop file selected (the nearest thing to the Mac's app bundle)
    function revealApp(rec) {
        const home = Quickshell.env("HOME");
        const dirs = [(Quickshell.env("XDG_DATA_HOME") || home + "/.local/share") + "/applications",
                      home + "/.local/share/flatpak/exports/share/applications", "/var/lib/flatpak/exports/share/applications",
                      "/usr/share/applications"];
        const script = 'for d in "$@"; do f="$d/' + rec.key.replace(/[^A-Za-z0-9._-]/g, "") + '.desktop"; '
            + 'if [ -e "$f" ]; then exec gdbus call --session --dest org.freedesktop.FileManager1 --object-path /org/freedesktop/FileManager1 '
            + '--method org.freedesktop.FileManager1.ShowItems "[\'file://$f\']" ""; fi; done';
        Quickshell.execDetached(["sh", "-c", script, "reveal"].concat(dirs));
    }
}
