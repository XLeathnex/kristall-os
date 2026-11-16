#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure speech recognisers and voices on this machine.

    voice_eval.py tts  <voice_dir> <sentences.txt> <out_dir> [lang]
    voice_eval.py asr  <engine> <model_dir> <manifest.json> [lang]
        engine: parakeet | canary | whisper | whisper5   (whisper5 = beam 5)
    manifest.json: [{"wav": path, "text": reference}, ...]

Each command runs in its own process (so memory numbers are clean) and prints
one JSON object: accuracy (WER after normalisation), real-time factor, load
time and peak resident memory.
"""
from __future__ import annotations

import json
import os
import re
import resource
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np                                                   # noqa: E402

from kristall_assistant.voice.speechtext import normalize           # noqa: E402

THREADS = int(os.environ.get("EVAL_THREADS", "4"))


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def read_wav(p: str) -> tuple[np.ndarray, int]:
    with wave.open(p, "rb") as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            a = a.reshape(-1, w.getnchannels()).mean(axis=1)
    return a, sr


def write_wav(p: str, a: np.ndarray, sr: int) -> None:
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def resample(a: np.ndarray, sr: int, to: int = 16000) -> np.ndarray:
    if sr == to:
        return a
    n = int(len(a) * to / sr)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


def words(text: str, lang: str) -> list[str]:
    t = normalize(text, lang).lower()
    t = t.replace("-", " ").replace("ß", "ss")  # Swiss/German spelling variants count as equal
    t = re.sub(r"[^\w\s']", " ", t)
    return t.split()


def wer(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev, d[j] = d[j], cur
    return d[len(hyp)], len(ref)


def cmd_tts(voice_dir: str, sentences: str, out_dir: str, lang: str = "de") -> dict:
    import sherpa_onnx
    vd = Path(voice_dir)
    onnx = next(p for p in vd.glob("*.onnx"))
    t0 = time.monotonic()
    cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(onnx), tokens=str(vd / "tokens.txt"),
                                                   data_dir=str(vd / "espeak-ng-data")),
        num_threads=THREADS))
    tts = sherpa_onnx.OfflineTts(cfg)
    load = time.monotonic() - t0
    os.makedirs(out_dir, exist_ok=True)
    lines = [l.strip() for l in open(sentences, encoding="utf-8") if l.strip() and not l.startswith("#")]
    manifest, synth, audio, first = [], 0.0, 0.0, None
    for i, l in enumerate(lines):
        t1 = time.monotonic()
        g = tts.generate(normalize(l, lang), sid=0, speed=1.0)
        dt = time.monotonic() - t1
        if first is None:
            first = dt
        synth += dt
        a = np.array(g.samples, dtype=np.float32)
        audio += len(a) / g.sample_rate
        p = os.path.join(out_dir, f"{i:02d}.wav")
        write_wav(p, resample(a, g.sample_rate), 16000)
        manifest.append({"wav": p, "text": l})
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w"), ensure_ascii=False, indent=1)
    return {"voice": vd.name, "sentences": len(lines), "load_s": round(load, 2), "rtf": round(synth / audio, 3),
            "first_sentence_s": round(first or 0, 3), "sample_rate": tts.sample_rate,
            "peak_rss_mb": round(rss_mb())}


def cmd_asr(engine: str, model_dir: str, manifest: str, lang: str = "de") -> dict:
    items = json.load(open(manifest, encoding="utf-8"))
    md = Path(model_dir)
    t0 = time.monotonic()
    if engine in ("parakeet", "canary"):
        import sherpa_onnx
        if engine == "parakeet":
            rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(md / "encoder.int8.onnx"), decoder=str(md / "decoder.int8.onnx"),
                joiner=str(md / "joiner.int8.onnx"), tokens=str(md / "tokens.txt"),
                num_threads=THREADS, model_type="nemo_transducer")
        else:
            rec = sherpa_onnx.OfflineRecognizer.from_nemo_canary(
                encoder=str(md / "encoder.int8.onnx"), decoder=str(md / "decoder.int8.onnx"),
                tokens=str(md / "tokens.txt"), src_lang=lang, tgt_lang=lang, num_threads=THREADS)

        def transcribe(a: np.ndarray) -> str:
            s = rec.create_stream()
            s.accept_waveform(16000, a)
            rec.decode_stream(s)
            return s.result.text
    else:
        from faster_whisper import WhisperModel
        model = WhisperModel(str(md), device="cpu", compute_type="int8", cpu_threads=THREADS)
        beam = 5 if engine == "whisper5" else 1

        def transcribe(a: np.ndarray) -> str:
            segs, _info = model.transcribe(a, language=None, beam_size=beam, vad_filter=False,
                                           condition_on_previous_text=False)
            return " ".join(s.text for s in segs)
    load = time.monotonic() - t0
    errs = n = 0
    proc = audio = 0.0
    worst = []
    for it in items:
        a, sr = read_wav(it["wav"])
        a = resample(a, sr)
        t1 = time.monotonic()
        hyp = transcribe(a)
        proc += time.monotonic() - t1
        audio += len(a) / 16000
        e, k = wer(words(it["text"], lang), words(hyp, lang))
        errs += e
        n += k
        if e:
            worst.append({"ref": it["text"], "hyp": hyp.strip(), "errors": e})
    worst.sort(key=lambda x: -x["errors"])
    return {"engine": engine, "items": len(items), "audio_s": round(audio, 1), "wer": round(errs / max(n, 1), 4),
            "word_errors": errs, "words": n, "rtf": round(proc / audio, 3), "load_s": round(load, 2),
            "peak_rss_mb": round(rss_mb()), "errors": worst[:12]}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "tts":
        res = cmd_tts(*sys.argv[2:])
    elif cmd == "asr":
        res = cmd_asr(*sys.argv[2:])
    else:
        raise SystemExit(__doc__)
    print(json.dumps(res, ensure_ascii=False))
