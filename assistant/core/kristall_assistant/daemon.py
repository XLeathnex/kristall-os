# SPDX-License-Identifier: GPL-3.0-or-later
"""kristall-assistant: the daemon.

Owns the socket, the conversation with Claude, the voice pipeline and the
state the interface shows.  Protocol: docs/contracts/assistant-ipc.md.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import PROTOCOL_VERSION, __version__
from .brain import cli as climod
from .brain import mcp_config
from .brain.brain import Brain, PermissionAsk, Turn
from .brain.memory import Memory
from .config import DirWatcher, Paths, load_settings, system_language
from .errors import ERRORS, error_event
from .policy.policy import GrantStore, Policy, PolicyPaths
from .replytext import ReplyText
from .server import Client, Server
from .voice.audio import (AudioSink, AudioSource, Ducker, FileSink, FileSource, PipeWireSink, PipeWireSource,
                          echo_cancel_source)
from .voice.models import ModelManager
from .voice.pipeline import ListenConfig, Listener, Speaker

log = logging.getLogger("kristall.daemon")

STATES = ("idle", "listening", "transcribing", "thinking", "acting", "speaking", "error")
DECISIONS = ("allow_once", "allow_always", "deny")


@dataclass
class PendingPermission:
    ask: PermissionAsk
    future: asyncio.Future
    event: dict


@dataclass
class ActiveTurn:
    id: str
    mode: str                       # "voice" | "text"
    source: str
    speak: bool
    context: dict
    text: str = ""
    phase: str = "starting"         # listening | transcribing | thinking | done
    task: asyncio.Task | None = None
    listener: Any = None
    speaker: Any = None
    brain_turn: Turn | None = None
    tools_running: set = field(default_factory=set)
    cancelled: bool = False
    reply: list = field(default_factory=list)
    lang: str = "de"
    error_shown: bool = False
    markup: Any = None              # replytext.ReplyText: reply markup normalised while streaming
    segment: int = 0


class Assistant:
    def __init__(self, paths: Paths, *, demo: bool = False,
                 source_factory: Callable[[], AudioSource] | None = None,
                 sink_factory: Callable[[], AudioSink] | None = None,
                 brain=None, account_check=None, demo_options: dict | None = None):
        self.paths = paths
        self.demo = demo
        self._settings = load_settings(paths)
        self.server = Server(paths.socket, self.on_message, self.on_connect, self.on_disconnect)
        self.state = "idle"
        self._state_detail: str | None = None
        self.turn: ActiveTurn | None = None
        self.transcription: dict | None = None   # transcribe-only session (§4 `transcribe`)
        self.last_error: dict | None = None
        self.pending: dict[str, PendingPermission] = {}
        self.cursor: dict | None = None
        self.account: dict = {"status": "checking"}
        self.models = ModelManager(paths.models_dir, self.settings)
        self.ducker = Ducker()
        self._source_factory = source_factory
        self._sink_factory = sink_factory
        self._account_check = account_check or (lambda: climod.check(self._settings.get("claude_path")))
        self._watch: DirWatcher | None = None
        self._bg: set[asyncio.Task] = set()
        self._stopping = asyncio.Event()
        self._echo_source: str | None = None
        self.demo_options = demo_options or {}
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory = Memory(paths.memory_file)
        self.mcp = mcp_config.load([paths.system_mcp_dir, paths.user_mcp_dir])
        self.policy = Policy(
            PolicyPaths(str(paths.workspace), [str(paths.grants_file), str(paths.user_mcp_dir),
                                               str(paths.memory_file), str(paths.settings_file)]),
            GrantStore(paths.grants_file), self.mcp.decls)
        if demo:
            from .demo import DemoBrain
            self.brain = brain or DemoBrain(self)
            self.account = {"status": "ready", "cli_version": "demo", "min_version": climod.MIN_VERSION_STR,
                            "logged_in": True, "auth_method": "demo", "cli_path": None}
        else:
            self.brain = brain or Brain(paths=paths, settings=self.settings, policy=self.policy,
                                        memory=self.memory, mcp_setup=lambda: self.mcp,
                                        ask_owner=self.ask_owner,
                                        cli_path=lambda: self.account.get("cli_path") or climod.find_cli(
                                            self._settings.get("claude_path")))

    # ------------------------------------------------------------------ basics
    def settings(self) -> dict:
        return self._settings

    def spawn(self, coro) -> asyncio.Task:
        t = asyncio.ensure_future(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    def emit(self, msg: dict, *, levels: bool = False) -> None:
        self.server.broadcast(msg, levels=levels)

    def lang(self) -> str:
        return self.turn.lang if self.turn else self._settings.get("language", "de")

    async def start(self) -> None:
        await self.server.start()
        loop = asyncio.get_running_loop()
        self._watch = DirWatcher([self.paths.config_dir, self.paths.user_mcp_dir, self.paths.system_mcp_dir,
                                  *[d for d in self.paths.settings_dropin_dirs if d.is_dir()],
                                  self.paths.grants_file.parent],
                                 self._on_file_changed)
        self._watch.attach(loop)
        if not self.demo:
            self.spawn(self.refresh_account())
            self.spawn(self._detect_echo_cancel())
        log.info("kristall-assistant %s ready (demo=%s)", __version__, self.demo)

    async def stop(self) -> None:
        self._stopping.set()
        await self.cancel_transcription()
        if self.turn:
            await self.cancel_turn()
        await self.ducker.restore()
        if self._watch:
            self._watch.close(asyncio.get_running_loop())
        await self.brain.shutdown()
        await self.server.stop()

    def _on_file_changed(self, path) -> None:
        if path == self.paths.settings_file or path.parent in self.paths.settings_dropin_dirs:
            old = self._settings
            self._settings = load_settings(self.paths)
            if (old.get("name"), old.get("owner_name"), old.get("model")) != \
                    (self._settings.get("name"), self._settings.get("owner_name"), self._settings.get("model")):
                self.brain.new_conversation()
            log.info("settings reloaded")
        elif path.suffix == ".json" and path.parent in (self.paths.user_mcp_dir, self.paths.system_mcp_dir):
            self.mcp = mcp_config.load([self.paths.system_mcp_dir, self.paths.user_mcp_dir])
            self.policy.tool_decls = self.mcp.decls
            log.info("tool servers reloaded: %s", sorted(self.mcp.servers))
            self.brain.new_conversation()
        elif path == self.paths.grants_file:
            self.policy.grants.load()

    async def _detect_echo_cancel(self) -> None:
        self._echo_source = await echo_cancel_source()

    # ------------------------------------------------------------------ state
    def _compute_state(self) -> str:
        t = self.turn
        if t is None:
            return "error" if self.last_error and self.last_error.get("_sticky") else "idle"
        if t.speaker is not None and getattr(t.speaker, "playing", False):
            return "speaking"
        if t.phase in ("listening", "transcribing"):
            return t.phase
        if t.phase == "thinking":
            if t.tools_running or self.pending:
                return "acting"
            return "thinking"
        if t.phase == "speaking":
            return "speaking"
        if t.phase == "error":
            return "error"
        return "thinking"

    def update_state(self) -> None:
        s = self._compute_state()
        detail = "waiting_for_permission" if s == "acting" and self.pending else None
        if (s, detail) != (self.state, self._state_detail):
            self.state, self._state_detail = s, detail
            ev = {"type": "state", "state": s, "turn_id": self.turn.id if self.turn else None}
            if detail:
                ev["detail"] = detail
            self.emit(ev)

    def snapshot(self) -> dict:
        t = self.turn
        return {
            "type": "snapshot", "state": self.state,
            "turn": None if t is None else {
                "turn_id": t.id, "input": t.mode, "text": t.text or None, "reply": "".join(t.reply),
                "speak": t.speak},
            "account": self.account,
            "pending_permissions": [p.event for p in self.pending.values()],
            "agent_cursor": self.cursor,
            "assistant": {"name": self._settings.get("name", "Kristall"),
                          "language": self._settings.get("language", "de"),
                          "input_mode": self._settings.get("input_mode", "voice")},
            "voice": self.voice_capabilities(),
        }

    def voice_capabilities(self) -> dict:
        if self.demo:
            return {"input": True, "output": True, "live_transcript": True}
        return {"input": self.models.asr_available() and (self._source_factory is not None or PipeWireSource.available()),
                "output": self.models.tts_available() and (self._sink_factory is not None or PipeWireSink.available()),
                "live_transcript": True}

    # ------------------------------------------------------------------ socket
    def on_connect(self, c: Client) -> None:
        self.server.send(c, {"type": "hello", "protocol": PROTOCOL_VERSION, "daemon": "kristall-assistant",
                             "version": __version__, "demo": self.demo})
        self.server.send(c, self.snapshot())

    def on_disconnect(self, c: Client) -> None:
        if c.role == "tool" and self.cursor and self.cursor.get("source") == c.name and self.cursor.get("visible"):
            self.cursor = dict(self.cursor, visible=False)
            self.emit({"type": "agent_cursor", **self.cursor, "turn_id": self.turn.id if self.turn else None})

    def _ack(self, c: Client, msg: dict, ok: bool = True, code: str | None = None, **extra) -> None:
        if "id" not in msg:
            return
        a = {"type": "ack", "id": msg["id"], "ok": ok}
        if code:
            a["code"] = code
            spec = ERRORS.get(code)
            if spec:
                a["message"] = {"de": spec.de.format(when="").strip(), "en": spec.en.format(when="").strip()}
        a.update(extra)
        self.server.send(c, a)

    async def on_message(self, c: Client, msg: dict) -> None:
        t = msg["type"]
        h = getattr(self, "_m_" + t, None)
        if h is None:
            self._ack(c, msg, False, "unknown_type")
            if "id" not in msg:
                self.server.send(c, {"type": "ack", "id": None, "ok": False, "code": "unknown_type", "re": t})
            return
        await h(c, msg)

    async def _m_hello(self, c: Client, m: dict) -> None:
        c.name = str(m.get("client") or "?")[:40]
        c.role = m.get("role") if m.get("role") in ("ui", "tool", "control") else "ui"
        if "levels" in (m.get("subscribe") or []):
            c.levels = True
        self._ack(c, m)

    async def _m_subscribe(self, c: Client, m: dict) -> None:
        c.levels = bool(m.get("levels", False))
        self._ack(c, m)

    async def _m_get_snapshot(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        self.server.send(c, self.snapshot())

    async def _m_prepare(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        if self.account.get("status") == "ready":
            self.brain.prepare()
        if not self.demo and self._settings.get("input_mode", "voice") == "voice" and self.models.asr_available():
            self.spawn(self.models.preload_asr())

    async def _m_new_conversation(self, c: Client, m: dict) -> None:
        self.brain.new_conversation()
        self._ack(c, m)

    async def _m_account_changed(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        self.spawn(self.refresh_account())

    async def _m_invoke(self, c: Client, m: dict) -> None:
        mode = m.get("mode", self._settings.get("input_mode", "voice"))
        if mode not in ("voice", "text"):
            self._ack(c, m, False, "bad_request")
            return
        text = m.get("text")
        if mode == "text" and (not isinstance(text, str) or not text.strip()):
            self._ack(c, m, False, "bad_request")
            return
        await self.cancel_transcription()
        if self.turn:
            await self.cancel_turn()
        speak_pref = self._settings.get("speak_replies", "voice_only")
        speak = m.get("speak")
        if not isinstance(speak, bool):
            speak = speak_pref == "always" or (speak_pref == "voice_only" and mode == "voice")
        ctx = m.get("context") if isinstance(m.get("context"), dict) else {}
        ctx = {k: str(v)[:2000] for k, v in ctx.items() if k in ("front_app", "window_title", "selection") and v}
        if m.get("new_conversation"):
            self.brain.new_conversation()
        at = ActiveTurn(id=uuid.uuid4().hex[:12], mode=mode, source=str(m.get("source") or "unknown")[:20],
                        speak=speak, context=ctx, text=(text or "").strip(),
                        lang=self._settings.get("language", "de"))
        self.turn = at
        self.last_error = None
        self._ack(c, m, True, turn_id=at.id)
        at.task = self.spawn(self._run_turn(at))

    async def _m_cancel(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        await self.cancel_turn()

    async def _m_end_listening(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        t = self.turn
        if t and t.listener is not None and t.phase == "listening":
            t.listener.finish()

    # ------------------------------------------------------------------ transcribe only
    async def _m_transcribe(self, c: Client, m: dict) -> None:
        """Microphone → speech recognition → text, nothing else: no turn, no Claude, no sign-in."""
        if self.turn is not None:
            self._ack(c, m, False, "busy")
            return
        limits = {}
        for key, lo, hi in (("no_speech_timeout_seconds", 1, 30), ("max_seconds", 1, 45)):
            v = m.get(key)
            if v is not None:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                    self._ack(c, m, False, "bad_request")
                    return
                limits[key] = float(v)
        await self.cancel_transcription()
        tr = {"id": "tr-" + uuid.uuid4().hex[:10], "listener": None, "cancelled": False}
        self.transcription = tr
        self._ack(c, m, True, transcription_id=tr["id"])
        tr["task"] = self.spawn(self._run_transcription(tr, limits))

    async def _m_transcribe_stop(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        tr = self.transcription
        if tr and tr["listener"] is not None and m.get("transcription_id") in (None, tr["id"]):
            tr["listener"].finish()

    async def _m_transcribe_cancel(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        tr = self.transcription
        if tr and m.get("transcription_id") in (None, tr["id"]):
            await self.cancel_transcription()

    async def cancel_transcription(self) -> None:
        tr = self.transcription
        if tr is None:
            return
        tr["cancelled"] = True
        if tr["listener"] is not None:
            tr["listener"].cancel()
        task = tr.get("task")
        if task and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), 3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()

    async def _run_transcription(self, tr: dict, limits: dict) -> None:
        tid = tr["id"]
        outcome, text, err, secs = "error", "", None, 0.0

        def partial(txt: str) -> None:
            if not tr["cancelled"]:
                self.emit({"type": "transcription", "transcription_id": tid, "text": txt, "final": False})
        try:
            if self.demo:
                from .demo import DemoTranscriber
                tr["listener"] = DemoTranscriber(self, partial)
            elif not self.models.asr_available():
                err = "speech_models_missing"
            elif self._source_factory is None and not PipeWireSource.available():
                err = "mic_unavailable"
            else:
                s = self._settings
                cfg = ListenConfig(end_of_speech_ms=int(s.get("end_of_speech_ms", 800)),
                                   no_speech_timeout=limits.get("no_speech_timeout_seconds",
                                                                float(s.get("no_speech_timeout_seconds", 7))),
                                   max_utterance=limits.get("max_seconds", float(s.get("max_utterance_seconds", 45))))
                tr["listener"] = Listener(self.models, self._make_source(), cfg,
                                          on_level=lambda v: self.emit({"type": "level", "source": "mic",
                                                                        "value": round(v, 3)}, levels=True),
                                          on_partial=partial)
            if tr["listener"] is not None:
                res = await tr["listener"].run()
                secs = res.audio_seconds
                if tr["cancelled"] or res.outcome == "cancelled":
                    outcome = "cancelled"
                elif res.outcome == "final":
                    outcome, text = "completed", res.text
                elif res.outcome == "nothing_heard":
                    outcome = "nothing_heard"
                else:
                    log.warning("transcription failed: %s", res.error)
                    err = "speech_models_missing" if "models" in (res.error or "") else "mic_unavailable"
        except asyncio.CancelledError:
            outcome = "cancelled"
        except Exception:   # noqa: BLE001
            log.exception("transcription failed")
            err = "internal"
        finally:
            if tr["cancelled"]:
                outcome, text, err = "cancelled", "", None
            if outcome == "completed":
                self.emit({"type": "transcription", "transcription_id": tid, "text": text, "final": True})
            self.emit({"type": "transcription_finished", "transcription_id": tid, "outcome": outcome,
                       "text": text, "error_code": err, "audio_seconds": round(float(secs or 0.0), 2)})
            if self.transcription is tr:
                self.transcription = None

    async def _m_stop_speaking(self, c: Client, m: dict) -> None:
        self._ack(c, m)
        t = self.turn
        if t:
            t.speak = False
            if t.speaker is not None:
                t.speaker.stop()
            self.update_state()

    async def _m_permission_reply(self, c: Client, m: dict) -> None:
        rid, dec = m.get("request_id"), m.get("decision")
        p = self.pending.get(rid)
        if p is None or dec not in DECISIONS:
            self._ack(c, m, False, "unknown_request" if p is None else "bad_request")
            return
        if dec == "allow_always" and not p.ask.decision.can_always:
            dec = "allow_once"
        self._ack(c, m)
        if not p.future.done():
            p.future.set_result((dec, "owner"))

    async def _m_agent_cursor(self, c: Client, m: dict) -> None:
        ev = {"type": "agent_cursor", "source": c.name}
        try:
            ev["visible"] = bool(m.get("visible", True))
            if "x" in m or "y" in m:
                ev["x"], ev["y"] = float(m["x"]), float(m["y"])
            elif self.cursor and "x" in self.cursor:
                ev["x"], ev["y"] = self.cursor["x"], self.cursor["y"]
            if m.get("pulse") in ("click", "double_click", "right_click", "drag_start", "drag_end", "type", "scroll"):
                ev["pulse"] = m["pulse"]
            if m.get("label") is not None:
                ev["label"] = str(m["label"])[:60]
            if isinstance(m.get("output"), str):
                ev["output"] = m["output"][:80]
            if isinstance(m.get("duration_ms"), (int, float)):
                ev["duration_ms"] = max(0, min(5000, int(m["duration_ms"])))
        except (KeyError, TypeError, ValueError):
            self._ack(c, m, False, "bad_request")
            return
        self.cursor = {k: v for k, v in ev.items() if k not in ("type", "pulse")}
        ev["turn_id"] = self.turn.id if self.turn else None
        self.emit(ev)
        self._ack(c, m)

    async def _m_tool_activity(self, c: Client, m: dict) -> None:
        text = m.get("text")
        if isinstance(text, str):
            text = {"de": text[:200], "en": text[:200]}
        if not isinstance(text, dict) or not text.get("de"):
            self._ack(c, m, False, "bad_request")
            return
        ev = {"type": "activity", "turn_id": self.turn.id if self.turn else None,
              "id": str(m.get("activity_id") or uuid.uuid4().hex[:8])[:64], "tool": f"{c.name}",
              "status": m.get("status") if m.get("status") in ("running", "done", "failed") else "running",
              "text": {"de": str(text.get("de"))[:200], "en": str(text.get("en") or text.get("de"))[:200]},
              "source": "tool"}
        self.emit(ev)
        self._ack(c, m)

    # demo-only helpers to show every state in the interface
    async def _m_demo_error(self, c: Client, m: dict) -> None:
        if not self.demo or m.get("code") not in ERRORS:
            self._ack(c, m, False, "bad_request")
            return
        self._ack(c, m)
        self.emit(error_event(m["code"], self.turn.id if self.turn else None,
                              resets_at=time.time() + 3 * 3600 if m["code"] in ("credit_exhausted", "rate_limited") else None))

    async def _m_demo_account(self, c: Client, m: dict) -> None:
        if not self.demo:
            self._ack(c, m, False, "bad_request")
            return
        self._ack(c, m)
        self.account = dict(self.account, status=str(m.get("status", "ready")))
        self.emit({"type": "account", **self.account})

    # ------------------------------------------------------------------ account
    async def refresh_account(self) -> dict:
        try:
            st = await self._account_check()
            d = st.as_dict() if hasattr(st, "as_dict") else dict(st)
        except Exception as e:   # noqa: BLE001
            log.warning("account check failed: %r", e)
            d = {"status": "unknown", "detail": "check failed"}
        if d != self.account:
            self.account = d
            self.emit({"type": "account", **d})
        return d

    # ------------------------------------------------------------------ permissions
    async def ask_owner(self, ask: PermissionAsk) -> str:
        t = self.turn
        if t is None or t.cancelled:
            return "cancelled"
        d = ask.decision
        timeout = float(self._settings.get("permission_timeout_seconds", 120))
        ev = {"type": "permission_request", "request_id": ask.request_id, "turn_id": t.id,
              "question": d.question, "action": d.action, "explanation": ask.explanation,
              "category": d.category, "can_always": d.can_always,
              "options": ["allow_once", "allow_always", "deny"] if d.can_always else ["allow_once", "deny"],
              "tool": ask.tool, "technical": d.technical[:1000], "expires_in": int(timeout)}
        fut = asyncio.get_running_loop().create_future()
        self.pending[ask.request_id] = PendingPermission(ask, fut, ev)
        self.emit(dict(ev))
        self.update_state()
        if t.speak and t.speaker is not None:
            t.speaker.feed(" " + d.question.get(t.lang, d.question["de"]) + "\n")
        try:
            decision, by = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            decision, by = "deny", "timeout"
        except asyncio.CancelledError:
            decision, by = "cancelled", "cancelled"
        self.pending.pop(ask.request_id, None)
        self.emit({"type": "permission_resolved", "request_id": ask.request_id, "turn_id": t.id,
                   "decision": "deny" if decision == "cancelled" else decision, "by": by})
        self.update_state()
        log.info("permission %s (%s) -> %s by %s", d.category, d.scope, decision, by)
        return decision

    def _cancel_pending(self) -> None:
        for p in list(self.pending.values()):
            if not p.future.done():
                p.future.set_result(("cancelled", "cancelled"))

    # ------------------------------------------------------------------ turns
    async def cancel_turn(self) -> None:
        t = self.turn
        if t is None:
            return
        t.cancelled = True
        if t.listener is not None:
            t.listener.cancel()
        if t.speaker is not None:
            t.speaker.stop()
        self._cancel_pending()
        if t.brain_turn is not None:
            t.brain_turn.cancelled = True
        await self.brain.cancel()
        if t.task and not t.task.done():
            try:
                await asyncio.wait_for(asyncio.shield(t.task), 3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.task.cancel()

    async def _preload_voice(self, lang: str) -> None:
        try:
            await self.models.voice(lang)
        except Exception as e:   # noqa: BLE001
            log.warning("voice preload failed: %r", e)

    def _make_source(self) -> AudioSource:
        if self._source_factory:
            return self._source_factory()
        return PipeWireSource(self._echo_source if self._barge_in_possible() else None)

    def _make_sink(self) -> AudioSink:
        if self._sink_factory:
            return self._sink_factory()
        return PipeWireSink()

    def _barge_in_possible(self) -> bool:
        b = self._settings.get("barge_in", "auto")
        return b == "on" or (b == "auto" and bool(self._echo_source))

    def _listener(self, at: ActiveTurn):
        if self.demo:
            from .demo import DemoListener
            return DemoListener(self, at)
        s = self._settings
        cfg = ListenConfig(end_of_speech_ms=int(s.get("end_of_speech_ms", 800)),
                           no_speech_timeout=float(s.get("no_speech_timeout_seconds", 7)),
                           max_utterance=float(s.get("max_utterance_seconds", 45)))

        def on_partial(txt: str) -> None:
            if not at.cancelled:
                self.emit({"type": "transcript", "turn_id": at.id, "text": txt, "final": False})

        def on_transcribing() -> None:
            at.phase = "transcribing"
            self.update_state()
        return Listener(self.models, self._make_source(), cfg,
                        on_level=lambda v: self.emit({"type": "level", "source": "mic", "value": round(v, 3)}, levels=True),
                        on_partial=on_partial, on_transcribing=on_transcribing)

    def _speaker(self, at: ActiveTurn):
        if self.demo:
            from .demo import DemoSpeaker
            sp = DemoSpeaker(self, at)
        else:
            if not self.models.tts_available(at.lang):
                return None
            sp = Speaker(self.models, self._make_sink(), rate=lambda: self._settings.get("speaking_rate", 1.0),
                         default_lang=lambda: at.lang,
                         on_level=lambda v: self.emit({"type": "level", "source": "speech", "value": round(v, 3)}, levels=True),
                         on_sentence=lambda i, s: self._on_sentence(at, i, s),
                         on_start=lambda: self._on_speech_start(at),
                         on_error=lambda e: self._on_speech_error(at, e),
                         on_idle=lambda: self._on_speech_idle(at))
        sp.playing = False
        sp.start()
        return sp

    def _on_sentence(self, at: ActiveTurn, i: int, s: str) -> None:
        if at.speaker is not None:
            at.speaker.playing = True
        self.emit({"type": "speech", "turn_id": at.id, "sentence": i, "text": s})
        self.update_state()

    def _on_speech_idle(self, at: ActiveTurn) -> None:
        if at.speaker is not None:
            at.speaker.playing = False
        self.update_state()

    def _on_speech_start(self, at: ActiveTurn) -> None:
        if self._settings.get("duck_other_audio", True) and not self.demo:
            self.spawn(self.ducker.duck())

    def _on_speech_error(self, at: ActiveTurn, e: str) -> None:
        log.warning("speech output failed: %s", e)
        at.speak = False
        self.emit(error_event("audio_output_unavailable", at.id))

    def _brain_emit(self, at: ActiveTurn) -> Callable[[dict], None]:
        def emit(ev: dict) -> None:
            if at.cancelled:
                return
            typ = ev["type"]
            if typ == "reply_delta":
                if at.markup is None:
                    # assistant-ipc §5.1: typed replies carry the interface's Markdown subset,
                    # spoken ones are plain; normalised here while streaming
                    at.markup = ReplyText(plain=at.speak)
                if ev.get("segment", 0) != at.segment:
                    self._reply_out(at, at.markup.flush())
                    at.segment = ev.get("segment", 0)
                self._reply_out(at, at.markup.feed(ev["text"]))
            elif typ == "activity":
                if ev["status"] == "running" and at.markup is not None:
                    self._reply_out(at, at.markup.flush())   # the preamble's last line is complete
                if ev["status"] == "running":
                    at.tools_running.add(ev["id"])
                else:
                    at.tools_running.discard(ev["id"])
                out = {"type": "activity", "turn_id": at.id, "id": ev["id"], "tool": ev["tool"],
                       "status": ev["status"], "text": ev["text"], "source": "assistant"}
                if ev.get("detail"):
                    out["detail"] = ev["detail"]
                self.emit(out)
                if at.speaker is not None and at.speak and ev["status"] == "running":
                    at.speaker.feed("\n")      # speak the preamble now, don't wait for more text
                self.update_state()
            elif typ == "_conversation":
                self.emit({"type": "conversation", "turn_id": at.id, "conversation_id": ev["conversation_id"],
                           "continued": ev["continued"]})
            elif typ == "_usage_warning":
                self.emit({"type": "usage_warning", "utilization": ev.get("utilization"),
                           "resets_at": ev.get("resets_at"), "window": ev.get("kind")})
            elif typ == "_retrying":
                self.emit({"type": "activity", "turn_id": at.id, "id": "retry", "tool": "_retry", "status": "running",
                           "source": "assistant",
                           "text": {"de": "Claude ist gerade ausgelastet, ich versuche es weiter …",
                                    "en": "Claude is busy, still trying …"}})
        return emit

    def _reply_out(self, at: ActiveTurn, text: str) -> None:
        if not text or at.cancelled:
            return
        at.reply.append(text)
        if len(at.reply) == 1:
            from .voice.speechtext import detect_language
            at.lang = detect_language(text + " " + at.text, at.lang)
        self.emit({"type": "reply_delta", "turn_id": at.id, "text": text, "segment": at.segment})
        if at.speaker is not None and at.speak:
            at.speaker.feed(text)

    async def _run_turn(self, at: ActiveTurn) -> None:
        outcome, err_code = "completed", None
        self.emit({"type": "turn_started", "turn_id": at.id, "input": at.mode, "source": at.source,
                   "text": at.text or None, "speak": at.speak})
        try:
            if self.account.get("status") != "ready" and not self.demo:
                await self.refresh_account()
            acct = self.account.get("status")
            if acct != "ready" and not self.demo:
                code = {"cli_missing": "cli_missing", "cli_outdated": "cli_outdated",
                        "signed_out": "not_signed_in"}.get(acct, "service_error")
                if acct != "unknown":
                    outcome, err_code = "error", code
                    return
            if at.mode == "voice":
                if not self.demo and not self.voice_capabilities()["input"]:
                    outcome, err_code = "error", ("speech_models_missing" if not self.models.asr_available()
                                                  else "mic_unavailable")
                    return
                self.brain.prepare()
                if at.speak and not self.demo and self.voice_capabilities()["output"]:
                    self.spawn(self._preload_voice(at.lang))   # ready before the first sentence
                if self._settings.get("duck_other_audio", True) and not self.demo:
                    await self.ducker.duck()
                at.phase = "listening"
                self.update_state()
                at.listener = self._listener(at)
                res = await at.listener.run()
                at.listener = None
                if at.cancelled or res.outcome == "cancelled":
                    outcome = "cancelled"
                    return
                if res.outcome == "nothing_heard":
                    outcome, err_code = "nothing_heard", "nothing_heard"
                    return
                if res.outcome == "error":
                    log.warning("listening failed: %s", res.error)
                    outcome, err_code = "error", ("mic_unavailable" if "models" not in (res.error or "") and
                                                  "asr" not in (res.error or "") else "speech_models_missing")
                    return
                at.text = res.text
                from .voice.speechtext import detect_language
                at.lang = detect_language(at.text, at.lang)
                self.emit({"type": "transcript", "turn_id": at.id, "text": at.text, "final": True})
            at.phase = "thinking"
            self.update_state()
            if at.speak:
                at.speaker = self._speaker(at)
            bt = Turn(id=at.id, text=at.text, spoken=at.speak, emit=self._brain_emit(at), context=at.context)
            at.brain_turn = bt
            if at.cancelled:
                outcome = "cancelled"
                return
            await self.brain.run_turn(bt)
            if at.cancelled or bt.cancelled and not bt.error_code:
                outcome = "cancelled"
                return
            if bt.error_code:
                outcome, err_code = "error", bt.error_code
                if bt.error_code in ("not_signed_in", "cli_missing", "cli_outdated"):
                    self.spawn(self.refresh_account())
            if at.markup is not None and not at.cancelled:
                self._reply_out(at, at.markup.flush())
            reply = "".join(at.reply)
            if reply:
                self.emit({"type": "reply_done", "turn_id": at.id, "text": reply, "spoken": bool(at.speak and at.speaker)})
        except asyncio.CancelledError:
            outcome = "cancelled"
        except Exception:   # noqa: BLE001
            log.exception("turn failed")
            outcome, err_code = "error", "internal"
        finally:
            await self._finish_turn(at, outcome, err_code)

    async def _finish_turn(self, at: ActiveTurn, outcome: str, err_code: str | None) -> None:
        if err_code and not at.cancelled:
            ev = error_event(err_code, at.id, resets_at=getattr(at.brain_turn, "resets_at", None))
            self.emit(ev)
            if at.speak and err_code != "nothing_heard" and not self.demo and self.voice_capabilities()["output"]:
                if at.speaker is None:
                    at.speaker = self._speaker(at)
                if at.speaker is not None:
                    at.speaker.feed(ev["message"].get(at.lang, ev["message"]["de"]) + "\n")
        if at.speaker is not None:
            if at.cancelled:
                at.speaker.stop()
            else:
                at.speaker.close()
                at.phase = "speaking"
                self.update_state()
                try:
                    await at.speaker.wait()
                except asyncio.CancelledError:
                    at.speaker.stop()
        if at.cancelled and outcome != "error":
            outcome = "cancelled"
        at.phase = "done"
        if at.speaker is not None:
            at.speaker.playing = False
        if self.turn is at:
            self.turn = None
        if not self.turn:
            await self.ducker.restore()
            # no turn, no agent cursor: a turn cancelled while a tool was moving it (the owner pressed
            # Escape mid-way) left it on screen (integration walkthrough, demo turn)
            if self.cursor and self.cursor.get("visible"):
                self.cursor = dict(self.cursor, visible=False)
                self.emit({"type": "agent_cursor", **self.cursor, "turn_id": at.id})
        self.emit({"type": "turn_finished", "turn_id": at.id, "outcome": outcome, "error_code": err_code})
        self.update_state()


def setup_logging(verbose: bool) -> None:
    fmt = "%(levelname)s %(name)s: %(message)s" if os.environ.get("JOURNAL_STREAM") else \
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format=fmt, stream=sys.stderr)
    for noisy in ("asyncio", "claude_agent_sdk", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def amain(args) -> int:
    paths = Paths.from_env()
    kw: dict = {}
    if args.audio_in:        # development: every voice request "hears" this WAV file
        kw["source_factory"] = lambda: FileSource(args.audio_in, realtime=1.0)
    if args.audio_out:       # development: everything spoken is appended to this WAV file
        sink = FileSink()
        kw["sink_factory"] = lambda: sink

        async def _flush():
            sink.write(args.audio_out)
    a = Assistant(paths, demo=args.demo, demo_options={"auto": args.demo_auto, "loop": args.demo_loop}, **kw)
    try:
        await a.start()
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    if args.demo and args.demo_loop:
        from .demo import demo_loop
        a.spawn(demo_loop(a, args.demo_loop))
    _sd_notify("READY=1")
    await stop.wait()
    _sd_notify("STOPPING=1")
    await a.stop()
    if args.audio_out:
        await _flush()
    return 0


def _sd_notify(state: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    import socket as _s
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with _s.socket(_s.AF_UNIX, _s.SOCK_DGRAM) as s:
            s.connect(addr)
            s.send(state.encode())
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kristall-assistant", description="Kristall OS assistant daemon")
    p.add_argument("--demo", action="store_true", help="replay a scripted session (no Claude, no audio)")
    p.add_argument("--demo-auto", action="store_true", help="in demo mode, answer permission prompts by itself")
    p.add_argument("--demo-loop", type=float, default=0, metavar="SECONDS",
                   help="in demo mode, start a new scripted session every SECONDS")
    p.add_argument("--audio-in", metavar="WAV", help="development: use this file instead of the microphone")
    p.add_argument("--audio-out", metavar="WAV", help="development: write speech to this file instead of speakers")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    setup_logging(args.verbose)
    os.environ.setdefault("LANG", "C.UTF-8")
    _ = system_language
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())
