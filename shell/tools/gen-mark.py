#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Draws the Kristall mark: a quartz crystal (hexagonal prism with a pyramidal point) seen from the
# front, cut into four facets separated by thin gaps. Monochrome (fill="currentColor"); the
# facets differ only in opacity so the glyph stays one colour in the menu bar.
# Writes icons/kristall/mark.svg. Original work of the Kristall project, GPL-3.0-or-later.
import os

GAP = 1.9           # facet gap in units of a 24-unit box (≥ 1 device px at 15 px and 1.0×)


def inset(poly, edges, d):
    """Move the listed edges (index i = edge poly[i]->poly[i+1]) inward by d; convex polygon."""
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    lines = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = (dx * dx + dy * dy) ** 0.5
        nx, ny = -dy / L, dx / L
        # inward normal points to the centroid
        if (cx - a[0]) * nx + (cy - a[1]) * ny < 0:
            nx, ny = -nx, -ny
        off = d if i in edges else 0.0
        lines.append(((a[0] + nx * off, a[1] + ny * off), (dx, dy)))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        det = d1[0] * d2[1] - d1[1] * d2[0]
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / det
        out.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    return out


def path(poly):
    return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in poly) + " Z"


T, UL, UR = (12, 0.6), (5.2, 6.4), (18.8, 6.4)
LL, LR, B = (5.2, 17.0), (18.8, 17.0), (12, 23.4)
C = (12, 10.2)
h = GAP / 2
facets = [
    ([T, UL, C], {1, 2}, 1.0),          # top-left (lit)
    ([T, C, UR], {0, 1}, 0.78),         # top-right
    ([UL, LL, B, C], {2, 3}, 0.92),     # front-left
    ([C, B, LR, UR], {0, 3}, 0.66),     # front-right (shade)
]
parts = []
for poly, edges, op in facets:
    parts.append(f'<path fill-opacity="{op}" d="{path(inset(poly, edges, h))}"/>')
svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">' + "".join(parts) + "</svg>\n")
out = os.path.join(os.path.dirname(__file__), "..", "icons", "kristall", "mark.svg")
open(out, "w").write(svg)
print(svg)
