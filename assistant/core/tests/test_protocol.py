# SPDX-License-Identifier: GPL-3.0-or-later
"""Protocol conformance: the daemon against docs/contracts/assistant-ipc.md."""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import stat
from pathlib import Path

import pytest

import ipc_schema
from conftest import ROOT, SockClient, run, start_daemon

CONTRACT = ROOT.parent.parent / "docs" / "contracts" / "assistant-ipc.md"


def assert_conforms(events):
    errs = []
    for e in events:
        errs += ipc_schema.check(e)
    assert not errs, errs[:10]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "seq must increase"


def test_contract_documents_exactly_the_events():
    doc = CONTRACT.read_text(encoding="utf-8")
    sect = doc.split("## 5.")[1].split("\n## 6.")[0]
    documented = set(re.findall(r"^### `([a-z_]+)`", sect, re.M))
    assert documented == set(ipc_schema.EVENTS), (documented ^ set(ipc_schema.EVENTS))
    req = doc.split("## 4.")[1].split("\n## 5.")[0]
    documented_req = set(re.findall(r"^### `([a-z_]+)`", req, re.M))
    from kristall_assistant.daemon import Assistant
    handled = {n[3:] for n in dir(Assistant) if n.startswith("_m_")}
    assert documented_req == handled, documented_req ^ handled
    for code in __import__("kristall_assistant.errors", fromlist=["ERRORS"]).ERRORS:
        assert f"`{code}`" in doc, f"error code {code} not documented"


def test_handshake_ack_and_errors(env):
    async def go():
        a = await start_daemon(env)
        st = os.stat(env.socket)
        assert stat.S_IMODE(st.st_mode) == 0o600
        assert stat.S_IMODE(os.stat(env.socket.parent).st_mode) == 0o700
        c = await SockClient.connect(env.socket)
        await c.wait_for(lambda e: e["type"] == "snapshot")
        assert c.events[0]["type"] == "hello" and c.events[0]["protocol"] == 1
        ack = await c.request({"type": "hello", "client": "test", "role": "ui"})
        assert ack["ok"] is True
        ack = await c.request({"type": "no_such_thing"})
        assert ack["ok"] is False and ack["code"] == "unknown_type"
        ack = await c.request({"type": "invoke", "mode": "text", "text": ""})
        assert ack["ok"] is False and ack["code"] == "bad_request"
        ack = await c.request({"type": "permission_reply", "request_id": "nope", "decision": "allow_once"})
        assert ack["code"] == "unknown_request"
        c.w.write(b"this is not json\n")
        await c.wait_for(lambda e: e.get("type") == "ack" and e.get("code") == "bad_json")
        c.w.write(b"[1,2]\n")
        await c.wait_for(lambda e: e.get("type") == "ack" and e.get("code") == "bad_json" and e is not c.events[-2])
        # the daemon is still fine
        ack = await c.request({"type": "get_snapshot"})
        assert ack["ok"]
        assert_conforms(c.events)
        await c.close()
        await a.stop()
    run(go())


def test_oversized_line_disconnects_only_that_client(env):
    async def go():
        a = await start_daemon(env)
        c1 = await SockClient.connect(env.socket)
        c2 = await SockClient.connect(env.socket)
        await c1.wait_for(lambda e: e["type"] == "snapshot")
        c1.w.write(b'{"type":"hello","x":"' + b"a" * (1 << 20 + 1) + b'"}\n')
        await c1.wait_for(lambda e: e.get("type") == "error" and e.get("code") == "bad_request")
        ack = await c2.request({"type": "get_snapshot"})
        assert ack["ok"]
        await c1.close()
        await c2.close()
        await a.stop()
    run(go())


def test_connect_before_ready_and_reconnect(env):
    """Clients retry with backoff; a restarted daemon replaces a stale socket."""
    async def go():
        a = await start_daemon(env)
        await a.stop()
        # stale socket file left by a crash
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(env.socket))
        s.close()
        a2 = await start_daemon(env)
        c = await SockClient.connect(env.socket)
        await c.wait_for(lambda e: e["type"] == "snapshot")
        # a second daemon refuses to steal a live socket
        from kristall_assistant.daemon import Assistant
        with pytest.raises(RuntimeError):
            await Assistant(env).start()
        await c.close()
        await a2.stop()
    run(go())


