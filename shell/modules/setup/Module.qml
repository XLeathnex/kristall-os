// SPDX-License-Identifier: GPL-3.0-or-later
// The `setup` module: the Setup Assistant (docs/contracts/setup.md). A full-screen, unhurried
// first-run experience on its own Overlay surfaces (namespace "kristall-setup-main"), one
// question per step, each with a default, resumable at every step (the step is stored in the
// shared settings as it changes), never in the installer's live session.
//
// Requests (ShellBus target "setup", `kristall-shellctl setup <action> -- [arg]`):
//   start [step]        open the Setup Assistant (resumes where it stopped; after it was finished,
//                       starts again from the welcome, or at `step`)
//   claude-signin [why] open the "Sign in with Claude" step on its own (from the assistant's
//                       interface); if the Setup Assistant is open it jumps there
//   close               close without finishing (resumes at the next start)
import QtQuick
import Quickshell
import Quickshell.Io
import qs.core
import qs.services

Scope {
    id: setupRoot

    // ---- state ---------------------------------------------------------------------------------
    property bool open: false
    property var mainWindow: null           // the main output's window (tests, focus)
    property string mode: "full"            // "full" | "signin" (the sign-in step alone)
    property string step: "welcome"
    property string direction: "forward"
    property string lastRequest: ""
    readonly property var order: ["welcome", "network", "appearance", "glass", "display", "keyboard", "trackpad",
                                  "assistant", "voice", "microphone", "privacy", "energy", "done"]
    readonly property var forced: (Quickshell.env("KRISTALL_SETUP_FORCE_STEPS") || "").split(",").filter(s => s !== "")

    // the live system (installer stick) never runs it: marker file or kernel command line
    property bool live: false
    property bool liveChecked: false
    property var _deferred: null
    Process {
        running: true
        command: ["sh", "-c", "test -e \"$1\" || grep -qw rd.live.image \"$2\"", "sh",
                  Quickshell.env("KRISTALL_SETUP_LIVE_MARKER") || "/etc/kristall/live",
                  Quickshell.env("KRISTALL_SETUP_CMDLINE") || "/proc/cmdline"]
        onExited: code => {
            setupRoot.live = code === 0;
            setupRoot.liveChecked = true;
            if (setupRoot._deferred !== null) {
                const d = setupRoot._deferred;
                setupRoot._deferred = null;
                d();
            }
            setupRoot._resumeCheck();
        }
    }

    // ---- optimistic settings: a choice shows at once, before the settings file echoes it -----
    property var pending: ({})
    function value(path, def) {
        if (pending[path] !== undefined)
            return pending[path];
        return Settings.get(path, def);
    }
    function put(path, v) {
        const p = Object.assign({}, pending);
        p[path] = v;
        pending = p;
        Settings.set(path, v);
    }
    Connections {
        target: Settings
        function onDataChanged() {
            const keep = {};
            let changed = false;
            for (const k in setupRoot.pending) {
                if (JSON.stringify(Settings.get(k, null)) === JSON.stringify(setupRoot.pending[k]))
                    changed = true;
                else
                    keep[k] = setupRoot.pending[k];
            }
            if (changed)
                setupRoot.pending = keep;
        }
    }
    readonly property string assistantName: {
        const n = String(value("assistant.name", "Kristall")).trim();
        return n !== "" ? n : "Kristall";
    }
    readonly property bool macKeys: value("keyboard.macShortcuts", true) === true
    // how to press it on the owner's keys: the Mac glyph and, in brackets, the keys as printed
    function keysFor(what) {
        const space = Strings.lang === "de" ? "Leertaste" : "Space";
        if (what === "search")
            return macKeys ? "⌘ " + space + " (Alt + " + space + ")" : "Win + " + space;
        return macKeys ? "⌥ " + space + " (Win + " + space + ")" : "Alt + " + space;
    }

    // ---- backends --------------------------------------------------------------------------------
    property SetupHelper helper: SetupHelper {}
    property AccountFlow account: AccountFlow {}

    // ---- which steps apply -----------------------------------------------------------------------
    property bool sawNetworkStep: false
    function applies(id) {
        if (forced.indexOf(id) >= 0)
            return true;
        switch (id) {
        case "network":
            return sawNetworkStep || !Network.connected;
        case "trackpad":
            return helper.touchpads.length > 0;
        default:
            return true;
        }
    }
    readonly property var visibleSteps: {
        Network.connected; helper.touchpads; sawNetworkStep;
        return order.filter(id => applies(id));
    }
    readonly property int stepIndex: visibleSteps.indexOf(step)

    function goTo(id, dir) {
        if (id === step)
            return;
        direction = dir || (order.indexOf(id) > order.indexOf(step) ? "forward" : "back");
        if (id === "network")
            sawNetworkStep = true;
        step = id;
        if (mode === "full")
            Settings.set("setup.step", id);
    }
    function next() {
        for (let i = order.indexOf(step) + 1; i < order.length; ++i) {
            if (applies(order[i])) {
                goTo(order[i], "forward");
                return;
            }
        }
        finish();
    }
    function back() {
        for (let i = order.indexOf(step) - 1; i >= 0; --i) {
            if (applies(order[i])) {
                goTo(order[i], "back");
                return;
            }
        }
    }

    // ---- lifecycle ---------------------------------------------------------------------------------
    function start(arg) {
        if (!liveChecked) {
            _deferred = () => setupRoot.start(arg);
            return;
        }
        if (live) {
            console.info("kristall-setup: live session, not starting");
            return;
        }
        Menus.close("replaced");
        const running = Settings.get("setup.running", false) === true;
        const done = Settings.get("setup.done", false) === true;
        let at = arg && order.indexOf(arg) >= 0 ? arg : "";
        if (at === "") {
            const saved = String(Settings.get("setup.step", ""));
            at = running && !done && order.indexOf(saved) >= 0 ? saved : "welcome";
        }
        mode = "full";
        step = at;
        if (at === "network")
            sawNetworkStep = true;
        open = true;
        Settings.set("setup.running", true);
        Settings.set("setup.step", at);
        helper.refresh();
        console.info("kristall-setup: started at", at, running ? "(resumed)" : "");
    }
    function signIn(why) {
        if (!liveChecked) {
            _deferred = () => setupRoot.signIn(why);
            return;
        }
        if (live)
            return;
        if (open && mode === "full") {
            goTo("assistant");
            return;
        }
        mode = "signin";
        step = "assistant";
        open = true;
        helper.refresh();
    }
    function close() {
        account.cancel();
        open = false;
        mode = "full";
    }
    function finish() {
        if (mode === "signin") {
            close();
            return;
        }
        account.cancel();
        Settings.set("setup.done", true);
        Settings.set("setup.running", false);
        Settings.set("setup.step", "");
        open = false;
        console.info("kristall-setup: finished");
    }
    function skipAll() {
        // everything stays at its defaults: those already make a set-up computer
        Settings.set("setup.skipped", true);
        finish();
    }

    onOpenChanged: ShellBus.setOpen("setup", "", open)

    Connections {
        target: ShellBus
        function onRequested(target, action, arg, output) {
            if (target !== "setup")
                return;
            setupRoot.lastRequest = action + (arg ? " " + arg : "");
            if (action === "start" || action === "show")
                setupRoot.start(arg);
            else if (action === "claude-signin")
                setupRoot.signIn(arg);
            else if (action === "close" || action === "hide")
                setupRoot.close();
        }
    }

    // resume after a crash or restart of the shell while the Setup Assistant was on screen
    property bool _checked: false
    function _resumeCheck() {
        if (_checked || !Settings.loaded || !liveChecked)
            return;
        _checked = true;
        if (Settings.get("setup.running", false) === true && Settings.get("setup.done", false) !== true && !live)
            start("");
    }
    Connections {
        target: Settings
        function onLoadedChanged() { setupRoot._resumeCheck(); }
    }
    Component.onCompleted: {
        ShellBus.claim("setup");
        _resumeCheck();
    }

    // ---- surfaces: one per output; the card on the main one ------------------------------------
    readonly property string mainOutput: {
        const outs = Bridge.outputs || [];
        const internal = outs.find(o => o.internal);
        if (internal && Quickshell.screens.some(s => s.name === internal.name))
            return internal.name;
        return Quickshell.screens.length ? Quickshell.screens[0].name : "";
    }
    Variants {
        model: setupRoot.open ? Quickshell.screens : []
        SetupWindow {
            required property var modelData
            screen: modelData
            ctl: setupRoot
            main: modelData.name === setupRoot.mainOutput
        }
    }

    LazyLoader {
        active: Quickshell.env("KRISTALL_SHELL_TEST") === "1"
        SetupTestHooks { ctl: setupRoot }
    }
}
