// SPDX-License-Identifier: GPL-3.0-or-later
// The shell's internal request bus. `kristall-shellctl <target> <action> [arg]` and the bar's
// buttons end up here; modules connect to `requested` and act on their own target.
// Targets reserved: shell, bar, panels, dock, search, apps, switcher, assistant, setup, gallery.
// See docs/contracts/shell.md §5.
pragma Singleton
import QtQuick
import Quickshell

Singleton {
    id: root

    // target, action, arg (string; may be empty), output (screen name the request concerns, "" = active)
    signal requested(string target, string action, string arg, string output)

    property var handled: ({})   // target -> true once a module claims it (diagnostics)
    // surfaces that are open right now, e.g. {"control-center": "eDP-1"}; modules keep it current so
    // the bar can highlight its buttons (setOpen("control-center", output, true/false))
    property var open: ({})

    function setOpen(name, output, isOpen) {
        const o = Object.assign({}, open);
        if (isOpen)
            o[name] = output || "";
        else
            delete o[name];
        open = o;
    }
    function isOpen(name, output) {
        return open[name] !== undefined && (!output || open[name] === "" || open[name] === output);
    }

    function request(target, action, arg, output) {
        root.requested(target, action, arg || "", output || "");
    }

    function claim(target) {
        const h = Object.assign({}, handled);
        h[target] = true;
        handled = h;
    }
}
