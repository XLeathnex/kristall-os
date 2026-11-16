# SPDX-License-Identifier: GPL-3.0-or-later
# Screenshots: dimensions and scale factors (1.0, 1.6, two outputs), mapping image pixels back to
# screen coordinates, excludeShell, owner-excluded windows, file mode, speed.
import os
import stat
import sys
import time

from PIL import Image

from common import *  # noqa: F403

PROBE_RGB = (0x30, 0x60, 0xC0)  # wlprobe's default fill


def shot(b, **params):
    t0 = time.monotonic()
    r = b.call("screenshot", timeout=30, **params)
    r["ms"] = (time.monotonic() - t0) * 1000
    return r


def pixel(r, gx, gy):
    """Colour at global logical (gx, gy), mapped into the image with the reply's own factors."""
    img = Image.open(r["path"]).convert("RGB")
    px = int((gx - r["originX"]) * r["scaleX"])
    py = int((gy - r["originY"]) * r["scaleY"])
    return img.getpixel((px, py))


def close_to(c, ref, tol=6):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


@test
def test_dimensions_and_scale_factors():
    """width/height/origin/scale are exact at scale 1.0 and 1.6, with and without maxWidth"""
    for scale in (1.0, 1.6):
        with Session(scale=scale) as s:
            b = s.bridge()
            b.subscribe("outputs")
            out = b.wait_event("outputs.changed", 3)["data"]["outputs"][0]
            p = s.wlprobe("--title", "probe", "--size", "300x200")
            w = place(b, window_by_title(b, "probe"), 100, 80, 300, 200)
            time.sleep(0.4)
            r = shot(b, target="desktop")
            note(f"[{scale}] desktop {r['width']}x{r['height']} in {r['ms']:.0f} ms (llvmpipe)")
            check(r["width"] == round(out["w"] * scale) and r["height"] == round(out["h"] * scale) and r["scaleX"] == scale and r["scaleY"] == scale,
                  f"[{scale}] native size {r['width']}x{r['height']} for a {out['w']}x{out['h']} logical output, scale {r['scaleX']}")
            st = os.stat(r["path"])
            check(stat.S_IMODE(st.st_mode) == 0o600 and r["path"].startswith(os.path.join(s.runtime, "kristall", "shots")), f"file mode 0600 under shots/: {r['path']}")
            img = Image.open(r["path"])
            check(img.size == (r["width"], r["height"]), "PNG size matches the reply")
            check(close_to(pixel(r, 250, 180), PROBE_RGB), f"[{scale}] the window's colour at its global position: {pixel(r, 250, 180)}")
            os.unlink(r["path"])

            r = shot(b, target="desktop", maxWidth=640)
            check(r["width"] == 640 and abs(r["height"] - 640 * out["h"] / out["w"]) <= 1, f"[{scale}] maxWidth 640 -> {r['width']}x{r['height']}")
            check(abs(r["scaleX"] - 640 / out["w"]) < 1e-9, f"[{scale}] scaleX = 640 / logical width = {r['scaleX']}")
            check(close_to(pixel(r, 250, 180), PROBE_RGB, 12), f"[{scale}] mapping back with scaleX/originX finds the window")

            r = shot(b, target={"region": {"x": 100, "y": 80, "w": 150, "h": 100}})
            check((r["width"], r["height"]) == (round(150 * scale), round(100 * scale)) and (r["originX"], r["originY"]) == (100, 80),
                  f"[{scale}] region {r['width']}x{r['height']} at origin ({r['originX']}, {r['originY']})")
            check(close_to(pixel(r, 175, 130), PROBE_RGB), "region content is the window")

            r = shot(b, target={"window": w["id"]}, maxHeight=100)
            check(r["height"] == 100 and abs(r["scaleY"] - 100 / w["h"]) < 1e-9 and r["originX"] == w["x"], f"[{scale}] window shot {r['width']}x{r['height']}, scale {r['scaleY']}")
            r = shot(b, target={"output": out["name"]})
            check(r["width"] == round(out["w"] * scale), "output shot")


