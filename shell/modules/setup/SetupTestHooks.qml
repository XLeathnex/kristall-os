// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC target "setuptest" (KRISTALL_SHELL_TEST=1): the state, and where a named control
// is on screen so tests can click it with the owner's real pointer.
import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: hooks
    property var ctl: null

    function find(item, name) {
        if (!item)
            return null;
        if (item.objectName === name && item.visible)
            return item;
        const kids = item.children || [];
        for (let i = 0; i < kids.length; ++i) {
            const f = find(kids[i], name);
            if (f)
                return f;
        }
        return null;
    }
    IpcHandler {
        target: "setuptest"
        function state(): string {
            const w = hooks.ctl.mainWindow;
            const item = w ? w.stepItem : null;
            return JSON.stringify({
                open: hooks.ctl.open, mode: hooks.ctl.mode, step: hooks.ctl.step, steps: hooks.ctl.visibleSteps,
                index: hooks.ctl.stepIndex, live: hooks.ctl.live, liveChecked: hooks.ctl.liveChecked, lastRequest: hooks.ctl.lastRequest,
                primary: item ? item.primaryText : "", primaryEnabled: item ? item.primaryEnabled : false,
                secondary: item ? item.secondaryText : "", title: item ? item.title : "",
                account: { phase: hooks.ctl.account.phase, status: hooks.ctl.account.status, stage: hooks.ctl.account.stage,
                           url: hooks.ctl.account.url, needCode: hooks.ctl.account.needCode, error: hooks.ctl.account.error },
                mic: item && item.micCheck ? { phase: item.micCheck.phase, transcript: item.micCheck.transcript, ready: item.micCheck.ready,
                                               connected: item.micCheck.connected } : null,
                touchpads: hooks.ctl.helper.touchpads, displays: hooks.ctl.helper.displays, power: hooks.ctl.helper.power !== null,
                apps: hooks.ctl.helper.apps, keyboard: hooks.ctl.helper.keyboard
            });
        }
        function rect(name: string): string {
            const w = hooks.ctl.mainWindow;
            if (!w)
                return "";
            const it = hooks.find(w.contentItem, name);
            if (!it)
                return "";
            const p = it.mapToItem(null, 0, 0);
            return JSON.stringify({ x: p.x, y: p.y, w: it.width, h: it.height });
        }
        function go(step: string): string {
            hooks.ctl.goTo(step);
            return hooks.ctl.step;
        }
        function text(name: string): string {
            const w = hooks.ctl.mainWindow;
            const it = w ? hooks.find(w.contentItem, name) : null;
            return it && it.text !== undefined ? String(it.text) : "";
        }
        // every visible text on the card (JSON array): tests look for unfilled {placeholders}
        function texts(): string {
            const out = [];
            const walk = item => {
                if (!item || item.visible === false)
                    return;
                if (item.text !== undefined && typeof item.text === "string" && item.text !== "")
                    out.push(item.text);
                for (let i = 0; i < item.children.length; ++i)
                    walk(item.children[i]);
            };
            const w = hooks.ctl.mainWindow;
            if (w)
                walk(w.contentItem);
            return JSON.stringify(out);
        }
    }
}
