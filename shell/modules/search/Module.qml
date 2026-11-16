// SPDX-License-Identifier: GPL-3.0-or-later
// The `search` module (docs/contracts/shell.md §2): "Search or Ask", summoned by the global
// shortcut (Meta+Space, the Mac's Command-Space; kglobalaccel/org.kristall.search.desktop) or a
// request. Requests (ShellBus target "search"): toggle, show (query), hide. It opens on the
// requested output, else where the front window is, else the first screen. Nothing exists while
// it is closed. The Ask row hands the text to the `assistant` module (request "assistant ask
// <text>") and is shown only while that module has claimed its target.
import QtQuick
import Quickshell
import qs.core
import qs.services

Scope {
    id: searchModule
    property string output: ""            // "" = closed
    property string initialQuery: ""
    property int serial: 0
    property string lastActivated: ""

    function _out(o) {
        if (o && Quickshell.screens.some(s => s.name === o))
            return o;
        const f = Bridge.frontWindow;
        if (f && Quickshell.screens.some(s => s.name === f.output))
            return f.output;
        return Quickshell.screens.length ? Quickshell.screens[0].name : "";
    }
    function show(o, q) {
        Menus.close("replaced");
        initialQuery = q || "";
        serial++;
        output = _out(o);
    }
    function hide() {
        output = "";
    }
    onOutputChanged: {
        ShellBus.setOpen("search", "", false);
        if (output !== "")
            ShellBus.setOpen("search", output, true);
    }

    Connections {
        target: ShellBus
        function onRequested(target, action, arg, o) {
            if (target === "shell" && action === "close-menus") {
                searchModule.hide();
                return;
            }
            if (target === "apps" || target === "panels" || target === "switcher") {
                searchModule.hide();      // another popover opens: Search steps aside
                return;
            }
            if (target !== "search")
                return;
            if (action === "toggle")
                searchModule.output !== "" ? searchModule.hide() : searchModule.show(o, "");
            else if (action === "show")
                searchModule.show(o, arg);
            else if (action === "hide")
                searchModule.hide();
        }
    }
    Component.onCompleted: ShellBus.claim("search")

    LazyLoader {
        id: loader
        active: searchModule.output !== ""
        SearchWindow {
            screen: Quickshell.screens.find(s => s.name === searchModule.output) || Quickshell.screens[0]
            initialQuery: searchModule.initialQuery
            onCloseRequested: searchModule.hide()
            onActivated: what => searchModule.lastActivated = what
        }
    }

    LazyLoader {
        active: Quickshell.env("KRISTALL_SHELL_TEST") === "1"
        SearchTestHooks { module: searchModule; window: loader.item }
    }
}
