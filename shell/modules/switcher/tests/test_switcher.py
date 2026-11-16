#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""App switcher tests — KWin's own switcher with our layout and our system-wide configuration
(/etc/xdg/kwinrc and kglobalshortcutsrc fragments, the layout under /usr/share/kwin/tabbox, all
given to KWin through XDG_CONFIG_DIRS/XDG_DATA_DIRS like on the image). Real key sequences are
played through KWin's fake-input protocol: quick taps, hold-tab-tab-release, reverse with Shift,
quit and hide while held, same-app window cycling. Real apps: Kate, Konsole, Dolphin."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(SW), "dock", "tests", "support"))
import appsession as A  # noqa: E402
from PIL import Image  # noqa: E402
sys.path.insert(0, os.path.join(A.REPO, "kwin", "glass", "tests", "support"))
import pattern  # noqa: E402

EVIDENCE = os.path.join(SW, "tests", "evidence")
failures, results = [], {}
check, info = A.check_factory(failures, results)
wait_until = A.wait_until


def sysconf(tmp):
    root = os.path.join(tmp, "sysconf")
    os.makedirs(os.path.join(root, "etc", "xdg"))
    os.makedirs(os.path.join(root, "usr", "share", "kwin", "tabbox"))
    # the same merge the image build does (into empty files here)
    for name in ("kwinrc", "kglobalshortcutsrc"):
        subprocess.run([sys.executable, os.path.join(A.DOCK, "image", "merge-ini"), os.path.join(root, "etc", "xdg", name),
                        os.path.join(SW, "kwin", name)], check=True)
    shutil.copytree(os.path.join(SW, "kwin", "tabbox", "org.kristall.switcher"), os.path.join(root, "usr", "share", "kwin", "tabbox", "org.kristall.switcher"))
    return root


def active(s):
    for w in s.windows():
        if w["active"]:
            return w["appId"]
    return None


