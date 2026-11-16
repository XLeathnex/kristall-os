#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Kristall sound theme: a small set of quiet, short event sounds synthesised here (no samples),
following the freedesktop sound naming spec. Restrained on purpose: no login/logout sound, no
sound for routine notifications beyond one soft chime, peaks around -18 dBFS.

    sounds.py OUTDIR   -> OUTDIR/kristall/{index.theme,stereo/*.wav}
"""
import math
import os
import struct
import sys
import wave

RATE = 48000
PEAK = 0.13   # ≈ -18 dBFS


def env(t, attack, decay):
    return (1 - math.exp(-t / attack)) * math.exp(-t / decay)


def tone(freqs, dur, attack=0.003, decay=0.12, glide=0.0):
    """sum of partials (freq, amplitude, decay factor); glide: relative pitch drop over the sound"""
    n = int(RATE * dur)
    out = [0.0] * n
    for f, a, dk in freqs:
        ph = 0.0
        for i in range(n):
            t = i / RATE
            fi = f * (1 - glide * min(1.0, t / dur))
            ph += 2 * math.pi * fi / RATE
            out[i] += a * math.sin(ph) * env(t, attack, decay * dk)
    return out


def noise(dur, decay, seed=1, lowpass=0.2):
    n = int(RATE * dur)
    x, y, out = seed, 0.0, []
    for i in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        r = x / 0x3FFFFFFF - 1.0
        y += lowpass * (r - y)
        out.append(y * math.exp(-(i / RATE) / decay))
    return out


def concat(*parts, gap=0.0):
    out = []
    for p in parts:
        out += p + [0.0] * int(RATE * gap)
    return out


def mix(a, b, offset=0.0):
    off = int(RATE * offset)
    n = max(len(a), off + len(b))
    out = a + [0.0] * (n - len(a))
    for i, v in enumerate(b):
        out[off + i] += v
    return out


def bell(f):
    # soft glassy bell: inharmonic partials decaying at different rates
    return [(f, 1.0, 1.0), (f * 2.76, 0.32, 0.45), (f * 5.40, 0.10, 0.25)]


SOUNDS = {
    "bell": lambda: tone(bell(1318.5), 0.35, decay=0.10),
    "dialog-warning": lambda: concat(tone(bell(1046.5), 0.16, decay=0.06), tone(bell(1046.5), 0.30, decay=0.09), gap=0.02),
    "dialog-error": lambda: tone([(392.0, 1.0, 1.0), (588.0, 0.35, 0.6)], 0.30, decay=0.08, glide=0.04),
    "dialog-information": lambda: tone(bell(1568.0), 0.30, decay=0.08),
    "dialog-question": lambda: tone(bell(1174.7), 0.30, decay=0.08),
    "message-new-instant": lambda: mix(tone(bell(1318.5), 0.5, decay=0.12), tone(bell(1975.5), 0.45, decay=0.14), 0.09),
    "message": lambda: mix(tone(bell(1318.5), 0.5, decay=0.12), tone(bell(1975.5), 0.45, decay=0.14), 0.09),
    "complete": lambda: mix(tone(bell(1046.5), 0.4, decay=0.1), tone(bell(1568.0), 0.4, decay=0.12), 0.07),
    "outcome-success": lambda: mix(tone(bell(1046.5), 0.4, decay=0.1), tone(bell(1568.0), 0.4, decay=0.12), 0.07),
    "outcome-failure": lambda: tone([(330.0, 1.0, 1.0), (495.0, 0.3, 0.6)], 0.28, decay=0.08, glide=0.05),
    "trash-empty": lambda: [v * 0.9 for v in mix(noise(0.22, 0.05, 3, 0.35), noise(0.18, 0.04, 9, 0.25), 0.07)],
    "screen-capture": lambda: mix(noise(0.05, 0.010, 5, 0.6), noise(0.06, 0.012, 7, 0.5), 0.085),
    "camera-shutter": lambda: mix(noise(0.05, 0.010, 5, 0.6), noise(0.06, 0.012, 7, 0.5), 0.085),
    "device-added": lambda: mix(tone(bell(1046.5), 0.25, decay=0.07), tone(bell(1568.0), 0.3, decay=0.09), 0.08),
    "device-removed": lambda: mix(tone(bell(1568.0), 0.25, decay=0.07), tone(bell(1046.5), 0.3, decay=0.09), 0.08),
    "power-plug": lambda: tone([(523.25, 1.0, 1.0), (1046.5, 0.25, 0.5)], 0.22, attack=0.004, decay=0.06),
    "power-unplug": lambda: tone([(392.0, 1.0, 1.0), (784.0, 0.25, 0.5)], 0.22, attack=0.004, decay=0.06),
    "audio-volume-change": lambda: tone([(1760.0, 1.0, 1.0), (3520.0, 0.15, 0.4)], 0.07, attack=0.001, decay=0.018),
    "window-attention": lambda: tone(bell(1318.5), 0.3, decay=0.08),
}


def write_wav(path, samples):
    peak = max(1e-9, max(abs(v) for v in samples))
    # 10 ms fade-out, scale to the house peak, 16-bit stereo
    n = len(samples)
    fade = int(RATE * 0.01)
    data = bytearray()
    for i, v in enumerate(samples):
        g = 1.0 if i < n - fade else (n - i) / fade
        s = int(max(-1.0, min(1.0, v / peak * PEAK * g)) * 32767)
        data += struct.pack("<hh", s, s)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(data))


def generate(out):
    d = os.path.join(out, "kristall")
    os.makedirs(os.path.join(d, "stereo"), exist_ok=True)
    with open(os.path.join(d, "index.theme"), "w") as f:
        f.write("[Sound Theme]\nName=Kristall\nName[de]=Kristall\n"
                "Comment=Quiet, short event sounds; no login or logout sound\n"
                "Comment[de]=Leise, kurze Ereignistöne; kein An- oder Abmeldeton\n"
                "Inherits=freedesktop\nDirectories=stereo\n\n[stereo]\nOutputProfile=stereo\n")
    for name, fn in SOUNDS.items():
        write_wav(os.path.join(d, "stereo", name + ".wav"), fn())
    # the freedesktop theme would otherwise play these at every login/logout
    for silent in ("service-login", "service-logout", "desktop-login", "desktop-logout"):
        write_wav(os.path.join(d, "stereo", silent + ".wav"), [0.0] * int(RATE * 0.02))
    return d


if __name__ == "__main__":
    print(generate(sys.argv[1]))