@test
def test_two_outputs():
    """a desktop shot spans both outputs; an output shot covers one"""
    with Session(outputs=2) as s:
        b = s.bridge()
        b.subscribe("outputs")
        outs = b.wait_event("outputs.changed", 3)["data"]["outputs"]
        r = shot(b, target="desktop")
        total_w = max(o["x"] + o["w"] for o in outs) - min(o["x"] for o in outs)
        check(r["width"] == total_w and r["height"] == max(o["h"] for o in outs), f"desktop {r['width']}x{r['height']} spans {len(outs)} outputs")
        r = shot(b, target={"output": outs[1]["name"]})
        check((r["originX"], r["width"]) == (outs[1]["x"], outs[1]["w"]), f"second output origin {r['originX']}")


@test
def test_exclude_shell_and_owner_exclusions():
    """excludeShell removes kristall-assistant* overlays only; owner-hidden windows are never captured"""
    with Session() as s:
        b = s.bridge()
        p = s.wlprobe("--title", "under", "--size", "300x200")
        w = place(b, window_by_title(b, "under"), 50, 50, 300, 200)
        start_shell(s)
        find_window(b, lambda v: v.get("namespace") == "kristall-assistant-glow", 15)
        dock = find_window(b, lambda v: v.get("namespace") == "kristall-dock", 5)
        time.sleep(0.8)
        with_shell = shot(b, target="desktop")
        without = shot(b, target="desktop", excludeShell=True)
        c1, c2 = pixel(with_shell, 100, 100), pixel(without, 100, 100)
        check(close_to(c1, (255, 0, 0)), f"the assistant glow is in a normal shot: {c1}")
        check(close_to(c2, PROBE_RGB), f"excludeShell shows the window under the glow instead: {c2}")
        d1, d2 = pixel(with_shell, 640, dock["y"] + 30), pixel(without, 640, dock["y"] + 30)
        check(close_to(d1, (0x30, 0x50, 0xFF)) and close_to(d2, (0x30, 0x50, 0xFF)), f"the Dock stays in both: {d1} {d2}")
        # the owner hides a window from screenshots (KWin's per-window exclusion)
        s2 = s.wlprobe("--title", "secret", "--size", "200x150", "--color", "ff00ff00")
        ws = place(b, window_by_title(b, "secret"), 700, 400, 200, 150)
        import subprocess
        script = os.path.join(s.tmp, "hide.js")
        with open(script, "w") as f:
            f.write('for (const w of workspace.windowList()) if (w.caption === "secret") w.excludeFromCapture = true;')
        r = subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", script, "hide"],
                           env=s.env(), capture_output=True, text=True)
        sid = r.stdout.split()[-1]
        subprocess.run(["busctl", "--user", "call", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run"], env=s.env())
        time.sleep(0.5)
        r = shot(b, target="desktop")
        c = pixel(r, 800, 470)
        check(not close_to(c, (0, 255, 0)), f"an owner-excluded window is not in the assistant's screenshot: {c}")
        try:
            shot(b, target={"window": ws["id"]})
            check(False, "a window shot of an excluded window must be refused")
        except BridgeError as e:
            check(e.code == "denied", f"window shot of an excluded window: {e.code}")


@test
def test_screenshot_validation_and_cleanup():
    """bad targets are rejected; forgotten files are pruned; a client gone mid-shot leaves no file"""
    with Session() as s:
        b = s.bridge()
        for target in ({"window": "nope"}, {"output": "nope"}, {"region": {"x": 0, "y": 0, "w": 0, "h": 10}}, {"region": {"x": 0, "y": 0, "w": 99999, "h": 10}},
                       "everything", {"foo": 1}, 7):
            try:
                b.call("screenshot", target=target)
                check(False, f"{target} must be rejected")
            except BridgeError as e:
                check(e.code in ("invalid", "not_found"), f"target {target!r}: {e.code}")
        for k, v in (("maxWidth", -1), ("maxWidth", 1e9), ("excludeShell", "yes")):
            try:
                b.call("screenshot", target="desktop", **{k: v})
                check(False, f"{k}={v} must be rejected")
            except BridgeError as e:
                check(e.code == "invalid", f"{k}={v!r}: invalid")
        c = s.bridge("quitter")
        c.send({"id": 1, "method": "screenshot", "params": {"target": "desktop"}})
        c.close()
        time.sleep(1.0)
        shots = os.listdir(os.path.join(s.runtime, "kristall", "shots"))
        check(shots == [], f"no file left behind by a client that went away: {shots}")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
