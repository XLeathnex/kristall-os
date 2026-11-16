// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC target "appstest" (KRISTALL_SHELL_TEST=1).
import QtQuick
import Quickshell
import Quickshell.Io
import "../dock/common"

Scope {
    id: hooks
    property var module: null
    property var window: null
    IpcHandler {
        target: "appstest"
        function state(): string {
            const w = hooks.window;
            return JSON.stringify({
                open: hooks.module.output !== "", lastLaunched: hooks.module.lastLaunched, lastHandOff: hooks.module.lastHandOff,
                category: w ? w.category : "", categories: w ? w.categories : [], filter: w ? w.filterText : "", current: w ? w.current : -1,
                shown: w ? w.shownApps.map(r => ({ key: r.key, name: r.name, category: r.category, flatpak: r.flatpak })) : [],
                catalog: AppCatalog.apps.map(r => r.key), pinned: AppCatalog.pinnedIds
            });
        }
        function openMenu(key: string): string {
            return hooks.window && hooks.window.openMenuForKey(key) ? "ok" : "no";
        }
        function setCategory(c: string): string {
            if (hooks.window)
                hooks.window.category = c;
            return "ok";
        }
    }
}
