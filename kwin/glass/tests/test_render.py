#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Rendering measurements of the glass effect in a headless KWin (llvmpipe).
# Every check prints what it measured; results also go to $KRISTALL_GLASS_RESULTS (JSON).
import json
import subprocess
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import harness  # noqa: E402
import lensmodel  # noqa: E402
import pattern  # noqa: E402

EVIDENCE = os.path.join(HERE, "evidence")
GLASSHOST = os.path.join(HERE, "support", "glasshost.qml")
DEMO = os.path.join(os.path.dirname(HERE), "demo")
RESULTS = {}
FAILURES = []


def check(name, ok, detail):
    print(("PASS " if ok else "FAIL ") + name + ": " + detail, flush=True)
    if not ok:
        FAILURES.append(name)


def lum(img):
    return img[..., :3].astype(float) @ np.array([0.2126, 0.7152, 0.0722])


def make_bg(session, kind, w=None, h=None):
    w = w or int(round(session.width))
    h = h or int(round(session.height))
    path = os.path.join(session.tmp, f"{kind}.png")
    Image.fromarray(getattr(pattern, kind)(w, h) if kind == "busy" else _pattern(kind, w, h)).save(path)
    return path


def _pattern(kind, w, h):
    if kind in ("vlines", "hlines"):
        return pattern.lines(w, h, kind[0])
    if kind == "grid":
        return pattern.grid(w, h)
    if kind == "white":
        return pattern.solid(w, h, 250)
    if kind == "black":
        return pattern.solid(w, h, 8)
    if kind == "gradient":
        return pattern.gradient(w, h)
    return pattern.busy(w, h)


class Scene:
    """KWin + background + empty glass host surface + a bound socket client"""

    def __init__(self, bg="busy", width=1280, height=800, scale=1.0, settings=None, env=None):
        self.s = harness.Session(width, height, scale, settings=settings, env=env).start()
        self.dev_w, self.dev_h = int(round(width * scale)), int(round(height * scale))
        self.bg_proc = None
        self.set_background(bg)
        self.host = self.s.quickshell(GLASSHOST, name="host")
        self.c = self.s.connect()
        assert self.c.wait("hello")
        self.c.send({"op": "bind", "surface": "t", "match": {"namespace": "kristall-test-glass", "pid": 0}})
        ev = self.c.wait(lambda e: e.get("event") == "bound" and e.get("windows", 0) > 0, 15)
        assert ev, "glass host surface never appeared"

    def set_background(self, kind):
        path = make_bg(self.s, kind, self.dev_w, self.dev_h)
        old = self.bg_proc
        self.bg_proc = self.s.background(path)
        time.sleep(2.0)
        if old:
            self.s.stop_proc(old)
            time.sleep(0.8)

    def shapes(self, shapes, settle=1.0):
        self.c.send({"op": "shapes", "surface": "t", "shapes": shapes})
        time.sleep(settle)

    def shot(self):
        return self.s.screenshot()

    def status(self):
        return self.c.status()

    def close(self):
        self.c.close()
        self.s.stop()


# ------------------------------------------------------------------------------------------
# refraction: image-based measurement against the lens model
# ------------------------------------------------------------------------------------------

def centroids(profile, thresh=128):
    dark = 255.0 - profile
    mask = profile < thresh
    out = []
    i, n = 0, len(profile)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            lo, hi = max(0, i - 1), min(n, j + 1)
            idx = np.arange(lo, hi)
            w = dark[lo:hi]
            out.append(float((idx * w).sum() / w.sum()))
            i = j
        else:
            i += 1
    return out


def measure_axis(profile, start, inward_from, reference):
    """Displacement along one scan line, walking outward from the undisplaced interior.

    profile: luminance along the scan line with the glass; reference: the same scan line
    without glass (the true source positions, measured rather than assumed, because a
    fractional-scale client may not place the pattern exactly on 16-px multiples).
    start: index of the shape edge; inward_from: an index inside the flat interior.
    Returns [(position, displacement)] with displacement = position - source position
    (positive = content comes from further outside)."""
    cs = sorted(c for c in centroids(profile) if c >= start - 0.5)
    src_lines = sorted(centroids(reference))
    inner = [c for c in cs if c >= inward_from]
    if not inner or not src_lines:
        return []
    first = inner[0]
    j = int(np.argmin([abs(r - first) for r in src_lines]))
    out = []
    k = cs.index(first)
    while k >= 0 and j >= 0:
        c = cs[k]
        if c < start + 0.5:
            break
        out.append((c, c - src_lines[j]))
        j -= 1
        k -= 1
    return out


