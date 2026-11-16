# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo mode: a realistic scripted session with no Claude and no audio.

Runs through the real daemon (same socket, same state machine, same events),
so the interface can be built, tested and screenshotted in a sandbox:

voice question → live transcript → thinking → tool activity with agent-cursor
movement → permission prompt → streamed answer → speaking.

``KRISTALL_DEMO_SPEED`` (default 1.0) scales every delay (tests use 20).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re

from .brain.brain import PermissionAsk, Turn
from .policy.policy import Decision, describe, question_for
from .voice.pipeline import ListenResult

VOICE_QUESTION = ("Kannst du die Fotos vom Gardasee in einen neuen Ordner Urlaub 2026 verschieben "
                  "und die doppelten löschen?")
TEXT_ANSWER = ("Morgen wird es in Berlin überwiegend sonnig, bei bis zu 14 Grad. "
               "Am Abend können ein paar Schauer durchziehen, nimm also besser einen Schirm mit.")


# Without a compositor bridge the demo assumes a 1280x800 logical screen at the origin: every
# laptop panel this runs on is at least that big, so the cursor never leaves the screen.
DEFAULT_SCREEN = (0.0, 0.0, 1280.0, 800.0)


async def screen_geometry(timeout: float = 0.5) -> tuple[float, float, float, float]:
    """(x, y, w, h) of the primary output in global logical pixels, asked from the bridge
    (docs/contracts/bridge.md, topic `outputs`); DEFAULT_SCREEN when there is no bridge."""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "kristall", "bridge.sock")
    if not os.path.exists(path):
        return DEFAULT_SCREEN
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), timeout)
        writer.write(b'{"id":1,"method":"hello","params":{"client":"kristall-assistant-demo","version":1}}\n'
                     b'{"id":2,"method":"subscribe","params":{"events":["outputs"]}}\n')
        await writer.drain()
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            line = await asyncio.wait_for(reader.readline(), max(0.01, end - loop.time()))
            if not line:
                return DEFAULT_SCREEN
            msg = json.loads(line)
            if msg.get("event") == "outputs.changed":
                outs = (msg.get("data") or {}).get("outputs") or []
                o = next((o for o in outs if o.get("primary")), outs[0] if outs else None)
                if not o:
                    return DEFAULT_SCREEN
                return float(o["x"]), float(o["y"]), float(o["w"]), float(o["h"])
    except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError):
        return DEFAULT_SCREEN
    finally:
        if writer is not None:
            writer.close()


def _speed() -> float:
    try:
        return max(0.05, float(os.environ.get("KRISTALL_DEMO_SPEED", "1")))
    except ValueError:
        return 1.0


async def pause(s: float) -> None:
    await asyncio.sleep(s / _speed())


class DemoListener:
    def __init__(self, a, at):
        self.a, self.at = a, at
        self._cancel = self._finish = False

    def finish(self) -> None:
        self._finish = True

    def cancel(self) -> None:
        self._cancel = True

    async def run(self) -> ListenResult:
        words = VOICE_QUESTION.split()
        rng = random.Random(7)
        await pause(0.4)
        t, shown, total = 0.0, 0, 4.5
        while t < total and not self._cancel and not self._finish:
            # speech-like envelope: syllable rhythm on a phrase contour
            v = 0.35 + 0.35 * abs(math.sin(t * 7.3)) * (0.6 + 0.4 * math.sin(t * 1.3)) + rng.uniform(0, 0.1)
            self.a.emit({"type": "level", "source": "mic", "value": round(min(v, 1.0), 3)}, levels=True)
            n = min(len(words), int(len(words) * (t / (total - 0.6))) + 1)
            if n > shown and int(t * 20) % 12 == 0:
                shown = n
                self.a.emit({"type": "transcript", "turn_id": self.at.id, "text": " ".join(words[:shown]),
                             "final": False})
            await pause(0.05)
            t += 0.05
        self.a.emit({"type": "level", "source": "mic", "value": 0.0}, levels=True)
        if self._cancel:
            return ListenResult("", "cancelled")
        self.at.phase = "transcribing"
        self.a.update_state()
        await pause(0.45)
        return ListenResult(VOICE_QUESTION, "final", 4.5)


MIC_CHECK = "Hallo Kristall, kannst du mich hören?"


