# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude Code integration against a fake ``claude`` replaying recorded streams."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from conftest import fake_log, run
from kristall_assistant.brain import cli as climod
from kristall_assistant.brain.brain import Brain, Turn
from kristall_assistant.brain.mcp_config import McpSetup
from kristall_assistant.brain.memory import Memory
from kristall_assistant.config import DEFAULTS
from kristall_assistant.policy.policy import GrantStore, Policy, PolicyPaths


def make_brain(paths, answers=("allow_once",), settings=None):
    asked = []
    it = iter(answers)

    async def ask_owner(req):
        asked.append(req)
        return next(it, "deny")
    s = dict(DEFAULTS, **(settings or {}))
    pol = Policy(PolicyPaths(str(paths.workspace), [str(paths.grants_file)]), GrantStore(paths.grants_file))
    b = Brain(paths=paths, settings=lambda: s, policy=pol, memory=Memory(paths.memory_file),
              mcp_setup=lambda: McpSetup(), ask_owner=ask_owner, cli_path=lambda: climod.find_cli())
    b.prepare_spare_later = lambda: None     # each test controls its processes
    return b, asked, s


async def turn(b, text, spoken=True):
    evs = []
    t = Turn(id=f"t{time.monotonic_ns()}", text=text, spoken=spoken, emit=evs.append)
    await b.run_turn(t)
    return t, evs


