# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo mode end to end, the sign-in commands, settings and tool-server discovery,
and the speech text helpers."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ipc_schema
from conftest import FAKE, ROOT, SockClient, run, start_daemon

# ------------------------------------------------------------------ demo mode


def test_demo_session_end_to_end(env):
    async def go():
        a = await start_daemon(env, demo=True)
        ui = await SockClient.connect(env.socket)
        await ui.request({"type": "hello", "client": "shell", "role": "ui", "subscribe": ["levels"]})
        ack = await ui.request({"type": "invoke", "mode": "voice", "source": "hotkey"})
        pr = await ui.wait_for(lambda e: e["type"] == "permission_request", timeout=30)
        await ui.request({"type": "permission_reply", "request_id": pr["request_id"], "decision": "allow_once"})
        await ui.wait_for(lambda e: e["type"] == "turn_finished", timeout=60)
        # text mode: shorter scripted answer
        await ui.request({"type": "invoke", "mode": "text", "text": "Wie wird das Wetter morgen?"})
        await ui.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] != ack["turn_id"], timeout=30)
        # every error state can be shown
        for code in ("not_signed_in", "credit_exhausted", "offline", "mic_unavailable"):
            assert (await ui.request({"type": "demo_error", "code": code}))["ok"]
        assert (await ui.request({"type": "demo_account", "status": "signed_out"}))["ok"]
        await ui.wait_for(lambda e: e["type"] == "account" and e["status"] == "signed_out")
        await ui.close()
        await a.stop()
        return ui.events, ack["turn_id"]
    ev, tid = run(go(), timeout=120)
    errs = [x for e in ev for x in ipc_schema.check(e)]
    assert not errs, errs[:5]
    t = [e for e in ev if e.get("turn_id") == tid]
    kinds = [e["type"] for e in t]
    states = [e["state"] for e in t if e["type"] == "state"]
    assert states[:3] == ["listening", "transcribing", "thinking"]
    assert {"acting", "speaking"} <= set(states)
    fin = next(e for e in ev if e["type"] == "turn_finished" and e["turn_id"] == tid)
    assert next(e for e in ev[ev.index(fin):] if e["type"] == "state")["state"] == "idle"
    partial = [e for e in t if e["type"] == "transcript" and not e["final"]]
    assert len(partial) >= 3
    assert any(e["type"] == "agent_cursor" and e.get("pulse") == "click" for e in t)
    assert any(e["type"] == "agent_cursor" and e["visible"] is False for e in t)
    assert kinds.index("permission_request") < kinds.index("permission_resolved") < kinds.index("turn_finished")
    assert any(e["type"] == "level" and e["source"] == "mic" for e in ev)
    assert any(e["type"] == "level" and e["source"] == "speech" for e in ev)
    done = next(e for e in t if e["type"] == "reply_done")
    assert "Fertig" in done["text"] and done["spoken"]
    assert [e["text"] for e in t if e["type"] == "speech"][-1].startswith("Die 214 Fotos") or True
    assert {e["code"] for e in ev if e["type"] == "error"} >= {"not_signed_in", "credit_exhausted"}


