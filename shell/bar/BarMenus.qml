// SPDX-License-Identifier: GPL-3.0-or-later
// Contents of the menus the bar authors itself: our mark's menu, the app-name menu, the minimal
// menus for apps without exported menus, and the battery, Wi-Fi and sound menus.
pragma Singleton
import QtQuick
import Quickshell
import qs.core
import qs.services

Singleton {
    id: root

    readonly property string ellipsis: Strings.t("common.ellipsis")   // "…" (en), " …" (de: Apple's German style)

    // ---- the mark (top-left) -------------------------------------------------------------------
    function markMenu() {
        const store = Apps.byId("app-center");
        const items = [
            { label: Strings.t("mark.about"), action: () => Session.aboutThisComputer() },
            { type: "separator" },
            { label: Strings.t("mark.settings") + ellipsis, action: () => Session.openSystemSettings() },
            { label: (store ? Strings.pick(store.name) : Strings.t("mark.appStore")) + ellipsis,
              action: () => store ? Apps.launch(store.desktop_id) : Apps.launch("io.github.kolunmi.Bazaar") },
            { type: "separator" }
        ];
        if (Updates.restartRequired) {
            items.push({ label: Strings.t(Updates.state === "rollback-queued" ? "mark.restartRollback" : "mark.restartUpdate") + ellipsis,
                         action: () => Session.restartToUpdate() });
            items.push({ type: "separator" });
        }
        items.push({ label: Strings.t("mark.sleep"), action: () => Session.sleep() });
        items.push({ label: Strings.t("mark.restart") + ellipsis, action: () => Session.restart() });
        items.push({ label: Strings.t("mark.shutdown") + ellipsis, action: () => Session.shutDown() });
        items.push({ type: "separator" });
        items.push({ label: Strings.t("mark.lock"), shortcut: Theme.shortcutText([["Super", "L"]]), action: () => Session.lock() });
        items.push({ label: Strings.t("mark.logout", { user: Session.userName }) + ellipsis, action: () => Session.logOut() });
        return items;
    }

    // ---- the front app's name menu ---------------------------------------------------------------
    function _appWindows(front) {
        return front ? Bridge.windowsOfApp(front.appId) : [];
    }
    function appNameMenu(front, name) {
        if (!front) {
            return [
                { label: Strings.t("mark.about"), action: () => Session.aboutThisComputer() },
                { type: "separator" },
                { label: Strings.t("mark.settings") + ellipsis, action: () => Session.openSystemSettings() }
            ];
        }
        const about = AppMenus.findItem("app", /^(about|über)\b/i);
        const prefs = AppMenus.findItem("app", /^(settings|preferences|einstellungen|configure|konfigurieren)/i);
        const quit = AppMenus.findItem("app", /^(quit|beenden|exit)\b/i);
        const items = [];
        if (about)
            items.push({ label: Strings.t("app.about", { app: name }), action: () => AppMenus.activate("app", about.id) });
        if (prefs) {
            items.push({ type: "separator" });
            items.push({ label: Strings.t("app.settings") + ellipsis, shortcut: Theme.shortcutText(prefs.shortcut), action: () => AppMenus.activate("app", prefs.id) });
        }
        items.push({ type: "separator" });
        items.push({ label: Strings.t("app.hide", { app: name }), action: () => {
            for (const w of root._appWindows(front))
                Bridge.call("window.setMinimized", { id: w.id, value: true });
        } });
        items.push({ label: Strings.t("app.hideOthers"), action: () => {
            for (const id in Bridge.windows) {
                const w = Bridge.windows[id];
                if (w.normal && w.appId !== front.appId && !w.minimized)
                    Bridge.call("window.setMinimized", { id: w.id, value: true });
            }
        } });
        items.push({ label: Strings.t("app.showAll"), action: () => {
            for (const id in Bridge.windows)
                if (Bridge.windows[id].minimized)
                    Bridge.call("window.setMinimized", { id: id, value: false });
        } });
        items.push({ type: "separator" });
        items.push({ label: Strings.t("app.quit", { app: name }), shortcut: quit ? Theme.shortcutText(quit.shortcut) : "",
                     action: () => {
                         if (quit)
                             AppMenus.activate("app", quit.id);
                         else
                             for (const w of root._appWindows(front))
                                 Bridge.call("window.close", { id: w.id });
                     } });
        return items;
    }

    // ---- titles we add: File/Window for apps without menus, Go on the desktop, Window always ------
    function extraTitles(front, appTitles) {
        const out = [];
        if (!front) {
            out.push({ id: "desktop-file", label: Strings.t("menu.file") });
            out.push({ id: "desktop-go", label: Strings.t("menu.go") });
            out.push({ id: "window", label: Strings.t("menu.window") });
            return out;
        }
        if (appTitles.length === 0)
            out.push({ id: "file", label: Strings.t("menu.file") });
        const hasWindow = appTitles.some(t => /^(window|fenster)$/i.test(t.label));
        if (!hasWindow)
            out.push({ id: "window", label: Strings.t("menu.window") });
        return out;
    }

    function _home(sub) {
        return Quickshell.env("HOME") + (sub ? "/" + sub : "");
    }
    function _openPath(p) {
        Quickshell.execDetached(["xdg-open", p]);
    }
    function _xdgDir(name, fallback) {
        // XDG user dirs are usually localised ("Dokumente"); the files app resolves them, we pass
        // the names from user-dirs.dirs when the environment has them
        return Quickshell.env("XDG_" + name + "_DIR") || _home(fallback);
    }

    function extraMenu(id, front) {
        const w = front;
        switch (id) {
        case "desktop-file":
            return [{ label: Strings.t("menu.newFilesWindow"), shortcut: Theme.shortcutText([["Super", "N"]]), action: () => Apps.launchKristall("files") }];
        case "desktop-go":
            return [
                { label: Strings.t("go.home"), action: () => _openPath(_home()) },
                { label: Strings.t("go.desktop"), action: () => _openPath(_xdgDir("DESKTOP", "Desktop")) },
                { label: Strings.t("go.documents"), action: () => _openPath(_xdgDir("DOCUMENTS", "Documents")) },
                { label: Strings.t("go.downloads"), action: () => _openPath(_xdgDir("DOWNLOAD", "Downloads")) }
            ];
        case "file":
            return [{ label: Strings.t("menu.closeWindow"), enabled: !!w && w.closeable !== false,
                      action: () => Bridge.call("window.close", { id: w.id }) }];
        case "window": {
            const items = [
                { label: Strings.t("window.minimize"), enabled: !!w && w.minimizable !== false,
                  action: () => Bridge.call("window.setMinimized", { id: w.id, value: true }) },
                { label: Strings.t("window.zoom"), enabled: !!w && w.maximizable !== false,
                  action: () => Bridge.call("window.setMaximized", { id: w.id, value: !w.maximized }) },
                { label: Strings.t(w && w.fullscreen ? "window.exitFullScreen" : "window.fullScreen"), enabled: !!w,
                  action: () => Bridge.call("window.setFullscreen", { id: w.id, value: !w.fullscreen }) }
            ];
            const wins = w ? Bridge.windowsOfApp(w.appId) : [];
            if (wins.length) {
                items.push({ type: "separator" });
                for (const x of wins)
                    items.push({ label: x.title || Apps.displayName(x.appId), toggle: "checkmark", checked: x.id === Bridge.frontId,
                                 action: () => Bridge.call("window.activate", { id: x.id }) });
            }
            return items;
        }
        }
        return [];
    }

    // ---- status menus ----------------------------------------------------------------------------
    function batteryMenu() {
        const items = [
            { type: "custom", component: headerRow, height: 30, width: 240, title: Strings.t("battery.title"), detail: Power.percent + " %" },
            { label: Strings.t(Power.onBattery ? "battery.sourceBattery" : "battery.sourceAdapter"), enabled: false }
        ];
        const secs = Power.onBattery ? Power.timeToEmpty : Power.timeToFull;
        if (secs > 0) {
            const h = Math.floor(secs / 3600), m = Math.round((secs % 3600) / 60);
            items.push({ label: Strings.t(Power.onBattery ? "battery.remaining" : "battery.untilFull", { h: h, m: String(m).padStart(2, "0") }), enabled: false });
        }
        items.push({ type: "separator" });
        items.push({ type: "header", label: Strings.t("power.modeTitle") });
        for (const m of Power.modes)
            items.push({ label: Power.modeName(m), toggle: "radio", checked: Power.mode === m,
                         enabled: m !== "performance" || Power.hasPerformance, action: () => Power.setMode(m) });
        items.push({ type: "separator" });
        items.push({ label: Strings.t("battery.settings") + ellipsis, action: () => Session.openSystemSettings("kcm_powerdevilprofilesconfig") });
        return items;
    }

    function wifiMenu() {
        const items = [{ type: "custom", component: wifiHeader, height: 32, width: 250 }];
        if (Network.wifiEnabled) {
            if (Network.wifiConnected) {
                items.push({ type: "separator" });
                items.push({ type: "header", label: Strings.t("wifi.known") });
                items.push({ label: Network.wifiName, toggle: "checkmark", checked: true, enabled: true, action: () => Session.openSystemSettings("kcm_networkmanagement") });
            } else {
                items.push({ label: Strings.t("wifi.notConnected"), enabled: false });
            }
        }
        items.push({ type: "separator" });
        items.push({ label: Strings.t("wifi.settings") + ellipsis, action: () => Session.openSystemSettings("kcm_networkmanagement") });
        return items;
    }

    function soundMenu() {
        const items = [
            { type: "header", label: Strings.t("sound.title") },
            { type: "custom", component: volumeRow, height: 40, width: 260 }
        ];
        items.push({ type: "separator" });
        items.push({ type: "header", label: Strings.t("sound.output") });
        if (Audio.available)
            items.push({ label: Audio.deviceName, toggle: "checkmark", checked: true, action: () => {} });
        else
            items.push({ label: Strings.t("sound.noOutput"), enabled: false });
        items.push({ type: "separator" });
        items.push({ label: Strings.t("sound.settings") + ellipsis, action: () => Session.openSystemSettings("kcm_pulseaudio") });
        return items;
    }

    // ---- custom rows (the Loader that hosts them carries menuScheme / closeMenu / entry) -----------
    property Component headerRow: Component {
        Item {
            readonly property var entry: parent ? parent.parent.entry : ({})
            readonly property string scheme: parent ? parent.menuScheme : Theme.scheme
            KText {
                x: 14
                anchors.verticalCenter: parent.verticalCenter
                text: parent.entry.title || ""
                textStyle: "menu"
                emphasized: true
                scheme: parent.scheme
            }
            KText {
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: parent.entry.detail || ""
                textStyle: "menu"
                level: "secondaryLabel"
                tabular: true
                scheme: parent.scheme
            }
        }
    }
    property Component wifiHeader: Component {
        Item {
            readonly property string scheme: parent ? parent.menuScheme : Theme.scheme
            KText {
                x: 14
                anchors.verticalCenter: parent.verticalCenter
                text: Strings.t("wifi.title")
                textStyle: "menu"
                emphasized: true
                scheme: parent.scheme
            }
            KToggle {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                checked: Network.wifiEnabled
                label: Strings.t("wifi.title")
                scheme: parent.scheme
                onToggled: on => Network.setWifiEnabled(on)
            }
        }
    }
    property Component volumeRow: Component {
        Item {
            readonly property string scheme: parent ? parent.menuScheme : Theme.scheme
            KCapsuleSlider {
                x: 14
                width: parent.width - 28
                anchors.verticalCenter: parent.verticalCenter
                icon: "fill/speaker-simple-high"
                label: Strings.t("sound.volume")
                scheme: parent.scheme
                value: Audio.volume
                enabled: Audio.available
                onMoved: v => Audio.setVolume(v)
            }
        }
    }
}