def test_text_turn_event_order_and_fanout(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_simple_followup")

    async def go():
        a = await start_daemon(env)
        await a.refresh_account()
        ui = await SockClient.connect(env.socket)
        other = await SockClient.connect(env.socket)
        ack = await ui.request({"type": "invoke", "mode": "text", "text": "Wie heißt die Hauptstadt von Australien?"})
        tid = ack["turn_id"]
        await ui.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] == tid)
        await other.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] == tid)
        ack2 = await ui.request({"type": "invoke", "mode": "text", "text": "Und wie viele Leute wohnen da?"})
        await ui.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] == ack2["turn_id"])
        await ui.close()
        await other.close()
        await a.stop()
        return ui.events, other.events, tid, ack2["turn_id"]
    ev, ev2, tid, tid2 = run(go())
    assert_conforms(ev)
    seq = [e["type"] for e in ev if e.get("turn_id") == tid and e["type"] != "ack"]
    assert seq[0] == "turn_started"
    assert seq.index("conversation") < seq.index("reply_delta") < seq.index("reply_done") < seq.index("turn_finished")
    states = [e["state"] for e in ev if e["type"] == "state"]
    assert states[:2] == ["thinking", "idle"]
    fin = [e for e in ev if e["type"] == "turn_finished"]
    assert fin[0]["outcome"] == "completed" and fin[0]["error_code"] is None
    done = next(e for e in ev if e["type"] == "reply_done" and e["turn_id"] == tid)
    assert done["text"] == "".join(e["text"] for e in ev if e["type"] == "reply_delta" and e["turn_id"] == tid)
    assert done["spoken"] is False
    conv = [e for e in ev if e["type"] == "conversation"]
    assert conv[0]["continued"] is False and conv[1]["continued"] is True
    # both clients saw the same stream (levels aside)
    strip = lambda es: [e["seq"] for e in es if e["type"] not in ("ack", "hello", "snapshot")]
    assert strip(ev) == strip(ev2)


def test_permission_round_trip_over_socket(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_delete_permission")

    async def go():
        a = await start_daemon(env)
        await a.refresh_account()
        c = await SockClient.connect(env.socket)
        ack = await c.request({"type": "invoke", "mode": "text", "text": "Lösch alt.txt endgültig"})
        pr = await c.wait_for(lambda e: e["type"] == "permission_request")
        st = await c.wait_for(lambda e: e["type"] == "state" and e.get("detail") == "waiting_for_permission")
        assert st["state"] == "acting"
        snap = a.snapshot()
        assert snap["pending_permissions"][0]["request_id"] == pr["request_id"]
        r = await c.request({"type": "permission_reply", "request_id": pr["request_id"], "decision": "allow_once"})
        assert r["ok"]
        res = await c.wait_for(lambda e: e["type"] == "permission_resolved")
        await c.wait_for(lambda e: e["type"] == "turn_finished")
        await c.close()
        await a.stop()
        return c.events, pr, res
    ev, pr, res = run(go())
    assert_conforms(ev)
    assert pr["question"]["de"] == "Darf ich „alt.txt“ endgültig löschen?"
    assert pr["category"] == "files.delete" and pr["can_always"] is True
    assert pr["options"] == ["allow_once", "allow_always", "deny"]
    assert "rm" in pr["technical"] and pr["explanation"]
    assert res["decision"] == "allow_once" and res["by"] == "owner"


def test_permission_timeout_denies(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_delete_denied")

    async def go():
        a = await start_daemon(env)
        a._settings["permission_timeout_seconds"] = 0.3
        await a.refresh_account()
        c = await SockClient.connect(env.socket)
        await c.request({"type": "invoke", "mode": "text", "text": "Lösch alt.txt"})
        res = await c.wait_for(lambda e: e["type"] == "permission_resolved")
        await c.wait_for(lambda e: e["type"] == "turn_finished")
        await c.close()
        await a.stop()
        return res
    res = run(go())
    assert res["decision"] == "deny" and res["by"] == "timeout"


def test_cancel_and_barge_in(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")

    async def go():
        a = await start_daemon(env)
        await a.refresh_account()
        c = await SockClient.connect(env.socket)
        t1 = (await c.request({"type": "invoke", "mode": "text", "text": "Erzähl"}))["turn_id"]
        await c.wait_for(lambda e: e["type"] == "reply_delta")
        # a new request interrupts the running one
        t2 = (await c.request({"type": "invoke", "mode": "text", "text": "Stopp, was anderes"}))["turn_id"]
        f1 = await c.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] == t1)
        await c.wait_for(lambda e: e["type"] == "reply_delta" and e["turn_id"] == t2)
        n = len(c.events)
        await c.request({"type": "cancel"})
        f2 = await c.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] == t2)
        idle = await c.wait_for(lambda e: e["type"] == "state" and e["state"] == "idle", start=n)
        late = [e for e in c.events[c.events.index(f2):] if e["type"] == "reply_delta"]
        await c.close()
        await a.stop()
        return f1, f2, late, c.events
    f1, f2, late, ev = run(go())
    assert f1["outcome"] == "cancelled" and f2["outcome"] == "cancelled"
    assert not late
    assert_conforms(ev)


