# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice pipeline on files: German/English round trip (synthesise → recognise),
end-of-speech, partial transcripts, cut-in, speaking, model unloading, and a
full spoken turn through the daemon.  Needs the speech models: set
KRISTALL_TEST_MODELS to a directory laid out like /usr/share/kristall/assistant/models."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import HERE, SockClient, run, start_daemon

MODELS = os.environ.get("KRISTALL_TEST_MODELS")
pytestmark = pytest.mark.skipif(not MODELS or not Path(MODELS, "asr").is_dir(),
                                reason="speech models not available (set KRISTALL_TEST_MODELS)")

from kristall_assistant.voice.audio import FileSink, FileSource, resample  # noqa: E402
from kristall_assistant.voice.models import RELEASE_AGAIN_AFTER, ModelManager  # noqa: E402
from kristall_assistant.voice.pipeline import ListenConfig, Listener, Speaker  # noqa: E402
from kristall_assistant.voice.speechtext import normalize                  # noqa: E402

NUMBERY = re.compile(r"\d")


def sentences(lang):
    p = HERE / "data" / f"roundtrip_{lang}.txt"
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def words(t, lang):
    t = normalize(t, lang).lower().replace("-", " ").replace("ß", "ss")
    return re.sub(r"[^\w\s']", " ", t).split()


def wer(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)]


def mm(settings=None):
    s = {"models_unload_after_seconds": 300, **(settings or {})}
    return ModelManager(Path(MODELS), lambda: s)


async def synth16k(models, text, lang):
    v = await models.voice(lang)
    a = await asyncio.to_thread(v.synth, normalize(text, lang), 1.0)
    return resample(a, v.sample_rate)


async def listen(models, samples, realtime=0.0, **cfg):
    partials = []
    levels = []
    lst = Listener(models, FileSource(samples=samples, realtime=realtime), ListenConfig(**cfg),
                   on_level=levels.append, on_partial=partials.append)
    res = await lst.run()
    return res, partials, levels


def roundtrip(lang, recognizer="parakeet"):
    async def go():
        models = mm({"recognizer": recognizer})
        rows = []
        for s in sentences(lang):
            a = await synth16k(models, s, lang)
            t0 = time.monotonic()
            res, _, _ = await listen(models, a)
            rows.append({"ref": s, "hyp": res.text, "errors": wer(words(s, lang), words(res.text, lang)),
                         "words": len(words(s, lang)), "outcome": res.outcome,
                         "seconds": round(time.monotonic() - t0, 2), "audio": round(len(a) / 16000, 2)})
        return rows
    rows = run(go(), timeout=600)
    errs, n = sum(r["errors"] for r in rows), sum(r["words"] for r in rows)
    num = [r for r in rows if NUMBERY.search(r["ref"])]
    num_errs, num_n = sum(r["errors"] for r in num), sum(r["words"] for r in num)
    report = {"lang": lang, "recognizer": recognizer, "sentences": len(rows), "wer": round(errs / n, 4),
              "wer_number_sentences": round(num_errs / max(num_n, 1), 4),
              "exact_sentences": sum(r["errors"] == 0 for r in rows),
              "mean_listen_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
              "worst": sorted(rows, key=lambda r: -r["errors"])[:5]}
    out = os.environ.get("KRISTALL_TEST_REPORT")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        Path(out, f"roundtrip_{lang}_{recognizer}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\nROUND TRIP {lang}/{recognizer}: WER {report['wer']:.1%} over {n} words, "
          f"number sentences {report['wer_number_sentences']:.1%}, exact {report['exact_sentences']}/{len(rows)}")
    for w in report["worst"][:3]:
        print(f"   {w['errors']}: {w['ref']}  →  {w['hyp']}")
    assert all(r["outcome"] == "final" for r in rows)
    return report


def test_roundtrip_german():
    r = roundtrip("de")
    assert r["wer"] <= 0.12, r


