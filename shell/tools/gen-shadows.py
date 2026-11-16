#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Generates the shadow nine-patches in core/assets/ from the shadow recipes in design.md §7.
# Each image is the blurred shape (offset down by y) with the shape itself cut out, so the glass
# interior stays clear (the effect draws glass *behind* the client's pixels).
# Output: shadow-<kind>-<radius>.png (1x) and @2x; KShadow.qml maps them with BorderImage.
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

RECIPES = {  # kind: (blur, y)   — keep in sync with Theme.shadows
    "menu": (24, 8), "panel": (40, 14), "control": (8, 2), "knob": (6, 1),
    "hud": (30, 10), "tooltip": (12, 4), "ambient": (24, 3),
}
SHAPES = [("menu", 12), ("panel", 26), ("panel", 16), ("tooltip", 8), ("hud", 22),
          ("control", 11), ("control", 14), ("control", 18), ("knob", 10), ("knob", 12)] + \
    [("ambient", r) for r in (12, 16, 20, 24, 28, 32, 40, 48)]


def margin(blur, y):
    return int(math.ceil(blur * 1.25)) + abs(y)


def render(kind, r, scale):
    blur, y = RECIPES[kind]
    m = margin(blur, y)
    size = 2 * (m + r) + 2
    W = size * scale
    ss = 4  # supersample the shape edges
    def mask(dy):
        im = Image.new("L", (W * ss, W * ss), 0)
        d = ImageDraw.Draw(im)
        x0, y0 = m * scale * ss, (m + dy) * scale * ss
        x1, y1 = (size - m) * scale * ss - 1, (size - m + dy) * scale * ss - 1
        d.rounded_rectangle([x0, y0, x1, y1], radius=r * scale * ss, fill=255)
        return im.resize((W, W), Image.LANCZOS)
    shadow = mask(y).filter(ImageFilter.GaussianBlur(blur * scale / 2.0))
    hole = mask(0)
    alpha = ImageChops.multiply(shadow, ImageChops.invert(hole))
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    out.putalpha(alpha)
    return out, m


def main(outdir, only=None):
    os.makedirs(outdir, exist_ok=True)
    for kind, r in SHAPES:
        if only and kind != only:
            continue
        for scale, suffix in ((1, ""), (2, "@2x")):
            img, m = render(kind, r, scale)
            img.save(os.path.join(outdir, f"shadow-{kind}-{r}{suffix}.png"), optimize=True)
        print(f"shadow-{kind}-{r}: margin {m}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "core", "assets"),
         sys.argv[2] if len(sys.argv) > 2 else None)