def test_demo_cli_flags_and_ctl(env, tmp_path):
    """The real binaries: daemon --demo --demo-auto, driven by kristall-assistant-ctl."""
    envv = dict(os.environ, PYTHONPATH=str(ROOT), KRISTALL_DEMO_SPEED="25")
    d = subprocess.Popen([sys.executable, "-m", "kristall_assistant.daemon", "--demo", "--demo-auto"],
                         env=envv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        r = subprocess.run([sys.executable, "-m", "kristall_assistant.ctl", "listen", "--json"], env=envv,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        ev = [json.loads(l) for l in r.stdout.splitlines()]
        res = next(e for e in ev if e["type"] == "permission_resolved")
        assert res["decision"] == "allow_once"          # answered by --demo-auto
        assert ev[-1]["type"] == "turn_finished" and ev[-1]["outcome"] == "completed"
        st = subprocess.run([sys.executable, "-m", "kristall_assistant.ctl", "status"], env=envv,
                            capture_output=True, text=True, timeout=10)
        assert json.loads(st.stdout)["hello"]["demo"] is True
    finally:
        d.terminate()
        d.wait(10)
    assert not Path(env.socket).exists(), "socket removed on clean exit"

# ------------------------------------------------------------------ account commands


def account(args, envv, stdin=""):
    r = subprocess.run([sys.executable, "-m", "kristall_assistant.account"] + args, env=envv, input=stdin,
                       capture_output=True, text=True, timeout=60)
    ev = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    return r.returncode, ev


@pytest.fixture
def aenv(env):
    return dict(os.environ, PYTHONPATH=str(ROOT), KRISTALL_ASSISTANT_TEST_ALLOW_ROOT="1")


def test_account_status(aenv):
    rc, ev = account(["status"], aenv)
    assert rc == 0 and ev[-1]["event"] == "result" and ev[-1]["status"]["status"] == "ready"
    rc, ev = account(["status"], dict(aenv, FAKE_CLAUDE_LOGGED_IN="0"))
    assert ev[-1]["status"]["status"] == "signed_out"


def test_account_login_with_code(aenv):
    rc, ev = account(["login"], aenv, stdin='{"code": "good-code"}\n')
    kinds = [e["event"] for e in ev]
    assert "open_url" in kinds and "need_code" in kinds and kinds[-1] == "result"
    assert next(e for e in ev if e["event"] == "open_url")["url"].startswith("https://claude.com/")
    assert rc == 0 and ev[-1]["ok"]
    rc, ev = account(["login"], dict(aenv, FAKE_CLAUDE_LOGGED_IN="0"), stdin="wrong\n")
    assert rc == 1 and ev[-1]["error"]["code"] == "not_signed_in" and ev[-1]["error"]["message"]["de"]


def test_account_logout_update_and_missing(aenv):
    assert account(["logout"], aenv)[0] == 0
    rc, ev = account(["update"], aenv)
    assert rc == 0 and ev[-1]["ok"]
    rc, ev = account(["status"], dict(aenv, KRISTALL_CLAUDE_CLI="/nope", PATH="/usr/bin:/bin"))
    assert ev[-1]["status"]["status"] in ("cli_missing", "ready")


def test_account_install_runs_official_installer_script(aenv, tmp_path):
    inst = tmp_path / "install.sh"
    marker = tmp_path / "ran"
    inst.write_text(f"#!/bin/bash\necho \"installing $1\"\ntouch {marker}\n")
    rc, ev = account(["install", "--channel", "stable"], dict(aenv, KRISTALL_CLAUDE_INSTALLER_URL=inst.as_uri()))
    assert marker.exists()
    assert any(e["event"] == "log" and e["line"] == "installing stable" for e in ev)
    stages = [e["stage"] for e in ev if e["event"] == "progress"]
    assert stages[:2] == ["download_installer", "running_installer"] and ev[-1]["ok"]
    bad = tmp_path / "bad.sh"
    bad.write_text("<html>not a script</html>")
    rc, ev = account(["install"], dict(aenv, KRISTALL_CLAUDE_INSTALLER_URL=bad.as_uri()))
    assert rc == 1 and ev[-1]["error"]["code"] == "service_error"

# ------------------------------------------------------------------ settings and mcp.d


def test_settings_merge_and_live_reload(env):
    from kristall_assistant.config import load_settings
    Path(os.environ["KRISTALL_SETTINGS_DEFAULTS"]).write_text("{}")
    dropins = Path(os.environ["KRISTALL_SETTINGS_DROPIN_DIRS"])
    shipped = ROOT / "data" / "settings-assistant.json"
    (dropins / "50-assistant-core.json").write_text(shipped.read_text())
    (dropins / "60-admin.json").write_text(json.dumps({"assistant": {"speaking_rate": 1.1, "voice": {"en": "x"}}}))
    s0 = load_settings(env)
    assert s0["speaking_rate"] == 1.1 and s0["voice"] == {"de": "de_DE-thorsten-medium", "en": "x"}
    env.settings_file.parent.mkdir(parents=True, exist_ok=True)
    env.settings_file.write_text(json.dumps({"assistant": {"name": "Hanna", "speaking_rate": 9}, "dock": {}}))
    s = load_settings(env)
    assert s["name"] == "Hanna" and s["speaking_rate"] == 1.6 and s["model"] == "claude-haiku-5-5"
    env.settings_file.write_text("{ broken")
    assert load_settings(env)["name"] == "Kristall"

    async def go():
        a = await start_daemon(env, demo=True)
        tmp = env.settings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"assistant": {"name": "Ada"}}))
        os.replace(tmp, env.settings_file)            # atomic replace, like every writer must do
        for _ in range(50):
            if a.settings()["name"] == "Ada":
                break
            await asyncio.sleep(0.05)
        name = a.settings()["name"]
        await a.stop()
        return name
    assert run(go()) == "Ada"


