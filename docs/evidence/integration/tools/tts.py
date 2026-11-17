#!/usr/bin/python3
# tts.py TEXT OUT.raw — German speech with the image's own Piper voice (sherpa-onnx), 16 kHz s16le mono
import sys, numpy as np, sherpa_onnx
d = "/usr/share/kristall/assistant/models/tts/de_DE-thorsten-medium/"
cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(vits=sherpa_onnx.OfflineTtsVitsModelConfig(
    model=d + "de_DE-thorsten-medium.onnx", tokens=d + "tokens.txt", data_dir=d + "espeak-ng-data"), num_threads=2))
tts = sherpa_onnx.OfflineTts(cfg)
a = tts.generate(sys.argv[1], sid=0, speed=1.0)
x = np.asarray(a.samples, dtype=np.float32)
n = int(len(x) * 16000 / a.sample_rate)
y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
pad = np.zeros(8000, dtype=np.float32)
y = np.concatenate([pad, y, pad, pad, pad])
open(sys.argv[2], "wb").write((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
print(sys.argv[2], len(y) / 16000.0, "s")
