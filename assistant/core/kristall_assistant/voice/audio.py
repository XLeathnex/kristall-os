# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin, swappable audio ends around the speech pipeline.

Capture yields mono float32 chunks at 16 kHz; playback takes float32 samples
at any rate.  On the laptop both ends are PipeWire command-line clients
(``pw-record`` / ``pw-play``), so we link to nothing and a broken audio stack
can never crash the daemon.  Tests use ``FileSource``/``FileSink``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import wave
from typing import AsyncIterator

import numpy as np

log = logging.getLogger("kristall.audio")

RATE = 16000
CHUNK = 320          # 20 ms
APP_PROPS = json.dumps({"application.name": "Kristall Assistant", "application.id": "kristall-assistant",
                        "media.role": "Assistant"})


class AudioUnavailable(Exception):
    pass


def level(samples: np.ndarray) -> float:
    """Perceptual level 0..1 from float samples (-60 dBFS → 0, 0 dBFS → 1)."""
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms <= 1e-6:
        return 0.0
    db = 20 * np.log10(rms)
    return float(min(1.0, max(0.0, (db + 60) / 60)))


# ----------------------------------------------------------------- capture

class AudioSource:
    async def chunks(self) -> AsyncIterator[np.ndarray]:  # pragma: no cover - interface
        raise NotImplementedError
        yield

    async def close(self) -> None:
        pass