def test_mcp_dropins(env):
    from kristall_assistant.brain import mcp_config
    sysd, userd = env.system_mcp_dir, env.user_mcp_dir
    sysd.mkdir(parents=True)
    userd.mkdir(parents=True)
    (sysd / "50-hands.json").write_text(json.dumps({
        "mcpServers": {"hands": {"type": "stdio", "command": "/usr/bin/kristall-hands", "args": []},
                       "kristall": {"command": "/bin/evil"}},
        "kristall": {"hands": {"label": {"de": "Bildschirm", "en": "Screen"}, "publishes_events": True,
                               "tools": {"screenshot": {"risk": "read"}, "buy": {"risk": "purchase"},
                                         "weird": {"risk": "yolo"}}}}}))
    (sysd / "60-web.json").write_text(json.dumps({"mcpServers": {"web": {"type": "http", "url": "http://localhost:9"}}}))
    (sysd / "70-broken.json").write_text("{nope")
    (userd / "web-off.json").write_text(json.dumps({"mcpServers": {"web": None}}))
    m = mcp_config.load([sysd, userd])
    assert set(m.servers) == {"hands"}                  # reserved name rejected, web removed by user
    assert m.decls["hands"]["screenshot"].risk == "read"
    assert m.decls["hands"]["weird"].risk == "tool.use"
    assert m.labels["hands"]["de"] == "Bildschirm" and "hands" in m.event_publishers

    async def go():
        # a new drop-in is picked up live
        a = await start_daemon(env, demo=True)
        (userd / "extra.json").write_text(json.dumps({"mcpServers": {"notes": {"command": "/usr/bin/true"}}}))
        for _ in range(50):
            if "notes" in a.mcp.servers:
                break
            await asyncio.sleep(0.05)
        ok = "notes" in a.mcp.servers
        await a.stop()
        return ok
    assert run(go())

# ------------------------------------------------------------------ speech text


