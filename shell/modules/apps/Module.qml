// SPDX-License-Identifier: GPL-3.0-or-later
// The `apps` module (docs/contracts/shell.md §2): the Apps grid, opened from the Dock's Apps tile,
// the global shortcut (kglobalaccel/org.kristall.apps.desktop) or a request. Requests (ShellBus
// target "apps"): toggle, show, hide. Opens on the requested output, else the front window's,
// else the first screen. Nothing exists while it is closed.
import QtQuick
import Quickshell
import qs.core
import qs.services

Scope {
    id: appsModule
    property string output: ""
    property string lastLaunched: ""
    property string lastHandOff: ""

    function _out(o) {
        if (o && Quickshell.screens.some(s => s.name === o))
            return o;
        const f = Bridge.frontWindow;
        if (f && Quickshell.screens.some(s => s.name === f.output))
            return f.output;
        return Quickshell.screens.length ? Quickshell.screens[0].name : "";
    }
    function show(o) {
        Menus.close("replaced");
        output = _out(o);
    }
    function hide() {
        output = "";
    }
    onOutputChanged: {
        ShellBus.setOpen("apps", "", false);
        if (output !== "")
            ShellBus.setOpen("apps", output, true);
    }
    Connections {
        target: ShellBus
        function onRequested(target, action, arg, o) {
            if (target === "shell" && action === "close-menus") {
                appsModule.hide();
                return;
            }
            if (target === "search" || target === "panels" || target === "switcher") {
                appsModule.hide();
                return;
            }
            if (target !== "apps")
                return;
            if (action === "toggle")
                appsModule.output !== "" ? appsModule.hide() : appsModule.show(o);
            else if (action === "show")
                appsModule.show(o);
            else if (action === "hide")
                appsModule.hide();
        }
    }
    Component.onCompleted: ShellBus.claim("apps")

    LazyLoader {
        id: loader
        active: appsModule.output !== ""
        AppsWindow {
            screen: Quickshell.screens.find(s => s.name === appsModule.output) || Quickshell.screens[0]
            onCloseRequested: { appsModule.lastHandOff = lastHandOff; appsModule.hide(); }
            onLaunched: key => appsModule.lastLaunched = key
        }
    }
    LazyLoader {
        active: Quickshell.env("KRISTALL_SHELL_TEST") === "1"
        AppsTestHooks { module: appsModule; window: loader.item }
    }
}