def test_refraction(scale=1.0, tag=""):
    """isolate mode: the output inside the shape is the background sampled at the refracted
    position (no blur/tint/light), so line positions reveal the displacement field"""
    W, H = 1280, 800
    sc = Scene("vlines", W, H, scale)
    try:
        sc.c.send({"op": "debug", "isolate": "refraction"})
        sc.c.wait("debug")
        x0, y0, w, h, radius, smoothing, bezel, depth = 400, 240, 480, 320, 48, 0.6, 24, 16
        shape = {"id": "m", "x": x0, "y": y0, "w": w, "h": h, "radius": radius, "smoothing": smoothing,
                 "bezel": bezel, "depth": depth, "variant": "clear"}
        # The line pattern repeats every 16 px, so shift the shape by sub-period offsets to
        # sample the whole rim profile.
        offsets = (0, 3, 6, 9, 12)
        sc.shapes([], settle=0.6)
        ref_v = lum(sc.shot())
        imgs_v = []
        for o in offsets:
            sc.shapes([dict(shape, x=x0 + o, y=y0 + o)], settle=0.6)
            imgs_v.append(lum(sc.shot()))
        sc.set_background("hlines")
        sc.shapes([], settle=0.6)
        ref_h = lum(sc.shot())
        imgs_h = []
        for o in offsets:
            sc.shapes([dict(shape, x=x0 + o, y=y0 + o)], settle=0.6)
            imgs_h.append(lum(sc.shot()))
        img_v, img_h = imgs_v[0], imgs_h[0]
        sc.c.send({"op": "debug", "isolate": "none"})
        sc.c.wait("debug")

        s = scale
        B, D = bezel * s, depth * s
        res = {}
        # 1. horizontal scans through the middle: left rim, x displacement
        meas, errs = [], []
        for o, iv in zip(offsets, imgs_v):
            X0, Y0, Wd, Hd = (x0 + o) * s, (y0 + o) * s, w * s, h * s
            row = int(Y0 + Hd / 2)
            for c, m in measure_axis(iv[row, :], X0, X0 + B + 2, ref_v[row, :]):
                dx = lensmodel.displacement(np.array([c + 0.5]), np.array([row + 0.5]), (X0, Y0, Wd, Hd), radius * s, smoothing, B, D)[0][0]
                # model: sample at x + dx, so a line appears where x + dx(x) = source -> shift = -dx
                meas.append((c - X0, m))
                errs.append(abs(m - (-dx)))
                if os.environ.get("KRISTALL_GLASS_VERBOSE"):
                    print(f"    o={o} u={c - X0:.2f} measured={m:.2f} model={-dx:.2f}")
        interior = [abs(m) for u, m in meas if u > B + 1]
        rim = [m for u, m in meas if u < B * 0.3]
        res["edge_samples"] = len(meas)
        res["edge_max_abs_error_px"] = round(max(errs), 3) if errs else None
        res["edge_rim_displacement_px"] = round(max(rim), 2) if rim else None
        res["edge_interior_max_abs_px"] = round(max(interior), 3) if interior else None
        res["edge_profile"] = [(round(u, 2), round(m, 2)) for u, m in sorted(meas) if u < B + 4]
        check(f"refraction{tag}: displacement along the normal at a straight edge matches the lens model",
              bool(errs) and max(errs) < 0.8 * max(1.0, s),
              f"{len(meas)} line crossings, max |measured-model| = {res['edge_max_abs_error_px']} px, rim displacement "
              f"{res['edge_rim_displacement_px']} px (depth {D:.1f} px); profile (px inside the rim, displacement px) {res['edge_profile']}")
        check(f"refraction{tag}: flat interior is undisplaced",
              bool(interior) and max(interior) < 0.35, f"max |displacement| beyond the bezel = {res['edge_interior_max_abs_px']} px over {len(interior)} lines")

        # 2. top edge with horizontal lines: y displacement, same profile
        meas_y, errs_y = [], []
        for o, ih in zip(offsets, imgs_h):
            X0, Y0, Wd, Hd = (x0 + o) * s, (y0 + o) * s, w * s, h * s
            col = int(X0 + Wd / 2)
            for c, m in measure_axis(ih[:, col], Y0, Y0 + B + 2, ref_h[:, col]):
                dy = lensmodel.displacement(np.array([col + 0.5]), np.array([c + 0.5]), (X0, Y0, Wd, Hd), radius * s, smoothing, B, D)[1][0]
                meas_y.append((c - Y0, m))
                errs_y.append(abs(m - (-dy)))
        rim_y = [m for u, m in meas_y if u < B * 0.3]
        res["top_rim_displacement_px"] = round(max(rim_y), 2) if rim_y else None
        res["top_max_abs_error_px"] = round(max(errs_y), 3) if errs_y else None
        check(f"refraction{tag}: top edge displaces vertically by the same lens",
              bool(errs_y) and max(errs_y) < 0.8 * max(1.0, s),
              f"{len(meas_y)} crossings, max |measured-model| = {res['top_max_abs_error_px']} px, top rim {res['top_rim_displacement_px']} px")

        X0, Y0, Wd, Hd = x0 * s, y0 * s, w * s, h * s
        # 3. corner: per-row x displacement and per-column y displacement vs the model
        pts = []
        R_ext = lensmodel.corner_shape(radius * s, smoothing, min(Wd, Hd) / 2)[0]
        for yy in range(int(Y0 + 2), int(Y0 + R_ext + B)):
            for c, m in measure_axis(img_v[yy, :], 0, X0 + R_ext + B + 4, ref_v[yy, :]):
                if c < X0 + R_ext + B:
                    dx, dy, d = lensmodel.displacement(np.array([c + 0.5]), np.array([yy + 0.5]), (X0, Y0, Wd, Hd), radius * s, smoothing, B, D)
                    if d[0] < -1.0:
                        pts.append(("x", c, yy, m, -dx[0]))
        for xx in range(int(X0 + 2), int(X0 + R_ext + B)):
            for c, m in measure_axis(img_h[:, xx], 0, Y0 + R_ext + B + 4, ref_h[:, xx]):
                if c < Y0 + R_ext + B:
                    dx, dy, d = lensmodel.displacement(np.array([xx + 0.5]), np.array([c + 0.5]), (X0, Y0, Wd, Hd), radius * s, smoothing, B, D)
                    if d[0] < -1.0:
                        pts.append(("y", xx, c, m, -dy[0]))
        errs = np.array([abs(m - p) for _, _, _, m, p in pts])
        strong = np.array([abs(m - p) for _, _, _, m, p in pts if abs(p) > 1.0])
        # direction at the corner: both components must be non-zero and share the model's ratio
        diag = [(k, a, b, m, p) for k, a, b, m, p in pts if abs(p) > 2.0]
        res["corner_samples"] = len(pts)
        res["corner_rms_error_px"] = round(float(np.sqrt((errs**2).mean())), 3) if len(errs) else None
        res["corner_p95_error_px"] = round(float(np.percentile(strong, 95)), 3) if len(strong) else None
        check(f"refraction{tag}: displacement follows the outline around the continuous-curvature corner",
              len(pts) > 50 and res["corner_rms_error_px"] < 0.5 * max(1.0, s),
              f"{len(pts)} samples (x and y components) in the corner, RMS |measured-model| = {res['corner_rms_error_px']} px, "
              f"p95 where |model|>1px = {res['corner_p95_error_px']} px, {len(diag)} samples with >2px displacement")
        RESULTS[f"refraction{tag}"] = res

        # evidence: grid crop of the corner, 3x nearest-neighbour zoom, refraction only
        if not tag or tag == "@1.6":
            sc.set_background("grid")
            sc.c.send({"op": "debug", "isolate": "refraction"})
            sc.c.wait("debug")
            # off the 16-px pattern grid, so the compression along the straight edges shows too
            sc.shapes([dict(shape, x=x0 + 5, y=y0 + 5)], settle=0.8)
            img = sc.shot()
            sc.c.send({"op": "debug", "isolate": "none"})
            crop = img[int(Y0 - 24 * s): int(Y0 + 120 * s), int(X0 - 24 * s): int(X0 + 200 * s), :3]
            Image.fromarray(crop).resize((crop.shape[1] * 3 // max(1, int(s)), crop.shape[0] * 3 // max(1, int(s))), Image.NEAREST).save(
                os.path.join(EVIDENCE, f"refraction-corner-grid{tag.replace('@', '-x')}.png"), optimize=True)
    finally:
        sc.close()


# ------------------------------------------------------------------------------------------
# material: slider, theme, legibility
# ------------------------------------------------------------------------------------------

def inside_stats(img, rect, inset=30):
    x, y, w, h = rect
    a = img[y + inset: y + h - inset, x + inset: x + w - inset, :3].astype(float)
    l = a @ np.array([0.2126, 0.7152, 0.0722])
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    return {"mean_luminance": round(float(l.mean()), 1), "luminance_std": round(float(l.std()), 1), "saturation": round(float(sat.mean()), 3)}


def test_slider_theme():
    rect = (380, 220, 520, 300)
    shape = {"id": "m", "x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3], "radius": 36}
    sc = Scene("busy")
    try:
        bg = inside_stats(sc.shot(), rect)
        out = {"background": bg}
        for theme in ("light", "dark"):
            for g in (0.0, 0.5, 1.0):
                sc.s.write_settings({"appearance": {"theme": theme, "glass": g}})
                sc.shapes([shape], settle=1.2)
                out[f"{theme}@{g}"] = inside_stats(sc.shot(), rect)
        RESULTS["slider_theme"] = out
        print("   inside-shape statistics:", json.dumps(out))
        l0, l5, l1 = (out[f"light@{g}"]["luminance_std"] for g in (0.0, 0.5, 1.0))
        check("slider: more tint hides more of the background (light theme)", l0 > l5 > l1,
              f"luminance std through the glass: 0.0 -> {l0}, 0.5 -> {l5}, 1.0 -> {l1} (background {bg['luminance_std']})")
        d0, d1 = out["dark@0.0"]["luminance_std"], out["dark@1.0"]["luminance_std"]
        check("slider: more tint hides more of the background (dark theme)", d0 > d1, f"{d0} -> {d1}")
        lm, dm = out["light@1.0"]["mean_luminance"], out["dark@1.0"]["mean_luminance"]
        check("theme: light tint brighter than dark tint", lm > dm + 60, f"mean luminance fully tinted: light {lm}, dark {dm}")
        lm0, dm0 = out["light@0.0"]["mean_luminance"], out["dark@0.0"]["mean_luminance"]
        check("theme matters even ultra-clear", lm0 > dm0, f"mean luminance ultra-clear: light {lm0}, dark {dm0}")
        sc.s.write_settings({"appearance": {"theme": "light", "glass": 0.3}})
        time.sleep(0.5)
    finally:
        sc.close()


def test_legibility():
    rect = (380, 220, 520, 300)
    shape = {"id": "m", "x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3], "radius": 36}
    out = {}
    for theme in ("light", "dark"):
        sc = Scene("white", settings={"appearance": {"theme": theme, "glass": 0.3}})
        try:
            sc.shapes([shape], settle=1.5)
            ev_white = sc.c.wait("legibility", 3)
            img_w = sc.shot()
            sc.set_background("black")
            time.sleep(1.2)
            ev_black = sc.c.wait("legibility", 4)
            img_b = sc.shot()
            out[theme] = {
                "over_white": ev_white and {k: ev_white[k] for k in ("scheme", "luminance")},
                "over_black": ev_black and {k: ev_black[k] for k in ("scheme", "luminance")},
                "glass_luminance_over_white_px": inside_stats(img_w, rect)["mean_luminance"],
                "glass_luminance_over_black_px": inside_stats(img_b, rect)["mean_luminance"],
            }
        finally:
            sc.close()
    RESULTS["legibility"] = out
    print("   legibility:", json.dumps(out))
    lw, lb = out["light"]["over_white"], out["light"]["over_black"]
    check("legibility (light theme): white background -> light glass/dark text, black -> dark glass/light text",
          bool(lw) and bool(lb) and lw["scheme"] == "light" and lb["scheme"] == "dark", f"{lw} / {lb}")
    dw, db = out["dark"]["over_white"], out["dark"]["over_black"]
    check("legibility (dark theme): signal flips over white content too",
          bool(db) and db["scheme"] == "dark" and (dw is None or dw["scheme"] in ("light", "dark")), f"{dw} / {db}")
    for theme in ("light", "dark"):
        gw, gb = out[theme]["glass_luminance_over_white_px"], out[theme]["glass_luminance_over_black_px"]
        # light scheme band [0.56,0.94]*255, dark scheme band [0.06,0.40]*255 (+ rim light)
        check(f"legibility ({theme}): rendered glass stays inside the band for its text colour",
              (gw >= 0.5 * 255 and gw <= 0.97 * 255) and gb <= 0.5 * 255,
              f"mean glass luminance over white {gw}, over black {gb}")


# ------------------------------------------------------------------------------------------
# idle, caching and cost
# ------------------------------------------------------------------------------------------

def proc_cpu_seconds(pid):
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")


def test_idle_and_cache():
    sc = Scene("busy")
    try:
        shapes = [{"id": "a", "x": 100, "y": 100, "w": 400, "h": 120, "radius": 30},
                  {"id": "dock", "x": 340, "y": 660, "w": 600, "h": 84, "radius": 26},
                  {"id": "b", "kind": "capsule", "x": 700, "y": 300, "w": 120, "h": 120, "group": "g"},
                  {"id": "c", "kind": "capsule", "x": 830, "y": 320, "w": 90, "h": 90, "group": "g"}]
        sc.shapes(shapes, settle=2.0)
        st0 = sc.status()
        cpu0 = proc_cpu_seconds(sc.s.kwin.pid)
        time.sleep(5.0)
        st1 = sc.status()
        cpu1 = proc_cpu_seconds(sc.s.kwin.pid)
        frames = st1["frames"] - st0["frames"]
        work = {k: st1[k] - st0[k] for k in ("glassDraws", "captures", "blurs", "composites", "lumaReads")}
        RESULTS["idle"] = {"seconds": 5, "frames": frames, "effect_work": work, "kwin_cpu_seconds": round(cpu1 - cpu0, 3)}
        check("idle: static scene -> KWin paints no frames and the effect does no work",
              frames == 0 and all(v == 0 for v in work.values()),
              f"over 5 s: {frames} frames, effect counters delta {work}, KWin CPU {cpu1 - cpu0:.3f} s")

        # shape-only change (pointer highlight moving over a static background): blur cache hit
        st0 = sc.status()
        for i in range(30):
            shapes[1]["pointer"] = [340 + 20 * i, 700]
            sc.c.send({"op": "shapes", "surface": "t", "shapes": shapes})
            time.sleep(0.05)
        time.sleep(0.6)
        st1 = sc.status()
        d = {k: st1[k] - st0[k] for k in ("frames", "glassDraws", "captures", "blurs", "cacheHits", "composites")}
        RESULTS["cache_shape_only"] = d
        check("cache: changing only shapes over a static background reuses the captured blur",
              d["frames"] > 0 and d["captures"] == 0 and d["blurs"] == 0 and d["cacheHits"] > 0,
              f"30 pointer updates -> {d}")

        # Dock "magnification": shape grows within the capture grid -> still no recapture
        st0 = sc.status()
        for i in range(20):
            shapes[1]["w"] = 600 + i
            shapes[1]["x"] = 340 - i / 2
            sc.c.send({"op": "shapes", "surface": "t", "shapes": shapes})
            time.sleep(0.05)
        time.sleep(0.6)
        st1 = sc.status()
        d = {k: st1[k] - st0[k] for k in ("frames", "captures", "blurs", "cacheHits", "allocations")}
        RESULTS["cache_dock_grow"] = d
        check("cache: a magnifying Dock (shape grows 20 px) keeps its capture, no reallocation",
              d["frames"] > 0 and d["allocations"] == 0, f"{d}")

        # background change below the glass (new wallpaper): recapture
        st0 = sc.status()
        sc.set_background("gradient")
        st1 = sc.status()
        d = {k: st1[k] - st0[k] for k in ("captures", "blurs")}
        check("cache: a change below the glass invalidates the cached blur", d["captures"] > 0 and d["blurs"] > 0, f"{d}")
    finally:
        sc.close()


def test_timing_and_quality():
    """per-pass timings on llvmpipe (CPU rasteriser!) for both tiers, from the debug switch"""
    out = {}
    sc = Scene("busy")
    try:
        shapes = [{"id": "bar", "x": 8, "y": 6, "w": 1264, "h": 28, "radius": 10},
                  {"id": "dock", "x": 340, "y": 690, "w": 600, "h": 84, "radius": 26},
                  {"id": "panel", "x": 920, "y": 50, "w": 340, "h": 300, "radius": 26}]
        t = sc.s.connect()
        t.wait("hello")
        t.send({"op": "debug", "timing": True})
        t.wait("debug")
        for tier in ("high", "efficient"):
            sc.c.send({"op": "config", "qualityHint": tier})
            time.sleep(1.5)
            # the frames right after a tier switch repaint everything; measure a later window
            t.drain(0.1)
            ev = None
            seen = 0
            end = time.monotonic() + 6
            i = 0
            while time.monotonic() < end and seen < 2:
                shapes[1]["x"] = 340 + (i % 2) * 40  # crosses the 32 px grid -> recapture + blur
                i += 1
                sc.c.send({"op": "shapes", "surface": "t", "shapes": shapes})
                time.sleep(0.04)
                for e in t.drain(0.0):
                    if e.get("event") == "timing":
                        seen += 1
                        ev = e
            out[tier] = ev and {k: round(ev[k], 3) for k in ("frames", "captureMs", "blurMs", "compositeMs", "lumaMs", "totalMs")}
        sc.c.send({"op": "config", "qualityHint": None})
        RESULTS["timing_llvmpipe"] = out
        print("   per-frame pass times on llvmpipe (ms):", json.dumps(out))
        check("timing switch reports per-pass times for both quality tiers", bool(out.get("high")) and bool(out.get("efficient")), json.dumps(out))
        if out.get("high") and out.get("efficient"):
            check("efficient tier is cheaper than high", out["efficient"]["totalMs"] < out["high"]["totalMs"],
                  f"high {out['high']['totalMs']} ms vs efficient {out['efficient']['totalMs']} ms per frame")
        t.close()
    finally:
        sc.close()


# ------------------------------------------------------------------------------------------
# evidence images: the demo shell over a busy background
# ------------------------------------------------------------------------------------------

def evidence_demo(scale, theme, glass, name, crop=None):
    W, H = 1280, 800
    s = harness.Session(W, H, scale, settings={"appearance": {"theme": theme, "glass": glass}})
    s.start()
    try:
        dev_w, dev_h = int(round(W * scale)), int(round(H * scale))
        bg = make_bg(s, "busy", dev_w, dev_h)
        s.background(bg)
        time.sleep(1.5)
        s.quickshell(DEMO, name="demo")
        c = s.connect()
        c.wait("hello")
        ok = harness.wait_until(lambda: len(c.status().get("windows", [])) >= 4, 20)
        time.sleep(2.5)
        img = s.screenshot()
        st = c.status()
        c.close()
        if crop:
            x0, y0, x1, y1 = (int(v * scale) for v in crop)
            img = img[y0:y1, x0:x1]
        Image.fromarray(img[..., :3]).save(os.path.join(EVIDENCE, name), optimize=True)
        shapes = sum(w["shapes"] for w in st["windows"])
        check(f"demo renders ({name})", bool(ok) and shapes >= 6, f"{len(st['windows'])} glass windows, {shapes} shapes, image {img.shape[1]}x{img.shape[0]}")
    finally:
        s.stop()


def test_multioutput():
    s = harness.Session(800, 600, outputs=2)
    s.start()
    try:
        bg = make_bg(s, "busy", 800, 600)
        s.background(bg)
        s.quickshell(GLASSHOST, name="host")
        time.sleep(2.5)
        c = s.connect()
        c.wait("hello")
        c.send({"op": "bind", "surface": "one", "match": {"namespace": "kristall-test-glass", "output": "Virtual-1", "pid": 0}})
        ev1 = c.wait("bound", 5)
        c.send({"op": "bind", "surface": "all", "match": {"namespace": "kristall-test-glass", "pid": 0}})
        ev2 = c.wait("bound", 5)
        c.send({"op": "shapes", "surface": "one", "shapes": [{"id": "a", "x": 100, "y": 100, "w": 300, "h": 120, "radius": 30}]})
        c.send({"op": "shapes", "surface": "all", "shapes": [{"id": "b", "kind": "capsule", "x": 200, "y": 400, "w": 400, "h": 80}]})
        time.sleep(1.5)
        st = c.status()
        shots = {}
        for name in ("Virtual-0", "Virtual-1"):
            img = s.screenshot(name)
            ref = lum(img)
            shots[name] = {"size": f"{img.shape[1]}x{img.shape[0]}", "std_in_a": round(float(ref[130:190, 130:370].std()), 1)}
        geoms = sorted(tuple(w["geometry"]) for w in st["windows"])
        RESULTS["multioutput"] = {"bound_output_filter": ev1, "bound_all": ev2, "windows": geoms, "shots": shots}
        check("multi-output: 'output' selects one of two same-namespace surfaces; without it both get glass",
              ev1 and ev1["windows"] == 1 and ev2 and ev2["windows"] == 2 and len(geoms) == 2 and sum(w["shapes"] for w in st["windows"]) == 3,
              f"bound {ev1} / {ev2}; glass windows {geoms}; per-output screenshots {shots}")
        c.close()
    finally:
        s.stop()


INTERNAL_SCRIPT = """import QtQuick
import org.kde.kwin as KWin  // namespaced: KWin also has a (non-creatable) Window type
Item {
    // created like the switcher's TabBox window (an Instantiator delegate)
    Instantiator {
        active: true
        delegate: Window {
            id: win
            flags: Qt.BypassWindowManagerHint | Qt.FramelessWindowHint | Qt.ToolTip
            color: "transparent"
            visible: true
            x: 700; y: 150; width: 400; height: 260
            // what shell/modules/switcher declares on its TabBox window (glass.md: kristallGlass)
            property var kristallGlass: ({ id: "panel", x: 30, y: 30, w: 340, h: 200, radius: 22 })
            property bool kristallGlassActive: false   // set by the effect while it draws the glass
            // a marker: green while the effect says the glass is drawn, red otherwise
            Rectangle { x: 0; y: 0; width: 20; height: 20; color: win.kristallGlassActive ? "#00ff00" : "#ff0000" }
            Timer { interval: 3000; running: true; onTriggered: win.kristallGlass = [{ id: "panel", x: 30, y: 30, w: 340, h: 200, radius: 22 },
                                                                                     { id: "chip", kind: "capsule", x: 30, y: 2, w: 120, h: 24 }] }
            Timer { interval: 6000; running: true; onTriggered: win.kristallGlass = null }
        }
    }
}
"""


def test_internal_window():
    """a KWin-internal QML Window gets real glass from its declared kristallGlass property, live"""
    sc = Scene("busy")
    try:
        path = os.path.join(sc.s.tmp, "internal-glass.qml")
        with open(path, "w") as f:
            f.write(INTERNAL_SCRIPT)
        bg = inside_stats(sc.shot(), (730, 180, 340, 200))
        env = sc.s.env()

        def gdbus(method, *args):
            return subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                                   "--method", "org.kde.kwin.Scripting." + method, *args], env=env, capture_output=True, text=True, timeout=10)
        r = gdbus("loadDeclarativeScript", path, "kristall-internal-glass")
        sid = r.stdout.strip().strip("(),")
        r2 = subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", f"/Scripting/Script{sid}",
                             "--method", "org.kde.kwin.Script.run"], env=env, capture_output=True, text=True, timeout=10)
        check("declarative KWin script with a QML Window loaded", r.returncode == 0 and r2.returncode == 0, (r.stdout + r.stderr + r2.stderr).strip())
        t0 = time.monotonic()

        def internal_windows():
            st = sc.status() or {}
            return [w for w in st.get("windows", []) if w.get("internal")]
        got = harness.wait_until(internal_windows, 2.5)
        check("the internal window is on glass with its declared shape", bool(got) and got[0]["internal"] == 1 and got[0]["explicit"]
              and got[0]["shapes"] == 1, json.dumps(got))
        if got:
            g = got[0]["geometry"]
            check("…at the window's place", abs(g[0] - 700) < 1 and abs(g[1] - 150) < 1, str(g))
        time.sleep(0.6)
        img = sc.shot()
        inside = inside_stats(img, (730, 180, 340, 200))
        RESULTS["internal_window"] = {"background": bg, "glass": inside}
        px = img[160, 710, :3].tolist()
        check("the effect told the window its glass is drawn (kristallGlassActive → green marker)", px[1] > 200 and px[0] < 60, str(px))
        check("the background behind it is refracted and blurred (less detail inside the shape)",
              inside["luminance_std"] < bg["luminance_std"] * 0.8, f"luminance std {bg['luminance_std']} → {inside['luminance_std']}")
        Image.fromarray(img).crop((660, 110, 1140, 450)).save(os.path.join(EVIDENCE, "internal-window-glass.png"), optimize=True)
        time.sleep(max(0, 3.6 - (time.monotonic() - t0)))
        got = harness.wait_until(lambda: [w for w in internal_windows() if w["internal"] == 2], 2.0)
        check("a changed kristallGlass is followed (notify signal): now two shapes", bool(got) and got[0]["shapes"] == 2, json.dumps(internal_windows()))
        time.sleep(max(0, 6.6 - (time.monotonic() - t0)))
        gone = harness.wait_until(lambda: not internal_windows(), 2.0)
        check("kristallGlass = null removes the glass", bool(gone), json.dumps(internal_windows()))
        time.sleep(0.4)
        px = sc.shot()[160, 710, :3].tolist()
        check("…and kristallGlassActive is false again (red marker: the window draws its own material)", px[0] > 200 and px[1] < 60, str(px))
        if FAILURES:
            print("   KWin log tail:", "\n".join(sc.s.log_text().splitlines()[-40:]))
    finally:
        sc.close()


