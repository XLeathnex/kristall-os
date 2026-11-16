// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Shape of each app icon, measured once from its pixels (AppIcon's analyser) and remembered in
// $XDG_CACHE_HOME/kristall/shell-apps/icon-shapes.json:
//   {k: "tile"  — already a filled rounded square: drawn as is, normalised to the common size
//      "plate" — any other shape (circle, folder, glyph, sharp square): placed on a rounded
//                plate like macOS 26 does for icons that do not follow the grid,
//    b: [x0, y0, x1, y1] — bounding box of the visible pixels, 0..1 of the canvas}
// Unknown icons draw as "plate" with the full box until measured (one frame).
Singleton {
    id: root

    readonly property string cachePath: (Quickshell.env("XDG_CACHE_HOME") || (Quickshell.env("HOME") + "/.cache")) + "/kristall/shell-apps/icon-shapes.json"
    property var shapes: ({})
    property int revision: 0
    property bool loaded: false

    function get(url) {
        revision;
        return shapes[url] || null;
    }
    function set(url, info) {
        const s = Object.assign({}, shapes);
        s[url] = info;
        shapes = s;
        revision++;
        saveTimer.restart();
    }

    // icons waiting for a measurement (IconProbe takes them one by one)
    property var queue: []
    function request(url) {
        if (!url || shapes[url] || queue.indexOf(url) >= 0)
            return;
        queue = queue.concat([url]);
    }
    function take() {
        if (!queue.length)
            return "";
        const u = queue[0];
        queue = queue.slice(1);
        return shapes[u] ? take() : u;
    }

    // alpha[] of n×n pixels → {k, b}
    function classify(alpha, n) {
        let x0 = n, y0 = n, x1 = -1, y1 = -1, count = 0;
        for (let y = 0; y < n; ++y)
            for (let x = 0; x < n; ++x)
                if (alpha[y * n + x] > 40) {
                    if (x < x0) x0 = x;
                    if (x > x1) x1 = x;
                    if (y < y0) y0 = y;
                    if (y > y1) y1 = y;
                }
        if (x1 < 0)
            return { k: "plate", b: [0, 0, 1, 1] };
        let solid = 0;
        for (let y = y0; y <= y1; ++y)
            for (let x = x0; x <= x1; ++x)
                if (alpha[y * n + x] > 160)
                    solid++;
        const w = x1 - x0 + 1, h = y1 - y0 + 1;
        const coverage = solid / (w * h);
        // the four corner pixels of the box: transparent for a rounded tile
        const corner = (alpha[y0 * n + x0] + alpha[y0 * n + x1] + alpha[y1 * n + x0] + alpha[y1 * n + x1]) / 4;
        const square = Math.abs(w - h) <= n * 0.08 && w >= n * 0.62;
        const rounded = coverage >= 0.86 && coverage < 0.985 && corner < 128;
        return { k: square && rounded ? "tile" : "plate", b: [x0 / n, y0 / n, (x1 + 1) / n, (y1 + 1) / n] };
    }

    FileView {
        id: out
        path: root.cachePath
        printErrors: false
        atomicWrites: true
        onLoaded: {
            try {
                const d = JSON.parse(text());
                if (d.schema === 1)
                    root.shapes = Object.assign({}, d.shapes || {}, root.shapes);
            } catch (e) { /* rebuilt as icons are seen */ }
            root.loaded = true;
            root.revision++;
        }
        onLoadFailed: { root.loaded = true; }
    }
    property bool _dirMade: false
    Timer {
        id: saveTimer
        interval: 2000
        onTriggered: {
            if (!root._dirMade) {
                root._dirMade = true;
                Quickshell.execDetached(["mkdir", "-p", root.cachePath.substring(0, root.cachePath.lastIndexOf("/"))]);
                restart();
                return;
            }
            out.setText(JSON.stringify({ schema: 1, shapes: root.shapes }));
        }
    }
}
