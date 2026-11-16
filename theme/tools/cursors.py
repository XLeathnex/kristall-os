#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Kristall pointer theme: drawn here from simple geometry (no traced artwork).

In the Mac's manner: a black arrow with a white edge and a soft shadow; a white pointing hand and
open/closed hands with a black edge; a thin I-beam; a neutral grey spinner (not a "beach ball").
Every shape is emitted twice from the same geometry:
  * SVG cursors (cursors_scalable/<name>/, KWin 6.2+ renders them sharp at any fractional scale)
  * XCursor files (cursors/<name>, sizes 24 32 36 48 64 72 96) for XWayland apps.
Shapes not drawn here are inherited from Breeze (also dark with a white edge).

    cursors.py OUTDIR     -> OUTDIR/Kristall/{index.theme,cursor.theme,cursors/,cursors_scalable/}
"""
import json
import math
import os
import struct
import sys

GRID = 32          # SVG canvas units (like Breeze); nominal size 24 => 24 px at scale 1
NOMINAL = 24
EDGE = 1.05        # outline half-width in grid units
SIZES = [24, 32, 36, 48, 64, 72, 96]

# ------------------------------------------------------------------ geometry
# primitive: (kind, data, fill, edge) kind: poly [(x,y)...] | rrect (x,y,w,h,r) | ellipse (cx,cy,rx,ry)
#            | line ((x0,y0),(x1,y1),width,color) — detail strokes drawn last, no outline
B, W = "#000000", "#FFFFFF"


def arrow(dx=0.0, dy=0.0, s=1.0):
    pts = [(5.0, 4.0), (5.0, 20.6), (9.0, 16.9), (11.7, 23.0), (14.2, 21.9), (11.6, 15.9), (16.8, 15.9)]
    return ("poly", [(dx + 5 + (x - 5) * s, dy + 4 + (y - 4) * s) for x, y in pts], B, W)


def badge(cx, cy, r, fill, edge=W):
    return ("ellipse", (cx, cy, r, r), fill, edge)


def double_arrow(angle, length=15.0, head=4.6, shaft=1.5, cx=16, cy=16):
    """a straight double-headed arrow through (cx, cy) at angle (degrees)"""
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -uy, ux
    h = length / 2
    pts = []
    def P(t, n):
        return (cx + ux * t + vx * n, cy + uy * t + vy * n)
    pts = [P(h, 0), P(h - head, head * 0.78), P(h - head, shaft / 2), P(-h + head, shaft / 2), P(-h + head, head * 0.78),
           P(-h, 0), P(-h + head, -head * 0.78), P(-h + head, -shaft / 2), P(h - head, -shaft / 2), P(h - head, -head * 0.78)]
    return ("poly", pts, B, W)


def bar_resize(vertical):
    """col-resize / row-resize: a bar with an arrow on each side"""
    prims = []
    if vertical:  # col-resize: vertical bar, arrows left/right
        prims.append(("rrect", (15.1, 7.5, 1.8, 17.0, 0.4), B, W))
        prims.append(("poly", [(13.6, 16), (9.6, 12.4), (9.6, 15.2), (6.0, 15.2), (6.0, 16.8), (9.6, 16.8), (9.6, 19.6)], B, W))
        prims.append(("poly", [(18.4, 16), (22.4, 12.4), (22.4, 15.2), (26.0, 15.2), (26.0, 16.8), (22.4, 16.8), (22.4, 19.6)], B, W))
    else:
        prims.append(("rrect", (7.5, 15.1, 17.0, 1.8, 0.4), B, W))
        prims.append(("poly", [(16, 13.6), (12.4, 9.6), (15.2, 9.6), (15.2, 6.0), (16.8, 6.0), (16.8, 9.6), (19.6, 9.6)], B, W))
        prims.append(("poly", [(16, 18.4), (12.4, 22.4), (15.2, 22.4), (15.2, 26.0), (16.8, 26.0), (16.8, 22.4), (19.6, 22.4)], B, W))
    return prims


def pointing_hand():
    # a white glove: index finger up, three fingers folded on the palm, thumb along the left side
    return [
        ("rrect", (12.4, 3.0, 3.8, 13.0, 1.9), W, B),             # index finger
        ("rrect", (9.0, 12.4, 13.4, 11.2, 4.2), W, B),            # palm
        ("rrect", (16.0, 10.2, 3.3, 7.4, 1.65), W, B),            # middle finger (folded)
        ("rrect", (19.0, 11.2, 3.1, 6.8, 1.55), W, B),            # ring finger
        ("rrect", (21.6, 12.6, 2.8, 6.0, 1.4), W, B),             # little finger
        ("poly", [(9.6, 21.5), (6.4, 16.8), (6.6, 14.6), (8.6, 14.4), (11.6, 18.0)], W, B),  # thumb
        ("rrect", (11.2, 21.0, 9.6, 6.0, 2.0), W, B),             # wrist
        ("line", ((16.15, 13.2), (16.15, 16.4), 0.75, B)),
        ("line", ((19.1, 14.0), (19.1, 16.9), 0.75, B)),
        ("line", ((21.65, 14.8), (21.65, 17.6), 0.75, B)),
    ]


def open_hand():
    return [
        ("rrect", (9.4, 6.4, 3.0, 11.0, 1.5), W, B),
        ("rrect", (12.6, 4.6, 3.1, 12.0, 1.55), W, B),
        ("rrect", (15.9, 5.4, 3.0, 11.6, 1.5), W, B),
        ("rrect", (19.1, 7.6, 2.8, 10.0, 1.4), W, B),
        ("poly", [(9.2, 20.0), (5.4, 15.2), (6.0, 13.2), (8.0, 13.4), (11.0, 16.6)], W, B),
        ("rrect", (8.8, 13.2, 13.4, 11.4, 4.4), W, B),
        ("line", ((12.5, 12.0), (12.5, 15.8), 0.7, B)),
        ("line", ((15.8, 12.0), (15.8, 15.8), 0.7, B)),
        ("line", ((19.0, 12.6), (19.0, 15.8), 0.7, B)),
    ]


def closed_hand():
    return [
        ("rrect", (9.0, 10.4, 13.6, 13.2, 4.6), W, B),
        ("rrect", (10.0, 9.0, 3.0, 5.0, 1.5), W, B),
        ("rrect", (13.1, 8.4, 3.0, 5.4, 1.5), W, B),
        ("rrect", (16.2, 8.8, 2.9, 5.2, 1.45), W, B),
        ("rrect", (19.2, 9.8, 2.7, 4.6, 1.35), W, B),
        ("line", ((13.05, 10.8), (13.05, 13.6), 0.7, B)),
        ("line", ((16.15, 10.8), (16.15, 13.6), 0.7, B)),
        ("line", ((19.15, 11.2), (19.15, 13.8), 0.7, B)),
    ]


def ibeam():
    return [
        ("rrect", (15.25, 7.6, 1.5, 16.8, 0.3), B, W),
        ("rrect", (12.4, 6.0, 7.2, 1.5, 0.6), B, W),
        ("rrect", (12.4, 24.5, 7.2, 1.5, 0.6), B, W),
        ("rrect", (13.6, 15.25, 4.8, 1.3, 0.3), B, W),
    ]


def spinner(frame, frames, cx=16, cy=16, r_in=4.0, r_out=9.0, spokes=12, scale=1.0):
    prims = [("ellipse", (cx, cy, (r_out + 1.6) * scale, (r_out + 1.6) * scale), "#FFFFFFF0", "#00000059")]
    for i in range(spokes):
        a = 2 * math.pi * i / spokes - math.pi / 2
        age = ((spokes - i) + frame * spokes / frames) % spokes
        alpha = 0.18 + 0.72 * (1 - age / spokes)
        c = "#1D1D1F%02X" % int(alpha * 255)
        x0, y0 = cx + math.cos(a) * r_in * scale, cy + math.sin(a) * r_in * scale
        x1, y1 = cx + math.cos(a) * r_out * scale, cy + math.sin(a) * r_out * scale
        prims.append(("line", ((x0, y0), (x1, y1), 1.9 * scale, c)))
    return prims


def plus_badge(cx, cy, r, color):
    return [badge(cx, cy, r, color), ("line", ((cx - r * 0.5, cy), (cx + r * 0.5, cy), 1.3, W)),
            ("line", ((cx, cy - r * 0.5), (cx, cy + r * 0.5), 1.3, W))]


def question_badge(cx, cy, r):
    k = r / 4.0
    return [badge(cx, cy, r, B),
            ("arc", (cx, cy - 1.0 * k, 1.4 * k, 200, 400, 1.15, W)),
            ("line", ((cx + 1.05 * k, cy - 0.35 * k), (cx, cy + 0.8 * k), 1.15, W)),
            ("ellipse", (cx, cy + 2.3 * k, 0.7, 0.7), W, None)]


def forbidden_badge(cx, cy, r):
    return [badge(cx, cy, r, B), ("ellipse", (cx, cy, r * 0.62, r * 0.62), "none", None, W),
            ("line", ((cx - r * 0.43, cy + r * 0.43), (cx + r * 0.43, cy - r * 0.43), 1.2, W))]


def magnifier(sign):
    p = [("ellipse", (13.5, 13.5, 6.8, 6.8), W, B), ("ellipse", (13.5, 13.5, 5.2, 5.2), "#FFFFFF", None),
         ("poly", [(18.0, 19.4), (19.4, 18.0), (25.6, 24.2), (24.2, 25.6)], B, W),
         ("line", ((10.6, 13.5), (16.4, 13.5), 1.5, B))]
    if sign == "+":
        p.append(("line", ((13.5, 10.6), (13.5, 16.4), 1.5, B)))
    return p


def crosshair():
    return [("rrect", (15.3, 4.0, 1.4, 9.4, 0.2), B, W), ("rrect", (15.3, 18.6, 1.4, 9.4, 0.2), B, W),
            ("rrect", (4.0, 15.3, 9.4, 1.4, 0.2), B, W), ("rrect", (18.6, 15.3, 9.4, 1.4, 0.2), B, W)]


def move4():
    return [double_arrow(0, 20, 4.4, 1.5), double_arrow(90, 20, 4.4, 1.5)]


# name -> (frames: list of primitive lists, hotspot (grid units), aliases)
def cursors():
    c = {}
    c["default"] = ([[arrow()]], (5.2, 4.2), ["left_ptr", "arrow", "top_left_arrow", "right_ptr"])
    c["pointer"] = ([pointing_hand()], (14.3, 3.3), ["hand", "hand1", "hand2", "pointing_hand",
                                                      "9d800788f1b08800ae810202380a0822", "e29285e634086352946a0e7090d73106"])
    c["text"] = ([ibeam()], (16, 16), ["xterm", "ibeam"])
    c["vertical-text"] = ([[(k, (d[1], d[0], d[3], d[2], d[4]) if k == "rrect" else d, f, e) for k, d, f, e in ibeam()]],
                          (16, 16), [])
    frames = 12
    c["wait"] = ([spinner(i, frames) for i in range(frames)], (16, 16), ["watch"])
    c["progress"] = ([[arrow()] + spinner(i, frames, 20.5, 21.0, 2.0, 4.6) for i in range(frames)], (5.2, 4.2),
                     ["left_ptr_watch", "half-busy", "00000000000000020006000e7e9ffc3f",
                      "08e8e1c95fe2fc01f976f1e063a24ccd", "3ecb610c1bf2410f44200f48c40d3599"])
    c["crosshair"] = ([crosshair()], (16, 16), ["cross", "tcross", "cross_reverse", "diamond_cross"])
    c["cell"] = ([[("rrect", (14.6, 7.0, 2.8, 18.0, 0.4), W, B), ("rrect", (7.0, 14.6, 18.0, 2.8, 0.4), W, B)]], (16, 16), ["plus"])
    c["move"] = ([move4()], (16, 16), ["all-scroll", "fleur", "size_all", "4498f0e0c1937ffe01fd06f973665830",
                                        "9081237383d90e509aa00f00170e968f", "dnd-move"])
    c["ew-resize"] = ([[double_arrow(0)]], (16, 16), ["e-resize", "w-resize", "h_double_arrow", "size_hor", "sb_h_double_arrow",
                                                      "left_side", "right_side", "028006030e0e7ebffc7f7070c0600140"])
    c["ns-resize"] = ([[double_arrow(90)]], (16, 16), ["n-resize", "s-resize", "v_double_arrow", "size_ver", "sb_v_double_arrow",
                                                       "top_side", "bottom_side", "00008160000006810000408080010102"])
    c["nwse-resize"] = ([[double_arrow(45)]], (16, 16), ["nw-resize", "se-resize", "size_fdiag", "bd_double_arrow",
                                                         "top_left_corner", "bottom_right_corner", "c7088f0f3e6c8088236ef8e1e3e70000"])
    c["nesw-resize"] = ([[double_arrow(-45)]], (16, 16), ["ne-resize", "sw-resize", "size_bdiag", "fd_double_arrow",
                                                          "top_right_corner", "bottom_left_corner", "fcf1c3c7cd4491d801f1e1c78f100000"])
    c["col-resize"] = ([bar_resize(True)], (16, 16), ["split_h", "sb_h_double_arrow", "14fef782d02440884392942c11205230"])
    c["row-resize"] = ([bar_resize(False)], (16, 16), ["split_v", "sb_v_double_arrow", "2870a09082c103050810ffdffffe0204"])
    c["not-allowed"] = ([[arrow()] + forbidden_badge(20.5, 20.5, 4.6)], (5.2, 4.2),
                        ["no-drop", "forbidden", "crossed_circle", "circle", "dnd-no-drop", "03b6e0fcb3499374a867c041f52298f0"])
    c["help"] = ([[arrow()] + question_badge(20.5, 20.5, 4.6)], (5.2, 4.2),
                 ["question_arrow", "whats_this", "left_ptr_help", "5c6cd98b3f3ebcb1f9c7f1c204630408", "d9ce0ab605698f320427677b458ad60b"])
    c["copy"] = ([[arrow()] + plus_badge(20.5, 20.5, 4.6, "#28C840")], (5.2, 4.2),
                 ["dnd-copy", "1081e37283d90000800003c07f3ef6bf", "6407b0e94181790501fd1e167b474872", "b66166c04f8c3109214a4fbd64a50fc8"])
    c["alias"] = ([[arrow(), badge(20.5, 20.5, 4.6, B), ("arc", (20.5, 22.2, 2.6, 180, 330, 1.2, W)),
                    ("poly", [(23.6, 19.4), (22.4, 22.4), (20.9, 19.9)], W, None)]], (5.2, 4.2),
                  ["link", "dnd-link", "3085a0e285430894940527032f8b26df", "640fb0e74195791501fd1ed57b41487f", "a2a266d0498c3104214a47bd64ab0fc8"])
    c["context-menu"] = ([[arrow(), ("rrect", (16.4, 15.8, 10.0, 9.4, 1.6), W, B),
                           ("line", ((18.2, 18.6), (24.6, 18.6), 1.0, B)), ("line", ((18.2, 22.4), (24.6, 22.4), 1.0, B))]], (5.2, 4.2), [])
    c["grab"] = ([open_hand()], (15, 14), ["openhand", "5aca4d189052212118709018842178c0"])
    c["grabbing"] = ([closed_hand()], (15, 14), ["closedhand", "fleur-grab", "208530c400c041818281048008011002"])
    c["zoom-in"] = ([magnifier("+")], (13.5, 13.5), [])
    c["zoom-out"] = ([magnifier("-")], (13.5, 13.5), [])
    return c


# ------------------------------------------------------------------ SVG
def _svg_prim(p, outline_pass, w_extra=0.0):
    kind = p[0]
    if kind == "line":
        (x0, y0), (x1, y1), width, color = p[1]
        if outline_pass:
            return ""
        col, op = _svg_color(color)
        return f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="{col}" stroke-opacity="{op}" stroke-width="{width:.2f}" stroke-linecap="round"/>'
    if kind == "arc":
        cx, cy, r, a0, a1, width, color = p[1]
        if outline_pass:
            return ""
        x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
        x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
        large = 1 if (a1 - a0) % 360 > 180 else 0
        return f'<path d="M{x0:.2f} {y0:.2f}A{r:.2f} {r:.2f} 0 {large} 1 {x1:.2f} {y1:.2f}" fill="none" stroke="{color}" stroke-width="{width:.2f}" stroke-linecap="round"/>'
    fill, edge = p[2], p[3]
    stroke_only = p[4] if len(p) > 4 else None
    if outline_pass:
        if not edge:
            return ""
        col, op = _svg_color(edge)
        attrs = f'fill="{col}" fill-opacity="{op}" stroke="{col}" stroke-opacity="{op}" stroke-width="{2 * EDGE + w_extra:.2f}" stroke-linejoin="round"'
    else:
        if stroke_only:
            attrs = f'fill="none" stroke="{stroke_only}" stroke-width="1.2"'
        else:
            col, op = _svg_color(fill)
            attrs = f'fill="{col}" fill-opacity="{op}"'
    if kind == "poly":
        d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in p[1]) + "Z"
        return f'<path d="{d}" {attrs}/>'
    if kind == "rrect":
        x, y, w, h, r = p[1]
        return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{r:.2f}" {attrs}/>'
    if kind == "ellipse":
        cx, cy, rx, ry = p[1]
        return f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" {attrs}/>'
    raise ValueError(kind)


def _svg_color(c):
    if c == "none":
        return "none", "1"
    if len(c) == 9:
        return c[:7], f"{int(c[7:], 16) / 255:.3f}"
    return c, "1"


def svg(prims):
    shapes = [p for p in prims if p[0] not in ("line", "arc")]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">',
           '<filter id="s" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB">'
           '<feGaussianBlur stdDeviation="0.8"/></filter>',
           '<g opacity="0.32" filter="url(#s)" transform="translate(0 1)">']
    for p in shapes:
        if p[3]:
            out.append(_svg_prim((p[0], p[1], "#000000", "#000000") + tuple(p[4:]), True))
    out.append("</g>")
    for p in shapes:
        out.append(_svg_prim(p, True))
    for p in prims:
        out.append(_svg_prim(p, False))
    out.append("</svg>")
    return "\n".join(x for x in out if x) + "\n"


# ------------------------------------------------------------------ raster (XCursor)
def raster(prims, size):
    from PIL import Image, ImageDraw, ImageFilter
    px = 32 * size / NOMINAL
    canvas = int(math.ceil(px))
    ss = 6
    S = px / 32 * ss
    big = canvas * ss

    def layer(pass_outline):
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for p in prims:
            kind = p[0]
            if kind in ("line", "arc"):
                if pass_outline:
                    continue
                if kind == "line":
                    (x0, y0), (x1, y1), width, color = p[1]
                    rgba = _rgba(color)
                    d.line([(x0 * S, y0 * S), (x1 * S, y1 * S)], fill=rgba, width=max(1, int(round(width * S))))
                    r = width * S / 2
                    for x, y in ((x0, y0), (x1, y1)):
                        d.ellipse([x * S - r, y * S - r, x * S + r, y * S + r], fill=rgba)
                else:
                    cx, cy, r, a0, a1, width, color = p[1]
                    d.arc([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], a0, a1, fill=_rgba(color),
                          width=max(1, int(round(width * S))))
                continue
            fill, edge = p[2], p[3]
            stroke_only = p[4] if len(p) > 4 else None
            if pass_outline:
                if not edge:
                    continue
                e = EDGE
                col = _rgba(edge)
            else:
                e = 0.0
                col = None if stroke_only else _rgba(fill)
            if kind == "poly":
                pts = [(x * S, y * S) for x, y in p[1]]
                if pass_outline:
                    d.polygon(pts, fill=col)
                    d.line(pts + [pts[0]], fill=col, width=int(round(2 * e * S)), joint="curve")
                    r = e * S
                    for x, y in pts:
                        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
                else:
                    d.polygon(pts, fill=col)
            elif kind == "rrect":
                x, y, w, h, r = p[1]
                box = [(x - e) * S, (y - e) * S, (x + w + e) * S, (y + h + e) * S]
                if stroke_only and not pass_outline:
                    d.rounded_rectangle(box, radius=(r + e) * S, outline=_rgba(stroke_only), width=int(1.2 * S))
                else:
                    d.rounded_rectangle(box, radius=(r + e) * S, fill=col)
            elif kind == "ellipse":
                cx, cy, rx, ry = p[1]
                box = [(cx - rx - e) * S, (cy - ry - e) * S, (cx + rx + e) * S, (cy + ry + e) * S]
                if stroke_only and not pass_outline:
                    d.ellipse(box, outline=_rgba(stroke_only), width=int(1.2 * S))
                elif col is not None:
                    d.ellipse(box, fill=col)
        return img

    outline = layer(True)
    fill = layer(False)
    # shadow from the outline's alpha
    a = outline.getchannel("A").filter(ImageFilter.GaussianBlur(0.8 * S))
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    shadow.putalpha(a.point(lambda v: int(v * 0.32)))
    shifted = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    shifted.paste(shadow, (0, int(round(1 * S))))
    out = Image.alpha_composite(shifted, outline)
    out = Image.alpha_composite(out, fill)
    return out.resize((canvas, canvas), Image.LANCZOS), px / 32


def _rgba(c):
    c = c.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    a = int(c[6:8], 16) if len(c) == 8 else 255
    return (r, g, b, a)


def xcursor(images):
    """images: list of (size, PIL RGBA, xhot, yhot, delay)"""
    chunks = []
    for nominal, im, xh, yh, delay in images:
        w, h = im.size
        px = im.load()
        data = bytearray()
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                # premultiplied ARGB, little endian
                r, g, b = r * a // 255, g * a // 255, b * a // 255
                data += struct.pack("<I", (a << 24) | (r << 16) | (g << 8) | b)
        chunks.append((nominal, struct.pack("<IIIIIIIII", 36, 0xFFFD0002, nominal, 1, w, h, xh, yh, delay) + bytes(data)))
    header = struct.pack("<4sIII", b"Xcur", 16, 0x10000, len(chunks))
    toc = b""
    offset = 16 + 12 * len(chunks)
    body = b""
    for nominal, chunk in chunks:
        toc += struct.pack("<III", 0xFFFD0002, nominal, offset + len(body))
        body += chunk
    return header + toc + body


def generate(out):
    theme = os.path.join(out, "Kristall")
    os.makedirs(os.path.join(theme, "cursors"), exist_ok=True)
    os.makedirs(os.path.join(theme, "cursors_scalable"), exist_ok=True)
    with open(os.path.join(theme, "index.theme"), "w") as f:
        f.write("[Icon Theme]\nName=Kristall\nName[de]=Kristall\nComment=Kristall pointer: black arrow, white edge\n"
                "Comment[de]=Kristall-Zeiger: schwarzer Pfeil, weißer Rand\nInherits=breeze_cursors\n")
    with open(os.path.join(theme, "cursor.theme"), "w") as f:
        f.write("[Icon Theme]\nName=Kristall\nInherits=breeze_cursors\n")
    for name, (frames, (hx, hy), aliases) in cursors().items():
        sdir = os.path.join(theme, "cursors_scalable", name)
        os.makedirs(sdir, exist_ok=True)
        meta = []
        delay = 60 if len(frames) > 1 else 0
        for i, prims in enumerate(frames):
            fname = f"{name}-{i + 1:02d}.svg" if len(frames) > 1 else f"{name}.svg"
            with open(os.path.join(sdir, fname), "w") as f:
                f.write(svg(prims))
            entry = {"filename": fname, "hotspot_x": hx, "hotspot_y": hy, "nominal_size": NOMINAL}
            if delay:
                entry["delay"] = delay
            meta.append(entry)
        with open(os.path.join(sdir, "metadata.json"), "w") as f:
            json.dump(meta, f, indent=1)
        imgs = []
        for size in SIZES:
            for prims in frames:
                im, k = raster(prims, size)
                imgs.append((size, im, int(round(hx * k)), int(round(hy * k)), delay))
        with open(os.path.join(theme, "cursors", name), "wb") as f:
            f.write(xcursor(imgs))
        for a in aliases:
            for base in ("cursors", "cursors_scalable"):
                link = os.path.join(theme, base, a)
                if os.path.lexists(link) or a == name:
                    continue
                os.symlink(name, link)
    return theme


if __name__ == "__main__":
    print(generate(sys.argv[1]))
