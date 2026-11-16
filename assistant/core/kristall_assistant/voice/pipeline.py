# SPDX-License-Identifier: GPL-3.0-or-later
"""Listening (capture → VAD → live transcript → final text) and speaking
(sentences → synthesis → playback), independent of where audio comes from.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import numpy as np

from .audio import RATE, AudioSink, AudioSource, AudioUnavailable, level
from .models import ModelManager
from .speechtext import SentenceChunker, detect_language, normalize

log = logging.getLogger("kristall.voice")

LEVEL_INTERVAL = 0.05          # 20 Hz level updates, only while active
PARTIAL_INTERVAL = 0.6         # re-decode the growing utterance this often
PRE_ROLL = int(0.3 * RATE)


@dataclass
class ListenResult:
    text: str
    outcome: str               # "final" | "nothing_heard" | "cancelled" | "error"
    audio_seconds: float = 0.0
    error: str | None = None


@dataclass
class ListenConfig:
    end_of_speech_ms: int = 800
    no_speech_timeout: float = 7.0
    max_utterance: float = 45.0
    partials: bool = True


class Listener:
    """One listening session.  Call ``run()``; ``finish()`` ends it early
    (push-to-talk released), ``cancel()`` throws it away."""

    def __init__(self, models: ModelManager, source: AudioSource, cfg: ListenConfig, *,
                 on_level: Callable[[float], None], on_partial: Callable[[str], None],
                 on_speech: Callable[[bool], None] = lambda s: None,
                 on_transcribing: Callable[[], None] = lambda: None):
        self.models = models
        self.source = source
        self.cfg = cfg
        self.on_level = on_level
        self.on_partial = on_partial
        self.on_speech = on_speech
        self.on_transcribing = on_transcribing
        self._finish = False
        self._cancel = False
        self._decoding: asyncio.Task | None = None

    def finish(self) -> None:
        self._finish = True

    def cancel(self) -> None:
        self._cancel = True

    async def run(self) -> ListenResult:
        try:
            vad_factory = self.models.vad()
            asr_task = asyncio.ensure_future(self.models.asr())      # load while the owner starts talking
            vad = await asyncio.to_thread(vad_factory.create)
        except Exception as e:   # noqa: BLE001
            return ListenResult("", "error", error=f"models: {e!r}")
        ring: list[np.ndarray] = []          # pre-roll before speech
        utter: list[np.ndarray] = []
        started = False
        heard_at = 0.0
        t_start = time.monotonic()
        audio_t = 0.0                        # seconds of audio consumed (stream clock)
        last_level = 0.0
        last_partial_at = 0.0
        last_partial = ""
        level_acc: list[np.ndarray] = []
        try:
            async for chunk in self.source.chunks():
                if self._cancel:
                    return ListenResult("", "cancelled")
                audio_t += len(chunk) / RATE
                level_acc.append(chunk)
                if audio_t - last_level >= LEVEL_INTERVAL:
                    self.on_level(level(np.concatenate(level_acc)))
                    level_acc.clear()
                    last_level = audio_t
                vad.accept_waveform(chunk)
                speech_now = vad.is_speech_detected()
                while not vad.empty():
                    vad.pop()
                if not started:
                    ring.append(chunk)
                    if sum(len(c) for c in ring) > PRE_ROLL:
                        ring.pop(0)
                    if speech_now:
                        started = True
                        heard_at = audio_t
                        utter = list(ring)
                        self.on_speech(True)
                    elif audio_t >= self.cfg.no_speech_timeout or self._finish:
                        return ListenResult("", "nothing_heard")
                    continue
                utter.append(chunk)
                if speech_now:
                    heard_at = audio_t
                silence = audio_t - heard_at
                dur = sum(len(c) for c in utter) / RATE
                if self.cfg.partials and audio_t - last_partial_at >= PARTIAL_INTERVAL and \
                        (self._decoding is None or self._decoding.done()) and asr_task.done():
                    last_partial_at = audio_t
                    buf = np.concatenate(utter)

                    async def _partial(b=buf):
                        nonlocal last_partial
                        try:
                            txt = await asyncio.to_thread(asr_task.result().transcribe, b)
                        except Exception:   # noqa: BLE001
                            return
                        if txt and txt != last_partial and not self._cancel:
                            last_partial = txt
                            self.on_partial(txt)
                    self._decoding = asyncio.ensure_future(_partial())
                if self._finish or silence * 1000 >= self.cfg.end_of_speech_ms or dur >= self.cfg.max_utterance:
                    break
            else:
                if not started:
                    return ListenResult("", "nothing_heard")
        except AudioUnavailable as e:
            return ListenResult("", "error", error=str(e))
        finally:
            await self.source.close()
            self.on_level(0.0)
        if self._cancel:
            return ListenResult("", "cancelled")
        self.on_speech(False)
        self.on_transcribing()
        try:
            asr = await asr_task
            if self._decoding and not self._decoding.done():
                await self._decoding
            buf = np.concatenate(utter) if utter else np.zeros(0, np.float32)
            text = await asyncio.to_thread(asr.transcribe, buf)
        except Exception as e:   # noqa: BLE001
            return ListenResult("", "error", error=f"asr: {e!r}")
        if self._cancel:
            return ListenResult("", "cancelled")
        if not text.strip():
            return ListenResult("", "nothing_heard", len(buf) / RATE)
        log.info("heard %.1fs in %.2fs total", len(buf) / RATE, time.monotonic() - t_start)
        return ListenResult(text.strip(), "final", len(buf) / RATE)


@dataclass
class SpeakItem:
    index: int
    text: str
    lang: str


class Speaker:
    """Speaks sentences as they arrive; synthesis of the next sentence overlaps
    playback of the current one.  ``stop()`` cuts off at once."""

    def __init__(self, models: ModelManager, sink: AudioSink, *, rate: Callable[[], float],
                 default_lang: Callable[[], str],
                 on_level: Callable[[float], None], on_sentence: Callable[[int, str], None],
                 on_start: Callable[[], None] = lambda: None, on_error: Callable[[str], None] = lambda e: None,
                 on_idle: Callable[[], None] = lambda: None):
        self.models = models
        self.sink = sink
        self.rate = rate
        self.default_lang = default_lang
        self.on_level = on_level
        self.on_sentence = on_sentence
        self.on_start = on_start
        self.on_error = on_error
        self.on_idle = on_idle
        self.chunker = SentenceChunker()
        self.queue: asyncio.Queue[SpeakItem | None] = asyncio.Queue()
        self.lang: str | None = None
        self.count = 0
        self.task: asyncio.Task | None = None
        self.stopped = False
        self.started = False
        self.spoken: list[str] = []
        self._level_task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.ensure_future(self._run())

    def feed(self, text: str) -> None:
        if self.stopped:
            return
        for s in self.chunker.feed(text):
            self._put(s)

    def close(self) -> None:
        """No more text will come."""
        if self.stopped:
            return
        for s in self.chunker.flush():
            self._put(s)
        self.queue.put_nowait(None)

    def _put(self, s: str) -> None:
        if not any(ch.isalnum() for ch in s):
            return
        if self.lang is None:
            self.lang = detect_language(s, self.default_lang())
        self.queue.put_nowait(SpeakItem(self.count, s, self.lang))
        self.count += 1

    def stop(self) -> None:
        self.stopped = True
        self.sink.stop()
        self.queue.put_nowait(None)
        if self._level_task:
            self._level_task.cancel()

    async def wait(self) -> bool:
        """True when everything was spoken, False when stopped or failed."""
        if self.task is None:
            return True
        return await self.task

    async def _synth(self, item: SpeakItem) -> tuple[np.ndarray, int]:
        voice = await self.models.voice(item.lang)
        text = normalize(item.text, item.lang)
        samples = await asyncio.to_thread(voice.synth, text, float(self.rate()))
        # 120 ms of breath between sentences
        return np.concatenate([samples, np.zeros(int(0.12 * voice.sample_rate), np.float32)]), voice.sample_rate

    async def _run(self) -> bool:
        """Queue items are SpeakItem, or None = end (close/stop)."""
        nothing_yet = object()
        pending: asyncio.Task | None = None
        try:
            item = await self.queue.get()
            while item is not None and not self.stopped:
                if pending is None:
                    pending = asyncio.ensure_future(self._synth(item))
                samples, sr = await pending
                pending = None
                nxt = self.queue.get_nowait() if not self.queue.empty() else nothing_yet
                if isinstance(nxt, SpeakItem):
                    pending = asyncio.ensure_future(self._synth(nxt))   # overlap with playback
                if self.stopped:
                    break
                if not self.started:
                    self.started = True
                    self.on_start()
                self.on_sentence(item.index, item.text)
                self._level_task = asyncio.ensure_future(self._levels(samples, sr))
                ok = await self.sink.play(samples, sr)
                self._level_task.cancel()
                self.on_level(0.0)
                if not ok:
                    return False
                self.spoken.append(item.text)
                if nxt is nothing_yet:
                    if self.queue.empty():
                        self.on_idle()          # nothing more to say right now (e.g. a tool is running)
                    item = await self.queue.get()
                else:
                    item = nxt
            return not self.stopped
        except AudioUnavailable as e:
            self.on_error(str(e))
            return False
        except Exception as e:   # noqa: BLE001
            log.exception("speaking failed")
            self.on_error(repr(e))
            return False
        finally:
            if pending:
                pending.cancel()

    async def _levels(self, samples: np.ndarray, sr: int) -> None:
        """Publish the speech level in step with playback (20 Hz, only while speaking)."""
        hop = int(sr * LEVEL_INTERVAL)
        t0 = time.monotonic()
        try:
            for i in range(0, len(samples), hop):
                self.on_level(level(samples[i:i + hop]))
                target = t0 + (i + hop) / sr
                await asyncio.sleep(max(0.0, target - time.monotonic()))
        except asyncio.CancelledError:
            pass
