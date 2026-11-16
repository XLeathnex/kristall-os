// SPDX-License-Identifier: GPL-3.0-or-later
// The microphone check: a short connection to the assistant daemon (assistant.sock) while the
// step is on screen. "Start listening" sends a voice `invoke` that is not spoken; the live
// transcript is shown; as soon as the final transcript arrives the turn is cancelled, so the
// owner's words are only recognised (on the laptop), not answered. Connected only while active.
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
    property string errorCode: ""

    readonly property bool ready: connected && haveSnapshot && (account === "ready" || account === "unknown" || demo) && voiceInput

    onActiveChanged: {
        if (active) {
            phase = "idle";
            transcript = "";
            sock.connected = true;
        } else {
            if (phase === "listening")
                send({ type: "cancel" });
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
        phase = "listening";
        send({ type: "invoke", id: "setup-mic", mode: "voice", source: "setup", speak: false, new_conversation: true });
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
            if (m.id === "setup-mic" && m.ok)
                turnId = m.turn_id || "";
            break;
        case "level":
            level = m.value || 0;
            break;
        case "transcript":
            if (phase === "listening" && (turnId === "" || m.turn_id === turnId)) {
                transcript = m.text || "";
                if (m.final) {
                    phase = transcript.trim() !== "" ? "heard" : "nothing";
                    _done();
                }
            }
            break;
        case "error":
            if (phase === "listening" && (m.turn_id === turnId || m.turn_id === null)) {
                errorCode = m.code || "";
                phase = m.code === "nothing_heard" ? "nothing" : "error";
                _done();
            }
            break;
        case "turn_finished":
            if (phase === "listening" && m.turn_id === turnId) {
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