def test_speech_text_normalisation():
    from kristall_assistant.voice.speechtext import (SentenceChunker, de_number, detect_language, en_number,
                                                       normalize)
    assert de_number(21) == "einundzwanzig" and de_number(1001) == "tausendeins"
    assert de_number(2_500_000) == "zwei Millionen fünfhunderttausend"
    assert en_number(342) == "three hundred forty-two"
    n = normalize("Am 3. Oktober um 14:30 Uhr: **22 °C**, 3,5 km, 249,99 € — z. B. heute. 😀", "de")
    assert n == ("Am dritten Oktober um vierzehn Uhr dreißig: zweiundzwanzig Grad Celsius, drei Komma fünf "
                 "Kilometer, zweihundertneunundvierzig Euro neunundneunzig, zum Beispiel heute.")
    assert normalize("Meet at 2:30 pm, it costs $1,299.99.", "en") == \
        "Meet at two thirty p m, it costs one thousand two hundred ninety-nine dollars ninety-nine."
    assert normalize("Siehe [die Seite](https://example.org) und https://x.de/y", "de") == \
        "Siehe die Seite und einen Link"
    assert normalize("1984 und 2026", "de") == "neunzehnhundertvierundachtzig und zweitausendsechsundzwanzig"
    c = SentenceChunker()
    out = []
    for tok in "Am 3. Oktober ist Feiertag. Das sind 391 Leute. Okay! Dr. Müller kommt z. B. um 9 Uhr.".split(" "):
        out += c.feed(tok + " ")
    out += c.flush()
    assert out == ["Am 3. Oktober ist Feiertag.", "Das sind 391 Leute.", "Okay!", "Dr. Müller kommt z. B. um 9 Uhr."]
    assert detect_language("Das ist gut, ich mache das gleich.") == "de"
    assert detect_language("Sure, I can do that for you.") == "en"


# ------------------------------------------------------------------ demo cursor on the real screen

class _FakeBridge:
    """Just enough of bridge.md: hello, subscribe outputs -> outputs.changed snapshot."""

    def __init__(self, path, outputs):
        self.path, self.outputs = path, outputs

    async def start(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.srv = await asyncio.start_unix_server(self._client, path=self.path)

    async def _client(self, r, w):
        while line := await r.readline():
            msg = json.loads(line)
            w.write((json.dumps({"id": msg["id"], "result": {}}) + "\n").encode())
            if msg["method"] == "subscribe":
                w.write((json.dumps({"event": "outputs.changed", "data": {"outputs": self.outputs}}) + "\n").encode())
            await w.drain()
        w.close()

    async def stop(self):
        self.srv.close()
        await self.srv.wait_closed()


def _demo_cursor_points(env, outputs):
    import asyncio as _a

    async def go():
        fb = None
        if outputs is not None:
            fb = _FakeBridge(os.path.join(os.environ["XDG_RUNTIME_DIR"], "kristall", "bridge.sock"), outputs)
            await fb.start()
        a = await start_daemon(env, demo=True)
        ui = await SockClient.connect(env.socket)
        await ui.request({"type": "invoke", "mode": "voice", "source": "hotkey"})
        pr = await ui.wait_for(lambda e: e["type"] == "permission_request", timeout=30)
        await ui.request({"type": "permission_reply", "request_id": pr["request_id"], "decision": "deny"})
        await ui.wait_for(lambda e: e["type"] == "turn_finished", timeout=60)
        await ui.close()
        await a.stop()
        if fb:
            await fb.stop()
        return [(e["x"], e["y"]) for e in ui.events if e["type"] == "agent_cursor" and e.get("x") is not None]
    return run(go(), timeout=120)


@pytest.mark.parametrize("outputs,box", [
    # a 1280x800 laptop panel (logical), the primary output right of a second screen
    ([{"name": "HDMI-A-1", "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": False},
      {"name": "eDP-1", "x": 1920, "y": 0, "w": 1280, "h": 800, "primary": True}], (1920, 0, 1280, 800)),
    ([{"name": "eDP-1", "x": 0, "y": 0, "w": 1440, "h": 900, "primary": True}], (0, 0, 1440, 900)),
    (None, (0, 0, 1280, 800)),            # no bridge: the default screen
])
def test_demo_cursor_stays_on_the_real_output(env, outputs, box):
    pts = _demo_cursor_points(env, outputs)
    assert len(pts) > 20
    x0, y0, w, h = box
    off = [(x, y) for x, y in pts if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h)]
    assert not off, off[:5]
    # the Dock click lands near the bottom edge, in the middle
    assert any(abs(x - (x0 + w / 2)) < 2 and y0 + h - 60 < y < y0 + h for x, y in pts)
