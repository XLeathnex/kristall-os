// SPDX-License-Identifier: GPL-3.0-or-later
// "Sign in with Claude", entirely graphical, through the assistant daemon's account commands
// (docs/contracts/assistant-ipc.md §9): status → install (Anthropic's official installer) →
// login (the browser opens; a code can be pasted if the browser shows one) → ready. Every
// failure ends in a plain sentence and a "Try Again"; cancel and skip are always possible.
import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: acc
    readonly property string tool: Quickshell.env("KRISTALL_ASSISTANT_ACCOUNT") || "kristall-assistant-account"

    // idle | checking | working | browser | ready | failed | cancelled
    property string phase: "idle"
    property string status: ""          // account status: ready, cli_missing, cli_outdated, signed_out, unknown
    property string stage: ""           // progress stage of the running command
    property real percent: -1
    property string url: ""
    property bool needCode: false
    property var error: null            // {code, message{de,en}}
    property string failedStep: ""      // install | update | login
    property var log: []
    property string _cmd: ""

    function check() {
        if (proc.running)
            return;
        phase = "checking";
        _launch(["status"]);
    }
    function signIn() {
        error = null;
        failedStep = "";
        url = "";
        needCode = false;
        if (status === "ready") {
            phase = "ready";
            return;
        }
        if (status === "cli_missing")
            _launch(["install"]);
        else if (status === "cli_outdated")
            _launch(["update"]);
        else
            _launch(["login", "--open"]);
        phase = "working";
    }
    function sendCode(code) {
        if (proc.running && code.trim() !== "") {
            proc.write(JSON.stringify({ code: code.trim() }) + "\n");
            needCode = false;
            stage = "code_received";
        }
    }
    function cancel() {
        if (proc.running) {
            _cancelled = true;
            proc.running = false;
        }
    }
    function openBrowser() {
        if (url !== "")
            Quickshell.execDetached(["xdg-open", url]);
    }
    property bool _cancelled: false

    function _launch(args) {
        _cmd = args[0];
        _cancelled = false;
        stage = args[0] === "install" ? "download_installer" : args[0] === "update" ? "updating" : args[0] === "login" ? "waiting_for_browser" : "";
        percent = -1;
        proc.command = [tool].concat(args);
        proc.running = true;
    }
    function _event(m) {
        switch (m.event) {
        case "progress":
            stage = m.stage || stage;
            percent = m.percent !== undefined ? m.percent : -1;
            if (stage === "waiting_for_browser")
                phase = "browser";
            break;
        case "open_url":
            url = m.url || "";
            phase = "browser";
            break;
        case "need_code":
            needCode = true;
            phase = "browser";
            break;
        case "status":
            status = m.status || status;
            break;
        case "log":
            log = log.slice(-40).concat([m.line]);
            break;
        case "result":
            _result(m);
            break;
        }
    }
    property var _last: null
    function _result(m) {
        _last = m;
        if (m.status && m.status.status)
            status = m.status.status;
    }
    function _finished(code) {
        const m = _last;
        _last = null;
        const cmd = _cmd;
        _cmd = "";
        if (_cancelled) {
            phase = "cancelled";
            stage = "";
            return;
        }
        if (cmd === "status") {
            phase = status === "ready" ? "ready" : "idle";
            return;
        }
        if (m && m.ok) {
            // installed or updated: go on to sign in; signed in: done
            if ((cmd === "install" || cmd === "update") && status !== "ready") {
                _launch(["login", "--open"]);
                return;
            }
            phase = status === "ready" || cmd === "login" ? "ready" : "idle";
            if (cmd === "login")
                status = "ready";
            stage = "done";
            return;
        }
        error = m && m.error ? m.error : { code: code === 0 ? "" : "failed" };
        failedStep = cmd;
        phase = "failed";
    }

    Process {
        id: proc
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => {
                try {
                    acc._event(JSON.parse(line));
                } catch (e) {
                    // not JSON: ignore (the contract says every line is JSON)
                }
            }
        }
        onExited: code => acc._finished(code)
    }
}