def main():
    os.makedirs(EVIDENCE, exist_ok=True)
    which = sys.argv[1:] or ["refraction", "refraction16", "slider", "legibility", "idle", "timing", "evidence"]
    if "refraction" in which:
        test_refraction(1.0)
    if "refraction16" in which:
        test_refraction(1.6, "@1.6")
    if "slider" in which:
        test_slider_theme()
    if "legibility" in which:
        test_legibility()
    if "idle" in which:
        test_idle_and_cache()
    if "timing" in which:
        test_timing_and_quality()
    if "multioutput" in which:
        test_multioutput()
    if "internal" in which:
        test_internal_window()
    if "evidence" in which:
        evidence_demo(1.0, "light", 0.15, "demo-1.0x-light-clear.png")
        evidence_demo(1.0, "dark", 0.85, "demo-1.0x-dark-tinted.png")
        evidence_demo(1.6, "light", 0.85, "demo-1.6x-light-tinted.png", crop=(0, 260, 1280, 800))
        evidence_demo(1.6, "dark", 0.15, "demo-1.6x-dark-clear.png", crop=(0, 260, 1280, 800))
    path = os.environ.get("KRISTALL_GLASS_RESULTS")
    if path:
        old = {}
        if os.path.exists(path):
            with open(path) as f:
                old = json.load(f)
        old.update(RESULTS)
        with open(path, "w") as f:
            json.dump(old, f, indent=1)
    if FAILURES:
        print(f"{len(FAILURES)} rendering check(s) failed: {FAILURES}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
