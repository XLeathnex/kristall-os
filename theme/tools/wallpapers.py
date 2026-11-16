#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Kristall wallpapers, drawn entirely by this code (no source images), so they are reproducible
and unambiguously ours. Each has a light and a dark variant; Plasma's image wallpaper swaps them
with the colour scheme (package folders images/ and images_dark/).

Designed for Liquid Glass: large soft colour fields and gentle structure give the lens something
to bend (edges of ribbons and facets displace visibly under the bar, Dock and panels), without
fine detail that would make glass text hard to read.

    wallpapers.py OUTDIR [WIDTH HEIGHT]     write <name>-<light|dark>.png previews (default 1440x900)
"""
import math
import os
import sys

import numpy as np

WALLPAPERS = ["kristall", "welle", "horizont"]
NAMES = {
    "kristall": {"en": "Crystal", "de": "Kristall"},
    "welle": {"en": "Wave", "de": "Welle"},
    "horizont": {"en": "Horizon", "de": "Horizont"},
}


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float32)


def srgb_to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


class Canvas:
    """Linear-light float canvas; coordinates u in [0, aspect], v in [0, 1] (v down)."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.aspect = w / h
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        self.u = (xs + 0.5) / h
        self.v = (ys + 0.5) / h
        self.px = 1.0 / h  # one pixel in v units
        self.img = np.zeros((h, w, 3), dtype=np.float32)

    def gradient(self, stops, axis="v", angle=None):
        """vertical (or angled) multi-stop gradient in linear light"""
        if angle is None:
            t = self.v if axis == "v" else self.u / self.aspect
        else:
            a = math.radians(angle)
            t = (self.u / self.aspect - 0.5) * math.cos(a) + (self.v - 0.5) * math.sin(a) + 0.5
        t = np.clip(t, 0, 1)
        out = np.zeros_like(self.img)
        pos = [s[0] for s in stops]
        cols = [srgb_to_lin(rgb(s[1])) for s in stops]
        for c in range(3):
            out[..., c] = np.interp(t, pos, [col[c] for col in cols])
        self.img[:] = out

    def blend(self, color, alpha):
        """paint linear colour (3,) or field (h,w,3) with alpha field (h,w)"""
        a = np.clip(alpha, 0, 1)[..., None]
        self.img[:] = self.img * (1 - a) + np.asarray(color, dtype=np.float32) * a

    def screen(self, color, alpha):
        a = np.clip(alpha, 0, 1)[..., None]
        c = np.asarray(color, dtype=np.float32)
        self.img[:] = 1 - (1 - self.img) * (1 - c * a)

    def glow(self, cx, cy, r, color, strength):
        d2 = ((self.u - cx) ** 2 + (self.v - cy) ** 2) / (r * r)
        self.screen(srgb_to_lin(rgb(color)), strength * np.exp(-d2))

    def to_uint8(self, seed=7):
        out = lin_to_srgb(self.img)
        # blue-noise-ish dither: two uniform fields averaged (triangular), ±1 LSB, against banding
        rs = np.random.RandomState(seed)
        n = (rs.random_sample(out.shape[:2]).astype(np.float32) + rs.random_sample(out.shape[:2]).astype(np.float32) - 1.0)
        out = out * 255.0 + n[..., None]
        return np.clip(np.round(out), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- Kristall: light through facets
def kristall(c, dark):
    if dark:
        c.gradient([(0.0, "#0B1030"), (0.55, "#1A1446"), (1.0, "#2A1036")])
        c.glow(0.35, 0.95, 0.75, "#3A2A8C", 0.55)
        c.glow(1.35, 0.15, 0.6, "#0E4C7A", 0.6)
        palette = ["#3B5BDB", "#7048E8", "#1098AD", "#C2255C", "#4C6EF5", "#5F3DC4"]
        edge = "#9FC2FF"
        facet_alpha = 0.42
    else:
        c.gradient([(0.0, "#C9DCFF"), (0.5, "#E2D6FF"), (1.0, "#FFD6C4")])
        c.glow(0.25, 0.9, 0.7, "#FFC49A", 0.6)
        c.glow(1.4, 0.1, 0.6, "#9EC3FF", 0.6)
        palette = ["#5B8CFF", "#9B7BFF", "#3FD3AE", "#FF8E8E", "#4FB2FF", "#B79BFF"]
        edge = "#FFFFFF"
        facet_alpha = 0.58
    A = c.aspect
    # large crystal facets: triangles fanning from a few apexes, soft-edged, layered with a
    # vertical gradient inside each facet (light passing through a cut stone)
    facets = [
        ((0.62 * A, -0.05), (1.02 * A, 0.62), (0.40 * A, 0.78), 0),
        ((0.62 * A, -0.05), (0.40 * A, 0.78), (0.10 * A, 0.30), 1),
        ((1.02 * A, 0.62), (0.70 * A, 1.10), (0.40 * A, 0.78), 2),
        ((0.62 * A, -0.05), (1.10 * A, 0.05), (1.02 * A, 0.62), 3),
        ((0.10 * A, 0.30), (0.40 * A, 0.78), (-0.05 * A, 0.95), 4),
        ((0.40 * A, 0.78), (0.70 * A, 1.10), (0.05 * A, 1.10), 5),
        ((-0.05 * A, -0.05), (0.62 * A, -0.05), (0.10 * A, 0.30), 4),
        ((1.10 * A, 0.05), (1.10 * A, 0.90), (1.02 * A, 0.62), 1),
    ]
    soft = 0.006
    for (ax, ay), (bx, by), (qx, qy), ci in facets:
        # signed distances to the three edges (positive inside for a CCW triangle)
        def edge_d(x0, y0, x1, y1):
            ex, ey = x1 - x0, y1 - y0
            n = math.hypot(ex, ey)
            return ((c.u - x0) * ey - (c.v - y0) * ex) / n
        d1, d2, d3 = edge_d(ax, ay, bx, by), edge_d(bx, by, qx, qy), edge_d(qx, qy, ax, ay)
        if (bx - ax) * (qy - ay) - (by - ay) * (qx - ax) > 0:  # make inside positive
            d1, d2, d3 = -d1, -d2, -d3
        inside = np.minimum(np.minimum(d1, d2), d3)
        mask = smoothstep(-soft, soft, inside)
        # gradient across the facet from apex a toward the opposite edge
        mx, my = (bx + qx) / 2, (by + qy) / 2
        L = math.hypot(mx - ax, my - ay)
        t = np.clip(((c.u - ax) * (mx - ax) + (c.v - ay) * (my - ay)) / (L * L), 0, 1)
        col = srgb_to_lin(rgb(palette[ci]))
        shade = (0.55 + 0.45 * t)[..., None] * col
        c.blend(shade, mask * facet_alpha * (0.6 + 0.4 * (1 - t)))
        # bright refracted rim along the facet edges (thin, soft)
        rim = np.exp(-(np.minimum(np.minimum(np.abs(d1), np.abs(d2)), np.abs(d3)) / 0.006) ** 2)
        c.screen(srgb_to_lin(rgb(edge)), rim * smoothstep(0.0, 0.004, inside) * (0.16 if dark else 0.30))
    # caustic glints where facets meet
    for x, y, r, s in ((0.62 * A, 0.0, 0.10, 0.5), (0.40 * A, 0.78, 0.07, 0.45), (1.02 * A, 0.62, 0.06, 0.4)):
        c.glow(x, y, r, edge, s * (0.6 if dark else 0.8))
    # gentle vignette for depth
    vig = ((c.u / A - 0.5) ** 2 + (c.v - 0.5) ** 2)
    c.img *= (1 - (0.35 if dark else 0.12) * vig)[..., None]


# ---------------------------------------------------------------- Welle: silk ribbons
def welle(c, dark):
    if dark:
        c.gradient([(0.0, "#05121F"), (0.6, "#0B1B33"), (1.0, "#161036")], angle=70)
        cols = ["#2F6BFF", "#8A3FFC", "#00B3A4", "#FF5C8A"]
        glow = [("#1E3A8A", 0.5), ("#5B21B6", 0.45)]
        sheen = "#BFD7FF"
    else:
        c.gradient([(0.0, "#E3ECFF"), (0.6, "#EDE5FF"), (1.0, "#FFE8DE")], angle=70)
        cols = ["#5C8DFF", "#A779FF", "#36D1C4", "#FF8FAE"]
        glow = [("#C7D7FF", 0.5), ("#FFD6E5", 0.45)]
        sheen = "#FFFFFF"
    A = c.aspect
    c.glow(0.2 * A, 0.2, 0.55, glow[0][0], glow[0][1])
    c.glow(0.85 * A, 0.85, 0.6, glow[1][0], glow[1][1])
    x = c.u / A
    ribbons = [
        # base, amp1, f1, phase1, amp2, f2, phase2, width, colour, alpha
        (0.66, 0.16, 0.8, 0.4, 0.05, 1.9, 1.3, 0.24, 0, 0.80),
        (0.50, 0.18, 0.6, 2.0, 0.06, 1.6, 0.2, 0.20, 1, 0.72),
        (0.78, 0.12, 1.0, 4.1, 0.04, 2.4, 2.4, 0.15, 2, 0.62),
        (0.36, 0.14, 0.9, 5.3, 0.05, 1.7, 4.0, 0.13, 3, 0.55),
    ]
    for base, a1, f1, p1, a2, f2, p2, wdt, ci, alpha in ribbons:
        yc = base + a1 * np.sin(2 * math.pi * f1 * x + p1) + a2 * np.sin(2 * math.pi * f2 * x + p2)
        # the ribbon twists: its width breathes along x, which gives the folds
        wv = wdt * (0.55 + 0.45 * np.cos(2 * math.pi * (f1 * 0.7) * x + p2))
        d = (c.v - yc) / np.maximum(wv, 0.01)
        body = np.exp(-d * d * 1.2)
        # shading across the ribbon (lit upper edge, shadowed lower edge) and a sheen line
        light = 0.65 + 0.35 * np.tanh(-1.8 * d)
        col = srgb_to_lin(rgb(cols[ci]))
        c.blend(light[..., None] * col, body * alpha)
        c.screen(srgb_to_lin(rgb(sheen)), np.exp(-((d + 0.45) / 0.12) ** 2) * body * (0.22 if dark else 0.35))
    vig = ((c.u / A - 0.5) ** 2 + (c.v - 0.5) ** 2)
    c.img *= (1 - (0.30 if dark else 0.08) * vig)[..., None]


# ---------------------------------------------------------------- Horizont: layered hills
def horizont(c, dark):
    A = c.aspect
    x = c.u / A
    if dark:
        c.gradient([(0.0, "#070B1E"), (0.45, "#1B1B4B"), (0.62, "#4B2A6B"), (0.70, "#7A3D6E")])
        c.glow(0.72 * A, 0.30, 0.05, "#FFF4D6", 0.9)     # moon
        c.glow(0.72 * A, 0.30, 0.22, "#6E6AC8", 0.45)
        layers = ["#3A2858", "#2A1F4A", "#1C1838", "#111127", "#0A0B18"]
        # a sparse, faint star field
        rs = np.random.RandomState(11)
        n = 260
        sx, sy = rs.random_sample(n) * A, rs.random_sample(n) * 0.5
        ss = rs.random_sample(n)
        stars = np.zeros(c.u.shape, dtype=np.float32)
        for i in range(n):
            r = 0.0009 + 0.0012 * ss[i]
            x0 = int((sx[i] - 4 * r) * c.h); x1 = int((sx[i] + 4 * r) * c.h) + 1
            y0 = int((sy[i] - 4 * r) * c.h); y1 = int((sy[i] + 4 * r) * c.h) + 1
            x0, y0 = max(x0, 0), max(y0, 0)
            sub_u, sub_v = c.u[y0:y1, x0:x1], c.v[y0:y1, x0:x1]
            stars[y0:y1, x0:x1] += (0.25 + 0.75 * ss[i]) * np.exp(-((sub_u - sx[i]) ** 2 + (sub_v - sy[i]) ** 2) / (r * r))
        c.screen(srgb_to_lin(rgb("#DDE6FF")), stars * smoothstep(0.62, 0.2, c.v) * 0.8)
        haze = "#5A3E7A"
    else:
        c.gradient([(0.0, "#8EC5FF"), (0.42, "#CFE3FF"), (0.62, "#FFE3CF"), (0.72, "#FFD0B5")])
        c.glow(0.30 * A, 0.56, 0.08, "#FFF8E8", 0.95)    # low sun
        c.glow(0.30 * A, 0.56, 0.35, "#FFC9A0", 0.55)
        layers = ["#B9B4E6", "#9C93D8", "#7F74C4", "#6155A8", "#46398A"]
        haze = "#FFE1D0"
    bases = [0.58, 0.66, 0.74, 0.83, 0.93]
    for k, (base, colr) in enumerate(zip(bases, layers)):
        f = 1.0 + 0.45 * k
        ridge = (base - 0.05 * np.sin(2 * math.pi * 0.8 * f * x + 1.3 * k)
                 - 0.025 * np.sin(2 * math.pi * 2.1 * f * x + 2.7 * k)
                 - 0.008 * np.sin(2 * math.pi * 5.3 * f * x + 0.9 * k))
        m = smoothstep(ridge - 1.5 * c.px, ridge + 1.5 * c.px, c.v)
        # each layer gets lighter toward its ridge (rim light) and hazier with distance
        depth = smoothstep(ridge, ridge + 0.25, c.v)
        col = srgb_to_lin(rgb(colr))
        top = srgb_to_lin(rgb(haze))
        layer = col[None, None, :] * (0.75 + 0.25 * depth[..., None]) * 0 + (col * (1 - 0.35 * (1 - depth))[..., None] + top * (0.35 * (1 - depth))[..., None] * (0.5 if k < 2 else 0.25))
        c.blend(layer, m)
        # soft mist band above each ridge
        mist = np.exp(-((c.v - (ridge - 0.02)) / 0.035) ** 2) * (0.18 if not dark else 0.10) * (1 - 0.15 * k)
        c.screen(srgb_to_lin(rgb(haze)), mist)


RENDER = {"kristall": kristall, "welle": welle, "horizont": horizont}


def render(name, dark, w, h):
    c = Canvas(w, h)
    RENDER[name](c, dark)
    return c.to_uint8(seed=hash(name) % 1000 if False else (3 + WALLPAPERS.index(name) * 2 + int(dark)))


def main(argv):
    from PIL import Image
    out = argv[1]
    w, h = (int(argv[2]), int(argv[3])) if len(argv) > 3 else (1440, 900)
    os.makedirs(out, exist_ok=True)
    for name in WALLPAPERS:
        for dark in (False, True):
            Image.fromarray(render(name, dark, w, h)).save(os.path.join(out, f"{name}-{'dark' if dark else 'light'}.png"))
            print("wrote", name, "dark" if dark else "light")


if __name__ == "__main__":
    main(sys.argv)