def test_simple_followup_and_invocation(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_simple_followup")
    b, _, _ = make_brain(env)

    async def go():
        t1, e1 = await turn(b, "Wie heißt die Hauptstadt von Australien?")
        t2, e2 = await turn(b, "Und wie viele Leute wohnen da ungefähr?")
        await b.shutdown()
        return t1, e1, t2, e2
    t1, e1, t2, e2 = run(go())
    assert t1.error_code is None and "Canberra" in t1.reply_text
    assert not t1.continued and t2.continued and t1.conversation_id == t2.conversation_id
    assert [e for e in e1 if e["type"] == "reply_delta"], "reply must stream as deltas"
    assert "470.000" in t2.reply_text
    # exact invocation: subscription login (never --bare), isolated from the owner's setup
    argv = next(l["data"] for l in fake_log(env) if l["kind"] == "argv" and "--output-format" in l["data"])
    assert "--bare" not in argv
    for flag in ["--model", "claude-haiku-5-5", "--setting-sources=", "--strict-mcp-config",
                 "--no-session-persistence", "--disable-slash-commands", "--include-partial-messages",
                 "--input-format", "stream-json", "--permission-prompt-tool", "stdio", "--system-prompt",
                 "--effort", "low"]:
        assert flag in argv, flag
    assert argv[argv.index("--permission-mode") + 1] == "default"
    sp = argv[argv.index("--system-prompt") + 1]
    assert "informal \"du\"" in sp and "read aloud" in sp
    # the per-turn context travels in the user message
    users = [l["data"] for l in fake_log(env) if l["kind"] == "in" and l["data"].get("type") == "user"]
    assert users[0]["message"]["content"].startswith("[Context: ")
    assert "reply will be read aloud" in users[0]["message"]["content"]


def test_child_environment_is_isolated(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    e = climod.child_env()
    assert "CLAUDECODE" not in e
    for k in ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "DISABLE_AUTOUPDATER"):
        assert e[k] == "1"
    assert e["CLAUDE_AGENT_SDK_CLIENT_APP"] == "kristall-assistant"


def test_conversation_window_expiry_starts_fresh(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_simple_followup")
    b, _, s = make_brain(env, settings={"conversation_window_seconds": 0})

    async def go():
        t1, _ = await turn(b, "Wie heißt die Hauptstadt von Australien?")
        await asyncio.sleep(0.05)
        t2, _ = await turn(b, "Etwas ganz anderes")
        await b.shutdown()
        return t1, t2
    t1, t2 = run(go())
    assert not t2.continued and t1.conversation_id != t2.conversation_id


def test_prepare_makes_a_warm_spare(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "en_simple")
    b, _, _ = make_brain(env)

    async def go():
        b.prepare()
        await asyncio.sleep(0.8)
        spare = b.spare
        assert spare is not None and spare.ready.is_set() and not spare.dead
        t, _ = await turn(b, "What's seventeen times twenty-three?")
        used = t.conversation_id == spare.id
        await b.shutdown()
        return t, used
    t, used = run(go())
    assert used and "391" in t.reply_text


def test_permission_allowed(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_delete_permission")
    (env.workspace).mkdir(parents=True, exist_ok=True)
    (env.workspace / "alt.txt").write_text("x")
    b, asked, _ = make_brain(env, answers=("allow_once",))

    async def go():
        t, evs = await turn(b, "Lösch bitte die Datei alt.txt endgültig.")
        await b.shutdown()
        return t, evs
    t, evs = run(go())
    assert len(asked) == 1
    req = asked[0]
    assert req.decision.category == "files.delete" and req.decision.question["de"] == "Darf ich „alt.txt“ endgültig löschen?"
    assert "lösche sie jetzt endgültig" in req.explanation      # the model's own words are shown
    acts = [e for e in evs if e["type"] == "activity"]
    assert acts[0]["text"]["de"] == "Schaue nach" and acts[0]["detail"]
    assert any(a["status"] == "done" and a["text"]["de"] == "Lösche Dateien" for a in acts)
    assert "gelöscht" in t.reply_text and t.error_code is None
    # the hook answered "ask" and the permission callback answered "allow"
    ins = [l["data"] for l in fake_log(env) if l["kind"] == "in" and l["data"].get("type") == "control_response"]
    decisions = [r["response"]["response"].get("hookSpecificOutput", {}).get("permissionDecision")
                 or r["response"]["response"].get("behavior") for r in ins if "response" in r["response"]]
    assert decisions[-3:] == ["allow", "ask", "allow"] or decisions.count("ask") == 1


def test_permission_denied(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_delete_denied")
    b, asked, _ = make_brain(env, answers=("deny",))

    async def go():
        t, evs = await turn(b, "Lösch bitte die Datei alt.txt.")
        await b.shutdown()
        return t, evs
    t, evs = run(go())
    assert len(asked) == 1 and t.error_code is None
    assert any(e["type"] == "activity" and e["status"] == "failed" for e in evs)
    assert "nicht gelöscht" in t.reply_text
    ins = [l["data"] for l in fake_log(env) if l["kind"] == "in" and l["data"].get("type") == "control_response"]
    beh = [r["response"]["response"] for r in ins if r["response"]["response"].get("behavior") == "deny"]
    assert beh and "declined" in beh[0]["message"]


def test_always_grant_skips_the_question(env, monkeypatch):
    """After "always", the same kind of action runs without a prompt: the
    recorded can_use_tool is then answered from the grant."""
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_delete_permission")
    b, asked, _ = make_brain(env)
    b.policy.grants.add("files.delete")

    async def go():
        t, _ = await turn(b, "Lösch bitte die Datei alt.txt endgültig.")
        await b.shutdown()
        return t
    # The hook now answers "allow" for the delete; the recorded permission callback
    # is still replayed and is answered from the grant without asking the owner.
    t = run(go())
    hooks = [l["data"]["response"]["response"] for l in fake_log(env)
             if l["kind"] == "in" and l["data"].get("type") == "control_response"
             and "hookSpecificOutput" in l["data"]["response"].get("response", {})]
    assert [h["hookSpecificOutput"]["permissionDecision"] for h in hooks] == ["allow", "allow"]
    assert asked == []


def test_memory_tool(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_remember")
    b, _, _ = make_brain(env)

    async def go():
        t, evs = await turn(b, "Merk dir bitte: Meine Schwester heißt Lena.")
        await b.shutdown()
        return t, evs
    t, evs = run(go())
    facts = json.loads(env.memory_file.read_text())["facts"]
    assert any("Lena" in f["text"] for f in facts)
    assert any(e["type"] == "activity" and e["text"]["de"] == "Merke mir das" for e in evs)
    # memory reaches the next conversation's system prompt
    b2, _, _ = make_brain(env)
    from kristall_assistant.brain.prompt import build_system_prompt
    assert "Lena" in build_system_prompt("Kristall", "", b2.memory.as_prompt())


def test_interrupt_recorded(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_interrupt")
    b, _, _ = make_brain(env)

    async def go():
        evs = []
        t = Turn(id="ti", text="Erzähl mir ausführlich die Geschichte von Berlin.", spoken=False, emit=evs.append)
        task = asyncio.ensure_future(b.run_turn(t))
        while not any(e["type"] == "reply_delta" for e in evs):
            await asyncio.sleep(0.01)
        t0 = time.monotonic()
        await b.cancel()
        await task
        dt = time.monotonic() - t0
        await b.shutdown()
        return t, dt
    t, dt = run(go())
    assert t.cancelled and t.error_code is None and dt < 2.0


def test_interrupt_stops_streaming_immediately(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    b, _, _ = make_brain(env)

    async def go():
        evs = []
        t = Turn(id="ts", text="Rede ohne Ende", spoken=False, emit=evs.append)
        task = asyncio.ensure_future(b.run_turn(t))
        while sum(e["type"] == "reply_delta" for e in evs) < 5:
            await asyncio.sleep(0.01)
        t0 = time.monotonic()
        await b.cancel()
        n_at_cancel = sum(e["type"] == "reply_delta" for e in evs)
        await task
        took = time.monotonic() - t0
        n_after = sum(e["type"] == "reply_delta" for e in evs)
        # the conversation stays usable after an interrupt
        alive = b.active is not None and not b.active.dead
        await b.shutdown()
        return t, took, n_at_cancel, n_after, alive
    t, took, n0, n1, alive = run(go())
    assert t.cancelled and took < 1.0
    assert n1 == n0, "no text may reach the owner after cancel"
    assert alive


@pytest.mark.parametrize("mode,code", [
    ("not_signed_in", "not_signed_in"), ("rate_limited", "rate_limited"), ("credit_exhausted", "credit_exhausted"),
    ("billing", "credit_exhausted"), ("offline", "offline"), ("overloaded", "overloaded"), ("refusal", "refused"),
    ("crash", "brain_crashed"),
])
def test_error_states(env, monkeypatch, mode, code):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    b, _, _ = make_brain(env)

    async def go():
        t, evs = await turn(b, "Hallo?")
        await b.shutdown()
        return t
    t = run(go(), timeout=30)
    assert t.error_code == code, (mode, t.error_code)
    if mode in ("rate_limited", "credit_exhausted"):
        assert t.resets_at and t.resets_at > time.time()


def test_cli_missing(env, monkeypatch):
    monkeypatch.setenv("KRISTALL_CLAUDE_CLI", "/nonexistent/claude")
    monkeypatch.setenv("HOME", str(env.state_dir))      # no ~/.local/bin/claude either
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    b, _, _ = make_brain(env)
    b._cli_path = lambda: None

    async def go():
        t, _ = await turn(b, "Hallo")
        st = await climod.check()
        await b.shutdown()
        return t, st
    t, st = run(go())
    assert t.error_code == "cli_missing"
    assert st.status in ("cli_missing",) or st.cli_path      # a system-wide claude may exist on a dev box


def test_cli_version_and_sign_in_checks(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_VERSION", "2.0.10 (Claude Code)")
    assert run(climod.check()).status == "cli_outdated"
    monkeypatch.setenv("FAKE_CLAUDE_VERSION", "2.1.325 (Claude Code)")
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", "0")
    assert run(climod.check()).status == "signed_out"
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", "1")
    st = run(climod.check())
    assert st.status == "ready" and st.cli_version == "2.1.325"
