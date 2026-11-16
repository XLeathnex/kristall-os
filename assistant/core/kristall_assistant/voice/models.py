# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech models: loaded on first use, unloaded after a quiet period.

Recogniser: NVIDIA Parakeet TDT 0.6B v3 (int8, sherpa-onnx) — detects the
spoken language itself, so German and English both work without a setting.
Optional "German only" mode: NVIDIA Canary 180M Flash with the language fixed
to German (more accurate on German read speech, but it *translates* other
languages, so it is opt-in).  Voice activity: Silero VAD.  Voices: Piper
(VITS) de_DE-thorsten-medium and en_US-joe-medium.  Measurements and licences
are in assistant/core/ASSETS.md.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("kristall.models")

ASR_DIRS = {
    "parakeet": "asr/parakeet-tdt-0.6b-v3-int8",
    "canary-de": "asr/canary-180m-flash-int8",
}
VAD_FILE = "vad/silero_vad.onnx"
VOICES = {
    "de_DE-thorsten-medium": "tts/de_DE-thorsten-medium",
    "en_US-joe-medium": "tts/en_US-joe-medium",
}
DEFAULT_VOICE = {"de": "de_DE-thorsten-medium", "en": "en_US-joe-medium"}


def _threads() -> int:
    return max(1, min(4, (os.cpu_count() or 2) // 2))


class Recognizer:
    def __init__(self, engine: str, d: Path):
        import sherpa_onnx
        self.engine = engine
        if engine == "canary-de":
            self.rec = sherpa_onnx.OfflineRecognizer.from_nemo_canary(
                encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
                tokens=str(d / "tokens.txt"), src_lang="de", tgt_lang="de", num_threads=_threads())
        else:
            self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
                joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
                num_threads=_threads(), model_type="nemo_transducer")
        self._lock = threading.Lock()

    def transcribe(self, samples: np.ndarray) -> str:
        with self._lock:
            s = self.rec.create_stream()
            s.accept_waveform(16000, samples)
            self.rec.decode_stream(s)
            text = s.result.text.strip()
        # Canary puts spaces before punctuation.
        return text.replace(" ,", ",").replace(" .", ".").replace(" ?", "?").replace(" !", "!")


class Voice:
    def __init__(self, name: str, d: Path):
        import sherpa_onnx
        onnx = next(d.glob("*.onnx"))
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(onnx), tokens=str(d / "tokens.txt"),
                                                       data_dir=str(d / "espeak-ng-data")),
            num_threads=_threads()))
        self.name = name
        self.tts = sherpa_onnx.OfflineTts(cfg)
        self.sample_rate = self.tts.sample_rate
        self._lock = threading.Lock()

    def synth(self, text: str, speed: float = 1.0) -> np.ndarray:
        with self._lock:
            g = self.tts.generate(text, sid=0, speed=speed)
        return np.asarray(g.samples, dtype=np.float32)


@dataclass
class Vad:
    model: str

    def create(self, min_silence: float = 0.25):
        import sherpa_onnx
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = self.model
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = min_silence
        cfg.silero_vad.min_speech_duration = 0.15
        cfg.silero_vad.window_size = 512
        cfg.sample_rate = 16000
        cfg.num_threads = 1
        return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)


class ModelManager:
    """Owns the loaded models; everything heavy runs in worker threads."""

    def __init__(self, models_dir: Path, settings):
        self.dir = models_dir
        self.settings = settings
        self._asr: Recognizer | None = None
        self._voices: dict[str, Voice] = {}
        self._unload: asyncio.TimerHandle | None = None
        self._load_lock = asyncio.Lock()
        self.last_use = time.monotonic()

    # availability -----------------------------------------------------------
    def asr_engine(self) -> str:
        e = self.settings().get("recognizer", "parakeet")
        return e if e in ASR_DIRS else "parakeet"

    def asr_available(self) -> bool:
        d = self.dir / ASR_DIRS[self.asr_engine()]
        return (d / "encoder.int8.onnx").exists() and (self.dir / VAD_FILE).exists()

    def voice_name(self, lang: str) -> str:
        v = (self.settings().get("voice") or {}).get(lang)
        return v if v in VOICES else DEFAULT_VOICE["en" if lang == "en" else "de"]

    def tts_available(self, lang: str = "de") -> bool:
        return (self.dir / VOICES[self.voice_name(lang)]).is_dir()

    # loading ----------------------------------------------------------------
    def touch(self) -> None:
        self.last_use = time.monotonic()
        if self._unload:
            self._unload.cancel()
        delay = float(self.settings().get("models_unload_after_seconds", 300))
        try:
            self._unload = asyncio.get_running_loop().call_later(delay, self.unload)
        except RuntimeError:
            pass

    async def asr(self) -> Recognizer:
        self.touch()
        engine = self.asr_engine()
        if self._asr is None or self._asr.engine != engine:
            async with self._load_lock:
                if self._asr is None or self._asr.engine != engine:
                    t = time.monotonic()
                    self._asr = await asyncio.to_thread(Recognizer, engine, self.dir / ASR_DIRS[engine])
                    log.info("loaded recogniser %s in %.1fs", engine, time.monotonic() - t)
                    self.touch()
        return self._asr

    def vad(self) -> Vad:
        return Vad(str(self.dir / VAD_FILE))

    async def voice(self, lang: str) -> Voice:
        self.touch()
        name = self.voice_name(lang)
        if name not in self._voices:
            async with self._load_lock:
                if name not in self._voices:
                    t = time.monotonic()
                    self._voices[name] = await asyncio.to_thread(Voice, name, self.dir / VOICES[name])
                    log.info("loaded voice %s in %.1fs", name, time.monotonic() - t)
                    self.touch()
        return self._voices[name]

    async def preload_asr(self) -> None:
        try:
            await self.asr()
        except Exception as e:   # noqa: BLE001
            log.warning("recogniser preload failed: %r", e)

    def unload(self) -> None:
        if self._asr or self._voices:
            log.info("unloading speech models after quiet period")
        self._asr = None
        self._voices.clear()
        gc.collect()

    @property
    def loaded(self) -> list[str]:
        out = list(self._voices)
        if self._asr:
            out.insert(0, self._asr.engine)
        return out