def open_app(s, args, app_id):
    p = subprocess.Popen(args, env=s.app_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s.procs.append(p)
    w = wait_until(lambda: s.app_windows(app_id), 20, 0.3)
    wait_until(lambda: active(s) == app_id, 5)
    time.sleep(0.4)
    return w[0] if w else None


def test_switcher():
    print("== app switcher (KWin TabBox + our layout), real key sequences", flush=True)
    tmp = tempfile.mkdtemp(prefix="kristall-switcher-")
    s = A.AppsSession(name="switcher", global_shortcuts=True, sysconf=sysconf(tmp))
    s.start()
    try:
        bg = os.path.join(s.tmp, "bg.png")
        Image.fromarray(pattern.busy(s.width, s.height)).save(bg)
        s.background(bg)
        s.start_shell()
        wait_until(lambda: "module switcher loaded" in s.shell_log(), 15)
        b = s.bridge_client()
        kate = open_app(s, ["kate", "-n"], "org.kde.kate")
        kons = open_app(s, ["konsole"], "org.kde.konsole")
        dol = open_app(s, ["dolphin", "--new-window"], "org.kde.dolphin")
        for i, w in enumerate((kate, kons, dol)):
            b.call("window.setGeometry", id=w["id"], x=80 + 160 * i, y=80 + 60 * i, w=700, h=480)
        time.sleep(1.0)
        check("three apps open, Dolphin in front (most recent: Dolphin, Konsole, Kate)", active(s) == "org.kde.dolphin", active(s))
        # quick tap: switches to the previous app without showing anything
        s.key("leftmeta", True)
        s.tap("tab")
        s.key("leftmeta", False)
        ok = wait_until(lambda: active(s) == "org.kde.konsole", 3)
        check("quick Meta+Tab tap (shortcut from our system-wide kglobalshortcutsrc) → previous app (Konsole)", bool(ok), active(s))
        time.sleep(0.5)
        # hold, Tab, Tab, release → the third app (MRU now: Konsole, Dolphin, Kate)
        s.key("leftmeta", True)
        s.tap("tab")
        time.sleep(0.25)
        s.tap("tab")
        time.sleep(0.6)
        img = s.screenshot()
        save = os.path.join(EVIDENCE, "switcher-held-light-1.0x.png")
        os.makedirs(EVIDENCE, exist_ok=True)
        Image.fromarray(img).crop((240, 220, 1040, 580)).save(save, optimize=True)
        check("still holding: no switch yet", active(s) in ("org.kde.konsole", None), active(s))
        s.key("leftmeta", False)
        ok = wait_until(lambda: active(s) == "org.kde.kate", 3)
        check("hold Meta, Tab, Tab, release → Kate", bool(ok), active(s))
        time.sleep(0.5)
        # reverse with Shift while held: Meta+Tab (→ Konsole), Shift+Tab (→ back to the first) … ; MRU: Kate, Konsole, Dolphin
        s.key("leftmeta", True)
        s.tap("tab")
        time.sleep(0.2)
        s.tap("tab")
        time.sleep(0.2)
        s.tap("leftshift", "tab")
        time.sleep(0.3)
        s.key("leftmeta", False)
        ok = wait_until(lambda: active(s) == "org.kde.konsole", 3)
        check("Shift reverses while held: Tab, Tab, Shift+Tab → Konsole", bool(ok), active(s))
        time.sleep(0.5)
        # Q while held quits the highlighted app (MRU: Konsole, Kate, Dolphin → Tab highlights Kate)
        s.key("leftmeta", True)
        s.tap("tab")
        time.sleep(0.4)
        s.tap("q")
        ok = wait_until(lambda: not s.app_windows("org.kde.kate"), 6)
        time.sleep(0.3)
        s.key("leftmeta", False)
        check("Q while held quits the highlighted app (Kate)", bool(ok), json.dumps([w["appId"] for w in s.windows() if w["normal"]]))
        time.sleep(0.6)
        # H while held hides the highlighted app
        s.key("leftmeta", True)
        s.tap("tab")
        time.sleep(0.4)
        target = [w for w in s.windows() if w["normal"] and not w["active"] and w["appId"] in ("org.kde.konsole", "org.kde.dolphin")]
        s.tap("h")
        time.sleep(0.4)
        s.key("leftmeta", False)
        ok = wait_until(lambda: any(w["minimized"] for w in s.windows() if target and w["appId"] == target[0]["appId"]), 4)
        check("H while held hides the highlighted app", bool(ok))
        # same-app window cycling: two Dolphin windows, Meta+` switches between them
        for w in s.windows():
            if w["minimized"]:
                b.call("window.activate", id=w["id"])
        dol2 = subprocess.Popen(["dolphin", "--new-window"], env=s.app_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s.procs.append(dol2)
        wait_until(lambda: len(s.app_windows("org.kde.dolphin")) == 2, 15)
        time.sleep(1.0)
        before = next((w["id"] for w in s.windows() if w["active"]), None)
        s.key("leftmeta", True)
        s.tap("grave")
        s.key("leftmeta", False)
        ok = wait_until(lambda: (lambda a: a and a["appId"] == "org.kde.dolphin" and a["id"] != before)(next((w for w in s.windows() if w["active"]), None)), 3)
        check("Meta+` cycles the front app's windows", bool(ok))
        bad = [l for l in s.log_text().splitlines() if "org.kristall.switcher" in l or ("main.qml" in l and "tabbox" in l.lower())]
        check("our layout loads in KWin without QML errors", not bad, "\n".join(bad[:6]))
    finally:
        s.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def test_dark():
    print("== switcher in the dark theme (Plasma colour scheme dark)", flush=True)
    tmp = tempfile.mkdtemp(prefix="kristall-switcher-")
    s = A.AppsSession(name="switcher-dark", global_shortcuts=True, sysconf=sysconf(tmp), settings={"appearance": {"theme": "dark", "glass": 0.3}})
    with open(os.path.join(s.config, "kdeglobals"), "w") as f:
        for g in ("Window", "View", "Button", "Tooltip"):
            f.write(f"[Colors:{g}]\nBackgroundNormal=32,33,36\nForegroundNormal=242,242,247\n\n")
    s.start()
    try:
        bg = os.path.join(s.tmp, "bg.png")
        Image.fromarray(pattern.busy(s.width, s.height)).save(bg)
        s.background(bg)
        s.start_shell()
        for args, app in ((["kate", "-n"], "org.kde.kate"), (["konsole"], "org.kde.konsole"), (["dolphin", "--new-window"], "org.kde.dolphin")):
            open_app(s, args, app)
        s.key("leftmeta", True)
        s.tap("tab")
        time.sleep(0.6)
        Image.fromarray(s.screenshot()).crop((240, 220, 1040, 580)).save(os.path.join(EVIDENCE, "switcher-held-dark-1.0x.png"), optimize=True)
        s.key("leftmeta", False)
        ok = wait_until(lambda: active(s) == "org.kde.konsole", 3)
        check("dark: switcher works the same", bool(ok))
    finally:
        s.stop()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        test_switcher()
        test_dark()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        check("switcher test ran to the end", False, repr(e))
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
