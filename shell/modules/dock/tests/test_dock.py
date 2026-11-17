#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dock tests (run inside the dev container under dbus-run-session; see run.sh).

Sections (argv selects; default all): static behaviour perf looks autohide
Against the REAL bridge plugin and real apps (Dolphin, Kate, Konsole), driven by the owner's
pointer and keyboard through KWin's fake-input protocol. Screenshots go to tests/evidence/.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import appsession as A  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.join(A.REPO, "kwin", "glass", "tests", "support"))
import pattern  # noqa: E402

EVIDENCE = os.path.join(A.DOCK, "tests", "evidence")
failures, results = [], {}
check, info = A.check_factory(failures, results)
wait_until = A.wait_until

# stand-ins for manifest apps that are not in the dev container (icons from Breeze)
FAKE = [("org.mozilla.firefox", "Firefox", "internet-web-browser"), ("org.kde.elisa", "Elisa", "org.kde.elisa"),
        ("com.visualstudio.code", "Visual Studio Code", "org.kde.kdevelop"), ("org.blender.Blender", "Blender", "org.kde.kolourpaint"),
        ("com.valvesoftware.Steam", "Steam", "org.kde.kpat"), ("io.github.kolunmi.Bazaar", "Bazaar", "org.kde.kget")]


EMITTER = """
import time
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
props = {"count": GLib.Variant("x", 3), "count-visible": GLib.Variant("b", True),
         "progress": GLib.Variant("d", 0.4), "progress-visible": GLib.Variant("b", True)}
bus.emit_signal(None, "/kristall/test", "com.canonical.Unity.LauncherEntry", "Update",
                GLib.Variant("(sa{sv})", ("application://org.kde.dolphin.desktop", props)))
bus.flush_sync(None)
time.sleep(30)
"""


def save(img, name, crop=None, quality=None):
    im = Image.fromarray(img)
    if crop:
        im = im.crop(crop)
    os.makedirs(EVIDENCE, exist_ok=True)
    path = os.path.join(EVIDENCE, name)
    if name.endswith(".jpg"):
        im.convert("RGB").save(path, quality=quality or 84, optimize=True)
    else:
        im.save(path, optimize=True)
    return path


def warnings(sess):
    bad = []
    for line in sess.shell_log().splitlines():
        if ("WARN" in line or "ERROR" in line or "CRITICAL" in line) and "fd limit" not in line:
            if any(k in line for k in ("quickshell.service.pipewire", "quickshell.network", "quickshell.service.upower",
                                       "quickshell.service.powerprofiles", "quickshell.bluetooth")):
                continue        # system services that this test does not mock
            bad.append(line)
    return bad


def photo(w, h):
    """a busy, colourful photo-like image of our own (soft saturated shapes, hard objects, grain)"""
    import numpy as np
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 3), np.float32)
    img[:] = (0.12, 0.22, 0.38)
    for _ in range(70):
        cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.03, 0.22) * w
        col = rng.uniform(0, 1, 3) ** 1.6
        a = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (r * r)) * 1.6)[..., None]
        img = img * (1 - a * 0.9) + col * a * 0.9
    for _ in range(40):
        x0, y0 = int(rng.uniform(0, w)), int(rng.uniform(0, h))
        img[y0:y0 + int(rng.uniform(8, 120)), x0:x0 + int(rng.uniform(8, 160))] = rng.uniform(0, 1, 3)
    img += rng.normal(0, 0.012, (h, w, 1))
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def new_session(name, settings=None, bg_kind="busy", **kw):
    s = A.AppsSession(name=name, settings=settings, **kw)
    for did, nm, icon in FAKE:
        s.desktop(did, nm, icon)
    s.start(wait_glass=kw.get("glass", True))
    bg = os.path.join(s.tmp, "bg.png")
    import numpy as np
    if bg_kind == "photo":
        Image.fromarray(photo(s.width, s.height)).save(bg)
    elif bg_kind in ("white", "black"):
        Image.fromarray(np.full((s.height, s.width, 3), 255 if bg_kind == "white" else 0, np.uint8)).save(bg)
    else:
        Image.fromarray(pattern.busy(s.width, s.height)).save(bg)
    s.background(bg)
    return s


def dock_state(s, pred=None, timeout=8.0):
    last = [None]

    def f():
        try:
            st = s.dock()
        except Exception:
            return None
        last[0] = st
        return st if st.get("dock") and (pred is None or pred(st)) else None
    return wait_until(f, timeout, 0.2) or last[0]


def tile(st, tid):
    for t in st["tiles"]:
        if t["id"] == tid:
            return t
    return None


def centre(t):
    return (t["x"] + t["w"] / 2, t["y"] + t["w"] / 2)


