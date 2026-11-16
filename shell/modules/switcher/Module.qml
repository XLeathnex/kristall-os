// SPDX-License-Identifier: GPL-3.0-or-later
// The `switcher` module. The app switcher itself (Command-Tab: hold, tab, release; Shift reverses;
// Q quits, H hides the highlighted app) is KWin's own switcher with our layout
// (kwin/tabbox/org.kristall.switcher), because only the compositor sees the key being held and
// released without a round trip: a shell surface would get each Tab through a global shortcut,
// a process start and IPC, and would miss quick taps. This module installs that and answers the
// shell-bus target "switcher" for programs (the assistant, tests) without any UI:
//   next      bring the most recently used other app forward (a quick Command-Tab)
//   previous  bring the least recently used app forward
//   commit    nothing to do (KWin commits on key release)
import QtQuick
import qs.core
import Quickshell
import qs.services

Scope {
    id: switcher
    // app keys, front-most first (by the stacking order of their windows)
    function order() {
        const seen = {};
        const out = [];
        for (let i = Bridge.stacking.length - 1; i >= 0; --i) {
            const w = Bridge.windows[Bridge.stacking[i]];
            if (!AppCatalog.isAppWindow(w) || w.minimized)
                continue;
            const k = AppCatalog.keyForAppId(w.appId);
            if (!seen[k]) {
                seen[k] = true;
                out.push(k);
            }
        }
        return out;
    }
    Connections {
        target: ShellBus
        function onRequested(target, action, arg, output) {
            if (target !== "switcher")
                return;
            const o = switcher.order();
            if (o.length < 2)
                return;
            if (action === "next")
                AppCatalog.activate(o[1]);
            else if (action === "previous")
                AppCatalog.activate(o[o.length - 1]);
        }
    }
    Component.onCompleted: ShellBus.claim("switcher")
}