class PipeWireSource(AudioSource):
    def __init__(self, target: str | None = None):
        self.target = target
        self.proc: asyncio.subprocess.Process | None = None

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("pw-record") or shutil.which("parecord") or shutil.which("arecord"))

    async def _start(self) -> None:
        if shutil.which("pw-record"):
            argv = ["pw-record", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16",
                    "--latency=20ms", "--media-role=Assistant", "-P", APP_PROPS]
            if self.target:
                argv.append(f"--target={self.target}")
            argv.append("-")
        elif shutil.which("parecord"):
            argv = ["parecord", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                    "--latency-msec=20", "--client-name=Kristall Assistant"]
        elif shutil.which("arecord"):
            argv = ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]
        else:
            raise AudioUnavailable("no capture tool")
        self.proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL)

    async def chunks(self) -> AsyncIterator[np.ndarray]:
        await self._start()
        assert self.proc and self.proc.stdout
        nbytes = CHUNK * 2
        got_any = False
        while True:
            try:
                if got_any:
                    data = await self.proc.stdout.readexactly(nbytes)
                else:   # a microphone that delivers nothing within 3 s is unusable
                    data = await asyncio.wait_for(self.proc.stdout.readexactly(nbytes), 3.0)
            except asyncio.TimeoutError:
                raise AudioUnavailable("no audio from microphone")
            except asyncio.IncompleteReadError as e:
                data = e.partial
                if not data:
                    err = b""
                    if self.proc.stderr:
                        try:
                            err = await asyncio.wait_for(self.proc.stderr.read(400), 0.5)
                        except asyncio.TimeoutError:
                            pass
                    if not got_any:
                        raise AudioUnavailable(f"capture ended: {err.decode(errors='replace')[:200]}")
                    return
            got_any = True
            yield np.frombuffer(data[:len(data) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0

    async def close(self) -> None:
        p, self.proc = self.proc, None
        if p and p.returncode is None:
            try:
                p.terminate()
                await asyncio.wait_for(p.wait(), 1.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    p.kill()
                except ProcessLookupError:
                    pass


def read_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def resample(a: np.ndarray, sr: int, to: int = RATE) -> np.ndarray:
    if sr == to or a.size == 0:
        return a.astype(np.float32)
    n = max(1, int(round(len(a) * to / sr)))
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


class FileSource(AudioSource):
    """Plays a WAV file into the pipeline (optionally in real time), then
    ``tail_silence`` seconds of silence so end-of-speech can trigger."""

    def __init__(self, path: str | None = None, samples: np.ndarray | None = None, realtime: float = 0.0,
                 tail_silence: float = 2.0, lead_silence: float = 0.3):
        if samples is None:
            a, sr = read_wav(path)
            samples = resample(a, sr)
        self.samples = np.concatenate([np.zeros(int(lead_silence * RATE), np.float32), samples,
                                       np.zeros(int(tail_silence * RATE), np.float32)])
        self.realtime = realtime     # 1.0 = real time, 0 = as fast as possible
        self.closed = False

    async def chunks(self) -> AsyncIterator[np.ndarray]:
        for i in range(0, len(self.samples), CHUNK):
            if self.closed:
                return
            if self.realtime:
                await asyncio.sleep(CHUNK / RATE / self.realtime)
            else:
                await asyncio.sleep(0)
            yield self.samples[i:i + CHUNK]

    async def close(self) -> None:
        self.closed = True


# ----------------------------------------------------------------- playback

class AudioSink:
    """Plays one buffer at a time; ``stop()`` cuts off immediately."""

    async def play(self, samples: np.ndarray, sr: int) -> bool:  # pragma: no cover - interface
        """Return True if played to the end, False if stopped."""
        raise NotImplementedError

    def stop(self) -> None:
        pass


class PipeWireSink(AudioSink):
    def __init__(self):
        self.proc: asyncio.subprocess.Process | None = None
        self._stopped = False

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay"))

    async def play(self, samples: np.ndarray, sr: int) -> bool:
        self._stopped = False
        if shutil.which("pw-play"):
            argv = ["pw-play", "--raw", f"--rate={sr}", "--channels=1", "--format=s16",
                    "--media-role=Assistant", "-P", APP_PROPS, "-"]
        elif shutil.which("paplay"):
            argv = ["paplay", "--raw", "--format=s16le", f"--rate={sr}", "--channels=1",
                    "--client-name=Kristall Assistant"]
        elif shutil.which("aplay"):
            argv = ["aplay", "-q", "-f", "S16_LE", "-r", str(sr), "-c", "1", "-t", "raw"]
        else:
            raise AudioUnavailable("no playback tool")
        data = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
        self.proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        try:
            self.proc.stdin.write(data)
            await self.proc.stdin.drain()
            self.proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass
        rc = await self.proc.wait()
        if self._stopped:
            return False
        if rc != 0:
            err = (await self.proc.stderr.read(300)).decode(errors="replace") if self.proc.stderr else ""
            raise AudioUnavailable(f"playback failed ({rc}): {err}")
        return True

    def stop(self) -> None:
        self._stopped = True
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass


class FileSink(AudioSink):
    """Collects everything 'played' (for tests); can simulate playback time."""

    def __init__(self, realtime: float = 0.0):
        self.realtime = realtime
        self.played: list[tuple[np.ndarray, int]] = []
        self._stop = asyncio.Event()

    async def play(self, samples: np.ndarray, sr: int) -> bool:
        self._stop.clear()
        if self.realtime:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=len(samples) / sr / self.realtime)
                return False
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(0)
            if self._stop.is_set():
                return False
        self.played.append((samples, sr))
        return True

    def stop(self) -> None:
        self._stop.set()

    def write(self, path: str) -> None:
        if not self.played:
            return
        sr = self.played[0][1]
        a = np.concatenate([s for s, _ in self.played])
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


# ----------------------------------------------------------------- ducking

class Ducker:
    """Lowers other applications' playback while the assistant listens or
    speaks, and restores it afterwards (PipeWire's PulseAudio interface)."""

    def __init__(self, factor: float = 0.3):
        self.factor = factor
        self.saved: dict[str, str] = {}
        self.enabled = bool(shutil.which("pactl"))

    async def _pactl(self, *args: str) -> str:
        p = await asyncio.create_subprocess_exec("pactl", *args, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL)
        out, _ = await p.communicate()
        return out.decode(errors="replace")

    async def duck(self) -> None:
        if not self.enabled or self.saved:
            return
        try:
            items = json.loads(await self._pactl("-f", "json", "list", "sink-inputs") or "[]")
        except (ValueError, OSError):
            return
        for it in items:
            props = it.get("properties", {})
            if props.get("application.id") == "kristall-assistant" or props.get("media.role") == "Assistant":
                continue
            idx = str(it.get("index"))
            vol = it.get("volume", {})
            first = next(iter(vol.values()), {}) if isinstance(vol, dict) else {}
            pct = str(first.get("value_percent", "100%")).rstrip("%")
            try:
                cur = float(pct)
            except ValueError:
                continue
            self.saved[idx] = f"{cur:.0f}%"
            await self._pactl("set-sink-input-volume", idx, f"{cur * self.factor:.0f}%")

    async def restore(self) -> None:
        saved, self.saved = self.saved, {}
        for idx, vol in saved.items():
            try:
                await self._pactl("set-sink-input-volume", idx, vol)
            except OSError:
                pass


async def echo_cancel_source() -> str | None:
    """Name of a PipeWire echo-cancelled source, if the system provides one."""
    if not shutil.which("pactl"):
        return None
    try:
        p = await asyncio.create_subprocess_exec("pactl", "list", "short", "sources",
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(p.communicate(), 3)
    except (OSError, asyncio.TimeoutError):
        return None
    for line in out.decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and "echo-cancel" in parts[1]:
            return parts[1]
    return None
