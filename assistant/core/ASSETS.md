# assistant-core — third-party assets and how they were chosen

Nothing listed here is committed to the repository. Models are downloaded at image build time by
`image/install.sh` from the pinned URLs in `image/models.tsv` and verified by SHA-256 before they are
installed into `/usr/share/kristall/assistant/models/`. Python packages are installed from
`image/requirements.txt` with `--require-hashes`.

## Speech models

| file(s) | what | licence | source | SHA-256 |
|---|---|---|---|---|
| `asr/parakeet-tdt-0.6b-v3-int8/{encoder,decoder,joiner}.int8.onnx`, `tokens.txt` | **NVIDIA Parakeet TDT 0.6B v3** (25 European languages, automatic language), int8 ONNX export by the sherpa-onnx project | CC-BY-4.0 (NVIDIA). Attribution: "Parakeet TDT 0.6B v3 by NVIDIA, licensed CC-BY-4.0, converted to ONNX by k2-fsa/sherpa-onnx" | huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 @ `ed5d7456` (upstream nvidia/parakeet-tdt-0.6b-v3) | encoder `1afbe69c…f2c479`, decoder `0222a861…c0b5`, joiner `cbd02f36…fc98`, tokens `d5854467…fc98`¹ |
| `asr/canary-180m-flash-int8/{encoder,decoder}.int8.onnx`, `tokens.txt` | **NVIDIA Canary 180M Flash** (en/de/es/fr), int8 ONNX by sherpa-onnx; optional "German only" recogniser | CC-BY-4.0 (NVIDIA) | huggingface.co/csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8 @ `9077164e` (upstream nvidia/canary-180m-flash) | encoder `7a75b4e2…303f`, decoder `e41a2ab9…cba2`, tokens `2dae6fc7…3e77`¹ |
| `vad/silero_vad.onnx` | **Silero VAD** voice-activity detector | MIT | github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx (upstream snakers4/silero-vad) | `9e2449e1…1fd6`¹ |
| `tts/de_DE-thorsten-medium/` | **Piper voice "thorsten" (medium)**, German, 22 050 Hz, VITS, packaged for sherpa-onnx with `espeak-ng-data` | voice: CC0 (Thorsten-Voice dataset, Thorsten Müller); fine-tuned from the Piper "rdh" base model (CC0). `espeak-ng-data`: GPL-3.0-or-later (eSpeak NG) | github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-de_DE-thorsten-medium.tar.bz2 (upstream rhasspy/piper-voices `de/de_DE/thorsten/medium`, MODEL_CARD included) | tarball `50487d9c…1714`¹ |
| `tts/en_US-joe-medium/` | **Piper voice "joe" (medium)**, US English | voice: CC0 (OHF-Voice voice-datasets); fine-tuned from the "rdh" base (CC0). `espeak-ng-data`: GPL-3.0-or-later | github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-joe-medium.tar.bz2 (upstream rhasspy/piper-voices `en/en_US/joe/medium`) | tarball `261b903a…bd3`¹ |

¹ Full hashes in `image/models.tsv`.

Runtime: **sherpa-onnx 1.13.8** (Apache-2.0, bundles ONNX Runtime, MIT) — pinned to 1.13.x because
2.0 removed the built-in espeak-ng phonemiser that Piper voices need (verified: 2.0.1 fails with
"no frontend available"). **Claude Agent SDK for Python 0.2.182** (MIT), installed from its source
distribution: its binary wheels bundle the proprietary Claude Code executable, which we must not
ship (the install script fails if a bundled binary appears). Other Python dependencies and their
licences are listed in `image/requirements.txt` (all MIT/BSD/Apache-2.0/PSF-compatible).

## How the recogniser and voices were chosen (measured 2026-11-15 in the build sandbox)

Machine: 4 vCPU cloud VM (slower than the i9-13900H laptop), CPU only, 4 threads, int8 models.
WER = word error rate after normalising numbers to words, case and punctuation (so "17" and
"siebzehn" match). Data: (a) round trip — our 25 German / 10 English assistant-style sentences
(`tests/data/roundtrip_*.txt`, names, numbers, times, dates, loan words, umlauts) synthesised by a
voice, then recognised; (b) real speech — 30 German utterances from Multilingual LibriSpeech
(test, CC-BY-4.0, 434 s, different speakers) and 15 English LibriSpeech test-clean utterances (99 s).

| recogniser | DE round trip (thorsten-medium) | DE round trip (thorsten-high) | DE real (MLS) | EN round trip | EN real (LS) | speed (RTF) | peak RAM | load |
|---|---|---|---|---|---|---|---|---|
| **Parakeet TDT 0.6B v3 int8** | 8.9 % | 7.6 % | 10.2 %² | 3.0 % | 1.5 % | 0.07–0.11 | 0.95–1.2 GB | 2.9 s |
| Canary 180M Flash int8 (lang fixed) | 8.1 % | 9.3 % | **4.9 %** | 7.1 % | 1.5 % | 0.13–0.17 | 0.41–0.64 GB | 1.3 s |
| Whisper large-v3-turbo (faster-whisper int8, beam 1) | 5.5 % | — | not finished | — | — | **3.4** (slower than real time) | 1.65 GB | 1.2 s |

² 37 of the 105 errors come from a single utterance that Parakeet's automatic language detection
took for English; without it 6.9 %.

Decision: **Parakeet** is the default — it is 30–45× faster than Whisper turbo here (Whisper turbo
is slower than real time on this CPU, ruling it out for an interactive assistant) and it detects
the language itself, which the owner needs (German first, English equally). **Canary** is more
accurate on real German read speech and half the memory, but with a fixed source language it
*translates* other languages (fed English with `de` it returned "Setzen Sie einen Alarm …"), so it
is shipped as the opt-in "German only" mode (`assistant.recognizer = "canary-de"`, +207 MB).

Voices: Piper (VITS) through sherpa-onnx. `de_DE-thorsten-medium` synthesises at RTF 0.042
(first sentence ready in 0.16 s, 261 MB); `thorsten-high` is 5× slower (RTF 0.21) for a round-trip
intelligibility difference within noise (7.6 % vs 8.9 % with Parakeet; 9.3 % vs 8.1 % with Canary)
and is fine-tuned from the "lessac" voice whose dataset licence is research-only, so it is not
used. `kerstin-low` (16 kHz) and other German Piper voices are fine-tuned from the
non-commercial "ryan" voice or have non-commercial data. English: `en_US-joe-medium` (CC0 chain,
RTF 0.049); `en_US-ryan-high` is CC-BY-NC-SA and excluded. Also examined: MOSS-TTS-Nano 100M
(Apache-2.0, German, ONNX export) — an autoregressive voice-cloning model needing a custom
decoding loop and a reference voice; not integrated in this round. Kokoro-82M has no German voice.

Test-suite round trip with the shipped configuration (`tests/test_voice.py`, through the real
Listener with VAD; three runs, the VITS voice is stochastic): German 6.8–8.5 % WER (15–17 of 25
sentences exact; sentences with numbers 6.9–11.5 %, mostly formatting such as "249,99 Euro" for
"249 Euro und 99 Cent" or "9.45 Uhr" for "9:45 Uhr"), English 1.0–3.0 %, German with Canary 9.8 %.
A real spoken turn (synthesised question → daemon → real Claude Haiku 5.5 → spoken answer, recognised
again) was transcribed correctly both ways.
