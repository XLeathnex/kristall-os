# SPDX-License-Identifier: GPL-3.0-or-later
"""The brain: Claude Haiku 5.5 through the owner's own ``claude`` CLI.

We use Anthropic's official Python Agent SDK (installed from its pure-Python
sdist, so the proprietary CLI binary it bundles in wheels is *not* shipped);
the SDK starts the owner's installed ``claude`` in streaming-JSON mode and
speaks its control protocol (permission callbacks, hooks, interrupts,
in-process MCP tools).

Lifecycle
---------
* A ``Conversation`` is one warm CLI process holding one conversation.
* Follow-ups within ``conversation_window_seconds`` of the last turn reuse it;
  a later request starts a fresh conversation (a pre-started *spare* process
  when one is ready, so there is no cold start).
* ``prepare()`` starts a spare in the background (the daemon calls it the
  moment the owner opens the panel or starts speaking).
* Idle processes are closed after ``brain_unload_after_seconds``.
* ``cancel()`` interrupts the running turn at once (control-protocol
  interrupt, falling back to killing the process).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from ..errors import AssistantError
from ..policy.policy import Decision, Policy
from . import cli as climod
from .memory import Memory, make_mcp_server
from .prompt import build_system_prompt, user_message

log = logging.getLogger("kristall.brain")

BUILTIN_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"]
DISALLOWED = ["Agent", "Task", "AskUserQuestion", "NotebookEdit", "Skill", "SlashCommand",
              "ExitPlanMode", "EnterPlanMode", "Monitor", "CronCreate", "RemoteTrigger"]

DENY_TO_MODEL = ("The owner's system policy does not allow this action. Do not try it another way; "
                 "tell the owner briefly that you can't do this.")
OWNER_SAID_NO = ("The owner declined this. Accept it, do not try another way around, and offer an "
                 "alternative if there is one.")


@dataclass
class PermissionAsk:
    request_id: str
    turn_id: str
    decision: Decision
    tool: str
    explanation: str           # the model's own words about what it is about to do
    cli_title: str = ""


@dataclass
class Turn:
    id: str
    text: str
    spoken: bool
    emit: Callable[[dict], None]
    context: dict = field(default_factory=dict)
    cancelled: bool = False
    segment: int = 0
    reply: list[str] = field(default_factory=list)
    preamble: str = ""
    tools: dict[str, dict] = field(default_factory=dict)
    error_code: str | None = None
    resets_at: float | None = None
    no_response_retries: int = 0
    streamed_msgs: set = field(default_factory=set)
    conversation_id: str = ""
    continued: bool = False
    stop_reason: str | None = None

    @property
    def reply_text(self) -> str:
        return "".join(self.reply)


BASH_ACTIVITY = {
    "read": ("Schaue nach", "Checking"),
    "reversible": ("Erledige das", "Doing it"),
    "files.modify": ("Ändere Dateien", "Changing files"),
    "files.delete": ("Lösche Dateien", "Deleting files"),
    "system.config": ("Ändere Einstellungen", "Changing settings"),
    "processes.stop": ("Beende ein Programm", "Stopping a program"),
    "system.power": ("Ändere den Energiezustand", "Changing power state"),
    "apps.install": ("Installiere Software", "Installing software"),
    "send": ("Sende etwas", "Sending"),
    "elevated": ("Führe einen Admin-Befehl aus", "Running an admin command"),
    "credentials": ("Greife auf Zugangsdaten zu", "Accessing sign-in data"),
}


def activity_text(tool: str, inp: dict, labels: dict[str, dict[str, str]]) -> dict[str, str]:
    """Human-readable line about what the assistant is doing right now."""
    def q(s: str, lang: str) -> str:
        s = str(s)[:60]
        return f"„{s}“" if lang == "de" else f"“{s}”"
    import os
    if tool == "WebSearch":
        qy = inp.get("query", "")
        return {"de": f"Suche im Web nach {q(qy, 'de')}", "en": f"Searching the web for {q(qy, 'en')}"}
    if tool == "WebFetch":
        host = urlparse(str(inp.get("url", ""))).hostname or "eine Webseite"
        return {"de": f"Lese {host}", "en": f"Reading {host}"}
    if tool == "Read":
        n = os.path.basename(str(inp.get("file_path", "")))
        return {"de": f"Lese {q(n, 'de')}", "en": f"Reading {q(n, 'en')}"}
    if tool in ("Glob", "Grep"):
        return {"de": "Durchsuche deine Dateien", "en": "Searching your files"}
    if tool == "Write":
        n = os.path.basename(str(inp.get("file_path", "")))
        return {"de": f"Schreibe {q(n, 'de')}", "en": f"Writing {q(n, 'en')}"}
    if tool == "Edit":
        n = os.path.basename(str(inp.get("file_path", "")))
        return {"de": f"Bearbeite {q(n, 'de')}", "en": f"Editing {q(n, 'en')}"}
    if tool == "Bash":
        return {"de": "Führe einen Befehl aus", "en": "Running a command"}
    if tool == "mcp__kristall__remember":
        return {"de": "Merke mir das", "en": "Remembering that"}
    if tool == "mcp__kristall__forget":
        return {"de": "Vergesse das", "en": "Forgetting that"}
    if tool.startswith("mcp__"):
        _, server, name = (tool.split("__", 2) + ["", ""])[:3]
        intent = inp.get("intent") or inp.get("description")
        if isinstance(intent, str) and intent.strip():
            return {"de": intent.strip()[:120], "en": intent.strip()[:120]}
        lbl = labels.get(server, {})
        return {"de": f"{lbl.get('de', server)}: {name}", "en": f"{lbl.get('en', server)}: {name}"}
    return {"de": f"Verwende {tool}", "en": f"Using {tool}"}


class Conversation:
    def __init__(self, brain: "Brain"):
        self.brain = brain
        self.id = uuid.uuid4().hex[:12]
        self.client = None
        self.turn: Turn | None = None
        self.turns = 0
        self.last_used = time.monotonic()
        self.created = time.monotonic()
        self.dead = False
        self.lock = asyncio.Lock()
        self.ready = asyncio.Event()
        self.start_error: BaseException | None = None
        self._pending_decisions: dict[str, Decision] = {}

    # --- SDK callbacks ---------------------------------------------------------
    async def pre_tool_use(self, input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        tool = input_data.get("tool_name", "")
        inp = input_data.get("tool_input") or {}
        d = self.brain.policy.evaluate(tool, inp)
        log.info("policy %s %s -> %s (%s%s)", tool, d.scope, d.verdict, d.reason,
                 ", granted" if d.granted else "")
        if d.verdict == "deny":
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                           "permissionDecision": "deny",
                                           "permissionDecisionReason": DENY_TO_MODEL}}
        if d.verdict == "allow":
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                           "permissionDecision": "allow",
                                           "permissionDecisionReason": "Kristall policy: " + d.category}}
        if tool_use_id:
            self._pending_decisions[tool_use_id] = d
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "ask",
                                       "permissionDecisionReason": "Needs the owner's permission: " + d.category}}

    async def can_use_tool(self, tool: str, inp: dict, ctx: Any):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        tuid = getattr(ctx, "tool_use_id", None)
        d = self._pending_decisions.pop(tuid, None) if tuid else None
        if d is None:
            d = self.brain.policy.evaluate(tool, inp)
            # Claude Code itself wants a confirmation our policy would not ask
            # for (e.g. a critical path) — then the owner decides.
            if d.verdict == "allow" and (getattr(ctx, "decision_reason", "") or "").lower().startswith("dangerous"):
                d.verdict = "ask"
        if d.verdict == "allow":
            return PermissionResultAllow(updated_input=inp)
        if d.verdict == "deny":
            return PermissionResultDeny(message=DENY_TO_MODEL)
        turn = self.turn
        if turn is None or turn.cancelled:
            return PermissionResultDeny(message="Cancelled.", interrupt=True)
        explanation = str(inp.get("description") or inp.get("intent") or "").strip()
        pre = turn.preamble.strip()
        if pre:
            explanation = pre if not explanation else f"{pre} ({explanation})"
        ask = PermissionAsk(uuid.uuid4().hex[:12], turn.id, d, tool, explanation[:600],
                            getattr(ctx, "title", "") or "")
        answer = await self.brain.ask_owner(ask)
        if answer in ("allow_once", "allow_always"):
            if answer == "allow_always" and d.can_always:
                self.brain.policy.grants.add(d.scope, d.action.get("de", ""))
            return PermissionResultAllow(updated_input=inp)
        if answer == "cancelled":
            return PermissionResultDeny(message="Cancelled by the owner.", interrupt=True)
        return PermissionResultDeny(message=OWNER_SAID_NO)

    # --- lifecycle -------------------------------------------------------------
    async def start(self) -> None:
        try:
            self.client = self.brain.make_client(self)
            await asyncio.wait_for(self.client.connect(), timeout=self.brain.connect_timeout)
        except BaseException as e:
            self.start_error = e
            self.dead = True
            raise
        finally:
            self.ready.set()

    async def close(self) -> None:
        self.dead = True
        c, self.client = self.client, None
        if c is not None:
            try:
                await asyncio.wait_for(c.disconnect(), timeout=5)
            except BaseException as e:   # noqa: BLE001 - closing must never raise
                log.debug("disconnect: %r", e)


class Brain:
    def __init__(self, *, paths, settings: Callable[[], dict], policy: Policy, memory: Memory,
                 mcp_setup: Callable[[], Any], ask_owner: Callable[[PermissionAsk], Awaitable[str]],
                 cli_path: Callable[[], str | None] | None = None):
        self.paths = paths
        self.settings = settings
        self.policy = policy
        self.memory = memory
        self.mcp_setup = mcp_setup
        self.ask_owner = ask_owner
        self._cli_path = cli_path or (lambda: climod.find_cli())
        self.active: Conversation | None = None
        self.spare: Conversation | None = None
        self.current_turn: Turn | None = None
        self.connect_timeout = 60.0
        self._spare_task: asyncio.Task | None = None
        self._unload_handle: asyncio.TimerHandle | None = None
        self._bg: set[asyncio.Task] = set()

    # --- options ---------------------------------------------------------------
    def make_client(self, conv: Conversation):
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher
        s = self.settings()
        path = self._cli_path()
        if not path:
            raise AssistantError("cli_missing")
        setup = self.mcp_setup()
        servers: dict[str, Any] = dict(setup.servers)
        servers["kristall"] = make_mcp_server(self.memory)
        self.paths.workspace.mkdir(parents=True, exist_ok=True)
        opts = ClaudeAgentOptions(
            cli_path=path,
            cwd=str(self.paths.workspace),
            model=s.get("model") or "claude-haiku-5-5",
            system_prompt=build_system_prompt(s.get("name", "Kristall"), s.get("owner_name", ""),
                                              self.memory.as_prompt()),
            tools=list(BUILTIN_TOOLS),
            disallowed_tools=list(DISALLOWED),
            setting_sources=[],
            strict_mcp_config=True,
            mcp_servers=servers,
            permission_mode="default",
            can_use_tool=conv.can_use_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[conv.pre_tool_use], timeout=30)]},
            include_partial_messages=True,
            effort=s.get("effort") or "low",   # measured: first token 0.85 s vs 5.4 s with adaptive thinking
            env=climod.child_env(),
            extra_args={"no-session-persistence": None, "disable-slash-commands": None},
            stderr=lambda line: log.debug("claude: %s", line.rstrip()),
        )
        return ClaudeSDKClient(options=opts)

    # --- conversation management ---------------------------------------------
    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.ensure_future(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    def prepare(self) -> None:
        """Make sure a process is warm for the next request (non-blocking)."""
        self._reschedule_unload()
        if self.active and not self.active.dead and self._within_window(self.active):
            return
        if self.spare and not self.spare.dead:
            return
        if not self._cli_path():
            return
        conv = Conversation(self)
        self.spare = conv

        async def _go():
            try:
                await conv.start()
                log.info("spare conversation %s warm", conv.id)
            except BaseException as e:   # noqa: BLE001
                log.warning("could not start claude: %r", e)
                if self.spare is conv:
                    self.spare = None
        self._spare_task = self._spawn(_go())

    def _within_window(self, conv: Conversation) -> bool:
        win = float(self.settings().get("conversation_window_seconds", 180))
        return time.monotonic() - conv.last_used <= win

    def new_conversation(self) -> None:
        old, self.active = self.active, None
        if old:
            self._spawn(old.close())

    async def _conversation_for_turn(self) -> tuple[Conversation, bool]:
        if self.active and not self.active.dead and self._within_window(self.active):
            return self.active, True
        self.new_conversation()
        conv = self.spare
        self.spare = None
        if conv is None or conv.dead:
            conv = Conversation(self)
            self._spawn(conv.start())
        await conv.ready.wait()
        if conv.dead:
            raise self._map_start_error(conv.start_error)
        self.active = conv
        return conv, False

    def _map_start_error(self, e: BaseException | None) -> AssistantError:
        if isinstance(e, AssistantError):
            return e
        name = type(e).__name__ if e else ""
        text = str(e or "")
        if name == "CLINotFoundError":
            return AssistantError("cli_missing", text)
        low = text.lower()
        if "login" in low or "not logged in" in low or "authenticat" in low:
            return AssistantError("not_signed_in", text)
        if isinstance(e, asyncio.TimeoutError):
            return AssistantError("timeout", "claude did not start")
        return AssistantError("brain_crashed", f"{name}: {text}"[:300])

    def _reschedule_unload(self) -> None:
        if self._unload_handle:
            self._unload_handle.cancel()
        delay = float(self.settings().get("brain_unload_after_seconds", 600))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._unload_handle = loop.call_later(delay, lambda: self._spawn(self.unload()))

    async def unload(self) -> None:
        """Close idle processes (memory matters on a 16 GB laptop)."""
        if self.current_turn is not None:
            self._reschedule_unload()
            return
        for c in (self.active, self.spare):
            if c:
                await c.close()
        self.active = self.spare = None
        log.info("brain unloaded after idle period")

    async def shutdown(self) -> None:
        if self._unload_handle:
            self._unload_handle.cancel()
        for c in (self.active, self.spare):
            if c:
                await c.close()
        for t in list(self._bg):
            t.cancel()

    # --- turns -------------------------------------------------------------------
    async def run_turn(self, turn: Turn) -> Turn:
        """Run one request to completion (or cancellation). Never raises for
        owner-facing failures: they are reported via ``turn.error_code``."""
        self.current_turn = turn
        self._reschedule_unload()
        try:
            try:
                conv, continued = await self._conversation_for_turn()
            except AssistantError as e:
                turn.error_code = e.code
                log.warning("cannot start conversation: %s", e.detail)
                return turn
            turn.conversation_id, turn.continued = conv.id, continued
            turn.emit({"type": "_conversation", "conversation_id": conv.id, "continued": continued})
            async with conv.lock:
                if turn.cancelled:
                    return turn
                conv.turn = turn
                prompt = user_message(turn.text, spoken=turn.spoken, **turn.context)
                try:
                    await conv.client.query(prompt)
                    async for msg in conv.client.receive_response():
                        self._handle(turn, msg)
                        if turn.error_code == "offline" and not turn.cancelled:
                            # Do not sit through a dozen retries: say so now.
                            turn.cancelled = True
                            self._spawn(self._interrupt(conv))
                except Exception as e:   # noqa: BLE001
                    if not turn.cancelled:
                        log.warning("conversation %s failed: %r", conv.id, e)
                        turn.error_code = turn.error_code or self._map_start_error(e).code
                        if turn.error_code in ("cli_missing",):
                            pass
                    conv.dead = True
                    self._spawn(conv.close())
                finally:
                    conv.turn = None
                    conv.turns += 1
                    conv.last_used = time.monotonic()
                if conv.dead and self.active is conv:
                    self.active = None
            return turn
        finally:
            if self.current_turn is turn:
                self.current_turn = None
            self._reschedule_unload()
            # Have a fresh process ready for the next unrelated request.
            if not self.spare:
                self.prepare_spare_later()

    def prepare_spare_later(self) -> None:
        if self.spare is None and self._cli_path():
            conv = Conversation(self)
            self.spare = conv

            async def _go():
                try:
                    await conv.start()
                except BaseException as e:   # noqa: BLE001
                    log.debug("spare failed: %r", e)
                    if self.spare is conv:
                        self.spare = None
            self._spawn(_go())

    async def cancel(self) -> None:
        turn = self.current_turn
        if turn is None:
            return
        turn.cancelled = True
        conv = self.active
        if conv and conv.turn is turn:
            await self._interrupt(conv)

    async def _interrupt(self, conv: Conversation) -> None:
        try:
            if conv.client is not None:
                await asyncio.wait_for(conv.client.interrupt(), timeout=2.0)
                return
        except BaseException as e:   # noqa: BLE001
            log.warning("interrupt failed (%r); restarting the process", e)
        conv.dead = True
        if self.active is conv:
            self.active = None
        await conv.close()

    # --- message translation ---------------------------------------------------
    def _handle(self, turn: Turn, msg: Any) -> None:
        from claude_agent_sdk import (AssistantMessage, RateLimitEvent, ResultMessage, StreamEvent,
                                      SystemMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage)
        emit = (lambda ev: None) if turn.cancelled else turn.emit
        if isinstance(msg, StreamEvent):
            ev = msg.event or {}
            et = ev.get("type")
            if et == "message_start":
                mid = (ev.get("message") or {}).get("id")
                if mid:
                    turn.streamed_msgs.add(mid)
            elif et == "content_block_delta":
                d = ev.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    self._text(turn, d["text"], emit)
            elif et == "content_block_start":
                cb = ev.get("content_block") or {}
                if cb.get("type") in ("tool_use", "server_tool_use", "mcp_tool_use"):
                    emit({"type": "_tool_pending"})
            return
        if isinstance(msg, AssistantMessage):
            if getattr(msg, "error", None):
                code = {"authentication_failed": "not_signed_in", "billing_error": "credit_exhausted",
                        "rate_limit": "rate_limited", "server_error": "overloaded",
                        "invalid_request": "service_error"}.get(msg.error, "service_error")
                if code == "rate_limited" and turn.error_code == "credit_exhausted":
                    code = "credit_exhausted"
                turn.error_code = turn.error_code or code
            if msg.stop_reason == "refusal":
                turn.stop_reason = "refusal"
            streamed = msg.message_id in turn.streamed_msgs if msg.message_id else False
            for b in msg.content:
                if isinstance(b, TextBlock) and not streamed and not msg.error and b.text:
                    self._text(turn, b.text, emit)
                elif isinstance(b, ToolUseBlock) and msg.parent_tool_use_id is None:
                    inp = b.input or {}
                    act = activity_text(b.name, inp, self.mcp_setup().labels)
                    detail = None
                    if b.name == "Bash":
                        cat = self.policy.evaluate("Bash", inp).category
                        de, en = BASH_ACTIVITY.get(cat, ("Führe einen Befehl aus", "Running a command"))
                        act = {"de": de, "en": en}
                        detail = str(inp.get("description") or "")[:200] or None
                    turn.tools[b.id] = {"tool": b.name, "text": act, "detail": detail}
                    ev = {"type": "activity", "id": b.id, "tool": b.name, "status": "running", "text": act}
                    if detail:
                        ev["detail"] = detail
                    emit(ev)
                    turn.segment += 1
            return
        if isinstance(msg, UserMessage):
            content = msg.content if isinstance(msg.content, list) else []
            for b in content:
                if isinstance(b, ToolResultBlock) and b.tool_use_id in turn.tools:
                    info = turn.tools[b.tool_use_id]
                    ev = {"type": "activity", "id": b.tool_use_id, "tool": info["tool"],
                          "status": "failed" if b.is_error else "done", "text": info["text"]}
                    if info.get("detail"):
                        ev["detail"] = info["detail"]
                    emit(ev)
                    turn.preamble = ""
            return
        if isinstance(msg, RateLimitEvent):
            info = msg.rate_limit_info
            if info.status == "rejected":
                long_window = info.rate_limit_type in ("seven_day", "seven_day_opus", "seven_day_sonnet", "overage") \
                    or bool(info.overage_disabled_reason) \
                    or (info.resets_at and info.resets_at - time.time() > 24 * 3600)
                turn.error_code = "credit_exhausted" if long_window else "rate_limited"
                turn.resets_at = info.resets_at
            elif info.status == "allowed_warning":
                emit({"type": "_usage_warning", "utilization": info.utilization,
                      "resets_at": info.resets_at, "kind": info.rate_limit_type})
            return
        if isinstance(msg, SystemMessage):
            if msg.subtype == "api_retry":
                d = msg.data or {}
                err = d.get("error")
                if d.get("error_status") is None and err in (None, "unknown", "server_error") or d.get("no_response"):
                    turn.no_response_retries += 1
                    if turn.no_response_retries >= 2:
                        turn.error_code = "offline"
                elif err == "authentication_failed":
                    turn.error_code = "not_signed_in"
                elif err == "billing_error":
                    turn.error_code = "credit_exhausted"
                elif err == "rate_limit" and turn.error_code is None:
                    emit({"type": "_retrying", "reason": "rate_limit"})
                elif err == "model_not_found":
                    turn.error_code = "cli_outdated"
                elif err == "overloaded":
                    emit({"type": "_retrying", "reason": "overloaded"})
            return
        if isinstance(msg, ResultMessage):
            if msg.stop_reason == "refusal":
                turn.stop_reason = "refusal"
            if msg.is_error and not turn.cancelled and not turn.error_code:
                text = " ".join([msg.result or ""] + list(msg.errors or [])).lower()
                st = msg.api_error_status
                if "login" in text or "authenticat" in text or "api key" in text or st == 401:
                    turn.error_code = "not_signed_in"
                elif st == 429 or "rate limit" in text or "usage limit" in text:
                    turn.error_code = "rate_limited"
                elif "credit" in text or "billing" in text or st == 402:
                    turn.error_code = "credit_exhausted"
                elif st in (500, 502, 503, 529) or "overloaded" in text:
                    turn.error_code = "overloaded"
                elif "model" in text and ("not found" in text or "not available" in text or "invalid" in text):
                    turn.error_code = "cli_outdated"
                elif "connection" in text or "network" in text or "enotfound" in text or "fetch failed" in text:
                    turn.error_code = "offline"
                elif msg.subtype == "error_during_execution" and not text.strip():
                    pass   # interrupted
                else:
                    turn.error_code = "service_error"
                log.warning("turn %s ended with error: subtype=%s status=%s text=%s",
                            turn.id, msg.subtype, st, text[:200])
            if turn.stop_reason == "refusal" and not turn.reply_text.strip():
                turn.error_code = turn.error_code or "refused"
            return

    def _text(self, turn: Turn, text: str, emit) -> None:
        turn.reply.append(text)
        turn.preamble += text
        emit({"type": "reply_delta", "text": text, "segment": turn.segment})
