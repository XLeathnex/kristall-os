#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Test helper: generates the known backgrounds the measurements run against.
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def grid(w, h, step=16, line=2):
    """white with black lines every `step` px (both axes), offset so lines straddle pixel centres"""
    a = np.full((h, w, 3), 255, np.uint8)
    for x in range(0, w, step):
        a[:, x : x + line] = 0
    for y in range(0, h, step):
        a[y : y + line, :] = 0
    return a


def lines(w, h, axis, step=16, line=2):
    """white with black lines every `step` px along one axis only ("v": vertical lines)"""
    a = np.full((h, w, 3), 255, np.uint8)
    if axis == "v":
        for x in range(0, w, step):
            a[:, x : x + line] = 0
    else:
        for y in range(0, h, step):
            a[y : y + line, :] = 0
    return a


def solid(w, h, v):
    return np.full((h, w, 3), v, np.uint8)


def gradient(w, h):
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    a = np.concatenate([0.15 + 0.7 * x * np.ones_like(y), 0.25 + 0.5 * y * np.ones_like(x), 0.6 - 0.4 * x * y], axis=2)
    return (np.clip(a, 0, 1) * 255).astype(np.uint8)


def busy(w, h, seed=7):
    """colourful, high-detail wallpaper stand-in: gradients, discs, stripes, text"""
    rng = np.random.default_rng(seed)
    img = Image.fromarray(gradient(w, h))
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(26):
        r = int(rng.integers(30, 220))
        cx, cy = int(rng.integers(0, w)), int(rng.integers(0, h))
        col = tuple(int(c) for c in rng.integers(0, 255, 3)) + (200,)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    for i in range(0, w + h, 46):
        d.line([(i, 0), (i - h, h)], fill=(255, 255, 255, 70), width=6)
    try:
        font = ImageFont.truetype("/usr/share/fonts/rsms-inter-fonts/Inter-Bold.ttf", 54)
        small = ImageFont.truetype("/usr/share/fonts/rsms-inter-fonts/Inter-Regular.ttf", 20)
    except OSError:
        font = small = ImageFont.load_default()
    for y in range(60, h, 140):
        d.text((40 + (y * 7) % 200, y), "Kristall Liquid Glass 0123456789", font=font, fill=(255, 255, 255, 235))
        d.text((60, y + 70), "The quick brown fox jumps over the lazy dog — Falsches Üben von Xylophonmusik quält jeden größeren Zwerg", font=small, fill=(10, 10, 20, 255))
    return np.array(img.convert("RGB"))


def main():
    kind, w, h, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    if kind == "grid":
        a = grid(w, h)
    elif kind in ("vlines", "hlines"):
        a = lines(w, h, kind[0])
    elif kind == "white":
        a = solid(w, h, 250)
    elif kind == "black":
        a = solid(w, h, 8)
    elif kind == "gray":
        a = solid(w, h, 128)
    elif kind == "gradient":
        a = gradient(w, h)
    else:
        a = busy(w, h)
    Image.fromarray(a).save(out)


if __name__ == "__main__":
    main()
