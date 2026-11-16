// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC target "docktest" (loaded with KRISTALL_SHELL_TEST=1): reports the Dock's state
// and tile rectangles (output coordinates) so tests can drive it with real pointer input, and
// counts the frames the Dock presents.
import QtQuick
import Quickshell
import Quickshell.Io
import qs.core
import qs.services
import "common"

Scope {
    id: hooks
    property var dock: null
    property var model: null
    property var places: null

    IpcHandler {
        target: "docktest"
        function state(): string {
            const d = hooks.dock;
            if (!d)
                return JSON.stringify({ dock: false });
            const tiles = [];
            for (let i = 0; i < d.slots.length; ++i) {
                const s = d.slots[i];
                const e = s.entry;
                tiles.push({ id: s.id, kind: e.kind, key: e.key || "", pinned: e.pinned === true,
                             running: e.kind === "app" && AppCatalog.isRunning(e.key),
                             launching: e.kind === "app" && hooks.model.launching[e.key] !== undefined,
                             badge: e.key ? (d.launcher.byKey[e.key] || null) : null,
                             x: d.layout.x[i], y: d.originY + d.iconBottom - d.layout.w[i], w: d.layout.w[i], presence: d.layout.p[i],
                             label: d.labelFor(e) });
            }
            return JSON.stringify({
                dock: true, screen: d.screenName, width: d.width, surfaceH: d.surfaceH, originY: d.originY,
                exclusiveZone: d.exclusiveZone, tileSize: d.tileSize, magSize: d.magSize, autoHide: d.autoHide, revealed: d.revealed,
                capsule: { x: d.layout.capL, y: d.originY + d.capTop, w: d.layout.capR - d.layout.capL, h: d.capH },
                hoverAmt: d.hoverAmt, magnifying: d.magnifying, hovering: d.hovering, hoverIndex: d.hoverIndex, label: d.labelText,
                menu: Menus.current ? Menus.current.owner : null, dragging: d.dragging,
                glassDrawn: GlassClient.active && (GlassClient.boundWindows["dock-" + d.screenName] || 0) > 0,
                scheme: d.scheme, frames: d.frames, tiles: tiles, pinnedIds: hooks.model.pinnedIds,
                trashFull: hooks.places.trashFull, downloads: hooks.places.downloads,
                catalog: AppCatalog.apps.length, hidden: Object.keys(AppCatalog.hiddenIds), dockRects: AppCatalog.dockRects
            });
        }
        function recordFrames(on: bool): string {
            const d = hooks.dock;
            if (!d)
                return "[]";
            if (on) {
                d.frameTimes = [];
                d.recordFrames = true;
                return "[]";
            }
            d.recordFrames = false;
            return JSON.stringify(d.frameTimes);
        }
        // cost of one layout pass (µs), averaged over n passes with a moving pointer
        function layoutBench(n: int): string {
            const d = hooks.dock;
            const t0 = Date.now();
            for (let i = 0; i < n; ++i)
                d.computeLayout(d.slots, 1, d.layout.capL + (i % 400) * 2, 1, d.tileSize, d.magSize, d.width);
            return JSON.stringify({ n: n, usPerPass: (Date.now() - t0) * 1000 / n, tiles: d.slots.length });
        }
        function openMenu(id: string): string {
            const d = hooks.dock;
            const i = d.slots.findIndex(s => s.id === id);
            if (i < 0)
                return "no tile";
            d.openMenu(i);
            return "ok";
        }
        function click(id: string): string {
            const d = hooks.dock;
            const i = d.slots.findIndex(s => s.id === id);
            if (i < 0)
                return "no tile";
            d.click(i);
            return "ok";
        }
    }
}
