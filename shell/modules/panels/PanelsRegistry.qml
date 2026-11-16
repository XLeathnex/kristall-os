// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell


// The panels' windows that exist right now ("cc:<output>", "nc:<output>", "banners:<output>",
// "hud:<output>"), for the test hooks and diagnostics.
Singleton {
    property var windows: ({})
    function add(key, win) {
        const w = Object.assign({}, windows);
        w[key] = win;
        windows = w;
    }
    function remove(key, win) {
        if (windows[key] !== win)
            return;
        const w = Object.assign({}, windows);
        delete w[key];
        windows = w;
    }
}