def settings_get(s, path):
    env = s.env()
    env.update(s.shell_env())
    r = subprocess.run(["kristall-settings", "get", path], env=env, capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def settings_set(s, path, value):
    env = s.env()
    env.update(s.shell_env())
    subprocess.run(["kristall-settings", "set", path, json.dumps(value)], env=env, check=True)


def launch(s, args, app_id):
    p = subprocess.Popen(args, env=s.app_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s.procs.append(p)
    w = wait_until(lambda: s.app_windows(app_id), 20, 0.3)
    return p, (w[0] if w else None)


def menu_items(s, level=0):
    st = json.loads(s.ipc("test", "state", ""))
    lv = st.get("levels") or []
    return lv[level]["items"] if len(lv) > level else []


def choose(s, prefix, level=0):
    """select the menu item starting with `prefix` with real ↓ presses (nothing selected yet) and press ↩"""
    s.move(5, 300)          # the pointer must not hover a row (hover selects)
    time.sleep(0.2)
    items = [i for i in menu_items(s, level) if not i.startswith("-") and "[disabled]" not in i]
    idx = next(k for k, i in enumerate(items) if i.startswith(prefix))
    for _ in range(idx + 1):
        s.tap("down")
    s.tap("return")


def rest_state(s, timeout=6.0):
    """pointer away from the Dock, wait until nothing is magnified or animating"""
    s.move(s.width / 2, s.height / 2 - 150)
    return dock_state(s, lambda st: st["hoverAmt"] == 0 and all(t["presence"] == 1 for t in st["tiles"]), timeout)


def icon_geometry(s):
    lines = s.kwin_script("for (const w of workspace.windowList()) { if (w.normalWindow) "
                          "console.warn('KRISTALL-PROBE', JSON.stringify({id: String(w.internalId).replace(/[{}]/g, ''), "
                          "x: w.iconGeometry.x, y: w.iconGeometry.y, w: w.iconGeometry.width, h: w.iconGeometry.height, min: w.minimized})); }")
    out = {}
    for l in lines:
        try:
            d = json.loads(l)
            out[d["id"]] = d
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------------------------------------------
def test_static():
    print("== static", flush=True)
    mods = os.path.join(A.SHELL, "modules")
    for m in ("dock", "search", "apps", "switcher"):
        d = os.path.join(mods, m)
        qd = os.path.join(d, "qmldir")
        if not os.path.exists(qd):
            continue
        listed = set()
        for line in open(qd):
            parts = line.split()
            if parts and not line.startswith("#"):
                listed.add(parts[-1])
        files = {f for f in os.listdir(d) if f.endswith(".qml") and f != "Module.qml"}
        check(f"{m}/qmldir lists every QML file", files <= listed, str(files - listed))
    for m in ("dock", "search", "apps", "switcher"):
        p = os.path.join(mods, m, "strings.json")
        if os.path.exists(p):
            t = json.load(open(p))
            check(f"{m}/strings.json: German and English have the same keys", set(t["en"]) == set(t["de"]), str(set(t["en"]) ^ set(t["de"])))
            check(f"{m}/strings.json: keys start with the module name", all(k.startswith(m + ".") for k in t["en"]))
    r = subprocess.run([sys.executable, "-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())",
                        os.path.join(A.DOCK, "helper", "kristall-dock-launcher-entries")], capture_output=True, text=True)
    check("launcher-entry helper compiles", r.returncode == 0, r.stderr)
    d = json.load(open(os.path.join(A.DOCK, "image", "settings.json")))
    check("dock settings defaults own only the 'dock' key", set(d) == {"dock"}, str(d.keys()))


# ---------------------------------------------------------------------------------------------------
def test_behaviour():
    print("== behaviour against real windows (real bridge)", flush=True)
    s = new_session("dock-behaviour")
    try:
        s.start_shell()
        st = dock_state(s, lambda st: st["catalog"] > 0 and st["glassDrawn"] and tile(st, "app:org.kde.dolphin"), 20)
        time.sleep(1.5)
        w = warnings(s)
        check("zero QML warnings at start", not w, "\n".join(w[:8]))
        ids = [t["id"] for t in st["tiles"]]
        check("Dock: kept apps from the manifest, Apps tile second, separator, Downloads, Trash",
              ids[:3] == ["app:org.kde.dolphin", "apps", "app:org.mozilla.firefox"] and ids[-3:] == ["sep", "downloads", "trash"], " ".join(ids))
        check("Dock reserves its height (exclusive zone = capsule + gap)", st["exclusiveZone"] == 66, str(st["exclusiveZone"]))
        check("Dock glass bound and drawn", st["glassDrawn"])
        cap = st["capsule"]
        check("capsule centred at the bottom", abs(cap["x"] + cap["w"] / 2 - s.width / 2) <= 1 and abs(cap["y"] + cap["h"] + 6 - s.height) <= 1, json.dumps(cap))
        save(s.screenshot(), "dock-rest-light-1.0x.png", crop=(0, s.height - 170, s.width, s.height))

        # ---- launch → bounce → window → dot
        t = tile(st, "app:org.kde.dolphin")
        t0 = time.monotonic()
        s.click(*centre(t))
        st2 = dock_state(s, lambda st: tile(st, "app:org.kde.dolphin")["launching"], 3)
        check("click on a kept app that is not running launches it and it bounces", bool(st2 and tile(st2, "app:org.kde.dolphin")["launching"]))
        win = wait_until(lambda: s.app_windows("org.kde.dolphin"), 20, 0.2)
        t_win = time.monotonic() - t0
        st2 = dock_state(s, lambda st: tile(st, "app:org.kde.dolphin")["running"] and not tile(st, "app:org.kde.dolphin")["launching"], 5)
        check("first window appears → bounce stops, running dot shows", bool(win) and bool(st2) and tile(st2, "app:org.kde.dolphin")["running"],
              f"window after {t_win:.1f} s")
        results["dolphin_launch_s"] = round(t_win, 2)
        dolphin = win[0]

        # ---- a running app that is not kept appears after the kept ones
        kate, kw = launch(s, ["kate", "-n"], "org.kde.kate")
        st2 = dock_state(s, lambda st: tile(st, "app:org.kde.kate") is not None, 8)
        ids = [t["id"] for t in st2["tiles"]]
        check("a running app that is not kept appears between the kept apps and the separator",
              "app:org.kde.kate" in ids and ids.index("app:org.kde.kate") == ids.index("sep") - 1, " ".join(ids))
        time.sleep(0.8)
        # ---- click a running app that is behind: its windows come forward
        b = s.bridge_client()
        b.call("window.activate", id=kw["id"])
        wait_until(lambda: any(w["active"] and w["appId"] == "org.kde.kate" for w in s.windows()), 5)
        s.click(*centre(tile(dock_state(s), "app:org.kde.dolphin")))
        ok = wait_until(lambda: any(w["active"] and w["appId"] == "org.kde.dolphin" for w in s.windows()), 5)
        check("click on a running app brings its window forward", bool(ok))
        # ---- minimise: the window flows into the Dock (icon geometry), a minimised tile appears
        st2 = rest_state(s)
        geo = icon_geometry(s)
        g = geo.get(dolphin["id"])
        dl = tile(st2, "downloads")
        check("bridge was told where Dolphin's window minimises to (KWin iconGeometry, a Dock slot)",
              bool(g) and g["w"] == 48 and abs(g["y"] - dl["y"]) <= 1 and dl["x"] - 60 <= g["x"] <= dl["x"] + 2, json.dumps(g) + " downloads " + json.dumps(dl))
        b.call("window.setMinimized", id=dolphin["id"], value=True)
        st2 = dock_state(s, lambda st: tile(st, "win:" + dolphin["id"]) is not None, 5)
        check("minimised window gets its own tile before Downloads", bool(st2) and [t["id"] for t in st2["tiles"]].index("downloads") - 1
              == [t["id"] for t in st2["tiles"]].index("win:" + dolphin["id"]))
        st2 = rest_state(s)
        wt = tile(st2, "win:" + dolphin["id"])
        geo = icon_geometry(s)
        g = geo.get(dolphin["id"])
        check("…exactly where the window flowed to", bool(g and wt) and abs(g["x"] - wt["x"]) <= 1 and abs(g["y"] - wt["y"]) <= 1,
              json.dumps(g) + " tile " + json.dumps(wt))
        save(s.screenshot(), "dock-minimised-tile-light-1.0x.png", crop=(0, s.height - 170, s.width, s.height))
        s.click(*centre(wt))
        ok = wait_until(lambda: any(w["id"] == dolphin["id"] and not w["minimized"] and w["active"] for w in s.windows()), 5)
        check("click on the minimised tile restores the window", bool(ok))
        b.call("window.setMinimized", id=dolphin["id"], value=True)
        st2 = rest_state(s)
        s.click(*centre(tile(st2, "app:org.kde.dolphin")))
        ok = wait_until(lambda: any(w["id"] == dolphin["id"] and not w["minimized"] for w in s.windows()), 5)
        check("click on an app whose windows are all minimised restores one", bool(ok))
        n_before = len(s.app_windows("org.kde.dolphin"))
        s.click(*centre(tile(rest_state(s), "app:org.kde.dolphin")))
        time.sleep(1.5)
        check("click on the front app does not open another window", len(s.app_windows("org.kde.dolphin")) == n_before)

        # ---- context menu (real right click, real keys)
        kt = tile(rest_state(s), "app:org.kde.kate")
        s.click(*centre(kt), button=A.BTN_RIGHT)
        st2 = dock_state(s, lambda st: st["menu"] == "dock:app:org.kde.kate", 4)
        menu = json.loads(s.ipc("test", "state", ""))
        items = menu["levels"][0]["items"] if menu.get("levels") else []
        check("right click opens the app's menu: its windows, Optionen ▸, Alle Fenster anzeigen, Ausblenden, Beenden",
              bool(st2) and any(i.startswith("Optionen") and i.endswith(">") for i in items) and "Beenden" in items and "Ausblenden" in items
              and any("Kate" in i or "Unbenannt" in i or "Untitled" in i for i in items), json.dumps(items, ensure_ascii=False))
        time.sleep(0.5)
        save(s.screenshot(), "dock-context-menu-light-1.0x.png", crop=(int(kt["x"]) - 260, s.height - 420, int(kt["x"]) + 260, s.height))
        # Optionen ▸ Im Dock behalten
        sel = [i for i in items if not i.startswith("-")]
        for _ in range(next(k for k, i in enumerate(sel) if i.startswith("Optionen")) + 1):
            s.tap("down")
        s.tap("right")
        time.sleep(0.3)
        check("Optionen ▸ shows Im Dock behalten and In „Dateien“ zeigen", menu_items(s, 1) == ["Im Dock behalten", "In „Dateien“ zeigen"], json.dumps(menu_items(s, 1), ensure_ascii=False))
        s.tap("return")
        ok = wait_until(lambda: "desktop:org.kde.kate" in (settings_get(s, "dock.pinned") or []), 5)
        check("Optionen ▸ Im Dock behalten keeps the app (dock.pinned)", bool(ok), json.dumps(settings_get(s, "dock.pinned")))

        # ---- drag to reorder (real press-drag-release): Firefox before Dateien
        st2 = rest_state(s)
        ff, fl = tile(st2, "app:org.mozilla.firefox"), tile(st2, "app:org.kde.dolphin")
        s.drag(centre(ff), (fl["x"] + 4, centre(fl)[1]))
        ok = wait_until(lambda: (settings_get(s, "dock.pinned") or [None])[0] == "browser", 5)
        st2 = dock_state(s, lambda st: [t["id"] for t in st["tiles"]][0] == "app:org.mozilla.firefox", 4)
        check("drag reorders the kept apps; the order persists in dock.pinned", bool(ok) and bool(st2), json.dumps(settings_get(s, "dock.pinned")))
        # ---- drag off to remove (Kate is still running: it stays as a running app)
        kt = tile(rest_state(s), "app:org.kde.kate")
        a = centre(kt)
        s.owner_proc.move(*a)
        s.owner_proc.button(A.BTN_LEFT, True)
        s.sweep([(a[0], a[1] - 8 * i) for i in range(1, 22)], 60)
        time.sleep(0.3)
        mid = dock_state(s)
        save(s.screenshot(), "dock-drag-remove-light-1.0x.png", crop=(int(a[0]) - 260, s.height - 260, int(a[0]) + 260, s.height))
        s.owner_proc.button(A.BTN_LEFT, False)
        ok = wait_until(lambda: "desktop:org.kde.kate" not in (settings_get(s, "dock.pinned") or []), 5)
        st2 = dock_state(s, lambda st: tile(st, "app:org.kde.kate") is not None and not tile(st, "app:org.kde.kate")["pinned"], 4)
        check("drag off the Dock shows “Entfernen” and removes the app from the kept ones; running, it stays",
              bool(ok) and bool(st2) and mid.get("label") == "Entfernen", f"label while dragging: {mid.get('label')!r}")

        # ---- Hide, Quit from the menu
        s.ipc("docktest", "openMenu", "app:org.kde.kate")
        wait_until(lambda: menu_items(s), 3)
        quit_items = menu_items(s)
        choose(s, "Beenden")
        ok = wait_until(lambda: not s.app_windows("org.kde.kate"), 8)
        st2 = dock_state(s, lambda st: tile(st, "app:org.kde.kate") is None, 4)
        check("Beenden closes the app's windows; its tile leaves the Dock", bool(ok) and bool(st2),
              json.dumps(quit_items, ensure_ascii=False) + " " + json.dumps([(w["appId"], w["title"], w["active"]) for w in s.windows()]))

        # ---- badges through the Unity launcher API
        # an app that stays on the bus (gdbus emit would leave at once, and the badge with it)
        emitter = subprocess.Popen([sys.executable, "-c", EMITTER], env=s.env())
        s.procs.append(emitter)
        st2 = dock_state(s, lambda st: (tile(st, "app:org.kde.dolphin")["badge"] or {}).get("count") == 3, 5)
        check("badge and progress from com.canonical.Unity.LauncherEntry", bool(st2), json.dumps(tile(dock_state(s), "app:org.kde.dolphin")["badge"]))
        time.sleep(0.5)
        fl = tile(rest_state(s), "app:org.kde.dolphin")
        save(s.screenshot(), "dock-badge-progress-light-1.0x.png", crop=(int(fl["x"]) - 40, s.height - 110, int(fl["x"]) + 160, s.height))

        # ---- Trash: empty/full, Empty Trash with confirmation
        with open(os.path.join(s.trash, "old.txt"), "w") as f:
            f.write("x")
        with open(os.path.join(s.data_home, "Trash", "info", "old.txt.trashinfo"), "w") as f:
            f.write("[Trash Info]\nPath=/tmp/old.txt\nDeletionDate=2026-11-15T10:00:00\n")
        st2 = dock_state(s, lambda st: st["trashFull"], 5)
        check("Trash shows full when something is in it (inotify, no polling)", bool(st2))
        s.ipc("docktest", "openMenu", "trash")
        wait_until(lambda: (json.loads(s.ipc("test", "state", "")).get("levels") or None), 3)
        items = json.loads(s.ipc("test", "state", ""))["levels"][0]["items"]
        check("Trash menu: Öffnen, Papierkorb entleeren …", items[0] == "Öffnen" and items[-1].startswith("Papierkorb entleeren"), json.dumps(items, ensure_ascii=False))
        choose(s, "Papierkorb entleeren")
        time.sleep(1.2)
        save(s.screenshot(), "dock-empty-trash-alert-light-1.0x.png", crop=(s.width // 2 - 260, 140, s.width // 2 + 260, 520))
        check("the confirmation leaves the Trash alone until confirmed", os.path.exists(os.path.join(s.trash, "old.txt")))
        s.tap("return")
        ok = wait_until(lambda: not os.listdir(s.trash), 6)
        st2 = dock_state(s, lambda st: not st["trashFull"], 5)
        check("Return in the alert empties the Trash; the icon turns empty", bool(ok) and bool(st2))

        # ---- the apps tile opens Apps; settings apply live
        settings_set(s, "dock.size", 60)
        st2 = dock_state(s, lambda st: st["tileSize"] == 60, 5)
        check("dock.size applies live", bool(st2) and st2["exclusiveZone"] == 6 + 60 + 2 * 8, str(st2 and st2["exclusiveZone"]))
        settings_set(s, "dock.size", 48)
        w = warnings(s)
        check("still zero QML warnings after the behaviour run", not w, "\n".join(w[:8]))
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------------
def test_perf():
    print("== magnification: frame pacing, per-frame cost, idle", flush=True)
    s = new_session("dock-perf")
    try:
        for did in ("org.kde.kate", "org.kde.konsole", "org.kde.dolphin"):
            pass
        s.start_shell()
        st = dock_state(s, lambda st: st["catalog"] > 0 and st["glassDrawn"] and len(st["tiles"]) >= 9, 20)
        time.sleep(1.5)
        bench = json.loads(s.ipc("docktest", "layoutBench", 2000))
        results["dock_layout_us_per_pass"] = round(bench["usPerPass"], 2)
        check("one layout pass (all tiles) costs < 100 µs", bench["usPerPass"] < 100, json.dumps(bench))
        cap = st["capsule"]
        y = cap["y"] + cap["h"] / 2
        x0, x1 = cap["x"] + 4, cap["x"] + cap["w"] - 4
        pts = []
        steps = 240
        for i in range(steps + 1):
            pts.append((x0 + (x1 - x0) * i / steps, y))
        pids = [s.shell.pid]
        s.move(x0 - 200, y - 200)
        time.sleep(0.6)
        f0 = s.dock()["frames"]
        s.ipc("docktest", "recordFrames", "true")
        c0 = A.proc_cpu_ms(pids)
        t0 = time.monotonic()
        s.sweep(pts, 120)
        mid = s.dock()
        dur = time.monotonic() - t0
        c1 = A.proc_cpu_ms(pids)
        times = json.loads(s.ipc("docktest", "recordFrames", "false"))
        frames = s.dock()["frames"] - f0
        iv = [b - a for a, b in zip(times, times[1:])]
        iv_sorted = sorted(iv)
        p50 = iv_sorted[len(iv) // 2] if iv else None
        p95 = iv_sorted[int(len(iv) * 0.95)] if iv else None
        worst = iv_sorted[-1] if iv else None
        r = {"sweep_s": round(dur, 2), "pointer_events": len(pts), "frames": frames, "fps": round(frames / dur, 1),
             "interval_ms_p50": p50, "interval_ms_p95": p95, "interval_ms_max": worst,
             "shell_cpu_ms": round(c1 - c0, 1), "cpu_ms_per_frame": round((c1 - c0) / max(1, frames), 2)}
        results["dock_magnify_sweep"] = r
        info("magnification sweep: " + json.dumps(r))
        check("magnifying while the pointer moves: a frame per output refresh (60 Hz here), p95 interval ≤ 20 ms",
              frames >= dur * 50 and p95 is not None and p95 <= 20, json.dumps(r))
        check("shell CPU per Dock frame (software renderer, llvmpipe compositor) < 8 ms", r["cpu_ms_per_frame"] < 8, json.dumps(r))
        check("mid-sweep the tile under the pointer is magnified (size ≈ dock.magnifiedSize)",
              max(t["w"] for t in mid["tiles"]) > 70 and mid["magnifying"], str(max(t["w"] for t in mid["tiles"])))
        # mid-magnification screenshot over the busy wallpaper, with running apps
        launch(s, ["konsole"], "org.kde.konsole")
        launch(s, ["kate", "-n"], "org.kde.kate")
        b = s.bridge_client()
        for w in s.windows():
            if w["normal"]:
                b.call("window.setGeometry", id=w["id"], x=120 + 80 * (hash(w["id"]) % 5), y=60, w=760, h=460)
        dock_state(s, lambda st: tile(st, "app:org.kde.konsole") is not None)
        time.sleep(0.5)
        st = rest_state(s)
        tgt = tile(st, "app:org.mozilla.firefox")
        cx, cy = centre(tgt)
        s.sweep([(cx - 60 + i * 3, cy) for i in range(21)], 60)
        time.sleep(0.5)
        save(s.screenshot(), "dock-magnified-light-1.0x.png", crop=(0, s.height - 200, s.width, s.height))
        # leaving: back to zero frames
        s.move(s.width / 2, 300)
        time.sleep(1.0)
        try:
            g = s.connect()
        except OSError:
            g = None
        # the pointer now rests over Kate/Konsole, whose hover repaint can land late on a loaded
        # machine: start the window once the compositor has been quiet for 1 s (at most 4 s)
        if g:
            last, quiet_since, give_up = g.status()["frames"], time.monotonic(), time.monotonic() + 4.0
            while time.monotonic() - quiet_since < 1.0 and time.monotonic() < give_up:
                time.sleep(0.25)
                now = g.status()["frames"]
                if now != last:
                    last, quiet_since = now, time.monotonic()
        # the menu bar's clock repaints once a minute, on the minute: keep the window clear of that
        sec = time.localtime().tm_sec
        if sec >= 54:
            time.sleep(61 - sec)
        f0 = s.dock()["frames"]
        g0 = g.status()["frames"] if g else None
        c0 = A.proc_cpu_ms(pids)
        time.sleep(4.0)
        c1 = A.proc_cpu_ms(pids)
        f1 = s.dock()["frames"]
        g1 = g.status()["frames"] if g else None
        idle = {"dock_frames": f1 - f0, "compositor_frames": None if g0 is None else g1 - g0, "shell_cpu_ms": round(c1 - c0, 1),
                "started_at_second": sec}
        results["dock_idle_after_leave"] = idle
        check("pointer left: the Dock presents no frames, the compositor repaints nothing, ~0 CPU (4 s)",
              idle["dock_frames"] == 0 and idle["compositor_frames"] in (0, None) and idle["shell_cpu_ms"] < 30, json.dumps(idle))
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------------
def shots(name, settings, width=1280, height=800, scale=1.0, glass=True, magnify=True, menu=True):
    s = new_session("dock-" + name, settings=settings, width=width, height=height, scale=scale, glass=glass)
    try:
        s.start_shell()
        st = dock_state(s, lambda st: st["catalog"] > 0 and len(st["tiles"]) >= 9, 20)
        launch(s, ["konsole"], "org.kde.konsole")
        st = dock_state(s, lambda st: tile(st, "app:org.kde.konsole") is not None)
        time.sleep(1.5)
        h = int(200 * scale)
        save(s.screenshot(), f"dock-rest-{name}.png", crop=(0, int(height * scale) - h, int(width * scale), int(height * scale)))
        if magnify:
            st = rest_state(s)
            t = tile(st, "app:org.mozilla.firefox")
            cx, cy = centre(t)
            s.sweep([(cx - 40 + i * 2, cy) for i in range(21)], 60)
            time.sleep(0.6)
            save(s.screenshot(), f"dock-magnified-{name}.png", crop=(0, int(height * scale) - h, int(width * scale), int(height * scale)))
        if menu:
            s.ipc("docktest", "openMenu", "app:org.kde.konsole")
            time.sleep(0.8)
            kt = tile(dock_state(s), "app:org.kde.konsole")
            x = int(kt["x"] * scale)
            save(s.screenshot(), f"dock-context-menu-{name}.png", crop=(max(0, x - int(260 * scale)), int((height - 420) * scale), x + int(260 * scale), int(height * scale)))
            s.tap("esc")
        w = warnings(s)
        check(f"{name}: zero QML warnings", not w, "\n".join(w[:6]))
        return dock_state(s)
    finally:
        s.stop()


def test_looks():
    print("== looks: light/dark, scale 1.6, fallback, reduce motion", flush=True)
    st = shots("dark-1.0x", {"appearance": {"theme": "dark", "glass": 0.3}})
    check("dark theme reaches the Dock", st and st["scheme"] == "dark", st and st["scheme"])
    st = shots("light-1.6x", {"appearance": {"theme": "light", "glass": 0.3}}, width=1800, height=1125, scale=1.6, menu=False)
    check("scale 1.6: Dock drawn and centred", bool(st) and abs(st["capsule"]["x"] + st["capsule"]["w"] / 2 - 900) <= 1)
    st = shots("dark-1.6x", {"appearance": {"theme": "dark", "glass": 0.6}}, width=1800, height=1125, scale=1.6, magnify=False, menu=False)
    st = shots("fallback-light-1.0x", {"appearance": {"theme": "light", "glass": 0.3}}, glass=False, menu=False)
    check("without the glass effect the Dock draws its fallback material", bool(st) and not st["glassDrawn"])
    st = shots("reduce-motion-light-1.0x", {"appearance": {"theme": "light", "glass": 0.3}, "accessibility": {"reduceMotion": True}},
               magnify=False, menu=False)
    check("reduce motion: Dock renders", bool(st))


def test_contrast():
    print("== contrast: the capsule reads as a solid object of glass over any background", flush=True)
    pre = os.environ.get("KRISTALL_EVIDENCE_PREFIX", "")
    W, H = 1280, 800
    crops = []
    for theme, bg in (("light", "photo"), ("dark", "photo"), ("light", "white"), ("dark", "black")):
        s = new_session(f"dock-contrast-{theme}-{bg}", settings={"appearance": {"theme": theme, "glass": 0.3}}, bg_kind=bg)
        try:
            s.start_shell()
            st = dock_state(s, lambda st: st["catalog"] > 0 and len(st["tiles"]) >= 9, 20)
            time.sleep(1.5)
            st = dock_state(s)
            c = st["capsule"]
            x0, x1 = int(c["x"]) - 40, int(c["x"] + c["w"]) + 40
            img = s.screenshot()
            crops.append(Image.fromarray(img[..., :3]).crop((x0, H - 140, x1, H)))
            w = warnings(s)
            check(f"contrast {theme}/{bg}: zero QML warnings", not w, "\n".join(w[:6]))
        finally:
            s.stop()
    # one sheet: the four crops stacked
    wmax = max(c.size[0] for c in crops)
    sheet = Image.new("RGB", (wmax, sum(c.size[1] for c in crops) + 6 * (len(crops) - 1)), (128, 128, 128))
    y = 0
    for c in crops:
        sheet.paste(c, (0, y))
        y += c.size[1] + 6
    os.makedirs(EVIDENCE, exist_ok=True)
    sheet.save(os.path.join(EVIDENCE, f"{pre}dock-contrast.png"), optimize=True)


def test_settingsapp():
    print("== System Settings opened on a page is one app in the Dock (kept tile, no second icon)", flush=True)
    s = new_session("dock-settingsapp", settings={"appearance": {"theme": "dark", "glass": 0.3}})
    try:
        s.start_shell()
        st = dock_state(s, lambda st: st["catalog"] > 0 and len(st["tiles"]) >= 9, 20)
        before = [t["key"] for t in st["tiles"] if t["kind"] == "app"]
        p = subprocess.Popen(["systemsettings", "kcm_kristall_energy"], env=s.app_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s.procs.append(p)
        wait_until(lambda: [w for w in s.windows() if w.get("normal") and "systemsettings" in (w.get("appId") or "")], 20, 0.3)
        time.sleep(2.0)
        wins = [(w.get("appId"), w.get("title"), w.get("type"), w.get("skipTaskbar"), w.get("normal")) for w in s.windows()]
        info("windows: " + json.dumps(wins))
        st = dock_state(s)
        keys = [t["key"] for t in st["tiles"] if t["kind"] == "app"]
        info("dock app keys: " + json.dumps(keys))
        settings_keys = [k for k in keys if "settings" in k.lower()]
        check("one System Settings tile while one System Settings window is open", len(settings_keys) == 1, json.dumps(settings_keys))
        t = next((t for t in st["tiles"] if t["key"] in settings_keys), None)
        check("…and it is the kept tile, shown as running", bool(t) and t.get("running") is True, json.dumps(t))
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------------
def test_autohide():
    print("== auto-hide", flush=True)
    s = new_session("dock-autohide")
    try:
        s.start_shell()
        dock_state(s, lambda st: st["catalog"] > 0, 20)
        settings_set(s, "dock.autoHide", True)
        st = dock_state(s, lambda st: st["autoHide"] and not st["revealed"], 5)
        check("auto-hide: hidden, reserves no space", bool(st) and st["exclusiveZone"] == 0, json.dumps(st and {k: st[k] for k in ("exclusiveZone", "revealed")}))
        time.sleep(0.6)
        img = s.screenshot()
        save(img, "dock-autohide-hidden-light-1.0x.png", crop=(0, s.height - 120, s.width, s.height))
        s.move(s.width / 2, s.height - 300)
        s.sweep([(s.width / 2, s.height - 300 + i * 30) for i in range(11)], 60)
        s.move(s.width / 2, s.height - 1)
        st = dock_state(s, lambda st: st["revealed"], 3)
        check("pointer at the bottom edge reveals the Dock", bool(st))
        time.sleep(0.5)
        s.move(s.width / 2, 200)
        st = dock_state(s, lambda st: not st["revealed"], 3)
        check("pointer leaves: the Dock hides again", bool(st))
        settings_set(s, "dock.autoHide", False)
        st = dock_state(s, lambda st: st["revealed"] and st["exclusiveZone"] == 66, 5)
        check("auto-hide off: shown, reserves its height again", bool(st))
    finally:
        s.stop()


def test_kwinconfig():
    print("== system-wide KWin configuration (merged kwinrc): minimise flows into the Dock", flush=True)
    import tempfile
    tmp = tempfile.mkdtemp(prefix="kristall-dock-kwin-")
    root = os.path.join(tmp, "sysconf")
    target = os.path.join(root, "etc", "xdg", "kwinrc")
    os.makedirs(os.path.dirname(target))
    with open(target, "w") as f:
        f.write("[Plugins]\nsomeOtherEffectEnabled=true\n[Windows]\nFocusPolicy=ClickToFocus\n")
    subprocess.run([sys.executable, os.path.join(A.DOCK, "..", "..", "image", "merge-ini"), target, os.path.join(A.DOCK, "kwin", "kwinrc")], check=True)
    subprocess.run([sys.executable, os.path.join(A.DOCK, "..", "..", "image", "merge-ini"), target, os.path.join(A.DOCK, "kwin", "kwinrc")], check=True)
    merged = open(target).read()
    check("merge keeps other components' keys and is idempotent", "someOtherEffectEnabled=true" in merged and "FocusPolicy=ClickToFocus" in merged
          and merged.count("magiclampEnabled=true") == 1, merged)
    s = A.AppsSession(name="dock-kwin", sysconf=root)
    # KWin loads no animation effects on a software renderer (llvmpipe) unless forced; on the
    # laptop's GPU it does. The harness also sets AnimationSpeed=0: undo both for this check.
    s.extra_env["KWIN_EFFECTS_FORCE_ANIMATIONS"] = "1"
    kr = os.path.join(s.config, "kwinrc")
    open(kr, "w").write(open(kr).read().replace("AnimationSpeed=0", "AnimationSpeed=3"))
    s.start()
    try:
        def loaded(name):
            r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Effects", "--method",
                                "org.kde.kwin.Effects.isEffectLoaded", name], env=s.env(), capture_output=True, text=True)
            info(f"isEffectLoaded {name}: {r.stdout.strip()} {r.stderr.strip()[:200]}")
            r2 = subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Effects", "--method",
                                 "org.freedesktop.DBus.Properties.Get", "org.kde.kwin.Effects", "loadedEffects"], env=s.env(), capture_output=True, text=True)
            info("loaded: " + r2.stdout.strip()[:600])
            return "true" in r.stdout
        time.sleep(2.0)
        check("KWin loads Magic Lamp (genie into the Dock) and not Squash", loaded("magiclamp") and not loaded("squash"),
              f"magiclamp {loaded('magiclamp')} squash {loaded('squash')}")
    finally:
        s.stop()


SECTIONS = {"static": test_static, "kwinconfig": test_kwinconfig, "behaviour": test_behaviour, "perf": test_perf, "looks": test_looks, "contrast": test_contrast, "settingsapp": test_settingsapp, "autohide": test_autohide}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SECTIONS)
    for name in wanted:
        try:
            SECTIONS[name]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    out = os.path.join(EVIDENCE, "results.json")
    os.makedirs(EVIDENCE, exist_ok=True)
    old = json.load(open(out)) if os.path.exists(out) else {}
    old.update(results)
    old["last_run"] = {"sections": wanted, "failures": failures, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    json.dump(old, open(out, "w"), indent=1)
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
