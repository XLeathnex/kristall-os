// SPDX-License-Identifier: GPL-3.0-or-later
// The microphone check: a short connection to the assistant daemon (assistant.sock) while the
// step is on screen. "Start listening" sends `transcribe` (assistant-ipc.md §4): the microphone
// opens, speech recognition runs on the laptop, the live level and the words are shown — no turn,
// nothing is sent to Claude, so it works before the owner has signed in. A daemon that does not
// know `transcribe` (older) gets the earlier way: a voice turn that is cancelled as soon as the
// words are known (needs the sign-in). Connected only while active.
import QtQuick
import Quickshell
import Quickshell.Io
import qs.services

Scope {
    id: mic
    property bool active: false
    readonly property string path: Quickshell.env("KRISTALL_ASSISTANT_SOCKET") || ((Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/kristall/assistant.sock")

    property bool connected: false
    property bool haveSnapshot: false
    property string account: ""          // the daemon's account status
    property bool voiceInput: true
    property bool demo: false
    // idle | listening | heard | nothing | error
    property string phase: "idle"
    property string transcript: ""
    property real level: 0
    property string turnId: ""
    property string transcriptionId: ""
    property string errorCode: ""
    property bool transcribeSupported: true   // false once the daemon refused `transcribe` as unknown

    readonly property bool accountReady: account === "ready" || account === "unknown" || demo
    readonly property bool ready: connected && haveSnapshot && voiceInput && (transcribeSupported || accountReady)

    onActiveChanged: {
        if (active) {
            phase = "idle";
            transcript = "";
            sock.connected = true;
        } else {
            if (phase === "listening")
                send(transcriptionId !== "" || transcribeSupported ? { type: "transcribe_cancel" } : { type: "cancel" });
            sock.connected = false;
            connected = false;
            haveSnapshot = false;
        }
    }

    function send(obj) {
        if (sock.connected)
            sock.write(JSON.stringify(obj) + "\n");
    }
    function listen() {
        transcript = "";
        errorCode = "";
        level = 0;
        phase = "listening";
        transcriptionId = "";
        turnId = "";
        if (transcribeSupported)
            send({ type: "transcribe", id: "setup-mic", no_speech_timeout_seconds: 8, max_seconds: 20 });
        else
            _listenTurn();
    }
    function _listenTurn() {
        send({ type: "invoke", id: "setup-mic-turn", mode: "voice", source: "setup", speak: false, new_conversation: true });
    }
    function _done() {
        send({ type: "cancel" });
        send({ type: "new_conversation" });
        // the assistant's own panel opened for this turn: put it away again
        ShellBus.request("assistant", "dismiss", "", "");
    }

    function _handle(line) {
        let m;
        try {
            m = JSON.parse(line);
        } catch (e) {
            return;
        }
        switch (m.type) {
        case "hello":
            demo = m.demo === true;
            break;
        case "snapshot":
            haveSnapshot = true;
            account = m.account ? String(m.account.status || "") : "";
            voiceInput = !m.voice || m.voice.input !== false;
            break;
        case "account":
            account = String(m.status || "");
            break;
        case "ack":
            if (m.id === "setup-mic") {
                if (m.ok) {
                    transcriptionId = m.transcription_id || "";
                } else if (m.code === "unknown_type") {
                    transcribeSupported = false;        // an older daemon: the voice-turn way
                    if (phase === "listening") {
                        if (accountReady)
                            _listenTurn();
                        else
                            phase = "idle";
                    }
                } else if (phase === "listening") {
                    errorCode = m.code || "";           // busy: the assistant is in a turn right now
                    phase = "error";
                }
            } else if (m.id === "setup-mic-turn" && m.ok) {
                turnId = m.turn_id || "";
            }
            break;
        case "level":
            if (phase === "listening" && (m.source === undefined || m.source === "mic"))
                level = m.value || 0;
            break;
        case "transcription":
            if (phase === "listening" && (transcriptionId === "" || m.transcription_id === transcriptionId))
                transcript = m.text || "";
            break;
        case "transcription_finished":
            if (phase === "listening" && (transcriptionId === "" || m.transcription_id === transcriptionId)) {
                level = 0;
                if (m.outcome === "completed") {
                    transcript = m.text || transcript;
                    phase = transcript.trim() !== "" ? "heard" : "nothing";
                } else if (m.outcome === "nothing_heard") {
                    phase = "nothing";
                } else if (m.outcome === "cancelled") {
                    phase = "idle";
                } else {
                    errorCode = m.error_code || "internal";
                    phase = "error";
                }
            }
            break;
        case "transcript":           // the voice-turn way (older daemon)
            if (phase === "listening" && transcriptionId === "" && !transcribeSupported && (turnId === "" || m.turn_id === turnId)) {
                transcript = m.text || "";
                if (m.final) {
                    phase = transcript.trim() !== "" ? "heard" : "nothing";
                    _done();
                }
            }
            break;
        case "error":
            if (phase === "listening" && !transcribeSupported && (m.turn_id === turnId || m.turn_id === null)) {
                errorCode = m.code || "";
                phase = m.code === "nothing_heard" ? "nothing" : "error";
                _done();
            }
            break;
        case "turn_finished":
            if (phase === "listening" && !transcribeSupported && m.turn_id === turnId) {
                phase = transcript.trim() !== "" ? "heard" : "nothing";
                _done();
            }
            break;
        }
    }

    Socket {
        id: sock
        path: mic.path
        connected: false
        onConnectedChanged: {
            mic.connected = connected;
            if (connected) {
                mic.send({ type: "hello", client: "kristall-setup", role: "ui" });
                mic.send({ type: "subscribe", levels: true });
            } else if (mic.active) {
                retry.start();
            }
        }
        onError: if (mic.active) retry.start()
        parser: SplitParser {
            onRead: data => mic._handle(data)
        }
    }
    Timer {
        id: retry
        interval: 2000
        onTriggered: if (mic.active && !sock.connected) sock.connected = true
    }
}