@pytest.mark.parametrize("mode,code,action", [
    ("not_signed_in", "not_signed_in", "sign_in"), ("rate_limited", "rate_limited", None),
    ("credit_exhausted", "credit_exhausted", None), ("offline", "offline", None),
    ("overloaded", "overloaded", None), ("refusal", "refused", None), ("crash", "brain_crashed", None),
])
def test_error_events(env, monkeypatch, mode, code, action):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)

    async def go():
        a = await start_daemon(env)
        await a.refresh_account()
        c = await SockClient.connect(env.socket)
        await c.request({"type": "invoke", "mode": "text", "text": "Hallo"})
        err = await c.wait_for(lambda e: e["type"] == "error")
        fin = await c.wait_for(lambda e: e["type"] == "turn_finished")
        await c.close()
        await a.stop()
        return err, fin, c.events
    err, fin, ev = run(go(), timeout=40)
    assert err["code"] == code and err["action"] == action
    assert err["message"]["de"] and err["message"]["en"] and "Traceback" not in err["message"]["de"]
    assert fin["outcome"] == "error" and fin["error_code"] == code
    assert ev.index(err) < ev.index(fin)
    assert_conforms(ev)


@pytest.mark.parametrize("version,logged_in,code", [
    ("1.0.0 (Claude Code)", "1", "cli_outdated"), ("2.1.325 (Claude Code)", "0", "not_signed_in"),
])
def test_account_states_block_turns_with_clear_error(env, monkeypatch, version, logged_in, code):
    monkeypatch.setenv("FAKE_CLAUDE_VERSION", version)
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", logged_in)

    async def go():
        a = await start_daemon(env)
        c = await SockClient.connect(env.socket)
        acct = await c.wait_for(lambda e: e["type"] == "account")
        await c.request({"type": "invoke", "mode": "text", "text": "Hallo"})
        err = await c.wait_for(lambda e: e["type"] == "error")
        await c.close()
        await a.stop()
        return acct, err
    acct, err = run(go())
    assert acct["status"] in ("cli_outdated", "signed_out")
    assert err["code"] == code


def test_voice_without_models_fails_soft(env):
    async def go():
        a = await start_daemon(env)
        await a.refresh_account()
        c = await SockClient.connect(env.socket)
        await c.request({"type": "invoke", "mode": "voice"})
        err = await c.wait_for(lambda e: e["type"] == "error")
        await c.close()
        await a.stop()
        return err, c.events
    err, ev = run(go())
    assert err["code"] in ("speech_models_missing", "mic_unavailable")
    snap = next(e for e in ev if e["type"] == "snapshot")
    assert snap["voice"]["input"] is False


def test_agent_cursor_and_tool_activity_relay(env):
    async def go():
        a = await start_daemon(env)
        ui = await SockClient.connect(env.socket)
        tool = await SockClient.connect(env.socket)
        await tool.request({"type": "hello", "client": "hands", "role": "tool"})
        r = await tool.request({"type": "agent_cursor", "x": 100, "y": 200.5, "visible": True, "label": "Senden",
                                "pulse": "click", "duration_ms": 250})
        assert r["ok"]
        cur = await ui.wait_for(lambda e: e["type"] == "agent_cursor")
        r = await tool.request({"type": "agent_cursor", "x": "left"})
        assert not r["ok"]
        await tool.request({"type": "tool_activity", "text": {"de": "Klicke auf „Senden“", "en": "Clicking “Send”"}})
        act = await ui.wait_for(lambda e: e["type"] == "activity")
        # a late UI sees the cursor in its snapshot
        late = await SockClient.connect(env.socket)
        snap = await late.wait_for(lambda e: e["type"] == "snapshot")
        # the tool disappears -> cursor hidden
        await tool.close()
        hid = await ui.wait_for(lambda e: e["type"] == "agent_cursor" and e["visible"] is False)
        await ui.close()
        await late.close()
        await a.stop()
        return cur, act, snap, hid, ui.events
    cur, act, snap, hid, ev = run(go())
    assert cur["x"] == 100 and cur["y"] == 200.5 and cur["pulse"] == "click" and cur["source"] == "hands"
    assert act["source"] == "tool" and act["text"]["de"].startswith("Klicke")
    assert snap["agent_cursor"]["label"] == "Senden" and snap["agent_cursor"]["x"] == 100
    assert hid["x"] == 100
    assert_conforms(ev)


def test_levels_only_for_subscribers(env):
    async def go():
        a = await start_daemon(env, demo=True)
        sub = await SockClient.connect(env.socket)
        plain = await SockClient.connect(env.socket)
        await sub.request({"type": "subscribe", "levels": True})
        await sub.request({"type": "invoke", "mode": "voice"})
        await sub.wait_for(lambda e: e["type"] == "level")
        await sub.wait_for(lambda e: e["type"] == "transcript" and e["final"])
        await sub.request({"type": "cancel"})
        await plain.wait_for(lambda e: e["type"] == "turn_finished")
        await sub.close()
        await plain.close()
        await a.stop()
        return sub.events, plain.events
    s, p = run(go())
    assert any(e["type"] == "level" for e in s)
    assert not any(e["type"] == "level" for e in p)
