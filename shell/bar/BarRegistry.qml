// SPDX-License-Identifier: GPL-3.0-or-later
// The bars by output name (keyboard access to the menu bar, tests).
pragma Singleton
import QtQuick
import Quickshell

Singleton {
    property var bars: ({})
    function add(name, bar) { const b = Object.assign({}, bars); b[name] = bar; bars = b; }
    function remove(name, bar) { if (bars[name] === bar) { const b = Object.assign({}, bars); delete b[name]; bars = b; } }
    // open menu `index` (0 = the mark) of the bar on `name` with keyboard selection
    function focus(name, index) {
        const bar = bars[name] || bars[Object.keys(bars)[0]];
        if (bar)
            bar.tracker.openAt(index || 0, true);
    }
}
