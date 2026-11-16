// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only IPC target "assistant-test" (loaded with KRISTALL_SHELL_TEST=1):
//   state()                 everything the tests check, as JSON
//   rects(output)           output-local rectangles of the panel's controls (for real pointer clicks)
//   arrivals(output)        cursor glides: [{target, arrived, x, y}] (wall-clock ms)
//   clearArrivals(output)
//   request(action, arg)    the same as `kristall-shellctl assistant <action> <arg>`
//   feed(%-encoded json)       a JSON array of daemon events, handled as if read from the socket
//   lightPreview(mode, lvl) show the light in a state without a turn ("" ends it)
//   lightEntry(progress)    freeze the entry bloom at 0..1 (−1 lets it run again)
//   runNoticeAction(i)      run the i-th button of the current notice
import QtQuick
import Quickshell
import Quickshell.Io
import qs.services

Scope {
    id: hooks
    required property var ctl

    function _find(item, name) {
        if (!item)
            return null;
        if (item.objectName === name && item.visible !== false)
            return item;
        const kids = item.children || [];
        for (let i = 0; i < kids.length; ++i) {
            const r = _find(kids[i], name);
            if (r)
                return r;
        }
        return null;
    }
    function _findAll(item, name, out) {
        if (!item)
            return out;
        if (item.objectName === name && item.visible !== false)
            out.push(item);
        const kids = item.children || [];
        for (let i = 0; i < kids.length; ++i)
            _findAll(kids[i], name, out);
        return out;
    }
    function _visibleUp(item) {
        for (let i = item; i; i = i.parent)
            if (i.visible === false || i.opacity === 0)
                return false;
        return true;
    }
    function _rect(body, item) {
        const p = item.mapToItem(null, 0, 0);
        return { x: Math.round(body.originX + p.x), y: Math.round(p.y), w: Math.round(item.width), h: Math.round(item.height) };
    }

    IpcHandler {
        target: "assistant-test"

        function state(): string {
            const c = hooks.ctl.client;
            const screens = {};
            for (const n in hooks.ctl.screensMap) {
                const o = hooks.ctl.screensMap[n];
                const body = o.panel.bodyItem();
                screens[n] = {
                    light: { mapped: o.light.mapped, fade: o.light.fade, mode: o.light.mode, updates: o.light.updates, level: o.light.level, sweep: o.light.sweep, onLight: o.light.onLight, sampled: o.light.sampled, depth: o.light.depth, reach: o.light.reach, lastEntryMs: o.light.lastEntryMs, lastExitMs: o.light.lastExitMs,
                             fallback: o.light.forceFallback },
                    panel: { mapped: o.panel.mapped, open: o.panel.open, w: body.width, h: body.height, targetW: body.targetW, targetH: body.targetH,
                             compact: body.compact, scheme: body.scheme, originX: body.originX },
                    cursor: { shown: o.cursor.shown, mapped: o.cursor.mapped, x: o.cursor.gx, y: o.cursor.gy, label: o.cursor.label,
                              output: o.cursor.output, gliding: o.cursor.gliding, opacity: o.cursor.opacityValue, held: o.cursor.held }
                };
            }
            const n = hooks.ctl.notice;
            return JSON.stringify({
                open: hooks.ctl.open, output: hooks.ctl.output, compact: hooks.ctl.compact, typed: hooks.ctl.typed,
                connected: c.connected, everConnected: c.everConnected, state: c.state, turnId: c.turnId, question: c.question,
                transcript: c.transcript, reply: c.reply, segments: c.segments, replyDone: c.replyDone,
                activity: c.activity ? Strings.pick(c.activity.text) : null, activityStatus: c.activity ? c.activity.status : null,
                permissions: c.permissions.map(p => ({ id: p.request_id, question: Strings.pick(p.question), answered: p._answered || null })),
                notice: n ? { message: n.message, icon: n.icon, actions: (n.actions || []).map(a => a.label), code: n.code || "" } : null,
                account: c.account.status, error: c.error ? c.error.code : null, history: hooks.ctl.history.length,
                micLive: hooks.ctl.micLive, lightShown: hooks.ctl.lightShown, lightMode: hooks.ctl.lightMode,
                largeReply: hooks.ctl.largeReply, orbMode: hooks.ctl.orbMode, lang: Strings.lang, screens: screens,
                handled: ShellBus.handled, setOpen: ShellBus.open
            });
        }

        function rects(output: string): string {
            const o = hooks.ctl.screensMap[output || hooks.ctl.output] || hooks.ctl.screensMap[Object.keys(hooks.ctl.screensMap)[0]];
            if (!o)
                return "{}";
            const body = o.panel.bodyItem();
            const out = {};
            for (const nm of ["allowBtn", "denyBtn", "alwaysBtn", "closeBtn", "field", "micBtn", "stopBtn", "copyBtn", "compactMic", "reply"]) {
                const all = hooks._findAll(body, nm, []).filter(i => hooks._visibleUp(i));
                if (all.length)
                    out[nm] = hooks._rect(body, all[0]);
            }
            out.panel = { x: Math.round(body.originX + body.x), y: Math.round(body.y), w: Math.round(body.width), h: Math.round(body.height) };
            return JSON.stringify(out);
        }

        function arrivals(output: string): string {
            const o = hooks.ctl.screensMap[output || Object.keys(hooks.ctl.screensMap)[0]];
            return JSON.stringify(o ? o.cursor.arrivals : []);
        }
        function ripples(output: string): string {
            const o = hooks.ctl.screensMap[output || Object.keys(hooks.ctl.screensMap)[0]];
            return JSON.stringify(o ? { log: o.cursor.rippleLog } : {});
        }
        function clearArrivals(output: string): string {
            const o = hooks.ctl.screensMap[output || Object.keys(hooks.ctl.screensMap)[0]];
            if (o) {
                o.cursor.arrivals = [];
                o.cursor.rippleLog = [];
            }
            return "ok";
        }
        function lightEntry(progress: real): string {
            for (const n in hooks.ctl.screensMap)
                hooks.ctl.screensMap[n].light.entryOverride = progress;
            return "ok";
        }
        function lightPreview(mode: string, level: real): string {
            hooks.ctl.lightOverride = mode === "" ? null : { mode: mode, level: level };
            return "ok";
        }
        // feed daemon events into the client exactly as if they came from the socket (for content
        // the demo daemon cannot produce without Claude: long formatted answers)
        function feed(events: string): string {
            // percent-encoded JSON (the ipc command line splits plain JSON at spaces)
            const list = JSON.parse(decodeURIComponent(events));
            for (const ev of list)
                hooks.ctl.client._event(ev);
            return "ok";
        }
        function runNoticeAction(index: int): string {
            const n = hooks.ctl.notice;
            if (!n || !n.actions || !n.actions[index])
                return "none";
            n.actions[index].run();
            return "ok";
        }
        function request(action: string, arg: string): string {
            ShellBus.request("assistant", action, arg, "");
            return "ok";
        }
    }
}
