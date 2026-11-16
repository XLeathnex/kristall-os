#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Kristall shell tests (run inside the dev container under dbus-run-session; see run.sh).

Sections (argv selects; default all): static core appmenu scale fallback modules restart plasma gallery
Each check prints PASS/FAIL/INFO lines; the exit status is non-zero if anything failed.
Screenshots go to tests/evidence/.
"""
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import shellsession as ss  # noqa: E402
import appmenu_probe  # noqa: E402
import pattern  # noqa: E402  (kwin/glass/tests/support)
from PIL import Image  # noqa: E402
import numpy as np  # noqa: E402

SHELL = ss.SHELL
REPO = ss.REPO
BUILD = os.environ.get("KRISTALL_SHELL_BUILD", "/tmp/kristall-shell-build")
MENUAPP = os.path.join(BUILD, "menuapp")
failures = []
results = {}


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(name)
    return ok


def info(msg):
    print("INFO " + msg, flush=True)


# Lines from Quickshell's own C++ services when the *system* service is absent are expected in
# sessions without the mocks; with mocks the log must be completely clean.
def shell_warnings(sess):
    return [l for l in ss.warnings_in(sess.shell_log())]


def wait_state(sess, pred, timeout=8.0):
    last = [None]

    def f():
        try:
            st = sess.state()
        except Exception:
            return None
        last[0] = st
        return st if pred(st) else None
    st = ss.wait_until(f, timeout, 0.25)
    return st or last[0]


def busy_bg(sess, w, h):
    bg = os.path.join(sess.tmp, "bg.png")
    Image.fromarray(pattern.busy(w, h)).save(bg)
    sess.background(bg)


def settings_set(sess, path, value):
    env = sess.env()
    env.update(sess.shell_env())
    subprocess.run(["kristall-settings", "set", path, json.dumps(value)], env=env, check=True)


def proc_stats(pids):
    """(cpu ticks, context switches) summed over the processes and their threads"""
    ticks = switches = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                parts = f.read().rsplit(")", 1)[1].split()
            ticks += int(parts[11]) + int(parts[12])
            for t in os.listdir(f"/proc/{pid}/task"):
                with open(f"/proc/{pid}/task/{t}/status") as f:
                    for line in f:
                        if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
                            switches += int(line.split()[1])
        except (OSError, IndexError):
            pass
    return ticks, switches


def children_of(pid):
    out = [pid]
    try:
        for line in subprocess.run(["ps", "-o", "pid=", "--ppid", str(pid)], capture_output=True, text=True).stdout.split():
            out += children_of(int(line))
    except ValueError:
        pass
    return out


def glass_frames(sess):
    try:
        c = sess.connect()
        st = c.status()
        c.close()
        return st.get("frames") if st else None
    except OSError:
        return None


def measure_idle(sess, seconds=5.0, label="idle"):
    # the clock legitimately repaints once a minute: keep the window clear of a minute boundary
    while not 2 <= time.localtime().tm_sec <= 60 - seconds - 3:
        time.sleep(0.5)
    pids = children_of(sess.shell.pid)
    f0 = glass_frames(sess)
    t0, s0 = proc_stats(pids)
    time.sleep(seconds)
    f1 = glass_frames(sess)
    t1, s1 = proc_stats(pids)
    frames = None if f0 is None or f1 is None else f1 - f0
    hz = os.sysconf("SC_CLK_TCK")
    r = {"seconds": seconds, "frames": frames, "cpu_ms": (t1 - t0) * 1000.0 / hz, "wakeups": s1 - s0, "processes": len(pids)}
    results[label] = r
    return r


# ---------------------------------------------------------------------------------------------------
def test_static():
    print("== static", flush=True)
    r = subprocess.run([sys.executable, "-m", "py_compile", os.path.join(SHELL, "helper", "kristall-shell-helper")], capture_output=True, text=True)
    check("helper compiles", r.returncode == 0, r.stderr.strip())
    for f in ("mockbridge.py", "mocksystem.py", "shellsession.py", "registrar.py", "appmenu_probe.py"):
        r = subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "support", f)], capture_output=True, text=True)
        check(f"{f} compiles", r.returncode == 0, r.stderr.strip())
    if shutil.which("shellcheck"):
        files = [os.path.join(SHELL, p) for p in ("image/install.sh", "bin/kristall-shell", "bin/kristall-shellctl",
                                                   "bin/kristall-shell-fallback", "tests/run.sh")]
        r = subprocess.run(["shellcheck", "-S", "warning"] + files, capture_output=True, text=True)
        check("shellcheck", r.returncode == 0, r.stdout[-800:])
    strings = json.load(open(os.path.join(SHELL, "strings", "strings.json")))
    check("strings: German and English have the same keys", set(strings["de"]) == set(strings["en"]),
          str(set(strings["de"]) ^ set(strings["en"])))
    # every Strings.t("…") key used in our QML exists
    import re
    used = set()
    for root, _, files in os.walk(SHELL):
        if "/tests" in root or "/.scratch" in root or "/modules" in root:
            continue
        for f in files:
            if f.endswith(".qml"):
                used |= set(re.findall(r'Strings\.tn?\("([a-zA-Z0-9_.]+)"', open(os.path.join(root, f), encoding="utf-8").read()))
    missing = sorted(k for k in used if k not in strings["en"] and not k.endswith("."))
    check("strings: every key used in QML exists", not missing, ", ".join(missing))
    # settings defaults: only our top-level keys, and the QML fallbacks equal the shipped defaults
    d = json.load(open(os.path.join(SHELL, "image", "settings.json")))
    check("settings defaults own only appearance/accessibility/bar", set(d) == {"appearance", "accessibility", "bar"}, str(set(d)))
    qml = open(os.path.join(SHELL, "services", "Settings.qml")).read()
    ok = all(f"{k}: {json.dumps(v)}" in qml.replace("\n", " ").replace("  ", " ") or f"{k}: {json.dumps(v).lower()}" in qml
             for sect in d.values() for k, v in sect.items())
    check("Settings.qml fallbacks mention every default", ok)
    env = dict(os.environ, KRISTALL_SETTINGS_DROPIN_DIRS=os.path.join(SHELL, "image"))
    # kristall-settings check-defaults wants NN-name.json files: validate through a temp dir
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(SHELL, "image", "settings.json"), os.path.join(tmp, "50-shell.json"))
    env["KRISTALL_SETTINGS_DROPIN_DIRS"] = tmp
    r = subprocess.run([os.path.join(REPO, "image", "rootfs", "usr", "bin", "kristall-settings"), "check-defaults"], env=env, capture_output=True, text=True)
    check("kristall-settings check-defaults accepts our drop-in", r.returncode == 0, (r.stdout + r.stderr)[-400:])
    # singleton files must not have braces in comments before `pragma Singleton` (Quickshell 0.2.1
    # then fails to register them as singletons — see shell.md §9)
    bad = []
    for root, _, files in os.walk(SHELL):
        for f in files:
            if f.endswith(".qml"):
                t = open(os.path.join(root, f), encoding="utf-8").read()
                if "pragma Singleton" in t and any(c in t[:t.index("pragma Singleton")] for c in "{}"):
                    bad.append(f)
    check("no braces before 'pragma Singleton'", not bad, ", ".join(bad))
    # unit files
    install = "/usr/libexec/kristall"
    os.makedirs(install, exist_ok=True)
    for b in ("kristall-shell", "kristall-shell-fallback"):
        shutil.copy(os.path.join(SHELL, "bin", b), install)
    r = subprocess.run(["systemd-analyze", "verify", "--man=no", os.path.join(SHELL, "systemd", "kristall-shell.service"),
                        os.path.join(SHELL, "systemd", "kristall-shell-fallback.service")], capture_output=True, text=True)
    errs = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and "graphical-session.target" not in l]
    check("systemd-analyze verify (user units; graphical-session.target absent in the container)", not errs, "; ".join(errs))
    # launcher crash ladder with a stand-in quickshell that prints its environment
    fake = tempfile.mkdtemp()
    with open(os.path.join(fake, "quickshell"), "w") as f:
        f.write("#!/bin/sh\necho \"SAFE=${KRISTALL_SHELL_SAFE:-0} ARGS=$*\"\n")
    os.chmod(os.path.join(fake, "quickshell"), 0o755)
    rt = tempfile.mkdtemp()
    env = dict(os.environ, PATH=fake + ":" + os.environ["PATH"], XDG_RUNTIME_DIR=rt)
    outs = [subprocess.run([os.path.join(SHELL, "bin", "kristall-shell")], env=env, capture_output=True, text=True).stdout.strip() for _ in range(4)]
    check("launcher: normal starts, then safe mode after 3 starts within 60 s",
          outs[0].startswith("SAFE=0") and outs[2].startswith("SAFE=0") and outs[3].startswith("SAFE=1") and "--no-duplicate" in outs[0], " | ".join(outs))


# ---------------------------------------------------------------------------------------------------
def test_core():
    print("== core: services, bar, menus, idle", flush=True)
    W, H = 1280, 800
    sess = ss.ShellSession(width=W, height=H, name="core", settings={"appearance": {"theme": "light", "glass": 0.3}})
    sess.start()
    try:
        sess.start_system()
        sess.start_audio()
        busy_bg(sess, W, H)
        sess.start_shell()
        sess.wait_ready()
        st = wait_state(sess, lambda s: s["bar"]["glassDrawn"] and s["audio"]["available"] and s["network"]["bars"] == 3 and s["power"]["battery"], 15)
        time.sleep(1.0)
        warns = shell_warnings(sess)
        check("shell starts with zero warnings (system services mocked)", not warns, "\n".join(warns[:10]))
        check("bar: glass bound and drawn", st["bar"]["glassDrawn"] and st["glass"] == "active", json.dumps(st["bar"]))
        check("shell subscribes to the bridge's 'menus' topic", sess.ctl({"cmd": "state"}).get("menuClients") == 1)
        check("locale: German strings and Mac clock format", st["lang"] == "de" and "." in st["clock"].split(" ")[0], st["clock"])
        check("battery from UPower", st["power"]["battery"] and st["power"]["percent"] == 76, json.dumps(st["power"]))
        check("audio from PipeWire", st["audio"]["available"], json.dumps(st["audio"]))
        check("Wi-Fi from NetworkManager", st["network"]["wifi"] and st["network"]["name"] == "Zuhause" and st["network"]["bars"] == 3, json.dumps(st["network"]))
        info("bluetooth: " + json.dumps(st["bluetooth"]))

        # ---- every service reacts to change (pushed, not polled)
        sess.mock("SetBattery", "dub", 18.0, 1, False)
        s2 = wait_state(sess, lambda s: s["power"]["percent"] == 18 and not s["power"]["onBattery"])
        check("battery change is pushed", s2["power"]["percent"] == 18 and not s2["power"]["onBattery"], json.dumps(s2["power"]))
        subprocess.run(["gdbus", "call", "--address", sess.system_address, "--dest", "org.freedesktop.UPower.PowerProfiles",
                        "--object-path", "/org/freedesktop/UPower/PowerProfiles", "--method", "org.freedesktop.DBus.Properties.Set",
                        "org.freedesktop.UPower.PowerProfiles", "ActiveProfile", "<'power-saver'>"], capture_output=True)
        s2 = wait_state(sess, lambda s: s["power"]["mode"] == "quiet")
        check("power mode follows the power-profiles API (power-saver = Leise)", s2["power"]["mode"] == "quiet", s2["power"]["mode"])
        sess.wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", "0.30")
        s2 = wait_state(sess, lambda s: abs(s["audio"]["volume"] - 0.30) < 0.02)
        check("volume change is pushed", abs(s2["audio"]["volume"] - 0.30) < 0.02, json.dumps(s2["audio"]))
        sess.wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", "1")
        s2 = wait_state(sess, lambda s: s["audio"]["muted"])
        check("mute is pushed", s2["audio"]["muted"])
        sess.wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", "0")
        sess.mock("SetWifiStrength", "y", 30)
        s2 = wait_state(sess, lambda s: s["network"]["bars"] == 1)
        check("Wi-Fi strength is pushed", s2["network"]["bars"] == 1, json.dumps(s2["network"]))
        sess.mock("SetWifiStrength", "y", 78)
        settings_set(sess, "appearance.accent", "purple")
        s2 = wait_state(sess, lambda s: s["accent"].lower() == "#af52de")
        check("settings change is applied live (accent)", s2["accent"].lower() == "#af52de", s2["accent"])
        settings_set(sess, "appearance.accent", "blue")
        with open(os.path.join(sess.update_dir, "status.json"), "w") as f:
            json.dump({"schema": 1, "state": "restart-required", "staged": {"version": "45.20261116.1"}}, f)
        s2 = wait_state(sess, lambda s: s["update"] == "restart-required")
        check("update status follows state.json (inotify)", s2["update"] == "restart-required", s2["update"])

        # ---- the mark menu
        sess.ipc("test", "openMenu", 0, "")
        s2 = wait_state(sess, lambda s: s["menu"] and s["levels"])
        items = s2["levels"][0]["items"] if s2["levels"] else []
        expected = ["Über diesen Computer", "Systemeinstellungen …", "App-Center …", "Neu starten, um zu aktualisieren …",
                    "Ruhezustand", "Neustart …", "Ausschalten …", "Bildschirm sperren"]
        check("mark menu: entries, German, restart-to-update while staged",
              all(any(i.startswith(e) for i in items) for e in expected) and any("abmelden" in i for i in items), json.dumps(items, ensure_ascii=False))
        busy_crop = (0, 0, 760, 340)
        sess.save(sess.screenshot(), "bar-mark-menu-light-1.0x.png", crop=busy_crop)
        sess.ipc("test", "key", "escape", "")
        with open(os.path.join(sess.update_dir, "status.json"), "w") as f:
            json.dump({"schema": 1, "state": "up-to-date"}, f)

        # ---- windows: front app, dimmed bar while maximised
        sess.ctl({"cmd": "open", "window": {"id": "w1", "appId": "org.kde.dolphin", "title": "Dokumente", "x": 200, "y": 120, "w": 700, "h": 500}})
        s2 = wait_state(sess, lambda s: s["bar"]["appName"] == "Dateien")
        check("front app name from the manifest (org.kde.dolphin = Dateien)", s2["bar"]["appName"] == "Dateien", s2["bar"]["appName"])
        sess.ctl({"cmd": "activate", "id": None})   # what KWin reports while our menu has keyboard focus
        time.sleep(0.5)
        check("front app survives 'no active window' (keyboard focus on a shell surface)", sess.state()["bar"]["appName"] == "Dateien")
        sess.ctl({"cmd": "activate", "id": "w1"})
        check("minimal menus for an app without exported menus (Ablage, Fenster)",
              "Ablage" in s2["bar"]["titles"] and "Fenster" in s2["bar"]["titles"], json.dumps(s2["bar"]["titles"], ensure_ascii=False))
        sess.ctl({"cmd": "set", "id": "w1", "changes": {"maximized": True, "x": 0, "y": 24, "w": W, "h": H - 24}})
        s2 = wait_state(sess, lambda s: s["bar"]["dimmed"])
        check("bar dims (solid) while the front window is maximised", s2["bar"]["dimmed"])
        time.sleep(1.0)
        # window menu acts through the bridge
        rects = sess.rects()
        idx = [r["text"] for r in rects].index("Fenster")
        sess.ipc("test", "openMenu", idx, "")
        s2 = wait_state(sess, lambda s: s["levels"])
        items = s2["levels"][0]["items"]
        zoom = [i for i, t in enumerate(items) if t.startswith("Zoomen")]
        sess.ctl({"cmd": "calls"})
        for _ in range(zoom[0] if zoom else 0):
            sess.ipc("test", "key", "down", "")
        sess.ipc("test", "key", "return", "")
        time.sleep(0.6)
        calls = sess.ctl({"cmd": "calls"})
        check("Window ▸ Zoom calls window.setMaximized through the bridge",
              any(c["method"] == "window.setMaximized" and c["params"].get("value") is False for c in calls), json.dumps(calls)[:300])
        s2 = wait_state(sess, lambda s: not s["bar"]["dimmed"])
        check("bar returns to glass when the window is no longer maximised", not s2["bar"]["dimmed"])
        sess.ctl({"cmd": "close", "id": "w1"})

        # ---- idle is idle
        sess.ipc("test", "close")
        time.sleep(1.5)
        r = measure_idle(sess, 5.0, "idle_bar")
        check("idle: no frames presented in 5 s with nothing happening", r["frames"] == 0, json.dumps(r))
        check("idle: shell + helper wake up < 2/s and use < 20 ms CPU in 5 s", r["wakeups"] < 10 and r["cpu_ms"] < 20, json.dumps(r))
        sess.ipc("test", "openMenu", 0, "")
        time.sleep(0.8)
        sess.ipc("test", "close")
        time.sleep(1.0)
        r = measure_idle(sess, 4.0, "idle_after_menu")
        check("idle again after a menu opened and closed", r["frames"] == 0 and r["wakeups"] < 10, json.dumps(r))

        # ---- themes / slider screenshots
        for theme, glass, name in (("light", 0.0, "light-clear"), ("light", 1.0, "light-tinted"), ("dark", 0.0, "dark-clear"), ("dark", 1.0, "dark-tinted")):
            sess.write_settings({"appearance": {"theme": theme, "glass": glass}})
            wait_state(sess, lambda s: s["theme"] == theme and abs(s["glassLevel"] - glass) < 0.01)
            time.sleep(1.5)
            sess.save(sess.screenshot(), f"bar-{name}-1.0x.png", crop=(0, 0, W, 40))
        sess.ipc("test", "openMenu", 1, "")
        time.sleep(1.0)
        sess.save(sess.screenshot(), "bar-app-menu-dark-1.0x.png", crop=busy_crop)
        sess.ipc("test", "close")
        st = sess.state()
        check("dark theme reaches the bar", st["theme"] == "dark")
        warns = shell_warnings(sess)
        check("still zero warnings after the whole core run", not warns, "\n".join(warns[:10]))
    finally:
        sess.stop()


# ---------------------------------------------------------------------------------------------------
def test_appmenu():
    print("== app menus (real Qt app over DBusMenu) and tray (real StatusNotifierItem)", flush=True)
    if not os.path.exists(MENUAPP):
        check("menuapp built", False, MENUAPP)
        return
    W, H = 1280, 800
    sess = ss.ShellSession(width=W, height=H, name="appmenu")
    sess.start()
    app = None
    try:
        busy_bg(sess, W, H)
        sess.start_shell()
        sess.wait_ready()
        env = sess.env()
        env.update({"QT_QPA_PLATFORM": "wayland", "QT_QPA_PLATFORMTHEME": "", "XDG_CURRENT_DESKTOP": ""})
        reg = subprocess.Popen([sys.executable, os.path.join(HERE, "support", "registrar.py")], stdout=subprocess.PIPE, text=True, env=env)
        reg.stdout.readline()
        app = subprocess.Popen([MENUAPP, "--tray"], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        service, path = appmenu_probe.find_menu(app.pid, env)
        check("Qt app exports its menu bar over DBusMenu", bool(service), f"{service} {path}")
        sess.ctl({"cmd": "open", "window": {"id": "q1", "appId": "org.kristall.MenuApp", "title": "Menu App", "pid": app.pid,
                                            "x": 560, "y": 300, "w": 600, "h": 400, "menu": {"service": service, "path": path}}})
        st = wait_state(sess, lambda s: "Darstellung" in s["bar"]["titles"])
        check("bar shows the app's own menus", all(t in st["bar"]["titles"] for t in ("Datei", "Bearbeiten", "Darstellung", "Hilfe")),
              json.dumps(st["bar"]["titles"], ensure_ascii=False))
        time.sleep(0.5)
        rects = sess.rects()
        texts = [r["text"] for r in rects]
        sess.ipc("test", "openMenu", texts.index("Datei"), "")
        st = wait_state(sess, lambda s: s["levels"] and any("Neu" in i for i in s["levels"][0]["items"]))
        items = st["levels"][0]["items"]
        check("app menu items: labels, shortcuts, disabled, submenu, separators",
              any(i.startswith("Neu {") for i in items) and any("Sichern [disabled]" in i for i in items)
              and any(i.startswith("Zuletzt geöffnet") and i.endswith(">") for i in items) and "-separator" in items, json.dumps(items, ensure_ascii=False))
        for k in ("down", "down", "right"):
            sess.ipc("test", "key", k, "")
        st = wait_state(sess, lambda s: len(s["levels"]) == 2)
        check("keyboard: → opens the submenu", len(st["levels"]) == 2 and st["levels"][1]["items"] == ["Brief.txt", "Notizen.md"], json.dumps(st["levels"][-1:], ensure_ascii=False))
        time.sleep(0.4)
        sess.save(sess.screenshot(), "appmenu-submenu-light-1.0x.png", crop=(0, 0, 760, 340))
        sess.ipc("test", "key", "return", "")
        r, _, _ = select.select([app.stdout], [], [], 4)
        said = app.stdout.readline().strip() if r else ""
        while said.startswith(("NATIVE", "TRAY")):
            r, _, _ = select.select([app.stdout], [], [], 4)
            said = app.stdout.readline().strip() if r else ""
        check("activating a menu item runs the app's action", said == "TRIGGERED Brief.txt", said)
        # checkable + radio items, ← → across menus
        sess.ipc("test", "openMenu", texts.index("Datei"), "")
        sess.ipc("test", "key", "right", "")
        sess.ipc("test", "key", "right", "")
        st = wait_state(sess, lambda s: s["levels"] and any("Statusleiste" in i for i in s["levels"][0]["items"]))
        items = st["levels"][0]["items"]
        check("→ moves across menu titles; check marks and radio groups",
              "Statusleiste [x]" in items and "Mittel [x]" in items and "Klein" in items, json.dumps(items, ensure_ascii=False))
        sess.ipc("test", "close")
        # press on a title, drag into the menu, release on an item (macOS press-drag-release)
        rects = sess.rects()
        edit = [r for r in rects if r["text"] == "Bearbeiten"][0]
        idx = [r["text"] for r in rects].index("Bearbeiten")
        sess.ipc("test", "openMenu", idx, "")
        st = wait_state(sess, lambda s: s["levels"])
        lv = st["levels"][0]
        sess.ipc("test", "close")
        y = lv["y"] + 5 + 24 * 1 + 12      # second row: Ausschneiden
        sess.ipc("test", "press", idx, "")
        time.sleep(0.3)
        sess.ipc("test", "pointer", edit["x"] + 30, y, "")
        time.sleep(0.2)
        res = sess.ipc("test", "release", edit["x"] + 30, y, "")
        r, _, _ = select.select([app.stdout], [], [], 4)
        said = app.stdout.readline().strip() if r else ""
        check("press-drag-release selects an item", res == "activated" and said == "TRIGGERED Ausschneiden", f"{res} {said}")
        # the app-name menu proxies the app's own About / Quit entries
        sess.ipc("test", "openMenu", 1, "")
        st = wait_state(sess, lambda s: s["levels"])
        items = st["levels"][0]["items"]
        check("app-name menu: About <app> from the app, Hide/Quit", any(i.startswith("Über ") for i in items) and any("beenden" in i for i in items),
              json.dumps(items, ensure_ascii=False))
        sess.ipc("test", "close")
        # tray
        st = wait_state(sess, lambda s: s["tray"])
        check("tray shows a real StatusNotifierItem", bool(st["tray"]), json.dumps(st["tray"]))
        rects = sess.rects()
        tray = [i for i, r in enumerate(rects) if r["owner"].startswith("tray:")]
        if tray:
            sess.ipc("test", "openMenu", tray[0], "")
            st = wait_state(sess, lambda s: s["levels"] and any("Synchronisieren" in i for i in s["levels"][0]["items"]))
            items = st["levels"][0]["items"] if st["levels"] else []
            check("tray item's menu renders in our glass menu", "Synchronisieren" in items and "Pausiert" in items, json.dumps(items, ensure_ascii=False))
            time.sleep(0.5)
            sess.save(sess.screenshot(), "tray-menu-light-1.0x.png", crop=(W - 520, 0, W, 200))
            sess.ipc("test", "key", "return", "")
            r, _, _ = select.select([app.stdout], [], [], 4)
            said = app.stdout.readline().strip() if r else ""
            check("tray menu item triggers the app", said == "TRIGGERED Synchronisieren", said + " | " + " ".join(l for l in sess.shell_log().splitlines() if "tray" in l)[-300:])
        # a real maximised window: the bar turns solid and calm (macOS 27)
        app.terminate()
        app.wait(5)
        app = subprocess.Popen([MENUAPP, "--maximized"], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        service, path = appmenu_probe.find_menu(app.pid, env)
        sess.ctl({"cmd": "close", "id": "q1"})
        sess.ctl({"cmd": "open", "window": {"id": "q2", "appId": "org.kristall.MenuApp", "title": "Menu App", "pid": app.pid, "maximized": True,
                                            "x": 0, "y": 24, "w": W, "h": H - 24, "menu": {"service": service, "path": path}}})
        st = wait_state(sess, lambda s: s["bar"]["dimmed"] and "Datei" in s["bar"]["titles"])
        check("real maximised window: bar dimmed, app menus shown", st["bar"]["dimmed"] and "Datei" in st["bar"]["titles"])
        time.sleep(1.2)
        sess.save(sess.screenshot(), "bar-dimmed-maximized-window-light-1.0x.png", crop=(0, 0, W, 120))
        warns = shell_warnings(sess)
        known = [w for w in warns if "quickshell.service" in w or "quickshell.network" in w or "quickshell.bluetooth" in w]
        check("no warnings besides absent system services", len(warns) == len(known), "\n".join(w for w in warns if w not in known)[:800])
        reg.terminate()
    finally:
        if app:
            app.terminate()
        sess.stop()


# ---------------------------------------------------------------------------------------------------
def test_scale():
    print("== scale 1.6 (2880×1800 panel)", flush=True)
    # the virtual backend's mode is width×scale: 1800×1125 logical → 2880×1800 device pixels
    sess = ss.ShellSession(width=1800, height=1125, scale=1.6, name="scale", settings={"appearance": {"theme": "light", "glass": 0.3}})
    sess.start()
    try:
        sess.start_system()
        busy_bg(sess, 1800, 1125)
        sess.start_shell()
        sess.wait_ready()
        time.sleep(2)
        img = sess.screenshot()
        check("output is 2880×1800 device px at scale 1.6", img.shape[1] == 2880 and img.shape[0] == 1800, str(img.shape))
        results["scale16_bar_device_px"] = int(round(24 * 1.6))
        sess.save(img, "bar-light-1.6x.png", crop=(0, 0, 2880, 64))
        sess.ipc("test", "openMenu", 0, "")
        time.sleep(1.0)
        sess.save(sess.screenshot(), "bar-mark-menu-light-1.6x.png", crop=(0, 0, 1200, 560))
        sess.ipc("test", "close")
        sess.write_settings({"appearance": {"theme": "dark", "glass": 0.6}})
        wait_state(sess, lambda s: s["theme"] == "dark")
        time.sleep(1.5)
        sess.save(sess.screenshot(), "bar-dark-1.6x.png", crop=(0, 0, 2880, 64))
        st = sess.state()
        check("bar at 1.6: glass drawn", st["bar"]["glassDrawn"])
        warns = shell_warnings(sess)
        known = [w for w in warns if "pipewire" in w]
        check("zero warnings at scale 1.6", len(warns) == len(known), "\n".join(w for w in warns if w not in known)[:800])
    finally:
        sess.stop()


def test_fallback():
    print("== fallback: no glass effect loaded", flush=True)
    W, H = 1280, 800
    sess = ss.ShellSession(width=W, height=H, glass=False, name="fallback")
    sess.start(wait_glass=False)
    try:
        sess.start_system()
        busy_bg(sess, W, H)
        sess.start_shell()
        st = sess.wait_ready()
        time.sleep(1.5)
        check("effect absent: shell runs, state 'absent'", st["glass"] == "absent" and not st["bar"]["glassDrawn"], st["glass"])
        img = sess.screenshot()
        bar = img[4:20, 600:900, :3].astype(float)
        # the fallback fill is ~80–94 % of #F6F6F8: light and fairly uniform over the busy wallpaper
        check("fallback fill is drawn under the bar", bar.mean() > 170, f"mean {bar.mean():.0f}")
        sess.save(img, "bar-fallback-no-effect-light-1.0x.png", crop=(0, 0, W, 40))
        sess.ipc("test", "openMenu", 0, "")
        time.sleep(0.8)
        sess.save(sess.screenshot(), "bar-fallback-mark-menu-1.0x.png", crop=(0, 0, 760, 340))
        sess.ipc("test", "close")
        warns = shell_warnings(sess)
        known = [w for w in warns if "pipewire" in w]
        check("zero warnings without the effect", len(warns) == len(known), "\n".join(w for w in warns if w not in known)[:800])
    finally:
        sess.stop()


def test_modules():
    print("== module isolation", flush=True)
    tmp = tempfile.mkdtemp(prefix="kristall-shell-copy-")
    shell = os.path.join(tmp, "shell")
    shutil.copytree(SHELL, shell, ignore=shutil.ignore_patterns("tests", ".scratch", "__pycache__"))
    os.makedirs(os.path.join(shell, "modules", "broken"))
    with open(os.path.join(shell, "modules", "broken", "Module.qml"), "w") as f:
        f.write("import QtQuick\nimport Quickshell\nScope { this is not QML }\n")
    os.makedirs(os.path.join(shell, "modules", "throws"))
    with open(os.path.join(shell, "modules", "throws", "Module.qml"), "w") as f:
        f.write("import QtQuick\nimport Quickshell\nimport qs.services\nScope { Component.onCompleted: { throw new Error('module bug'); } }\n")
    os.makedirs(os.path.join(shell, "modules", "probe"))
    with open(os.path.join(shell, "modules", "probe", "Module.qml"), "w") as f:
        f.write("import QtQuick\nimport Quickshell\nimport qs.core\nimport qs.services\n"
                "Scope { Component.onCompleted: { ShellBus.claim('probe'); console.info('probe module:', Strings.t('probe.hello'), Theme.radius.menu); } }\n")
    with open(os.path.join(shell, "modules", "probe", "strings.json"), "w") as f:
        json.dump({"en": {"probe.hello": "hello"}, "de": {"probe.hello": "hallo"}}, f)
    for m in ("broken", "throws", "probe"):
        open(os.path.join(shell, "modules", m, "qmldir"), "w").write("# test module\n")
    os.makedirs(os.path.join(shell, "modules", "noqmldir"))
    with open(os.path.join(shell, "modules", "noqmldir", "Module.qml"), "w") as f:
        f.write("import QtQuick\nimport Quickshell\nScope {}\n")
    with open(os.path.join(shell, "modules.list"), "a") as f:
        f.write("broken\nthrows\nprobe\nnoqmldir\nghost\n")
    listed = [l.split("#")[0].strip() for l in open(os.path.join(SHELL, "modules.list"))]
    listed = [m for m in listed if m]
    sess = ss.ShellSession(width=1280, height=800, name="modules")
    sess.start()
    try:
        sess.start_shell(path=shell)
        st = sess.wait_ready()
        time.sleep(1.5)
        log = sess.shell_log()
        status = json.loads(sess.ipc("shell", "status"))
        check("broken module is logged and skipped", status["modules"].get("broken") == "failed" and "module broken failed to load" in log, json.dumps(status["modules"]))
        check("module that throws is isolated (shell keeps running)", bool(st["bar"]) and "module bug" in log)
        check("good module loads, sees the core and its own strings", status["modules"].get("probe") == "loaded" and "probe module: hallo 12" in log,
              [l for l in log.splitlines() if "probe" in l][:3].__str__())
        check("a listed module without a directory is skipped silently", status["modules"].get("ghost") == "absent"
              and "ghost" not in "".join(ss.warnings_in(log)), json.dumps(status["modules"]))
        check("a module without a qmldir is logged clearly", "module noqmldir has no qmldir" in log)
        present = [m for m in listed if os.path.exists(os.path.join(SHELL, "modules", m, "Module.qml"))]
        for m in listed:
            if m not in present:
                check(f"module {m}: absent, skipped", status["modules"].get(m) == "absent", str(status["modules"].get(m)))
                continue
            w = [l for l in ss.warnings_in(log) if f"/modules/{m}/" in l or f"module {m} " in l]
            check(f"module {m}: present → loaded without warnings", status["modules"].get(m) == "loaded" and not w, "\n".join(w[:5]) or str(status["modules"].get(m)))
        # safe mode skips modules
    finally:
        sess.stop()
    sess = ss.ShellSession(width=1280, height=800, name="safemode")
    sess.start()
    try:
        sess.start_shell(path=shell, extra_env={"KRISTALL_SHELL_SAFE": "1"})
        sess.wait_ready()
        status = json.loads(sess.ipc("shell", "status"))
        check("safe mode: bar runs, no modules", status["safeMode"] and not status["modules"], json.dumps(status))
    finally:
        sess.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def test_restart():
    print("== restart after a crash (unit semantics emulated: no systemd in the container)", flush=True)
    sess = ss.ShellSession(width=1280, height=800, name="restart")
    sess.start()
    sup_stop = [False]
    try:
        # supervisor with the unit's Restart=always / RestartSec=1, running the real launcher
        env = sess.env()
        env.update(sess.shell_env({"KRISTALL_SHELL_DIR": SHELL, "KRISTALL_SHELL_HELPER": os.path.join(SHELL, "helper", "kristall-shell-helper"),
                                   "QT_QPA_PLATFORM": "wayland", "QT_QUICK_BACKEND": "software"}))
        sess.shell_path = SHELL
        starts = []
        import threading

        def supervise():
            while not sup_stop[0]:
                p = subprocess.Popen([os.path.join(SHELL, "bin", "kristall-shell")], env=env,
                                     stdout=open(os.path.join(sess.tmp, f"shell-run{len(starts)}.log"), "w"), stderr=subprocess.STDOUT)
                starts.append(p)
                p.wait()
                if sup_stop[0]:
                    break
                time.sleep(1.0)
        if not sess.bridge:
            import mockbridge
            sess.bridge = mockbridge.MockBridge(sess.bridge_path).start()
        threading.Thread(target=supervise, daemon=True).start()
        ss.wait_until(lambda: starts, 5)
        sess.shell = starts[-1]
        sess.wait_ready()
        first = starts[-1].pid
        os.kill(first, signal.SIGKILL)
        t0 = time.monotonic()
        ss.wait_until(lambda: len(starts) >= 2, 10)
        sess.shell = starts[-1]
        st = sess.wait_ready(20)
        took = time.monotonic() - t0
        check("killed shell is back (bar present) after restart", bool(st.get("bar")), f"{took:.1f} s")
        results["restart_seconds"] = round(took, 1)
        status = json.loads(sess.ipc("shell", "status"))
        check("one crash: normal mode", not status["safeMode"])
        for _ in range(2):
            n = len(starts)
            os.kill(starts[-1].pid, signal.SIGKILL)
            ss.wait_until(lambda: len(starts) > n, 10)
            sess.shell = starts[-1]
            sess.wait_ready(20)
        status = json.loads(sess.ipc("shell", "status"))
        check("third crash within 60 s: restarted in safe mode", status["safeMode"], json.dumps(status))
    finally:
        sup_stop[0] = True
        for p in starts if 'starts' in dir() else []:
            if p.poll() is None:
                p.terminate()
        sess.stop()


def test_plasma():
    print("== Plasma default layout (desktop only, no panels)", flush=True)
    import harness
    for mode in ("kristall", "fedora"):
        s = harness.Session(name="plasma-" + mode)
        s.start(wait_glass=False)
        try:
            data = os.path.join(s.tmp, "share")
            conf = os.path.join(s.tmp, "xdg")
            os.makedirs(os.path.join(data, "plasma", "look-and-feel"))
            shutil.copytree(os.path.join(SHELL, "plasma", "look-and-feel", "org.kristall.desktop"),
                            os.path.join(data, "plasma", "look-and-feel", "org.kristall.desktop"))
            os.makedirs(conf)
            shutil.copy(os.path.join(SHELL, "plasma", "xdg", "kdeglobals"), conf)
            env = s.env()
            env["QT_QPA_PLATFORM"] = "wayland"
            env["XDG_CONFIG_DIRS"] = "/etc/xdg:/usr/share/kde-settings/kde-profile/default/xdg"
            if mode == "kristall":
                env["XDG_DATA_DIRS"] = data + ":/usr/share"
                env["XDG_CONFIG_DIRS"] = conf + ":" + env["XDG_CONFIG_DIRS"]
            kam = subprocess.Popen(["/usr/libexec/kactivitymanagerd"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            p = subprocess.Popen(["plasmashell", "--no-respawn"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(15)
            if mode == "kristall":
                # without Plasma's panels (system tray) plasmashell runs no notification server:
                # org.freedesktop.Notifications is free for the shell's panels module
                r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                                    "--method", "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.Notifications"],
                                   env=env, capture_output=True, text=True, timeout=10)
                check("plasmashell with our layout does not take org.freedesktop.Notifications", "false" in r.stdout, r.stdout.strip() + r.stderr.strip())
            p.terminate()
            p.wait(10)
            kam.terminate()
            rc = os.path.join(s.config, "plasma-org.kde.plasma.desktop-appletsrc")
            txt = open(rc).read() if os.path.exists(rc) else ""
            plugins = [l.split("=", 1)[1] for l in txt.splitlines() if l.startswith("plugin=")]
            if mode == "kristall":
                check("our look-and-feel layout: desktop containment, image wallpaper, no panel",
                      "org.kde.plasma.folder" in plugins and "org.kde.panel" not in plugins and "wallpaperplugin=org.kde.image" in txt, str(plugins))
            else:
                check("(control) Fedora's default layout has a panel", "org.kde.panel" in plugins, str(plugins[:4]))
        finally:
            s.stop()


def _desktop_actions(path):
    """{action id: [shortcut strings]} of a kglobalaccel desktop file, plus whether it has NoDisplay"""
    import configparser
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    acts = {}
    for sec in cp.sections():
        if sec.startswith("Desktop Action "):
            v = cp[sec].get("X-KDE-Shortcuts", "").strip()
            acts[sec[len("Desktop Action "):]] = [k.strip() for k in v.split(",") if k.strip()]
    nodisplay = any(l.strip().lower().startswith("nodisplay") for l in open(path, encoding="utf-8"))
    return acts, nodisplay


QT_MODS = {"Shift": 0x02000000, "Ctrl": 0x04000000, "Alt": 0x08000000, "Meta": 0x10000000}


def _qt_key(text):
    """'Meta+Shift+F23' -> Qt key combination int"""
    v = 0
    for part in text.split("+"):
        if part in QT_MODS:
            v |= QT_MODS[part]
        elif part == "Space":
            v |= 0x20
        elif len(part) == 1:
            v |= ord(part.upper())
        elif part[0] == "F" and part[1:].isdigit():
            v |= 0x01000030 + int(part[1:]) - 1
        else:
            raise ValueError(part)
    return v


def test_shortcuts():
    print("== global shortcuts: every kglobalaccel file registers, with its default keys", flush=True)
    import glob
    import harness
    files = sorted(glob.glob(os.path.join(SHELL, "**", "kglobalaccel", "*.desktop"), recursive=True))
    check("kglobalaccel desktop files found", len(files) >= 5, ", ".join(os.path.relpath(f, SHELL) for f in files))
    declared = {}
    for f in files:
        acts, nodisplay = _desktop_actions(f)
        check(f"{os.path.relpath(f, SHELL)}: no NoDisplay (kglobalacceld ignores such files)", not nodisplay)
        declared[os.path.basename(f)] = acts
    # a KWin session with global shortcuts on (the harness turns them off) and the files in a
    # share/kglobalaccel/ directory on XDG_DATA_DIRS, as /usr/share/kglobalaccel/ in the image
    s = harness.Session(name="shortcuts")
    share = os.path.join(s.tmp, "sys", "share")
    os.makedirs(os.path.join(share, "kglobalaccel"))
    for f in files:
        shutil.copy(f, os.path.join(share, "kglobalaccel"))
    orig_env, orig_kwin = s.env, harness.KWIN
    s.env = lambda: dict(orig_env(), XDG_DATA_DIRS=share + ":/usr/share")
    wrapper = os.path.join(s.tmp, "kwin-with-shortcuts")
    with open(wrapper, "w") as fw:
        fw.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = --no-global-shortcuts ] || set -- "$@" "$a"; shift; done\nexec %s "$@"\n' % orig_kwin)
    os.chmod(wrapper, 0o755)
    harness.KWIN = wrapper
    try:
        s.start(wait_glass=False)
    finally:
        harness.KWIN = orig_kwin
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def call(path, iface, method, args=None):
            return bus.call_sync("org.kde.kglobalaccel", path, iface, method, args, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()
        comps = []
        for _ in range(20):
            try:
                comps = call("/kglobalaccel", "org.kde.KGlobalAccel", "allComponents")[0]
                if comps:
                    break
            except GLib.Error:
                pass
            time.sleep(0.5)
        registered = {}
        for path in comps:
            try:
                infos = call(path, "org.kde.kglobalaccel.Component", "allShortcutInfos")[0]
            except GLib.Error as e:
                info(f"{path}: {e.message}")
                continue
            for inf in infos:
                # KGlobalShortcutInfo: (action, friendly, component, component friendly, context,
                # context friendly, keys, defaultKeys) — keys as Qt key combinations
                action, comp = inf[0], inf[2]
                ints = []

                def flat(x):
                    if isinstance(x, int):
                        ints.append(x)
                    elif isinstance(x, (list, tuple)):
                        for y in x:
                            flat(y)
                flat(inf[-1])
                registered.setdefault(comp, {})[action] = ints
        ours = {c: a for c, a in registered.items() if c.startswith("org.kristall.")}
        info("registered kristall components: " + json.dumps({c: {a: [hex(k) for k in v] for a, v in acts.items()} for c, acts in ours.items()}))
        for fname, acts in declared.items():
            comp = registered.get(fname)
            check(f"{fname}: component registered with kglobalacceld", comp is not None, ", ".join(sorted(registered)[:12]))
            if comp is None:
                continue
            for action, keys in acts.items():
                want = [_qt_key(k) for k in keys]
                got = comp.get(action)
                check(f"{fname} ▸ {action}: registered with default {', '.join(keys) or '(none)'}",
                      got is not None and all(w in got for w in want), f"got {[hex(g) for g in (got or [])]}")
    finally:
        s.stop()


def test_ctl():
    print("== kristall-shellctl passes its argument verbatim", flush=True)
    sess = ss.ShellSession(name="ctl")
    sess.start(wait_glass=False)
    try:
        sess.start_shell()
        sess.wait_ready()
        env = sess.env()
        env.update(sess.shell_env())
        env["KRISTALL_SHELL_DIR"] = sess.shell_path
        ctl = os.path.join(SHELL, "bin", "kristall-shellctl")
        cases = [("-1", ["gallery", "noop", "-1"]), ("-5.5", ["gallery", "noop", "-5.5"]), ("", ["gallery", "noop", ""]),
                 ("zwei Wörter mit Leerzeichen", ["gallery", "noop", "zwei Wörter mit Leerzeichen"]),
                 ("Grüße aus Köln: äöüß ÄÖÜ", ["gallery", "noop", "Grüße aus Köln: äöüß ÄÖÜ"]),
                 ('{"x":1,"y":2}', ["gallery", "noop", '{"x":1,"y":2}']), ("[1, 2]", ["gallery", "noop", "[1, 2]"]),
                 ("--output", ["gallery", "noop", "--", "--output"]), ("-h", ["gallery", "noop", "--", "-h"])]
        for want, argv in cases:
            r = subprocess.run([ctl] + argv + ["--output", "Virtual-0"] if "--" not in argv else [ctl, "--output", "Virtual-0"] + argv,
                               env=env, capture_output=True, text=True, timeout=15)
            last = json.loads(sess.ipc("test", "lastRequests") or "[]")
            got = last[-1] if last else None
            check(f"shellctl delivers {want!r}", r.returncode == 0 and got is not None and got["arg"] == want and got["output"] == "Virtual-0"
                  and got["target"] == "gallery", f"rc={r.returncode} {r.stderr.strip()} got={got}")
        # control: without "--" quickshell's parser takes "-1" for an option (the old shellctl's bug)
        r = subprocess.run(["quickshell", "ipc", "-p", sess.shell_path, "call", "shell", "request", "gallery", "noop", "-1", ""],
                           env=env, capture_output=True, text=True, timeout=15)
        info(f"control: 'quickshell ipc call … -1' without '--' exits {r.returncode}: {(r.stderr or r.stdout).strip()[:160]}")
        r = subprocess.run([ctl, "gallery", "noop", "x"], env=dict(env, KRISTALL_SHELL_DIR=os.path.join(sess.tmp, "nowhere")),
                           capture_output=True, text=True, timeout=15)
        check("shellctl: no shell there → exit 1 with a message (never a silent 0)", r.returncode == 1 and "kristall-shellctl:" in r.stderr, f"rc={r.returncode} {r.stderr.strip()}")
        r = subprocess.run([ctl, "gallery"], env=env, capture_output=True, text=True, timeout=15)
        check("shellctl: missing action is a usage error (exit 2)", r.returncode == 2, str(r.returncode))
        r = subprocess.run([ctl, "gallery", "noop", "a", "b"], env=env, capture_output=True, text=True, timeout=15)
        check("shellctl: a fourth positional is a usage error (exit 2)", r.returncode == 2, str(r.returncode))
    finally:
        sess.stop()


def _stale_socket(path):
    """a socket file nobody listens on: connect() is refused (ECONNREFUSED), like after a crash"""
    import socket as _s
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    k = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
    k.bind(path)
    k.close()


class FakeGlass:
    """the smallest glass.sock: answers hello with state active (enough for GlassClient.state)"""
    def __init__(self, path, hello=None):
        self.hello = hello or b'{"event":"hello","server":"kristall-glass","protocol":1,"state":"active","theme":"light","glass":0.3}\n'
        import socket as _s
        import threading
        if os.path.exists(path):
            os.unlink(path)
        self.srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(4)
        self.conns = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.conns.append(c)
            c.sendall(self.hello)

    def close(self):
        self.srv.close()
        for c in self.conns:
            c.close()


def test_reconnect():
    print("== reconnect: bridge and glass sockets that appear after the shell (refused first)", flush=True)
    for helper in (True, False):
        label = "with the helper (inotify)" if helper else "without the helper (backoff 0.25 s → 5 s)"
        sess = ss.ShellSession(name="reconnect", glass=False)
        sess.start(wait_glass=False)
        glass_path = os.path.join(sess.tmp, "fake-glass.sock")
        try:
            _stale_socket(sess.bridge_path)
            _stale_socket(glass_path)
            extra = {"KRISTALL_GLASS_SOCKET": glass_path}
            if not helper:
                extra["KRISTALL_SHELL_HELPER"] = "/nonexistent/kristall-shell-helper"
            sess.start_shell(extra_env=extra, bridge=False)
            sess.wait_ready()
            time.sleep(4.0 if helper else 7.0)       # refused attempts happen meanwhile
            st = json.loads(sess.ipc("shell", "status"))
            check(f"{label}: refused sockets: not connected, fallback state", st["bridge"] is False and st["glass"] != "active", json.dumps(st))
            t0 = time.monotonic()
            sess.bridge = ss.mockbridge.MockBridge(sess.bridge_path, outputs=[
                {"name": "Virtual-0", "x": 0, "y": 0, "w": sess.width, "h": sess.height, "scale": 1.0, "refresh": 60.0,
                 "internal": True, "primary": True}]).start()
            fg = FakeGlass(glass_path)
            ok = ss.wait_until(lambda: (lambda st: st["bridge"] is True and st["glass"] == "active")(json.loads(sess.ipc("shell", "status"))), 8, 0.2)
            dt = time.monotonic() - t0
            check(f"{label}: bridge and glass connect within 6 s of appearing", bool(ok) and dt <= 6.0, f"{dt:.2f} s")
            results["reconnect_" + ("helper" if helper else "backoff") + "_s"] = round(dt, 2)
            # the server goes away and comes back: connects again
            fg.close()
            time.sleep(1.0)
            t0 = time.monotonic()
            fg = FakeGlass(glass_path)
            ok = ss.wait_until(lambda: json.loads(sess.ipc("shell", "status"))["glass"] == "active", 8, 0.2)
            dt = time.monotonic() - t0
            check(f"{label}: glass restarts → reconnected within 6 s", bool(ok) and dt <= 6.0, f"{dt:.2f} s")
            fg.close()
            if helper:
                # the effect comes back disabled by its crash guard: one gentle notification per session
                time.sleep(0.5)
                fg = FakeGlass(glass_path, b'{"event":"hello","server":"kristall-glass","protocol":1,"state":"disabled","reason":"crash-guard","theme":"light","glass":0.3}\n')
                marker = os.path.join(sess.runtime, "kristall", "glass-guard-notified")
                ok = ss.wait_until(lambda: os.path.exists(marker), 8, 0.2)
                check("glass disabled by its crash guard: the owner is told once (notification, marker for this session)", bool(ok))
                fg.close()
        finally:
            sess.stop()


def test_controls():
    print("== core controls are binding-safe (a click never breaks the owner's binding)", flush=True)
    owner_bin = os.path.join(os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp/kristall-bridge-build"), "bin", "owner")
    sess = ss.ShellSession(name="controls")
    sess.start(wait_glass=False)
    owner = None
    try:
        sess.start_shell()
        sess.wait_ready()
        sess.ipc("test", "toggleTest", "true")
        st = ss.wait_until(lambda: json.loads(sess.ipc("test", "toggleState") or "null"), 5, 0.2)
        check("toggle shows the setting (off)", st and st["checked"] is False and st["shown"] is False, json.dumps(st))
        if os.path.exists(owner_bin):
            owner = subprocess.Popen([owner_bin], env=sess.env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
            if owner.stdout.readline().strip() != "ready":
                raise RuntimeError("owner: no fake input")

            def cmd(c):
                owner.stdin.write(c + "\n")
                owner.stdin.flush()
                owner.stdout.readline()
            cmd("move 141 132")
            time.sleep(0.2)
            cmd("button 272 1")
            time.sleep(0.05)
            cmd("button 272 0")
            how = "pointer click"
        else:
            check("the owner's input client is built (kwin/bridge/tests)", False, owner_bin)
            return
        st = ss.wait_until(lambda: (lambda x: x if x and x["setting"] is True else None)(json.loads(sess.ipc("test", "toggleState"))), 5, 0.2)
        check(f"{how}: the toggle requests the change and the setting follows", bool(st) and st["checked"] is True and st["shown"] is True, json.dumps(st))
        settings_set(sess, "bar.showBatteryPercentage", False)
        st = ss.wait_until(lambda: (lambda x: x if x and x["checked"] is False else None)(json.loads(sess.ipc("test", "toggleState"))), 5, 0.2)
        check("after the click, an outside change of the setting moves the toggle (binding intact)", bool(st) and st["shown"] is False, json.dumps(st))
        settings_set(sess, "bar.showBatteryPercentage", True)
        st = ss.wait_until(lambda: (lambda x: x if x and x["checked"] is True else None)(json.loads(sess.ipc("test", "toggleState"))), 5, 0.2)
        check("…and back on", bool(st) and st["shown"] is True, json.dumps(st))
        w = [l for l in shell_warnings(sess) if "quickshell.service" not in l and "quickshell.network" not in l and "quickshell.bluetooth" not in l]
        check("no warnings (system services are not mocked in this session)", not w, "\n".join(w[:6]))
    finally:
        if owner:
            owner.kill()
        sess.stop()


def test_menus():
    print("== menus: submenu safe triangle (synthetic pointer paths)", flush=True)
    sess = ss.ShellSession(name="menus")
    sess.start(wait_glass=False)
    try:
        sess.start_shell()
        sess.wait_ready()

        def state():
            return json.loads(sess.ipc("test", "menuState"))

        def play(points, ms=0):
            sess.ipc("test", "hoverPath", ";".join(f"{x:.1f},{y:.1f}" for x, y in points))

        def open_first():
            sess.ipc("test", "openTestMenu", 200, 120)
            st = ss.wait_until(state, 3, 0.1)
            r0 = st[0]["rows"][0]
            x0 = st[0]["x"] + st[0]["w"] * 0.5
            play([(x0, r0["y"] + r0["h"] / 2)])
            time.sleep(0.4)                       # 120 ms hover delay: the submenu opens
            return ss.wait_until(lambda: (lambda s: s if s and len(s) == 2 else None)(state()), 3, 0.1)
        st = open_first()
        check("hovering a row with a submenu opens it", bool(st) and st[1]["anchorRow"] == 0, json.dumps(st and [l["anchorRow"] for l in st]))
        p, sub = st[0], st[1]
        r0 = p["rows"][0]
        a = (p["x"] + p["w"] * 0.5, r0["y"] + r0["h"] / 2)
        b = (sub["x"] + 8, sub["y"] + sub["h"] - 10)     # a lower item of the submenu, diagonally
        path = [(a[0] + (b[0] - a[0]) * t / 14, a[1] + (b[1] - a[1]) * t / 14) for t in range(1, 15)]
        crossed = sorted({k for (x, y) in path for k, r in enumerate(p["rows"]) if r["y"] <= y < r["y"] + r["h"] and x < p["x"] + p["w"]} - {0})
        play(path, 16)
        time.sleep(0.1)
        st = state()
        check("diagonal path to the submenu crosses other rows" , len(crossed) >= 1, str(crossed))
        check("safe triangle: the submenu stays open while the pointer crosses other rows on the way",
              bool(st) and len(st) == 2 and st[1]["anchorRow"] == 0, json.dumps(st and [l["anchorRow"] for l in st]))
        check("…and the pointer arrives in it (its row is selected)", bool(st) and len(st) == 2 and st[1]["current"] >= 0, json.dumps(st and [l["current"] for l in st]))
        sess.ipc("shell", "request", "shell", "close-menus", "", "")
        time.sleep(0.4)
        # control: moving straight down to another row and resting there switches after ~300 ms
        st = open_first()
        p = st[0]
        r3 = p["rows"][3]
        x = p["x"] + p["w"] * 0.5
        for k in (1, 2, 3):
            play([(x, p["rows"][k]["y"] + p["rows"][k]["h"] / 2)])
        time.sleep(0.6)
        st = state()
        check("off course (straight down) and resting: the hovered row's submenu takes over",
              bool(st) and len(st) == 2 and st[1]["anchorRow"] == 3, json.dumps(st and [l["anchorRow"] for l in st]))
        sess.ipc("shell", "request", "shell", "close-menus", "", "")
        # resting inside the triangle over another row (no submenu): after 300 ms that row wins
        st = open_first()
        p, sub = st[0], st[1]
        r0, r1 = p["rows"][0], p["rows"][1]
        play([(p["x"] + p["w"] - 30, r0["y"] + r0["h"] / 2), (p["x"] + p["w"] - 20, r1["y"] + 4)], 16)
        time.sleep(0.15)
        mid = state()
        time.sleep(0.4)
        st = state()
        check("resting in the triangle: the submenu stays first, then (≈ 300 ms) the row under the pointer takes over",
              bool(mid) and len(mid) == 2 and bool(st) and len(st) == 1 and st[0]["current"] == 1,
              json.dumps({"after150ms": mid and [l["anchorRow"] for l in mid], "after550ms": st and [(l["anchorRow"], l["current"]) for l in st]}))
        sess.ipc("shell", "request", "shell", "close-menus", "", "")
    finally:
        sess.stop()


def test_reveal():
    print("== full screen: the menu bar slides down at the top edge (not over games)", flush=True)
    owner_bin = os.path.join(os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp/kristall-bridge-build"), "bin", "owner")
    sess = ss.ShellSession(name="reveal")
    sess.start(wait_glass=False)
    owner = None
    try:
        sess.start_shell()
        sess.wait_ready()
        owner = subprocess.Popen([owner_bin], env=sess.env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        if owner.stdout.readline().strip() != "ready":
            raise RuntimeError("owner: no fake input")

        def cmd(c):
            owner.stdin.write(c + "\n")
            owner.stdin.flush()
            owner.stdout.readline()

        def rv():
            return sess.state()["bar"]["reveal"]
        cmd("move 640 400")
        st = rv()
        check("no hot strip without a full-screen window", not st["strip"], json.dumps(st))
        sess.ctl({"cmd": "open", "window": {"id": "v1", "appId": "org.mozilla.firefox", "title": "Video", "x": 0, "y": 0,
                                            "w": sess.width, "h": sess.height, "fullscreen": True}})
        sess.ctl({"cmd": "activate", "id": "v1"})
        st = wait_state(sess, lambda s: s["bar"]["reveal"]["strip"], 4)["bar"]["reveal"]
        check("full-screen window in front: the 2-px hot strip waits at the top edge", st["strip"] and not st["revealed"], json.dumps(st))
        cmd("move 640 1")
        time.sleep(0.1)
        early = rv()
        st = wait_state(sess, lambda s: s["bar"]["reveal"]["revealed"] and s["bar"]["reveal"]["slideY"] == 0, 3)["bar"]["reveal"]
        check("resting at the top edge reveals the bar after ~250 ms (not at once)", not early["revealed"] and st["revealed"], json.dumps({"after100ms": early, "later": st}))
        img = sess.screenshot()
        sess.save(img, "bar-reveal-fullscreen.png", crop=(0, 0, sess.width, 60))
        cmd("move 640 12")                      # on the bar
        time.sleep(0.6)
        check("stays while the pointer is on the bar", rv()["revealed"], json.dumps(rv()))
        cmd("move 640 400")                     # away from the bar
        st = wait_state(sess, lambda s: not s["bar"]["reveal"]["revealed"], 3)["bar"]["reveal"]
        check("leaving the bar slides it away again", not st["revealed"] and st["strip"], json.dumps(st))
        # a game (X11 client in full screen): the edge is left alone
        sess.ctl({"cmd": "open", "window": {"id": "g1", "appId": "steam_app_12345", "title": "Spiel", "x": 0, "y": 0,
                                            "w": sess.width, "h": sess.height, "fullscreen": True, "xwayland": True}})
        sess.ctl({"cmd": "activate", "id": "g1"})
        st = wait_state(sess, lambda s: s["bar"]["reveal"]["gameLike"], 4)["bar"]["reveal"]
        check("full-screen game (Xwayland): no hot strip, no reveal", st["gameLike"] and not st["strip"], json.dumps(st))
        cmd("move 640 1")
        time.sleep(0.6)
        check("…the pointer at the top edge does nothing", not rv()["revealed"], json.dumps(rv()))
        sess.ctl({"cmd": "close", "id": "g1"})
        sess.ctl({"cmd": "close", "id": "v1"})
        st = wait_state(sess, lambda s: not s["bar"]["reveal"]["strip"], 4)["bar"]["reveal"]
        check("no full-screen window: the strip is unmapped again", not st["strip"], json.dumps(st))
        w = [l for l in shell_warnings(sess) if "quickshell.service" not in l and "quickshell.network" not in l and "quickshell.bluetooth" not in l]
        check("no warnings", not w, "\n".join(w[:6]))
    finally:
        if owner:
            owner.kill()
        sess.stop()


def test_gallery():
    print("== gallery screenshots", flush=True)
    W, H = 1800, 1125
    for theme in ("light", "dark"):
        sess = ss.ShellSession(width=W, height=H, name="gallery-" + theme, settings={"appearance": {"theme": theme, "glass": 0.3}})
        sess.start()
        try:
            busy_bg(sess, W, H)
            sess.start_shell(extra_env={"KRISTALL_SHELL_GALLERY": "1"})
            sess.wait_ready()
            time.sleep(3)
            sess.save(sess.screenshot(), f"gallery-{theme}-1.0x.jpg", quality=84)
            warns = shell_warnings(sess)
            known = [w for w in warns if "quickshell.service" in w or "quickshell.network" in w or "quickshell.bluetooth" in w]
            check(f"gallery ({theme}) renders without QML warnings", len(warns) == len(known), "\n".join(w for w in warns if w not in known)[:800])
        finally:
            sess.stop()


def test_realbridge():
    print("== against the real bridge plugin (kwin/bridge), if it builds", flush=True)
    bridge_plugins = os.environ.get("KRISTALL_BRIDGE_PLUGINS", "/tmp/kristall-bridge-build/plugins")
    if not os.path.exists(os.path.join(bridge_plugins, "kwin", "plugins", "kristall_bridge.so")):
        info("bridge plugin not built — section skipped")
        return
    W, H = 1280, 800
    sess = ss.ShellSession(width=W, height=H, name="realbridge",
                           env={"QT_PLUGIN_PATH": ss.harness.PLUGINS + ":" + bridge_plugins, "KRISTALL_BRIDGE_DEV": "1"})
    with open(os.path.join(sess.config, "kwinrc"), "a") as f:
        f.write("[Plugins]\nkristall_glassEnabled=true\nkristall_bridgeEnabled=true\n")
    sess.start()
    app = None
    try:
        check("real bridge socket appears", bool(ss.wait_until(lambda: os.path.exists(sess.bridge_path), 10)))
        busy_bg(sess, W, H)
        sess.start_shell(bridge=False)
        sess.wait_ready()
        st = wait_state(sess, lambda s: s["bridge"], 8)
        check("shell connects to the real bridge", st["bridge"])
        env = sess.env()
        env.update({"QT_QPA_PLATFORM": "wayland"})
        # kded's appmenu module publishes the registrar once the bridge owns org.kde.kappmenuview,
        # which it does while the shell is subscribed to "menus"
        kded = subprocess.Popen(["kded6"], env=env, stdout=subprocess.DEVNULL, stderr=open(os.path.join(sess.tmp, "kded.log"), "w"))
        sess.procs.append(kded)
        reg = ss.wait_until(lambda: "com.canonical.AppMenu.Registrar" in subprocess.run(["busctl", "--user", "list", "--no-pager"], env=env,
                                                                                    capture_output=True, text=True).stdout, 10)
        check("the shell's 'menus' subscription makes kded publish the AppMenu registrar", bool(reg))
        app = subprocess.Popen([MENUAPP], env=dict(env, QT_QPA_PLATFORMTHEME="kde"), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        st = wait_state(sess, lambda s: s["activeId"] and "Darstellung" in s["bar"]["titles"], 15)
        check("real bridge: front app and its exported menus (Qt, KDE platform theme, app-menu protocol)",
              st["bar"]["appName"] == "MenuApp" and all(t in st["bar"]["titles"] for t in ("Datei", "Bearbeiten", "Darstellung", "Hilfe")),
              json.dumps(st["bar"], ensure_ascii=False))
        time.sleep(0.5)
        texts = [r["text"] for r in sess.rects()]
        if "Datei" in texts:
            sess.ipc("test", "openMenu", texts.index("Datei"), "")
            wait_state(sess, lambda s: s["levels"] and any(i.startswith("Neu") for i in s["levels"][0]["items"]))
            time.sleep(0.4)
            sess.save(sess.screenshot(), "realbridge-app-menu-light-1.0x.png", crop=(0, 0, 760, 340))
            sess.ipc("test", "key", "return", "")
            r, _, _ = select.select([app.stdout], [], [], 4)
            said = ""
            while r:
                said = app.stdout.readline().strip()
                if said.startswith("TRIGGERED") or not said:
                    break
                r, _, _ = select.select([app.stdout], [], [], 4)
            check("real bridge: choosing 'Neu' in our menu runs the app's action", said == "TRIGGERED Neu", said)
        texts = [r["text"] for r in sess.rects()]
        sess.ipc("test", "openMenu", texts.index("Fenster"), "")
        wait_state(sess, lambda s: s["levels"])
        sess.ipc("test", "key", "down", "")
        sess.ipc("test", "key", "return", "")
        st = wait_state(sess, lambda s: s["bar"]["dimmed"], 8)
        check("Window ▸ Zoom maximises the real window via the bridge; the bar dims", st["bar"]["dimmed"])
        time.sleep(1.0)
        sess.save(sess.screenshot(), "realbridge-maximized-dimmed-light-1.0x.png", crop=(0, 0, W, 120))
    finally:
        if app:
            app.terminate()
        sess.stop()


SECTIONS = {"realbridge": test_realbridge, "static": test_static, "shortcuts": test_shortcuts, "ctl": test_ctl, "reconnect": test_reconnect, "controls": test_controls, "menus": test_menus, "reveal": test_reveal, "core": test_core, "appmenu": test_appmenu, "scale": test_scale, "fallback": test_fallback,
            "modules": test_modules, "restart": test_restart, "plasma": test_plasma, "gallery": test_gallery}

if __name__ == "__main__":
    wanted = sys.argv[1:] or [k for k in SECTIONS if k != "realbridge"] + ["realbridge"]
    for name in wanted:
        try:
            SECTIONS[name]()
        except Exception as e:  # a crashed section is a failure, the others still run
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    os.makedirs(ss.EVIDENCE, exist_ok=True)
    out = os.path.join(ss.EVIDENCE, "results.json")
    old = json.load(open(out)) if os.path.exists(out) else {}
    old.update(results)
    old["last_run"] = {"sections": wanted, "failures": failures, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    json.dump(old, open(out, "w"), indent=1)
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