class DemoTranscriber:
    """Transcribe-only in demo mode: levels, partial text, a final text; no turn, no state change."""

    def __init__(self, a, on_partial):
        self.a, self.on_partial = a, on_partial
        self._cancel = self._finish = False

    def finish(self) -> None:
        self._finish = True

    def cancel(self) -> None:
        self._cancel = True

    async def run(self) -> ListenResult:
        words = MIC_CHECK.split()
        t, total = 0.0, 2.0
        await pause(0.2)
        while t < total and not self._cancel and not self._finish:
            v = 0.3 + 0.4 * abs(math.sin(t * 7.3))
            self.a.emit({"type": "level", "source": "mic", "value": round(min(v, 1.0), 3)}, levels=True)
            if int(t * 20) % 8 == 0:
                self.on_partial(" ".join(words[:max(1, int(len(words) * t / total) + 1)]))
            await pause(0.05)
            t += 0.05
        self.a.emit({"type": "level", "source": "mic", "value": 0.0}, levels=True)
        if self._cancel:
            return ListenResult("", "cancelled")
        return ListenResult(MIC_CHECK, "final", t)


class DemoSpeaker:
    """Pretends to speak: sentence events and a speech-level envelope in real time."""

    def __init__(self, a, at):
        self.a, self.at = a, at
        from .voice.speechtext import SentenceChunker
        self.chunker = SentenceChunker()
        self.q: asyncio.Queue = asyncio.Queue()
        self.stopped = False
        self.task = None
        self.count = 0
        self.playing = False

    def start(self) -> None:
        self.task = asyncio.ensure_future(self._run())

    def feed(self, text: str) -> None:
        if not self.stopped:
            for s in self.chunker.feed(text):
                self.q.put_nowait(s)

    def close(self) -> None:
        for s in self.chunker.flush():
            self.q.put_nowait(s)
        self.q.put_nowait(None)

    def stop(self) -> None:
        self.stopped = True
        self.q.put_nowait(None)

    async def wait(self) -> bool:
        return await self.task if self.task else True

    async def _run(self) -> bool:
        while True:
            s = await self.q.get()
            if s is None or self.stopped:
                break
            if not re.search(r"\w", s):
                continue
            self.a._on_sentence(self.at, self.count, s)
            self.count += 1
            dur = max(0.8, len(s) / 14.0)
            t = 0.0
            while t < dur and not self.stopped:
                v = 0.3 + 0.45 * abs(math.sin(t * 9.1)) * (0.7 + 0.3 * math.sin(t * 2.1))
                self.a.emit({"type": "level", "source": "speech", "value": round(v, 3)}, levels=True)
                await pause(0.05)
                t += 0.05
            self.a.emit({"type": "level", "source": "speech", "value": 0.0}, levels=True)
            if self.q.empty():
                self.a._on_speech_idle(self.at)
        self.playing = False
        return not self.stopped


