#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apps grid tests — run inside the dev container under dbus-run-session (run.sh).
Sections: behaviour looks. Real pointer and keys (fake input), real bridge, real Kate."""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(APPS), "dock", "tests", "support"))
import appsession as A  # noqa: E402
from PIL import Image  # noqa: E402
sys.path.insert(0, os.path.join(A.REPO, "kwin", "glass", "tests", "support"))
import pattern  # noqa: E402

EVIDENCE = os.path.join(APPS, "tests", "evidence")
failures, results = [], {}
check, info = A.check_factory(failures, results)
wait_until = A.wait_until
FAKE = [("org.mozilla.firefox", "Firefox", "internet-web-browser", "Network;WebBrowser;"), ("org.kde.elisa", "Elisa", "org.kde.elisa", "AudioVideo;Audio;"),
        ("org.blender.Blender", "Blender", "org.kde.kolourpaint", "Graphics;3DGraphics;"), ("com.valvesoftware.Steam", "Steam", "org.kde.kpat", "Game;"),
        ("org.kde.okular", "Okular", "okular", "Office;"), ("org.kde.kcalc", "KCalc", "kcalc", "Utility;"), ("org.kde.gwenview", "Gwenview", "gwenview", "Graphics;")]


def save(img, name, crop=None):
    im = Image.fromarray(img)
    if crop:
        im = im.crop(crop)
    os.makedirs(EVIDENCE, exist_ok=True)
    # full-screen shots as JPEG (the evidence of all four modules stays under 5 MB)
    im.convert("RGB").save(os.path.join(EVIDENCE, name.replace(".png", ".jpg")), quality=82, optimize=True)


def state(s):
    return json.loads(s.ipc("appstest", "state"))


def wait_state(s, pred, timeout=5.0):
    last = [None]

    def f():
        try:
            st = state(s)
        except Exception:
            return None
        last[0] = st
        return st if pred(st) else None
    return wait_until(f, timeout, 0.15) or last[0]


def session(name, settings=None, shortcuts=False, **kw):
    tmp = tempfile.mkdtemp(prefix="kristall-apps-")
    root = os.path.join(tmp, "sysconf")
    os.makedirs(os.path.join(root, "usr", "share", "kglobalaccel"))
    shutil.copy(os.path.join(APPS, "kglobalaccel", "org.kristall.apps.desktop"), os.path.join(root, "usr", "share", "kglobalaccel"))
    s = A.AppsSession(name=name, settings=settings, global_shortcuts=shortcuts, sysconf=root, **kw)
    for did, n, icon, cats in FAKE:
        s.desktop(did, n, icon, extra=f"Categories={cats}\n")
    # "Deinstallieren" hands off to appstream://: a stub store here. The dev container's real handler
    # is Firefox, whose window appeared a moment later and took the keyboard (the next ↩ went to it)
    s.desktop("kristall-test-appstore", "Test app store", extra="NoDisplay=true\nMimeType=x-scheme-handler/appstream;\n")
    os.makedirs(s.config, exist_ok=True)
    with open(os.path.join(s.config, "mimeapps.list"), "a") as f:
        f.write("[Default Applications]\nx-scheme-handler/appstream=kristall-test-appstore.desktop\n")
    s.start()
    bg = os.path.join(s.tmp, "bg.png")
    Image.fromarray(pattern.busy(s.width, s.height)).save(bg)
    s.background(bg)
    s.start_shell()
    wait_until(lambda: "module apps loaded" in s.shell_log(), 15)
    return s


def warnings(s):
    return [l for l in s.shell_log().splitlines() if ("WARN" in l or "ERROR" in l)
            and not any(k in l for k in ("pipewire", "quickshell.network", "upower", "powerprofiles", "bluetooth"))]


def test_behaviour():
    print("== behaviour", flush=True)
    s = session("apps", shortcuts=True)
    try:
        time.sleep(2)
        s.tap("leftmeta", "a")
        st = wait_state(s, lambda st: st["open"], 5)
        if not (st and st["open"]):         # kglobalaccel may still be reading its files
            time.sleep(2)
            s.tap("leftmeta", "a")
            st = wait_state(s, lambda st: st["open"], 5)
        check("Meta+A opens Apps (system-wide kglobalaccel file)", bool(st and st["open"]))
        st = wait_state(s, lambda st: len(st["shown"]) >= 10, 5)
        keys = [x["key"] for x in st["shown"]]
        check("grid: every visible desktop entry, manifest names (Dateien, Systemeinstellungen, Terminal)",
              all(k in keys for k in ("org.kde.dolphin", "systemsettings", "org.kde.konsole", "org.mozilla.firefox"))
              and any(x["name"] == "Dateien" for x in st["shown"]) and any(x["name"] == "Terminal" for x in st["shown"]), json.dumps([x["name"] for x in st["shown"]], ensure_ascii=False))
        check("manifest apps marked show_in_apps:false stay hidden (Ark)", "org.kde.ark" not in keys)
        check("categories offered", st["categories"][0] == "all" and "games" in st["categories"] and "media" in st["categories"], json.dumps(st["categories"]))
        time.sleep(0.8)
        save(s.screenshot(), "apps-grid-light-1.0x.png")
        # live install / remove (no restart)
        s.desktop("io.github.example.Neu", "Neue App", "org.kde.kget", extra="Categories=Utility;\nExec=flatpak run --branch=stable --arch=x86_64 io.github.example.Neu\n")
        st = wait_state(s, lambda st: any(x["key"] == "io.github.example.Neu" for x in st["shown"]), 8)
        check("a newly installed app appears while Apps is open", bool(st) and any(x["key"] == "io.github.example.Neu" for x in st["shown"]))
        neu = [x for x in st["shown"] if x["key"] == "io.github.example.Neu"]
        check("Flatpak apps are recognised (uninstall is offered for them)", bool(neu) and neu[0]["flatpak"] == "io.github.example.Neu", json.dumps(neu))
        s.ipc("appstest", "openMenu", "io.github.example.Neu")
        time.sleep(0.6)
        menu = json.loads(s.ipc("test", "state", ""))
        its = menu["levels"][0]["items"] if menu.get("levels") else []
        check("context menu: Öffnen, Im Dock behalten, Deinstallieren …", its[:2] == ["Öffnen", "Im Dock behalten"] and its[-1].startswith("Deinstallieren"),
              json.dumps(its, ensure_ascii=False))
        save(s.screenshot(), "apps-context-menu-light-1.0x.png")
        s.move(5, 400)
        for _ in range(3):
            s.tap("down")
        s.tap("return")
        st = wait_state(s, lambda st: not st["open"], 3)
        check("Deinstallieren hands off to the app store (appstream://<flatpak id>), no package work here",
              bool(st) and st["lastHandOff"] == "appstream://io.github.example.Neu", st and st["lastHandOff"])
        s.ipc("shell", "request", "apps", "toggle", "x", "")
        wait_state(s, lambda st: st["open"], 3)
        s.ipc("appstest", "setCategory", "games")
        st = wait_state(s, lambda st: st["category"] == "games", 3)
        check("a category shows only its apps", [x["key"] for x in st["shown"]] == ["com.valvesoftware.Steam"], json.dumps([x["key"] for x in st["shown"]]))
        s.ipc("appstest", "setCategory", "all")
        os.remove(os.path.join(s.apps_dir, "io.github.example.Neu.desktop"))
        st = wait_state(s, lambda st: not any(x["key"] == "io.github.example.Neu" for x in st["shown"]), 8)
        check("an uninstalled app disappears without a restart", bool(st) and not any(x["key"] == "io.github.example.Neu" for x in st["shown"]))
        # typing filters; arrows + return open
        for ch in "kate":
            s.tap(ch)
        st = wait_state(s, lambda st: st["filter"] == "kate", 3)
        check("typing filters the grid (search)", bool(st) and st["shown"] and st["shown"][0]["key"] == "org.kde.kate", json.dumps([x["key"] for x in st["shown"]][:4]))
        s.tap("return")
        ok = wait_until(lambda: s.app_windows("org.kde.kate"), 15)
        st = wait_state(s, lambda st: not st["open"], 3)
        check("↩ opens the selected app and closes Apps", bool(ok) and bool(st) and st["lastLaunched"] == "org.kde.kate")
        # the Dock's Apps tile opens it; ⎋ closes
        d = json.loads(s.ipc("docktest", "state"))
        t = next(x for x in d["tiles"] if x["id"] == "apps")
        s.click(t["x"] + t["w"] / 2, t["y"] + t["w"] / 2)
        st = wait_state(s, lambda st: st["open"], 4)
        check("the Dock's Apps tile opens Apps", bool(st and st["open"]))
        time.sleep(0.5)
        s.tap("esc")
        st = wait_state(s, lambda st: not st["open"], 3)
        check("⎋ closes Apps", bool(st) and not st["open"])
        bad = warnings(s)
        check("zero QML warnings", not bad, "\n".join(bad[:8]))
    finally:
        s.stop()


def test_looks():
    print("== looks", flush=True)
    for name, settings, w, h, sc in (("dark-1.0x", {"appearance": {"theme": "dark", "glass": 0.3}}, 1280, 800, 1.0),
                                     ("light-1.6x", {"appearance": {"theme": "light", "glass": 0.3}}, 1800, 1125, 1.6)):
        s = session("apps-" + name, settings=settings, width=w, height=h, scale=sc)
        try:
            time.sleep(1.5)
            s.ipc("shell", "request", "apps", "toggle", "x", "")
            wait_state(s, lambda st: st["open"] and st["shown"], 5)
            time.sleep(1.0)
            img = s.screenshot()
            if sc != 1.0:
                save(img, f"apps-grid-{name}.png", crop=(int(100 * sc), int(60 * sc), int((w - 100) * sc), int((h - 60) * sc)))
            else:
                save(img, f"apps-grid-{name}.png")
            bad = warnings(s)
            check(f"{name}: zero QML warnings", not bad, "\n".join(bad[:6]))
        finally:
            s.stop()


SECTIONS = {"behaviour": test_behaviour, "looks": test_looks}
if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SECTIONS)
    for name in wanted:
        try:
            SECTIONS[name]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