def test_roundtrip_english():
    r = roundtrip("en")
    assert r["wer"] <= 0.08, r


def test_roundtrip_german_canary():
    r = roundtrip("de", "canary-de")
    assert r["wer"] <= 0.15, r


def test_partials_levels_and_end_of_speech():
    async def go():
        models = mm()
        a = await synth16k(models, "Wie wird das Wetter am Wochenende in München und in Hamburg?", "de")
        await models.asr()      # the daemon preloads on `prepare`/hotkey; here explicitly
        t0 = time.monotonic()
        res, partials, levels = await listen(models, a, realtime=3.0, end_of_speech_ms=700)
        return res, partials, levels, time.monotonic() - t0, len(a) / 16000
    res, partials, levels, took, dur = run(go())
    assert res.outcome == "final" and "Wetter" in res.text
    assert partials, "live transcript expected while speaking"
    assert any(v > 0.3 for v in levels) and levels[-1] == 0.0
    # ended by silence detection, well before the 2 s of trailing silence ran out
    assert took < (0.3 + dur + 2.0) / 3.0 + 1.5


def test_nothing_heard_and_finish_and_cancel():
    async def go():
        models = mm()
        silence = np.zeros(16000 * 10, np.float32)
        r1, _, _ = await listen(models, silence, no_speech_timeout=2.0)
        a = await synth16k(models, "Hallo, das ist ein Test.", "de")
        lst = Listener(models, FileSource(samples=a, realtime=2.0, tail_silence=10), ListenConfig(end_of_speech_ms=5000),
                       on_level=lambda v: None, on_partial=lambda t: None)
        task = asyncio.ensure_future(lst.run())
        await asyncio.sleep((0.3 + len(a) / 16000) / 2.0 + 0.3)
        lst.finish()
        r2 = await asyncio.wait_for(task, 5)
        lst3 = Listener(models, FileSource(samples=a, realtime=1.0), ListenConfig(),
                        on_level=lambda v: None, on_partial=lambda t: None)
        task = asyncio.ensure_future(lst3.run())
        await asyncio.sleep(0.5)
        lst3.cancel()
        r3 = await asyncio.wait_for(task, 2)
        return r1, r2, r3
    r1, r2, r3 = run(go())
    assert r1.outcome == "nothing_heard"
    assert r2.outcome == "final" and "Test" in r2.text
    assert r3.outcome == "cancelled"


def test_speaker_sentences_levels_and_cut_in():
    async def go():
        models = mm()
        sink = FileSink(realtime=8.0)
        said, levels = [], []
        sp = Speaker(models, sink, rate=lambda: 1.0, default_lang=lambda: "de", on_level=levels.append,
                     on_sentence=lambda i, s: said.append(s))
        sp.start()
        for tok in "Hallo! Es ist 14:30 Uhr. Morgen wird es sonnig, bei 22 °C.".split(" "):
            sp.feed(tok + " ")
        sp.close()
        ok = await sp.wait()
        # cut-in: real-time sink, stop during the first sentence
        sink2 = FileSink(realtime=1.0)
        sp2 = Speaker(models, sink2, rate=lambda: 1.0, default_lang=lambda: "de", on_level=lambda v: None,
                      on_sentence=lambda i, s: None)
        sp2.start()
        sp2.feed("Das ist ein sehr langer Satz, der gleich unterbrochen wird, weil jemand dazwischen redet. ")
        sp2.feed("Und noch einer. ")
        sp2.close()
        await asyncio.sleep(0.6)
        t0 = time.monotonic()
        sp2.stop()
        ok2 = await sp2.wait()
        return ok, said, sink, levels, ok2, time.monotonic() - t0, sink2
    ok, said, sink, levels, ok2, took, sink2 = run(go())
    assert ok and said == ["Hallo!", "Es ist 14:30 Uhr.", "Morgen wird es sonnig, bei 22 °C."]
    assert len(sink.played) == 3 and all(sr == 22050 for _, sr in sink.played)
    assert any(v > 0.2 for v in levels)
    assert ok2 is False and took < 0.3 and sink2.played == []