class DemoBrain:
    def __init__(self, a):
        self.a = a
        self.current: Turn | None = None
        self.screen = DEFAULT_SCREEN

    def prepare(self) -> None:
        pass

    def new_conversation(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def cancel(self) -> None:
        if self.current:
            self.current.cancelled = True

    async def _say(self, turn: Turn, text: str, segment: int) -> None:
        for tok in re.findall(r"\S+\s*", text):
            if turn.cancelled:
                return
            turn.emit({"type": "reply_delta", "text": tok, "segment": segment})
            await pause(0.045)

    async def _tool(self, turn: Turn, tid: str, tool: str, de: str, en: str, secs: float, detail: str | None = None):
        ev = {"type": "activity", "id": tid, "tool": tool, "status": "running", "text": {"de": de, "en": en}}
        if detail:
            ev["detail"] = detail
        turn.emit(ev)
        await pause(secs)
        turn.emit(dict(ev, status="done"))

    async def _cursor(self, path: list[tuple[float, float, str | None, str | None]]) -> None:
        """Move the agent cursor along ``path`` like hands would. Points are (fx, fy, pulse, label)
        with fx, fy fractions of the primary output; fy > 1 means "that many px above the bottom
        edge" counted as fy - 1 (the Dock)."""
        ox, oy, ow, oh = self.screen
        prev = self.a.cursor or {"x": ox + ow / 2, "y": oy + oh / 2}
        for fx, fy, pulse, label in path:
            x = round(ox + fx * ow, 1)
            y = round(oy + oh - (fy - 1) if fy > 1 else oy + fy * oh, 1)
            x0, y0 = prev.get("x", x), prev.get("y", y)
            steps = 12
            for i in range(1, steps + 1):
                f = 0.5 - 0.5 * math.cos(math.pi * i / steps)
                ev = {"type": "agent_cursor", "source": "demo-hands", "visible": True,
                      "x": round(x0 + (x - x0) * f, 1), "y": round(y0 + (y - y0) * f, 1)}
                if label:
                    ev["label"] = label
                if i == steps and pulse:
                    ev["pulse"] = pulse
                self.a.cursor = {k: v for k, v in ev.items() if k not in ("type", "pulse")}
                ev["turn_id"] = self.current.id if self.current else None
                self.a.emit(ev)
                await pause(0.035)
            prev = {"x": x, "y": y}
            await pause(0.35)

    async def run_turn(self, turn: Turn) -> Turn:
        self.current = turn
        self.screen = await screen_geometry()
        try:
            turn.emit({"type": "_conversation", "conversation_id": "demo", "continued": False})
            await pause(0.9)
            if "Fotos" not in turn.text:
                await self._tool(turn, "demo-ws", "WebSearch", "Suche im Web nach „Wetter Berlin morgen“",
                                 "Searching the web for “weather Berlin tomorrow”", 1.4)
                await self._say(turn, TEXT_ANSWER, 1)
                return turn
            await self._say(turn, "Klar, ich schaue mir die Fotos kurz an. ", 0)
            await self._tool(turn, "demo-glob", "Glob", "Durchsuche deine Dateien", "Searching your files", 1.2)
            turn.emit({"type": "activity", "id": "demo-hands", "tool": "mcp__hands__click", "status": "running",
                       "text": {"de": "Öffne „Dateien“", "en": "Opening “Files”"}})
            await self._cursor([(0.5, 1 + 30, "click", "Dateien"), (0.215, 0.228, "double_click", "Bilder"),
                                (0.34, 0.29, None, "Gardasee")])
            turn.emit({"type": "activity", "id": "demo-hands", "tool": "mcp__hands__click", "status": "done",
                       "text": {"de": "Öffne „Dateien“", "en": "Opening “Files”"}})
            if turn.cancelled:
                return turn
            pre = ("Ich habe 214 Fotos gefunden, 12 davon sind doppelt. Ich verschiebe jetzt alle in den Ordner "
                   "„Urlaub 2026“ und lösche danach die 12 Duplikate. ")
            await self._say(turn, pre, 1)
            await self._tool(turn, "demo-mv", "Bash", "Erledige das", "Doing it", 1.0,
                             detail="Fotos in „Urlaub 2026“ verschieben")
            act = describe("files.delete", targets=["a.jpg"] * 12)
            d = Decision("ask", "files.delete", "files.delete", True, act, question_for(act),
                         "rm ~/Bilder/Urlaub\\ 2026/Duplikate/*.jpg  (12 Dateien)")
            turn.emit({"type": "activity", "id": "demo-rm", "tool": "Bash", "status": "running",
                       "text": {"de": "Lösche Dateien", "en": "Deleting files"},
                       "detail": "12 doppelte Fotos löschen"})
            ask = PermissionAsk("demo-perm-1", turn.id, d, "Bash", pre.strip())
            if self.a.demo_options.get("auto"):
                async def auto():
                    await pause(4.0)
                    p = self.a.pending.get(ask.request_id)
                    if p and not p.future.done():
                        p.future.set_result(("allow_once", "owner"))
                asyncio.ensure_future(auto())
            answer = await self.a.ask_owner(ask)
            if turn.cancelled or answer == "cancelled":
                return turn
            allowed = answer in ("allow_once", "allow_always")
            await pause(0.8 if allowed else 0.2)
            turn.emit({"type": "activity", "id": "demo-rm", "tool": "Bash",
                       "status": "done" if allowed else "failed",
                       "text": {"de": "Lösche Dateien", "en": "Deleting files"}, "detail": "12 doppelte Fotos löschen"})
            await self._cursor([(0.52, 0.53, None, None)])
            self.a.cursor = dict(self.a.cursor or {}, visible=False)
            self.a.emit({"type": "agent_cursor", "source": "demo-hands", "visible": False,
                         "x": self.a.cursor.get("x"), "y": self.a.cursor.get("y"), "turn_id": turn.id})
            await pause(0.6)
            if allowed:
                await self._say(turn, "Fertig! Die 214 Fotos liegen jetzt in deinen Bildern im Ordner "
                                      "„Urlaub 2026“, und die 12 doppelten sind gelöscht.", 2)
            else:
                await self._say(turn, "In Ordnung, die Duplikate bleiben liegen. Die Fotos sind trotzdem "
                                      "schon im Ordner „Urlaub 2026“.", 2)
            return turn
        finally:
            self.current = None


async def demo_loop(a, every: float) -> None:
    """Start a scripted voice session every ``every`` seconds (for screenshots)."""
    from .server import Client  # noqa: F401  (keeps import graph obvious)
    await asyncio.sleep(1.0)
    n = 0
    while True:
        if a.turn is None:
            mode = "voice" if n % 2 == 0 else "text"
            msg = {"type": "invoke", "mode": mode, "source": "demo"}
            if mode == "text":
                msg["text"] = "Wie wird das Wetter morgen in Berlin?"
            await a._m_invoke(_NullClient(), msg)
            n += 1
        await asyncio.sleep(every)


class _NullClient:
    name = "demo-loop"
    role = "control"
    levels = False
