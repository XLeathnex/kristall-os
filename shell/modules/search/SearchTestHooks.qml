// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC target "searchtest" (KRISTALL_SHELL_TEST=1): state, timing of the synchronous
// search per keystroke, and what the last chosen row did.
import QtQuick
import qs.core
import Quickshell
import Quickshell.Io
import qs.services

Scope {
    id: hooks
    property var module: null
    property var window: null
    IpcHandler {
        target: "searchtest"
        function state(): string {
            const w = hooks.window;
            return JSON.stringify({
                open: hooks.module.output !== "", output: hooks.module.output, lastActivated: hooks.module.lastActivated,
                query: w ? w.query : "", selected: w ? w.selectedId : "", lastSearchMs: w ? w.lastSearchMs : 0,
                rows: w ? w.rows.map(r => ({ id: r.id, kind: r.kind, title: r.title, subtitle: r.subtitle || "" })) : [],
                panel: w ? { h: w.animatedH } : null, assistant: ShellBus.handled["assistant"] === true, apps: AppCatalog.apps.length
            });
        }
        // the synchronous part of a keystroke (apps, settings, actions, calculator), µs per run
        function bench(q: string, n: int): string {
            const w = hooks.window;
            if (!w)
                return "{}";
            const t0 = Date.now();
            for (let i = 0; i < n; ++i)
                w.compute(q.substring(0, 1 + (i % q.length)));
            const us = (Date.now() - t0) * 1000 / n;
            w.compute(w.query);
            return JSON.stringify({ n: n, usPerKeystroke: us, apps: AppCatalog.apps.length });
        }
        // the matching alone (no list rebuild), µs per run
        function benchEngine(q: string, n: int): string {
            const w = hooks.window;
            const parts = { apps: 0, settings: 0, actions: 0 };
            for (let i = 0; i < n; ++i) {
                const s = q.substring(0, 1 + (i % q.length));
                let t = Date.now();
                AppCatalog.search(s, 8);
                parts.apps += Date.now() - t;
                t = Date.now();
                w._settingsRows(s);
                parts.settings += Date.now() - t;
                t = Date.now();
                w._actionRows(s);
                parts.actions += Date.now() - t;
            }
            for (const k in parts)
                parts[k] = parts[k] * 1000 / n;
            return JSON.stringify(parts);
        }
        function frameLog(): string {
            return JSON.stringify(hooks.window ? hooks.window.frameLog : []);
        }
        // the synchronous app matching alone, one call, in µs (performance clock not in QML: n runs)
        function setQuery(q: string): string {
            hooks.module.show(hooks.module.output, q);
            return "ok";
        }
    }
}
