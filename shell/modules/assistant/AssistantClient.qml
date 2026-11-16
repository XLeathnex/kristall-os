// SPDX-License-Identifier: GPL-3.0-or-later
// Client for the assistant daemon's socket (docs/contracts/assistant-ipc.md, protocol 1).
// Keeps a complete, render-ready model of what the daemon says: state, the current turn
// (transcript, reply segments, activity, permission prompts, error), account, voice abilities,
// the agent cursor. The whole model is rebuilt from the `snapshot` the daemon sends on every
// (re)connect. The daemon may be absent or restart at any time: the shell's helper watches the
// socket path with inotify (no polling while it is missing); without the helper we retry with
// backoff 0.2 s doubling to 5 s, as the contract asks.
import QtQuick
import Quickshell
import Quickshell.Io
import qs.services

QtObject {
    id: client

    // ---- connection ---------------------------------------------------------------------------
    readonly property string socketPath: Quickshell.env("KRISTALL_ASSISTANT_SOCKET") || (Quickshell.env("XDG_RUNTIME_DIR") + "/kristall/assistant.sock")
    property bool connected: false          // socket open and hello+snapshot received
    property bool socketExists: false
    property bool everConnected: false
    property bool demo: false
    property string daemonVersion: ""
    property int lastSeq: -1
    property int restarts: 0                 // daemon restarts noticed (diagnostics)
    property bool lostTurn: false            // a turn was running when the connection dropped

    // ---- model --------------------------------------------------------------------------------
    property string state: "idle"            // idle listening transcribing thinking acting speaking error
    property string stateDetail: ""
    property string turnId: ""
    property string turnInput: ""            // voice | text
    property string turnSource: ""
    property bool turnSpeak: false
    property string question: ""             // typed text or the final transcript
    property string transcript: ""           // live (partial) transcript while listening
    property bool transcriptFinal: false
    property var segments: []                // reply text per segment (strings)
    property bool replyDone: false
    property int speechSentence: -1
    property string speechText: ""
    property var activity: null              // {id, text{de,en}, status, detail, tool, at}
    property real lastDeltaAt: 0             // when reply text last arrived (ms)
    property var permissions: []             // pending permission_request payloads (+ _answered)
    property var error: null                 // last error event of this turn (or a persistent one)
    property string lastOutcome: ""          // outcome of the last finished turn
    property var account: ({ status: "unknown" })
    property var voice: ({ input: true, output: true, live_transcript: true })
    property string assistantName: "Kristall"
    property string assistantLanguage: "de"
    property var usage: null
    property real level: 0                   // last level value (mic or speech)
    property string levelSource: ""
    property var cursor: null                // last agent cursor fields (visible, x, y, label, output)

    readonly property string reply: segments.join("")
    readonly property bool busy: state !== "idle" && state !== "error"
    readonly property bool available: connected && (account.status === "ready" || account.status === "unknown" || account.status === "checking")

    signal turnStarted(string turnId, string input, string source)
    signal turnArchived(string question, string reply, string outcome)   // the previous turn, before a new one replaces it
    signal turnFinished(string turnId, string outcome, string errorCode)
    signal conversationStarted(bool continued)
    signal cursorEvent(var ev, real receivedMs)
    signal levelEvent(string source, real value)
    signal errorEvent(var err)
    signal acked(var id, bool ok, string code, string turnId)
    signal resynced()                        // the model was rebuilt from a snapshot

    // ---- requests ---------------------------------------------------------------------------
    property int _nextId: 1
    function send(obj) {
        if (!sock || !sock.connected)
            return false;
        sock.write(JSON.stringify(obj) + "\n");
        sock.flush();
        return true;
    }
    function invoke(mode, text, source, context, extra) {
        const m = { type: "invoke", id: "ui-" + (_nextId++), mode: mode, source: (source || "").substring(0, 20) };
        if (mode === "text")
            m.text = text;
        if (context)
            m.context = context;
        if (extra)
            Object.assign(m, extra);
        return send(m) ? m.id : "";
    }
    function prepare() { return send({ type: "prepare" }); }
    function cancel() { return send({ type: "cancel" }); }
    function endListening() { return send({ type: "end_listening" }); }
    function stopSpeaking() { return send({ type: "stop_speaking" }); }
    function newConversation() { return send({ type: "new_conversation" }); }
    function permissionReply(requestId, decision) {
        const ps = permissions.map(p => p.request_id === requestId ? Object.assign({}, p, { _answered: decision }) : p);
        permissions = ps;
        return send({ type: "permission_reply", id: "ui-" + (_nextId++), request_id: requestId, decision: decision });
    }

    // ---- event handling -----------------------------------------------------------------------
    function _clearTurn() {
        turnId = "";
        turnInput = "";
        turnSource = "";
        turnSpeak = false;
        question = "";
        transcript = "";
        transcriptFinal = false;
        segments = [];
        replyDone = false;
        speechSentence = -1;
        speechText = "";
        activity = null;
        permissions = [];
    }

    function _snapshot(s) {
        _clearTurn();
        error = null;
        state = s.state || "idle";
        stateDetail = "";
        account = s.account || { status: "unknown" };
        voice = s.voice || { input: true, output: true, live_transcript: true };
        if (s.assistant) {
            assistantName = s.assistant.name || "Kristall";
            assistantLanguage = s.assistant.language || "de";
        }
        const t = s.turn;
        if (t) {
            turnId = t.turn_id || "";
            turnInput = t.input || "";
            question = t.text || "";
            turnSpeak = t.speak === true;
            segments = t.reply ? [t.reply] : [];
        }
        permissions = (s.pending_permissions || []).slice();
        cursor = s.agent_cursor ? Object.assign({ visible: true }, s.agent_cursor) : null;
        cursorEvent(cursor ? Object.assign({ duration_ms: 0 }, cursor) : { visible: false }, Date.now());
        resynced();
    }

    function _event(ev) {
        if (typeof ev.seq === "number") {
            if (lastSeq >= 0 && ev.seq < lastSeq && ev.type !== "hello")
                restarts++;
            lastSeq = ev.seq;
        }
        switch (ev.type) {
        case "hello":
            demo = ev.demo === true;
            daemonVersion = ev.version || "";
            if (ev.protocol !== 1)
                console.warn("kristall-assistant: daemon speaks protocol", ev.protocol, "(this interface knows 1)");
            break;
        case "snapshot":
            _snapshot(ev);
            connected = true;
            everConnected = true;
            break;
        case "state":
            state = ev.state || "idle";
            stateDetail = ev.detail || "";
            break;
        case "turn_started":
            if (question !== "" || reply !== "")
                turnArchived(question, reply, lastOutcome);
            _clearTurn();
            error = null;
            lostTurn = false;
            turnId = ev.turn_id || "";
            turnInput = ev.input || "";
            turnSource = ev.source || "";
            turnSpeak = ev.speak === true;
            question = ev.text || "";
            turnStarted(turnId, turnInput, turnSource);
            break;
        case "conversation":
            conversationStarted(ev.continued === true);
            break;
        case "transcript":
            if (ev.turn_id !== turnId)
                break;
            transcript = ev.text || "";
            transcriptFinal = ev.final === true;
            if (transcriptFinal)
                question = transcript;
            break;
        case "reply_delta": {
            if (ev.turn_id !== turnId)
                break;
            const seg = Math.max(0, ev.segment || 0);
            const s = segments.slice();
            while (s.length <= seg)
                s.push("");
            s[seg] += ev.text || "";
            segments = s;
            lastDeltaAt = Date.now();
            break;
        }
        case "reply_done":
            if (ev.turn_id !== turnId)
                break;
            replyDone = true;
            if (ev.text && ev.text !== reply)        // contract: deltas concatenated == text
                segments = [ev.text];
            break;
        case "speech":
            if (ev.turn_id !== turnId)
                break;
            speechSentence = ev.sentence;
            speechText = ev.text || "";
            break;
        case "activity":
            if (ev.turn_id && turnId && ev.turn_id !== turnId)
                break;
            if (ev.status === "running" || !activity || activity.id === ev.id)
                activity = { id: ev.id, text: ev.text, status: ev.status, detail: ev.detail || "", tool: ev.tool || "", at: Date.now() };
            break;
        case "permission_request": {
            const ps = permissions.filter(p => p.request_id !== ev.request_id);
            const copy = Object.assign({}, ev);
            copy._received = Date.now();
            ps.push(copy);
            permissions = ps;
            break;
        }
        case "permission_resolved":
            permissions = permissions.filter(p => p.request_id !== ev.request_id);
            break;
        case "turn_finished":
            lastOutcome = ev.outcome || "";
            permissions = [];
            if (activity && activity.status === "running")
                activity = Object.assign({}, activity, { status: "done" });
            turnFinished(ev.turn_id || "", ev.outcome || "", ev.error_code || "");
            break;
        case "error":
            error = { code: ev.code || "internal", message: ev.message || null, retryable: ev.retryable === true,
                      action: ev.action || null, resetsAt: ev.resets_at || 0, turnId: ev.turn_id || "" };
            errorEvent(error);
            break;
        case "account":
            account = ev;
            break;
        case "usage_warning":
            usage = ev;
            break;
        case "level":
            level = Math.max(0, Math.min(1, Number(ev.value) || 0));
            levelSource = ev.source || "";
            levelEvent(levelSource, level);
            break;
        case "agent_cursor": {
            const c = Object.assign({}, cursor || {}, ev);
            delete c.type;
            delete c.pulse;
            if (ev.visible === false)
                c.visible = false;
            cursor = c;
            cursorEvent(ev, Date.now());
            break;
        }
        case "ack":
            acked(ev.id, ev.ok === true, ev.code || "", ev.turn_id || "");
            if (ev.ok === false && ev.code && ev.code !== "unknown_request")
                console.warn("kristall-assistant: request refused:", ev.code, ev.re || "");
            break;
        }
    }

    function _handle(line) {
        let ev;
        try {
            ev = JSON.parse(line);
        } catch (e) {
            console.warn("kristall-assistant: bad JSON from daemon");
            return;
        }
        if (ev && typeof ev.type === "string")
            _event(ev);
    }

    readonly property bool debug: Quickshell.env("KRISTALL_ASSISTANT_DEBUG") === "1"
    function _lost() {
        if (debug)
            console.info("kristall-assistant: connection lost; socket exists:", socketExists, "retry running:", retry.running, "backoff:", _backoff);
        if (connected && busy)
            lostTurn = true;
        connected = false;
        state = "idle";
        level = 0;
        if (cursor && cursor.visible) {
            cursor = Object.assign({}, cursor, { visible: false });
            cursorEvent({ visible: false }, Date.now());
        }
        permissions = [];
        if (!retry.running && (socketExists || !Helper.ready))
            retry.start();
    }

    // ---- socket -------------------------------------------------------------------------------
    // A fresh Socket object per connection attempt: after a refused connect, re-arming the same
    // Quickshell Socket does not always start a new attempt (seen with Quickshell 0.2.1).
    property int _backoff: 200
    property var sock: null
    readonly property bool sockConnected: sock !== null && sock.connected
    property Component _sockComponent: Component {
        Socket {
            id: s
            path: client.socketPath
            connected: false
            onConnectedChanged: {
                if (s !== client.sock)
                    return;
                if (connected) {
                    client.retry.stop();
                    client._backoff = 200;
                    client.lastSeq = -1;
                    client.send({ type: "hello", client: "kristall-shell", role: "ui", subscribe: ["levels"] });
                } else {
                    client._lost();
                }
            }
            onError: if (s === client.sock) client._lost()
            parser: SplitParser {
                onRead: data => { if (s === client.sock) client._handle(data); }
            }
        }
    }
    function connectNow() {
        if (sock && sock.connected)
            return;
        const old = sock;
        sock = _sockComponent.createObject(client);
        if (old)
            old.destroy();
        sock.connected = true;
    }

    property Timer retry: Timer {
        interval: client._backoff
        onTriggered: {
            if (client.debug)
                console.info("kristall-assistant: retry; socket exists:", client.socketExists);
            client._backoff = Math.min(client._backoff * 2, 5000);
            if (Helper.ready && !client.socketExists)
                return;           // the helper tells us when the socket appears
            client.connectNow();
        }
    }
    // without the helper: try plainly once after start-up, then back off
    property Timer noHelper: Timer {
        interval: 2500
        onTriggered: if (!Helper.ready && !client.sockConnected) client.connectNow()
    }
    property Connections helperConn: Connections {
        target: Helper
        function onEvent(ev) {
            if (ev.event !== "socket" || ev.path !== client.socketPath)
                return;
            if (client.debug)
                console.info("kristall-assistant: socket", ev.exists ? "appeared" : "gone");
            client.socketExists = ev.exists;
            if (ev.exists && !client.sockConnected) {
                client._backoff = 200;
                client.connectNow();
                // the daemon creates the socket before it accepts; retry briefly if refused
                if (!client.sockConnected && !client.retry.running)
                    client.retry.start();
            } else if (!ev.exists) {
                client.retry.stop();
            }
        }
        function onReadyChanged() {
            if (Helper.ready)
                Helper.request("watch.socket", { path: client.socketPath });
        }
    }
    Component.onCompleted: {
        Helper.request("watch.socket", { path: socketPath });
        noHelper.start();
    }
}
