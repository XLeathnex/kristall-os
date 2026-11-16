// SPDX-License-Identifier: GPL-3.0-or-later
// assistant-ui: the face of the assistant (docs/contracts/assistant-ipc.md, hands.md §8,
// shell.md). Owns: the crystal light around the screen edge, the glass panel that grows into a
// conversation, the assistant's own cursor, invocation (global shortcut, menu-bar button, the
// hand-off from Search), push-to-talk (the helper reports the key's release).
//
// Requests (ShellBus target "assistant"):
//   invoke  arg bar|shortcut|search|… — start listening (the bar button toggles the panel;
//           the shortcut while listening means "done talking")
//   ask     arg = text                 — the typed question from Search, submitted with the panel open
//   dismiss                            — close (stops everything, never leaves the microphone on)
//   toggle / show / hide               — panel only
//   release   arg = held ms (optional)  — the shortcut key was released (push-to-talk, see below)
// Settings (`assistant.ui`, defaults in image/settings.json): light.enabled, light.intensity,
// light.maxFps, light.cornerRadius, holdMs.
import QtQuick
import Quickshell
import qs.core
import qs.services
import "Markdown.js" as Md

Scope {
    id: assistant

    readonly property AssistantClient client: AssistantClient {}

    // ---- panel session ---------------------------------------------------------------------
    property bool open: false
    property string output: ""
    property var history: []                 // [{question, reply}] earlier turns of this session
    property string localNotice: ""          // restarted | noSetup | stopped | voiceOff
    property bool typed: false               // the owner switched to typing in this session
    property string typedQuestion: ""        // a typed question before its turn_started arrives
    property bool pendingVoice: false        // voice invoked, turn not started yet
    property bool _suppressCancel: false
    property var _last: ({ mode: "voice", text: "" })
    signal focusRequested()

    readonly property string name: client.assistantName || "Kristall"
    readonly property string st: client.connected ? client.state : "idle"
    readonly property bool listening: st === "listening" || st === "transcribing"
    readonly property bool micLive: client.connected && st === "listening"
    readonly property bool canSpeak: client.connected && client.voice.input !== false
    readonly property bool accountReady: ["ready", "unknown", "checking"].indexOf(client.account.status) >= 0
    readonly property bool compact: !typed && history.length === 0 && notice === null && client.permissions.length === 0
                                    && client.reply.trim() === "" && client.activity === null
                                    && (listening || (pendingVoice && client.connected))
    readonly property string orbMode: errorFlashing ? "error" : (st === "error" ? "error" : st)
    readonly property bool showThinking: (st === "thinking" || (st === "transcribing" && client.transcriptFinal))
                                         && client.reply.trim() === "" && client.permissions.length === 0
                                         && !(client.activity && client.activity.status === "running")
    // the line shows what runs now; a finished step stays until the assistant says something new
    readonly property bool showActivity: client.activity !== null && client.busy && !listening
                                         && (client.activity.status === "running" || client.activity.at > client.lastDeltaAt)
    // short, spoken-style answers (one paragraph, no markup) are set large
    readonly property bool largeReply: client.segments.filter(s => s.trim() !== "").length <= 1 && !Md.hasMarkup(client.reply)
                                       && client.reply.trim().length <= 240 && client.reply.indexOf("\n\n") < 0

    // ---- the light ------------------------------------------------------------------------------
    property bool errorFlashing: false
    Timer {
        id: errorFlashTimer
        interval: 1100
        onTriggered: assistant.errorFlashing = false
    }
    readonly property string lightMode: errorFlashing ? "error"
                                      : st === "listening" ? "listening"
                                      : (st === "transcribing" || st === "thinking") ? "thinking"
                                      : st === "acting" ? "acting"
                                      : st === "speaking" ? "speaking" : "thinking"
    readonly property bool lightShown: lightOverride !== null || (client.connected && (client.busy || errorFlashing))
    property var lightOverride: null         // tests/screenshots: {mode, level}
    readonly property string lightOutput: output !== "" ? output : defaultOutput()

    // ---- notices: every non-happy state as a calm sentence with what to do next ---------------
    readonly property var notice: {
        Strings.revision;
        if (!client.connected) {
            if (!client.everConnected || !client.lostTurn)
                return { icon: "plug", tone: "secondary", message: Strings.t(client.everConnected ? "assistant.reconnecting" : "assistant.unavailable", { name: name }),
                         hint: client.everConnected ? "" : Strings.t("assistant.unavailableHint"), actions: [] };
            return { icon: "arrow-clockwise", tone: "secondary", message: Strings.t("assistant.reconnecting", { name: name }), actions: [] };
        }
        if (localNotice === "noSetup")
            return { icon: "info", tone: "secondary", message: Strings.t("assistant.noSetup", { name: name }), actions: [] };
        const acct = client.account.status;
        const acctAction = { cli_missing: "install_cli", cli_outdated: "update_cli", signed_out: "sign_in" }[acct];
        if (acctAction)
            return { icon: "user-circle", tone: "accent", message: Strings.t("assistant.account." + acct, { name: name }),
                     actions: [{ label: Strings.t("assistant.action." + acctAction), primary: true, run: () => assistant.runAction(acctAction) }] };
        if (localNotice === "restarted")
            return { icon: "arrow-clockwise", tone: "secondary", message: Strings.t("assistant.restarted", { name: name }),
                     actions: [{ label: Strings.t("assistant.action.retry"), primary: true, run: () => assistant.retry() }] };
        const e = client.error;
        if (e)
            return errorNotice(e);
        if (acct === "checking" && !client.busy)
            return { icon: "circle-notch", tone: "secondary", message: Strings.t("assistant.account.checking"), quiet: true, actions: [] };
        if (localNotice === "voiceOff")
            return { icon: "microphone-slash", tone: "secondary", message: Strings.t("assistant.voiceOff"), quiet: true, actions: [] };
        if (localNotice === "stopped")
            return { icon: "stop", tone: "secondary", message: Strings.t("assistant.stopped"), quiet: true, actions: [] };
        return null;
    }
    readonly property var errorIcons: ({
        cli_missing: "user-circle", cli_outdated: "user-circle", not_signed_in: "user-circle",
        offline: "wifi-slash", credit_exhausted: "hourglass", rate_limited: "clock", overloaded: "clock",
        refused: "hand-palm", mic_unavailable: "microphone-slash", audio_output_unavailable: "speaker-slash",
        speech_models_missing: "microphone-slash", nothing_heard: "ear-slash"
    })
    function errorNotice(e) {
        const msg = Strings.pick(e.message) || Strings.t("assistant.unavailable", { name: name });
        const actions = [];
        if (e.action)
            actions.push({ label: Strings.t("assistant.action." + e.action), primary: true, run: () => assistant.runAction(e.action) });
        if (e.retryable)
            actions.push({ label: Strings.t("assistant.action.retry"), primary: actions.length === 0, run: () => assistant.retry() });
        if (e.code === "mic_unavailable" || e.code === "speech_models_missing")
            actions.push({ label: Strings.t("assistant.action.type"), primary: false, run: () => assistant.typingStarted() });
        const tone = ["cli_missing", "cli_outdated", "not_signed_in"].indexOf(e.code) >= 0 ? "accent"
                   : ["credit_exhausted", "rate_limited", "overloaded", "service_error", "internal", "brain_crashed", "timeout"].indexOf(e.code) >= 0 ? "warning" : "secondary";
        return { icon: errorIcons[e.code] || "warning-circle", tone: tone, message: msg, actions: actions, quiet: e.code === "nothing_heard", code: e.code };
    }

    // ---- actions ------------------------------------------------------------------------------
    function defaultOutput() {
        const f = Bridge.frontWindow;
        if (f && f.output && Quickshell.screens.some(s => s.name === f.output))
            return f.output;
        return Quickshell.screens.length ? Quickshell.screens[0].name : "";
    }
    function context() {
        const f = Bridge.frontWindow;
        if (!f)
            return null;
        return { front_app: Apps.displayName(f.appId).substring(0, 200), window_title: (f.title || "").substring(0, 300) };
    }
    function show(out) {
        const target = out && Quickshell.screens.some(s => s.name === out) ? out : (open ? output : defaultOutput());
        if (open && output !== target)
            ShellBus.setOpen("assistant", output, false);
        output = target;
        if (!open) {
            open = true;
            history = [];
            typed = false;
            localNotice = "";
        }
        ShellBus.setOpen("assistant", output, true);
        Qt.callLater(() => assistant.focusRequested());
    }
    function listen(source, out) {
        client.prepare();                        // warm Claude while the owner speaks
        show(out);
        localNotice = "";
        if (!client.connected || !accountReady)
            return;
        if (!canSpeak) {
            typed = true;
            localNotice = "voiceOff";
            return;
        }
        typed = false;
        typedQuestion = "";
        _suppressReopen = false;
        pendingVoice = true;
        _last = { mode: "voice", text: "" };
        client.invoke("voice", "", source, context());
    }
    function ask(text, source, out) {
        const t = (text || "").trim();
        client.prepare();
        show(out);
        typed = true;
        localNotice = "";
        if (t === "")
            return;
        typedQuestion = t;
        _suppressReopen = false;
        pendingVoice = false;
        _last = { mode: "text", text: t };
        if (client.connected && accountReady)
            client.invoke("text", t, source, context());
    }
    function retry() {
        localNotice = "";
        if (_last.mode === "text" && _last.text !== "")
            ask(_last.text, "retry");
        else
            listen("retry");
    }
    property bool _suppressReopen: false     // dismissed before our own turn had even started
    function dismiss(reason) {
        if (pendingVoice || (typedQuestion !== "" && !client.busy))
            _suppressReopen = true;
        if (client.busy || pendingVoice)
            client.cancel();
        pendingVoice = false;
        if (open)
            ShellBus.setOpen("assistant", output, false);
        open = false;
        typed = false;
        typedQuestion = "";
        localNotice = "";
        history = [];
        client.error = null;                     // a past failure is not news next time
    }
    function stop() {
        if (client.busy || pendingVoice) {
            client.cancel();
            localNotice = "stopped";
        }
        pendingVoice = false;
    }
    function endListening() {
        client.endListening();
    }
    function typingStarted() {
        const first = !typed;
        typed = true;
        if (localNotice === "voiceOff")
            localNotice = "";
        if (listening || pendingVoice || client.busy) {
            // the owner types over the voice or over an answer: stop it at once, quietly
            _suppressCancel = true;
            client.cancel();
            pendingVoice = false;
        }
        if (first)
            Qt.callLater(() => assistant.focusRequested());
    }
    function decide(requestId, decision) {
        client.permissionReply(requestId, decision);
    }
    function runAction(action) {
        if (action === "sign_in" || action === "install_cli" || action === "update_cli") {
            if (ShellBus.handled["setup"]) {
                ShellBus.request("setup", "claude-signin", action, output);
                dismiss("setup");
            } else {
                localNotice = "noSetup";
            }
        } else if (action === "open_sound_settings") {
            Session.openSystemSettings("kcm_pulseaudio");
            dismiss("settings");
        }
    }

    // ---- daemon events ------------------------------------------------------------------------
    Connections {
        target: assistant.client
        function onTurnStarted(turnId, input, source) {
            assistant.pendingVoice = false;
            assistant._suppressCancel = false;
            if (input === "text")
                assistant.typedQuestion = "";
            if (assistant.localNotice !== "noSetup")
                assistant.localNotice = "";
            if (assistant._suppressReopen) {
                assistant._suppressReopen = false;   // ours, already dismissed (and cancelled)
                return;
            }
            if (!assistant.open)
                assistant.show("");       // a turn started elsewhere (Search, ctl): show it
        }
        function onTurnArchived(question, reply, outcome) {
            if (!assistant.open || (reply === "" && question === ""))
                return;
            if (reply === "" && outcome === "cancelled")
                return;
            const h = assistant.history.slice(-5);
            h.push({ question: question, reply: reply });
            assistant.history = h;
        }
        function onConversationStarted(continued) {
            if (!continued)
                assistant.history = [];
        }
        function onTurnFinished(turnId, outcome, code) {
            assistant.pendingVoice = false;
        }
        function onErrorEvent(err) {
            assistant.errorFlashing = true;
            errorFlashTimer.restart();
            if (!assistant.open && err.code !== "nothing_heard")
                assistant.show("");
        }
        function onConnectedChanged() {
            if (assistant.client.connected && assistant.client.lostTurn && assistant.open)
                assistant.localNotice = "restarted";
            if (!assistant.client.connected)
                assistant.pendingVoice = false;
        }
    }

    // ---- requests -----------------------------------------------------------------------------
    property real _pressAt: 0
    Connections {
        target: ShellBus
        function onRequested(target, action, arg, out) {
            if (target !== "assistant")
                return;
            if (action === "invoke") {
                if (arg === "bar" && assistant.open) {
                    assistant.dismiss("toggle");
                } else if (arg === "shortcut" && assistant.open && assistant.micLive) {
                    assistant.endListening();
                } else {
                    assistant._pressAt = Date.now();
                    assistant.listen(arg === "shortcut" ? "hotkey" : (arg || "shell"), out);
                }
            } else if (action === "ask") {
                assistant.ask(arg, "search", out);
            } else if (action === "dismiss" || action === "hide") {
                assistant.dismiss("request");
            } else if (action === "show") {
                assistant.show(out);
            } else if (action === "toggle") {
                if (assistant.open)
                    assistant.dismiss("toggle");
                else
                    assistant.show(out);
            } else if (action === "release") {
                assistant.shortcutReleased(arg);
            }
        }
    }
    Component.onCompleted: ShellBus.claim("assistant")

    // ---- push-to-talk ------------------------------------------------------------------------------
    // The key is owned by shell-core's helper as a kglobalaccel D-Bus action, which sees press and
    // release (desktop-file shortcuts only report presses): press = "invoke shortcut", release =
    // "release <held ms>". Held at least holdMs (350): the owner talked while holding — end the
    // utterance (end_listening). A shorter tap keeps tap-to-talk (listening goes on hands-free; the
    // next tap is "done talking").
    readonly property int holdMs: Number(Settings.get("assistant.ui.holdMs", 350)) || 350
    function shortcutReleased(heldArg) {
        const held = Number(heldArg) > 0 ? Number(heldArg) : (_pressAt > 0 ? Date.now() - _pressAt : 0);
        if (_pressAt > 0 && held >= holdMs && (micLive || pendingVoice))
            client.endListening();
        _pressAt = 0;
    }

    // ---- per output: light, panel, cursor ----------------------------------------------------------
    Variants {
        model: Quickshell.screens
        delegate: Component {
            Scope {
                id: perScreen
                required property var modelData
                EdgeLight {
                    id: light
                    screen: perScreen.modelData
                    shown: assistant.lightShown && assistant.lightOutput === perScreen.modelData.name
                    mode: assistant.lightOverride ? assistant.lightOverride.mode : assistant.lightMode
                    levelTarget: assistant.lightOverride ? assistant.lightOverride.level : assistant.client.level
                    hole: panel.glassRect
                }
                Panel {
                    id: panel
                    screen: perScreen.modelData
                    ctl: assistant
                }
                AgentCursor {
                    id: cursor
                    screen: perScreen.modelData
                    Connections {
                        target: assistant.client
                        function onCursorEvent(ev, receivedMs) { cursor.handle(ev, receivedMs); }
                    }
                }
                Component.onCompleted: assistant._registerScreen(perScreen.modelData.name, { light: light, panel: panel, cursor: cursor })
                Component.onDestruction: assistant._unregisterScreen(perScreen.modelData.name)
            }
        }
    }
    property var screensMap: ({})
    function _registerScreen(n, o) {
        const m = Object.assign({}, screensMap);
        m[n] = o;
        screensMap = m;
    }
    function _unregisterScreen(n) {
        const m = Object.assign({}, screensMap);
        delete m[n];
        screensMap = m;
    }

    // ---- test hooks (KRISTALL_SHELL_TEST=1 only) -----------------------------------------------------
    LazyLoader {
        active: Quickshell.env("KRISTALL_SHELL_TEST") === "1"
        AssistantTestHooks { ctl: assistant }
    }
}