def test_english_reply_uses_english_voice():
    async def go():
        models = mm()
        sink = FileSink()
        sp = Speaker(models, sink, rate=lambda: 1.0, default_lang=lambda: "de", on_level=lambda v: None,
                     on_sentence=lambda i, s: None)
        sp.start()
        sp.feed("Sure, it is twenty past three in the afternoon. ")
        sp.close()
        await sp.wait()
        return sp.lang, models.loaded
    lang, loaded = run(go())
    assert lang == "en" and "en_US-joe-medium" in loaded


def test_models_unload_after_quiet_period():
    async def go():
        models = mm({"models_unload_after_seconds": 0.2})
        await models.voice("de")
        before = list(models.loaded)
        await asyncio.sleep(0.5)
        return before, models.loaded
    before, after = run(go())
    assert before and after == []


def test_unloaded_models_give_memory_back():
    """unloading must lower the process's RSS, not only drop references (glibc keeps freed pages
    unless trimmed: the daemon stayed at ~1 GB after its first use in the integrated session)"""
    def rss_kb():
        return int(next(l for l in open("/proc/self/status") if l.startswith("VmRSS:")).split()[1])

    async def go():
        models = mm({"models_unload_after_seconds": 3600})
        base = rss_kb()
        await models.voice("de")
        await models.asr()
        loaded = rss_kb()
        models.unload()
        await asyncio.sleep(RELEASE_AGAIN_AFTER + 0.5)
        return base, loaded, rss_kb()
    base, loaded, after = run(go())
    grown = loaded - base
    assert grown > 100_000, f"models did not load ({base} → {loaded} kB)"
    assert after - base < grown * 0.4, f"RSS stayed high after unloading: {base} → {loaded} → {after} kB"


def test_full_spoken_turn_through_daemon(env, monkeypatch):
    """Voice question (synthesised) → transcript → Claude (recorded) → spoken answer."""
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "de_simple_followup")

    async def go():
        models = mm()
        q = await synth16k(models, "Wie heißt die Hauptstadt von Australien?", "de")
        sink = FileSink()
        a = await start_daemon(env, source_factory=lambda: FileSource(samples=q, realtime=4.0),
                               sink_factory=lambda: sink)
        await a.refresh_account()
        c = await SockClient.connect(env.socket)
        await c.request({"type": "subscribe", "levels": True})
        snap = next(e for e in c.events if e["type"] == "snapshot")
        await c.request({"type": "invoke", "mode": "voice", "source": "test"})
        fin = await c.wait_for(lambda e: e["type"] == "turn_finished", timeout=60)
        await c.close()
        await a.stop()
        return c.events, fin, sink, snap
    ev, fin, sink, snap = run(go(), timeout=120)
    import ipc_schema
    assert not [e for x in ev for e in ipc_schema.check(x)]
    assert snap["voice"]["input"] and snap["voice"]["output"]
    final = next(e for e in ev if e["type"] == "transcript" and e["final"])
    assert "Hauptstadt" in final["text"] and "Australien" in final["text"]
    states = [e["state"] for e in ev if e["type"] == "state"]
    assert states[:3] == ["listening", "transcribing", "thinking"] and "speaking" in states and states[-1] == "idle"
    assert any(e["type"] == "level" and e["source"] == "mic" for e in ev)
    assert any(e["type"] == "level" and e["source"] == "speech" for e in ev)
    spoken = [e["text"] for e in ev if e["type"] == "speech"]
    assert spoken and "Canberra" in spoken[0]
    assert len(sink.played) == len(spoken)
    assert next(e for e in ev if e["type"] == "reply_done")["spoken"] is True
    assert fin["outcome"] == "completed"
