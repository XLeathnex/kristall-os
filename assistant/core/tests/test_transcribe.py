# SPDX-License-Identifier: GPL-3.0-or-later
"""Transcribe only (assistant-ipc §4 `transcribe`): microphone → text, no turn, no Claude, no sign-in."""
from __future__ import annotations

import ipc_schema
from conftest import SockClient, fake_log, run, start_daemon


def conforms(events):
    errs = [x for e in events for x in ipc_schema.check(e)]
    assert not errs, errs[:5]


def test_transcribe_demo_round_trip_without_claude_or_sign_in(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", "0")    # signed out: irrelevant for transcribing

    async def go():
        a = await start_daemon(env, demo=True)
        ui = await SockClient.connect(env.socket)
        await ui.request({"type": "hello", "client": "setup", "role": "ui", "subscribe": ["levels"]})
        ack = await ui.request({"type": "transcribe", "no_speech_timeout_seconds": 5})
        assert ack["ok"] and ack["transcription_id"].startswith("tr-")
        fin = await ui.wait_for(lambda e: e["type"] == "transcription_finished", timeout=30)
        # stop early and cancel
        ack2 = await ui.request({"type": "transcribe"})
        await ui.request({"type": "transcribe_cancel", "transcription_id": ack2["transcription_id"]})
        fin2 = await ui.wait_for(lambda e: e["type"] == "transcription_finished"
                                 and e["transcription_id"] == ack2["transcription_id"], timeout=30)
        ack3 = await ui.request({"type": "transcribe"})
        await ui.request({"type": "transcribe_stop"})
        fin3 = await ui.wait_for(lambda e: e["type"] == "transcription_finished"
                                 and e["transcription_id"] == ack3["transcription_id"], timeout=30)
        # an invoke cancels a running transcription first
        ack4 = await ui.request({"type": "transcribe"})
        inv = await ui.request({"type": "invoke", "mode": "text", "text": "Wie wird das Wetter?"})
        fin4 = await ui.wait_for(lambda e: e["type"] == "transcription_finished"
                                 and e["transcription_id"] == ack4["transcription_id"], timeout=30)
        await ui.wait_for(lambda e: e["type"] == "turn_started", timeout=30)
        busy = await ui.request({"type": "transcribe"})
        await ui.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] == inv["turn_id"], timeout=60)
        bad = await ui.request({"type": "transcribe", "max_seconds": 99})
        await ui.close()
        await a.stop()
        return ui.events, ack, fin, fin2, fin3, fin4, busy, bad
    ev, ack, fin, fin2, fin3, fin4, busy, bad = run(go(), timeout=150)
    conforms(ev)
    tid = ack["transcription_id"]
    mine = [e for e in ev if e.get("transcription_id") == tid and e["type"] != "ack"]
    assert fin["outcome"] == "completed" and fin["error_code"] is None
    assert fin["text"] == "Hallo Kristall, kannst du mich hören?"
    partial = [e for e in mine if e["type"] == "transcription" and not e["final"]]
    final = [e for e in mine if e["type"] == "transcription" and e["final"]]
    assert len(partial) >= 2 and len(final) == 1 and final[0]["text"] == fin["text"]
    assert mine[-1]["type"] == "transcription_finished"
    first_fin = ev.index(fin)
    assert any(e["type"] == "level" and e["source"] == "mic" for e in ev[:first_fin])
    # no turn, no state change, nothing for Claude
    assert not any(e["type"] in ("turn_started", "state") for e in ev[:first_fin] if e["type"] != "snapshot")
    assert fin2["outcome"] == "cancelled" and fin2["text"] == ""
    assert fin3["outcome"] == "completed"             # stopped early: what was heard so far
    assert fin4["outcome"] == "cancelled"
    assert not busy["ok"] and busy["code"] == "busy"
    assert not bad["ok"] and bad["code"] == "bad_request"


def test_transcribe_without_models_fails_soft_and_never_calls_claude(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", "0")

    async def go():
        a = await start_daemon(env)
        await a.refresh_account()
        ui = await SockClient.connect(env.socket)
        ack = await ui.request({"type": "transcribe"})
        fin = await ui.wait_for(lambda e: e["type"] == "transcription_finished", timeout=30)
        await ui.close()
        await a.stop()
        return ui.events, ack, fin
    ev, ack, fin = run(go())
    conforms(ev)
    assert ack["ok"]
    assert fin["outcome"] == "error" and fin["error_code"] == "speech_models_missing" and fin["text"] == ""
    assert not any(e["type"] in ("turn_started", "conversation") for e in ev)
    assert not [l for l in fake_log(env) if l.get("dir") == "argv"], "no Claude session was started"
    acct = [e for e in ev if e["type"] in ("account", "snapshot")]
    assert acct and (acct[-1].get("status") or acct[-1]["account"]["status"]) == "signed_out", "works while signed out"
