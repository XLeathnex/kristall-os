# SPDX-License-Identifier: GPL-3.0-or-later
# Reference implementation (numpy) of the lens geometry in composite.frag, used to compare the
# measured pixel displacement with what the material is specified to do.
import math

import numpy as np


def corner_shape(radius, smoothing, max_extent):
    if radius <= 0.01:
        return 0.0, 2.0
    R = min(radius * (1 + smoothing), max_extent)
    k = max(1.0, R / radius)
    v = 1 - (math.sqrt(2) - 1) / (math.sqrt(2) * k)
    return R, min(max(-math.log(2) / math.log(v), 2.0), 8.0)


def sdf(px, py, cx, cy, hx, hy, R, p):
    """signed distance (negative inside) and outward unit normal, arrays"""
    with np.errstate(divide="ignore", invalid="ignore"):
        return _sdf(px, py, cx, cy, hx, hy, R, p)


def _sdf(px, py, cx, cy, hx, hy, R, p):
    rx, ry = px - cx, py - cy
    ax, ay = np.abs(rx), np.abs(ry)
    qx, qy = ax - (hx - R), ay - (hy - R)
    d = np.empty_like(px, dtype=float)
    gx = np.zeros_like(d)
    gy = np.zeros_like(d)
    corner = (qx > 0) & (qy > 0)
    if p < 2.01:
        L = np.hypot(qx, qy)
        d = np.where(corner, L - R, d)
        gx = np.where(corner, qx / np.maximum(L, 1e-4), gx)
        gy = np.where(corner, qy / np.maximum(L, 1e-4), gy)
    else:
        m = np.maximum(np.maximum(qx, qy), 1e-6)
        qnx, qny = np.clip(qx / m, 0, None), np.clip(qy / m, 0, None)
        sp = qnx**p + qny**p
        L = m * sp ** (1 / p)
        grx = qnx ** (p - 1) / sp ** (1 - 1 / p)
        gry = qny ** (p - 1) / sp ** (1 - 1 / p)
        gl = np.maximum(np.hypot(grx, gry), 1e-4)
        d = np.where(corner, (L - R) / gl, d)
        gx = np.where(corner, grx / gl, gx)
        gy = np.where(corner, gry / gl, gy)
    edge_x = ~corner & (qx > qy)
    edge_y = ~corner & ~(qx > qy)
    d = np.where(edge_x, qx - R, d)
    d = np.where(edge_y, qy - R, d)
    gx = np.where(edge_x, 1.0, gx)
    gy = np.where(edge_x, 0.0, gy)
    gx = np.where(edge_y, 0.0, gx)
    gy = np.where(edge_y, 1.0, gy)
    nx = gx * np.where(rx < 0, -1, 1)
    ny = gy * np.where(ry < 0, -1, 1)
    return d, nx, ny


def displacement(px, py, rect, radius, smoothing, bezel, depth):
    """predicted (dx, dy): the background is sampled at (px, py) + (dx, dy)"""
    x, y, w, h = rect
    cx, cy, hx, hy = x + w / 2, y + h / 2, w / 2, h / 2
    R, p = corner_shape(radius, smoothing, min(hx, hy))
    d, nx, ny = sdf(px, py, cx, cy, hx, hy, R, p)
    t = np.clip(-d / bezel, 0, 1)
    D = depth * (1 - t) ** 2
    D = np.where(d > 0, 0, D)
    return D * nx, D * ny, d
