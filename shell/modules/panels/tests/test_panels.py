#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the panels module (Control Center, notifications, HUD). Run inside the dev container
under dbus-run-session (see run.sh). Sections (argv selects; default all):
  static cc wifi notifications hud absent looks idle
Each check prints PASS/FAIL/INFO; the exit status is non-zero if anything failed. Screenshots go
to tests/evidence/.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import panelsession as ps  # noqa: E402
from panelsession import wait_until, PANELS, SHELL, REPO  # noqa: E402

sys.path.insert(0, os.path.join(REPO, "kwin", "glass", "tests", "support"))
import pattern  # noqa: E402
from PIL import Image  # noqa: E402
import numpy as np  # noqa: E402

failures = []
results = {}
NOTIFY = [sys.executable, os.path.join(HERE, "support", "notifyclient.py")]


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(name)
    return ok


def info(msg):
    print("INFO " + msg, flush=True)


def warnings(sess, known=()):
    out = []
    for line in sess.shell_log().splitlines():
        if ("WARN" in line or "ERROR" in line or "CRITICAL" in line) and "fd limit" not in line:
            if not any(k in line for k in known):
                out.append(line)
    return out


def wait_ps(sess, pred, timeout=8.0):
    last = [None]

    def f():
        try:
            st = sess.pstate()
        except Exception:
            return None
        last[0] = st
        try:
            return st if pred(st) else None
        except (KeyError, TypeError, IndexError):
            return None
    return wait_until(f, timeout, 0.2) or last[0]


def shown(sess, name):
    try:
        return json.loads(sess.pt("shown", name))
    except ValueError:
        return {}


def busy_bg(sess, w, h):
    bg = os.path.join(sess.tmp, "bg.png")
    Image.fromarray(pattern.busy(w, h)).save(bg)
    sess.background(bg)


def proc_stats(pids):
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
    while not 2 <= time.localtime().tm_sec <= 60 - seconds - 3:      # the clock ticks on the minute
        time.sleep(0.5)
    pids = children_of(sess.shell.pid)
    f0 = glass_frames(sess)
    t0, s0 = proc_stats(pids)
    time.sleep(seconds)
    f1 = glass_frames(sess)
    t1, s1 = proc_stats(pids)
    hz = os.sysconf("SC_CLK_TCK")
    r = {"seconds": seconds, "frames": None if f0 is None or f1 is None else f1 - f0, "cpu_ms": (t1 - t0) * 1000.0 / hz,
         "wakeups": s1 - s0, "processes": len(pids)}
    results[label] = r
    return r


def open_cc(sess, page=None):
    sess.ipc("shell", "request", "panels", "show-control-center", "", "")
    st = wait_ps(sess, lambda s: s["cc"]["t"] >= 0.999)
    if page:
        sess.pt("page", page)
        st = wait_ps(sess, lambda s: s["cc"]["page"] == page)
        time.sleep(0.5)
    return st


def close_all(sess):
    sess.ipc("shell", "request", "panels", "close", "", "")
    wait_ps(sess, lambda s: not s["windows"] or all(w.startswith(("banners", "hud")) for w in s["windows"]), 5)


def notify(sess, *args, wait=True):
    """notify-send (libnotify's standard client) against our server"""
    return sess.run(["notify-send"] + list(args), wait=wait)


def full_session(name, w=1280, h=800, scale=1.0, settings=None, media=True, plasma=False, system_opts=(), session_opts=(), glass=True,
                 audio=True):
    sess = ps.PanelsSession(width=w, height=h, scale=scale, name=name, glass=glass,
                            settings=settings or {"appearance": {"theme": "light", "glass": 0.3}})
    sess.start(wait_glass=glass)
    sess.start_system(*system_opts)
    art = os.path.join(sess.tmp, "art.png")
    make_art(art)
    sopts = list(session_opts) + (["--media", "--art", art] if media else [])
    sess.start_session_mocks(*sopts)
    if audio:
        sess.start_audio()
    busy_bg(sess, w, h)
    if plasma:
        sess.start_plasma()
    sess.start_shell()
    sess.wait_ready()
    sess.wait_panels()
    return sess


def make_art(path):
    """album art drawn here (no third-party artwork): a warm gradient with a sun"""
    w = 300
    y, x = np.mgrid[0:w, 0:w]
    img = np.zeros((w, w, 3), np.uint8)
    img[..., 0] = (250 - y * 0.4).clip(0, 255)
    img[..., 1] = (120 + x * 0.3 - y * 0.2).clip(0, 255)
    img[..., 2] = (90 + y * 0.45).clip(0, 255)
    d = np.hypot(x - 150, y - 170)
    img[d < 60] = (255, 214, 120)
    Image.fromarray(img).save(path)


# =================================================================================================
def test_static():
    print("== static", flush=True)
    files = [os.path.join(PANELS, "helper", "kristall-panels-helper")] + glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "support", "*.py"))
    for f in files:
        r = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True)
        check(f"{os.path.basename(f)} compiles", r.returncode == 0, r.stderr.strip())
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", "-S", "warning", os.path.join(PANELS, "image", "install.sh"), os.path.join(HERE, "run.sh")],
                           capture_output=True, text=True)
        check("shellcheck install.sh run.sh", r.returncode == 0, r.stdout[-800:])
    strings = json.load(open(os.path.join(PANELS, "strings.json")))
    check("strings: German and English have the same keys", set(strings["de"]) == set(strings["en"]), str(set(strings["de"]) ^ set(strings["en"])))
    check("strings: keys start with 'panels.'", all(k.startswith("panels.") for k in strings["en"]))
    core = json.load(open(os.path.join(SHELL, "strings", "strings.json")))["en"]
    used = set()
    for f in glob.glob(os.path.join(PANELS, "*.qml")):
        used |= set(re.findall(r'Strings\.tn?\("([a-zA-Z0-9_.]+)"', open(f, encoding="utf-8").read()))
    missing = sorted(k for k in used if not k.endswith(".") and k not in strings["en"] and k not in core and k + ".one" not in strings["en"])
    check("strings: every key used in QML exists", not missing, ", ".join(missing))
    dyn = [f"panels.energy.{m}" for m in ("quiet", "balanced", "performance")] + [f"panels.energy.{m}.hint" for m in ("auto", "quiet", "balanced", "performance")]
    check("strings: power mode names and hints exist", all(k in strings["en"] for k in dyn))
    # the qmldir lists every type of the module (Quickshell does not scan module directories)
    qmldir = open(os.path.join(PANELS, "qmldir")).read()
    types = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(PANELS, "*.qml")) if os.path.basename(f) != "Module.qml")
    listed = re.findall(r"^(?:singleton )?(\w+) 1\.0 \w+\.qml$", qmldir, re.M)
    check("qmldir lists every QML type", sorted(listed) == types, str(set(types) ^ set(listed)))
    single = [os.path.basename(f)[:-4] for f in glob.glob(os.path.join(PANELS, "*.qml")) if "pragma Singleton" in open(f).read()]
    check("qmldir marks the singletons", all(f"singleton {s} 1.0" in qmldir for s in single), str(single))
    bad = [os.path.basename(f) for f in glob.glob(os.path.join(PANELS, "*.qml"))
           if "pragma Singleton" in open(f).read() and any(c in open(f).read().split("pragma Singleton")[0] for c in "{}")]
    check("no braces before 'pragma Singleton'", not bad, str(bad))
    d = json.load(open(os.path.join(PANELS, "image", "settings.json")))
    check("settings drop-in owns only 'panels'", set(d) == {"panels"}, str(set(d)))
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(PANELS, "image", "settings.json"), os.path.join(tmp, "50-panels.json"))
    r = subprocess.run([os.path.join(REPO, "image", "rootfs", "usr", "bin", "kristall-settings"), "check-defaults"],
                       env=dict(os.environ, KRISTALL_SETTINGS_DROPIN_DIRS=tmp), capture_output=True, text=True)
    check("kristall-settings check-defaults accepts the drop-in", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    # symbols exist
    missing = []
    for f in glob.glob(os.path.join(PANELS, "*.qml")):
        for n in re.findall(r'"((?:fill|bold)/[a-z0-9-]+)"', open(f).read()):
            w, b = n.split("/")
            if not os.path.exists(os.path.join(SHELL, "icons", "phosphor", w, b + ".svg")):
                missing.append(n)
    check("every symbol exists in the bundled set", not missing, str(sorted(set(missing))))
    # namespaces start with kristall- and are the reserved ones
    ns = set()
    for f in glob.glob(os.path.join(PANELS, "*.qml")):
        ns |= set(re.findall(r'WlrLayershell\.namespace: "([^"]+)"', open(f).read()))
    check("layer-shell namespaces are the reserved kristall-cc/-notifications/-banners/-hud",
          ns == {"kristall-cc", "kristall-notifications", "kristall-banners", "kristall-hud"}, str(ns))
    # install into a scratch prefix
    pre = tempfile.mkdtemp()
    r = subprocess.run(["bash", os.path.join(PANELS, "image", "install.sh")], cwd=PANELS, capture_output=True, text=True,
                       env=dict(os.environ, KRISTALL_PREFIX=pre + "/usr", KRISTALL_SYSCONFDIR=pre + "/etc",
                                KRISTALL_CTX=REPO))
    inst = os.path.join(pre, "usr", "share", "kristall", "shell", "modules", "panels")
    check("install.sh installs the module, helper, OSD override, unit drop-in, shortcuts, defaults",
          r.returncode == 0 and os.path.exists(os.path.join(inst, "Module.qml")) and os.path.exists(os.path.join(inst, "qmldir"))
          and os.access(os.path.join(inst, "helper", "kristall-panels-helper"), os.X_OK)
          and os.path.exists(os.path.join(pre, "usr", "share", "kristall", "panels", "plasma-qml", "org", "kde", "plasma", "workspace", "osd", "Osd.qml"))
          and os.path.exists(os.path.join(pre, "usr", "lib", "systemd", "user", "plasma-plasmashell.service.d", "50-kristall-osd.conf"))
          and os.path.exists(os.path.join(pre, "usr", "share", "kglobalaccel", "org.kristall.panels.desktop"))
          and os.path.exists(os.path.join(pre, "usr", "share", "kristall", "defaults", "settings.d", "50-panels.json"))
          and not os.path.exists(os.path.join(inst, "tests")),
          (r.stdout + r.stderr)[-600:])
    shutil.rmtree(pre, ignore_errors=True)


# =================================================================================================
def test_cc():
    print("== Control Center: every module both ways", flush=True)
    W, H = 1280, 800
    sess = full_session("cc", W, H)
    try:
        wait_ps(sess, lambda s: s["hw"]["night"].get("available") and s["hw"]["backlight"] and s["media"]["available"], 8)
        st = open_cc(sess)
        time.sleep(1.0)
        warns = warnings(sess)
        check("shell + panels start with zero QML warnings (services mocked)", not warns, "\n".join(warns[:10]))
        c = st["cc"]["controls"]
        check("Control Center opens with its modules", all(x in c for x in ("cc.wifi", "cc.bt", "cc.focus", "cc.display", "cc.sound", "cc.kbd",
                                                                            "cc.energy.open", "cc.media.toggle", "cc.screenshot", "cc.nightlight")), str(c))
        check("the bar's Control Center button knows it is open", st["open"].get("control-center") == "Virtual-0", str(st["open"]))

        # ---- Wi-Fi on/off
        sess.pt("click", "cc.wifi")
        ok = wait_until(lambda: "false" in sess.gdbus("--dest", "org.freedesktop.NetworkManager", "--object-path", "/org/freedesktop/NetworkManager",
                                                      "--method", "org.freedesktop.DBus.Properties.Get", "org.freedesktop.NetworkManager",
                                                      "WirelessEnabled", system=True), 5)
        check("Wi-Fi button → NetworkManager WirelessEnabled off", bool(ok))
        st = wait_ps(sess, lambda s: not s["hw"]["wifiEnabled"])
        check("… and the button shows off", shown(sess, "cc.wifi").get("on") is False)
        sess.mocksys("SetWifiEnabled", True)
        wait_ps(sess, lambda s: s["hw"]["wifiEnabled"])
        check("Wi-Fi switched on elsewhere → button on", shown(sess, "cc.wifi").get("on") is True)

        # ---- Bluetooth
        sess.pt("click", "cc.bt")
        st = wait_ps(sess, lambda s: not s["hw"]["btEnabled"])
        check("Bluetooth button → adapter powered off", not st["hw"]["btEnabled"])
        sess.mocksys("SetAdapterPowered", True)
        wait_ps(sess, lambda s: s["hw"]["btEnabled"])
        check("Bluetooth powered on elsewhere → button on", shown(sess, "cc.bt").get("on") is True)

        # ---- Do Not Disturb
        sess.pt("click", "cc.focus")
        st = wait_ps(sess, lambda s: s["notifications"]["dnd"])
        check("Focus button → Do Not Disturb on (until switched off)", st["notifications"]["dnd"] and st["notifications"]["dndUntil"] == -1,
              json.dumps(st["notifications"]))
        sess.settings_set("panels.focus.until", 0)
        wait_ps(sess, lambda s: not s["notifications"]["dnd"])
        check("Do Not Disturb off elsewhere (settings) → button off", shown(sess, "cc.focus").get("on") is False)

        # ---- brightness (PowerDevil org.kde.ScreenBrightness)
        sess.calls(system=False)
        sess.pt("slide", "cc.display", 0.3)
        ok = wait_until(lambda: [x for x in sess.calls(system=False) if x.get("method") == "SetBrightness"], 4)
        check("brightness slider → SetBrightness 3000/10000 with the 'no OSD' flag",
              bool(ok) and ok[-1]["value"] == 3000 and ok[-1]["flags"] == 1, json.dumps(ok))
        # while the owner is dragging, values coming back do not move the knob (no jitter)
        sess.pt("slide", "cc.display", 0.35)
        sess.mocksess("SetBrightness", 9000)
        time.sleep(0.2)
        a = shown(sess, "cc.display").get("shown")
        time.sleep(1.2)
        b = shown(sess, "cc.display").get("shown")
        check("no jitter while dragging; afterwards the slider follows the service", abs(a - 0.35) < 0.01 and abs(b - 0.9) < 0.01, f"{a} {b}")
        sess.mocksess("SetBrightness", 2000)
        wait_ps(sess, lambda s: abs(s["hw"]["brightness"] - 0.2) < 0.01)
        time.sleep(0.3)
        check("brightness changed elsewhere (keys) → slider moves", abs(shown(sess, "cc.display").get("shown", 0) - 0.2) < 0.01)

        # ---- volume (PipeWire)
        sess.pt("slide", "cc.sound", 0.4)
        ok = wait_until(lambda: "0.40" in sess.wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"), 4)
        check("volume slider → PipeWire default sink 0.40", bool(ok), sess.wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"))
        time.sleep(0.8)
        sess.wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", "0.70")
        wait_ps(sess, lambda s: abs(s["audio"]["volume"] - 0.7) < 0.02)
        time.sleep(0.3)
        check("volume changed elsewhere → slider moves", abs(shown(sess, "cc.sound").get("shown", 0) - 0.7) < 0.02, str(shown(sess, "cc.sound")))
        sess.pt("click", "cc.sound.mute")
        ok = wait_until(lambda: "MUTED" in sess.wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"), 4)
        check("speaker symbol in the slider mutes", bool(ok))
        time.sleep(0.3)
        check("muted → slider at zero", shown(sess, "cc.sound").get("shown") == 0)
        sess.wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", "0")
        wait_ps(sess, lambda s: not s["audio"]["muted"])

        # ---- keyboard backlight
        sess.pt("slide", "cc.kbd", 1.0)
        ok = wait_until(lambda: [x for x in sess.calls(system=False) if x.get("method") == "setKeyboardBrightnessSilent"], 4)
        check("keyboard slider → setKeyboardBrightnessSilent 3/3", bool(ok) and ok[-1]["value"] == 3, json.dumps(ok))
        time.sleep(1.0)
        sess.mocksess("SetKbd", 0)
        wait_ps(sess, lambda s: s["hw"]["kbdLevel"] == 0)
        time.sleep(0.3)
        check("keyboard backlight changed elsewhere → slider moves", shown(sess, "cc.kbd").get("shown") == 0)

        # ---- Night Light (the real KWin NightLight interface of the headless KWin)
        st = sess.pstate()
        info("night light as KWin reports it: " + json.dumps(st["hw"]["night"]))
        if st["hw"]["night"].get("available"):
            sess.pt("click", "cc.nightlight")
            st = wait_ps(sess, lambda s: s["hw"]["nightOn"], 8)
            check("Night Light button → KWin night light enabled (kwinrc + reloadConfig)", st["hw"]["nightOn"], json.dumps(st["hw"]["night"]))
            sess.pt("click", "cc.nightlight")
            st = wait_ps(sess, lambda s: not s["hw"]["nightOn"], 8)
            check("Night Light button again → inhibited (as Plasma's applet does)", not st["hw"]["nightOn"] and st["hw"]["night"].get("inhibited"),
                  json.dumps(st["hw"]["night"]))

        # ---- now playing (MPRIS)
        st = sess.pstate()
        check("now playing from MPRIS: title, artist", st["media"]["title"] == "Morgenlicht" and st["media"]["artist"] == "Die Kristalle", json.dumps(st["media"]))
        sess.calls(system=False)
        sess.pt("click", "cc.media.toggle")
        ok = wait_until(lambda: [x for x in sess.calls(system=False) if x.get("method") in ("PlayPause", "Pause")], 4)
        check("play/pause → the player", bool(ok))
        st = wait_ps(sess, lambda s: not s["media"]["playing"])
        check("player paused → the button shows play", not st["media"]["playing"])
        sess.mocksess("SetPlaying", True)
        wait_ps(sess, lambda s: s["media"]["playing"])
        sess.pt("click", "cc.media.next")
        st = wait_ps(sess, lambda s: s["media"]["title"] == "Abendrot")
        check("next → new track shown", st["media"]["title"] == "Abendrot", json.dumps(st["media"]))

        # ---- appearance (shell setting appearance.theme)
        sess.pt("page", "display")
        wait_ps(sess, lambda s: s["cc"]["page"] == "display")
        sess.pt("segment", "cc.display.appearance", 1)
        st = wait_ps(sess, lambda s: s["theme"] == "dark")
        check("Appearance: Dunkel → appearance.theme dark, the shell turns dark", st["theme"] == "dark")
        sess.settings_set("appearance.theme", "light")
        wait_ps(sess, lambda s: s["theme"] == "light")
        time.sleep(0.3)
        check("appearance changed elsewhere → segment follows", shown(sess, "cc.display.appearance").get("index") == 0)

        # ---- energy modes (power contract: power-profiles API + kristall-power mode auto)
        state = os.path.join(sess.runtime, "kristall", "power.json")

        def daemon(manual):
            with open(state + ".tmp", "w") as f:
                json.dump({"schema": 1, "automatic": True, "manual": manual, "reason": "manual" if manual else "auto", "mode": "balanced"}, f)
            os.replace(state + ".tmp", state)
        daemon(None)
        sess.pt("page", "energy")
        st = wait_ps(sess, lambda s: s["cc"]["page"] == "energy" and s["power"]["selected"] == "auto")
        check("Automatisch is offered and shown chosen (session daemon: automatic, no manual choice)",
              st["power"]["selected"] == "auto" and "cc.energy.auto" in st["cc"]["controls"], json.dumps(st["power"]))
        time.sleep(0.6)
        sess.pt("click", "cc.energy.quiet")
        ok = wait_until(lambda: "power-saver" in sess.gdbus("--dest", "org.freedesktop.UPower.PowerProfiles", "--object-path",
                                                           "/org/freedesktop/UPower/PowerProfiles", "--method", "org.freedesktop.DBus.Properties.Get",
                                                           "org.freedesktop.UPower.PowerProfiles", "ActiveProfile", system=True), 4)
        daemon({"mode": "quiet", "on_battery": True, "since": "now"})       # what the daemon records for a hand-picked mode
        st = wait_ps(sess, lambda s: s["power"]["selected"] == "quiet")
        check("Leise → power-profiles power-saver; shown as the owner's choice", bool(ok) and st["power"]["selected"] == "quiet", json.dumps(st["power"]))
        sess.gdbus("--dest", "org.freedesktop.UPower.PowerProfiles", "--object-path", "/org/freedesktop/UPower/PowerProfiles", "--method",
                   "org.freedesktop.DBus.Properties.Set", "org.freedesktop.UPower.PowerProfiles", "ActiveProfile", "<'performance'>", system=True)
        st = wait_ps(sess, lambda s: s["power"]["mode"] == "performance")
        check("profile changed elsewhere (hotkey) → Leistung checked", st["power"]["selected"] == "performance" and shown(sess, "cc.energy.performance").get("checked") is True)
        sess.pt("click", "cc.energy.auto")
        st = wait_ps(sess, lambda s: s["power"]["selected"] == "auto")
        calls = open(os.path.join(sess.tmp, "power-calls.log")).read() if os.path.exists(os.path.join(sess.tmp, "power-calls.log")) else ""
        check("Automatisch → kristall-power mode auto", st["power"]["selected"] == "auto" and "mode auto" in calls, calls)
        check("kristall-power status --json was read for the battery details", "status --json" in calls, calls)
        sess.save_evidence(sess.screenshot(), "cc-energy-expanded-light-1.0x.png", crop=(W - 420, 0, W, 520))

        # ---- sound page: outputs and the microphone in use
        sess.pt("page", "sound")
        st = wait_ps(sess, lambda s: s["cc"]["page"] == "sound" and len(s["hw"]["sinks"]) >= 2)
        check("Sound: both outputs listed", set(st["hw"]["sinks"]) >= {"Lautsprecher (Test)", "Kopfhörer (Test)"}, str(st["hw"]["sinks"]))
        sess.pt("click", "cc.sound.out:Kopfhörer (Test)")
        st = wait_ps(sess, lambda s: s["hw"]["defaultSink"] == "Kopfhörer (Test)")
        check("choosing an output makes it the default sink", st["hw"]["defaultSink"] == "Kopfhörer (Test)", st["hw"]["defaultSink"])
        sess.pt("click", "cc.sound.out:Lautsprecher (Test)")
        wait_ps(sess, lambda s: s["hw"]["defaultSink"] == "Lautsprecher (Test)")
        rec = sess.record("Rekorder")
        st = wait_ps(sess, lambda s: s["hw"]["micInUse"], 8)
        check("microphone in use is shown, with the app", st["hw"]["micInUse"] and st["hw"]["micUser"] == "Rekorder", json.dumps(st["hw"]))
        time.sleep(0.5)
        sess.save_evidence(sess.screenshot(), "cc-sound-expanded-light-1.0x.png", crop=(W - 420, 0, W, 520))
        rec.terminate()
        st = wait_ps(sess, lambda s: not s["hw"]["micInUse"], 8)
        check("… and disappears when it stops", not st["hw"]["micInUse"])

        # ---- Bluetooth page: devices, battery, connect/disconnect
        sess.pt("page", "bluetooth")
        st = wait_ps(sess, lambda s: len(s["hw"]["bt"]) == 2)
        bt = {d["name"]: d for d in st["hw"]["bt"]}
        check("Bluetooth: paired devices, connected first, battery where reported",
              list(bt) == ["AirPods Kristall", "Maus"] and abs(bt["AirPods Kristall"]["battery"] - 0.8) < 0.01, json.dumps(st["hw"]["bt"]))
        sess.mocksys("Calls")
        sess.pt("click", "cc.bt.dev:Maus")
        st = wait_ps(sess, lambda s: any(d["name"] == "Maus" and d["connected"] for d in s["hw"]["bt"]))
        check("click a device → it connects", any(d["name"] == "Maus" and d["connected"] for d in st["hw"]["bt"]))
        sess.pt("click", "cc.bt.dev:AirPods Kristall")
        st = wait_ps(sess, lambda s: any(d["name"] == "AirPods Kristall" and not d["connected"] for d in s["hw"]["bt"]))
        check("click a connected device → it disconnects", any(d["name"] == "AirPods Kristall" and not d["connected"] for d in st["hw"]["bt"]))
        sess.mocksys("SetDeviceConnected", "AirPods Kristall", True)
        st = wait_ps(sess, lambda s: any(d["name"] == "AirPods Kristall" and d["connected"] for d in s["hw"]["bt"]))
        check("device connected elsewhere → shown connected", any(d["name"] == "AirPods Kristall" and d["connected"] for d in st["hw"]["bt"]))

        # ---- keyboard and pointer, the real input pipeline
        sess.pt("page", "main")
        owner = sess.owner()
        try:
            owner.key("esc")
            st = wait_ps(sess, lambda s: "cc:Virtual-0" not in s["windows"], 4)
            check("Escape closes Control Center", "cc:Virtual-0" not in st["windows"], json.dumps(st["windows"]))
            open_cc(sess, "wifi")
            owner.key("esc")
            st = wait_ps(sess, lambda s: s["cc"]["page"] == "main", 3)
            check("Escape in an expanded module goes back first", st["cc"]["page"] == "main")
            # Tab reaches the first control; Space switches it
            owner.key("tab")
            time.sleep(0.2)
            owner.key("space")
            st = wait_ps(sess, lambda s: not s["hw"]["wifiEnabled"], 4)
            check("keyboard: Tab to Wi-Fi, Space switches it", not st["hw"]["wifiEnabled"])
            owner.key("space")
            wait_ps(sess, lambda s: s["hw"]["wifiEnabled"], 4)
            owner.click(200, 500)
            st = wait_ps(sess, lambda s: "cc:Virtual-0" not in s["windows"], 4)
            check("a click outside closes it", "cc:Virtual-0" not in st["windows"])
            # a real click on a tile
            open_cc(sess)
            r = json.loads(sess.pt("rect", "cc.focus"))
            owner.click(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
            st = wait_ps(sess, lambda s: s["notifications"]["dnd"], 4)
            check("a real click on the Focus button switches Do Not Disturb", st["notifications"]["dnd"])
            owner.click(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
            wait_ps(sess, lambda s: not s["notifications"]["dnd"], 4)
        finally:
            owner.close()
        # another popover (a menu-bar menu) closes it
        open_cc(sess)
        sess.ipc("test", "openMenu", 0, "")
        st = wait_ps(sess, lambda s: "cc:Virtual-0" not in s["windows"], 4)
        check("a menu-bar menu opening closes Control Center", "cc:Virtual-0" not in st["windows"])
        sess.ipc("test", "close")
        sess.ipc("shell", "request", "panels", "toggle-control-center", "", "")
        wait_ps(sess, lambda s: "cc:Virtual-0" in s["windows"])
        sess.ipc("shell", "request", "panels", "toggle-notifications", "", "")
        st = wait_ps(sess, lambda s: "cc:Virtual-0" not in s["windows"] and "nc:Virtual-0" in s["windows"], 4)
        check("Notification Centre opening closes Control Center", "cc:Virtual-0" not in st["windows"] and "nc:Virtual-0" in st["windows"])
        close_all(sess)
        warns = warnings(sess)
        check("still zero warnings after the whole Control Center run", not warns, "\n".join(warns[:10]))
    finally:
        sess.stop()


# =================================================================================================
def test_wifi():
    print("== Wi-Fi: networks, joining, our password sheet", flush=True)
    W, H = 1280, 800
    sess = full_session("wifi", W, H)
    try:
        open_cc(sess, "wifi")
        st = wait_ps(sess, lambda s: len(s["hw"]["networks"]) == 4)
        nets = st["hw"]["networks"]
        check("networks: connected first, then known, then by signal; lock where protected",
              [n["name"] for n in nets] == ["Zuhause", "Büro", "Café Sonne", "Nachbar"] and nets[0]["connected"] and nets[1]["known"]
              and not nets[2]["secured"] and nets[3]["secured"], json.dumps(nets, ensure_ascii=False))
        sess.calls()
        sess.pt("click", "cc.wifi.net:Büro")
        st = wait_ps(sess, lambda s: any(n["name"] == "Büro" and n["connected"] for n in s["hw"]["networks"]), 6)
        calls = sess.calls()
        check("a known network connects at once (no password asked)", any(n["name"] == "Büro" and n["connected"] for n in st["hw"]["networks"])
              and st["cc"]["page"] == "wifi", json.dumps(calls, ensure_ascii=False))
        sess.pt("click", "cc.wifi.net:Nachbar")
        st = wait_ps(sess, lambda s: s["cc"]["page"] == "password")
        check("a new protected network opens our password sheet", st["cc"]["page"] == "password")
        time.sleep(0.4)
        sess.pt("type", "cc.wifi.password", "falsch123")
        sess.pt("click", "cc.wifi.join")
        time.sleep(2.0)
        calls = sess.calls()
        add = [c for c in calls if c.get("method") == "AddAndActivateConnection"]
        st = sess.pstate()
        check("Join → NetworkManager AddAndActivateConnection with the key, owned by the user",
              add and add[0]["ssid"] == "Nachbar" and add[0]["pskGiven"] and add[0]["keyMgmt"] == "wpa-psk" and add[0]["permissions"],
              json.dumps(calls, ensure_ascii=False))
        check("a refused password: the sheet stays and says so; nothing wrong is kept",
              st["cc"]["page"] == "password" and any(c.get("method") == "Delete" for c in calls), json.dumps(calls, ensure_ascii=False))
        sess.save_evidence(sess.screenshot(), "cc-wifi-password-wrong-light-1.0x.png", crop=(W - 420, 0, W, 420))
        sess.pt("type", "cc.wifi.password", "richtig123")
        sess.pt("accept", "cc.wifi.password")
        st = wait_ps(sess, lambda s: s["cc"]["page"] == "wifi" and any(n["name"] == "Nachbar" and n["connected"] for n in s["hw"]["networks"]), 8)
        check("the right password joins and the sheet returns to the list",
              st["cc"]["page"] == "wifi" and any(n["name"] == "Nachbar" and n["connected"] for n in st["hw"]["networks"]), json.dumps(st["hw"]["networks"], ensure_ascii=False))
        sess.pt("click", "cc.wifi.net:Zuhause")
        wait_ps(sess, lambda s: any(n["name"] == "Zuhause" and n["connected"] for n in s["hw"]["networks"]), 6)
        time.sleep(0.8)
        sess.save_evidence(sess.screenshot(), "cc-wifi-expanded-light-1.0x.png", crop=(W - 420, 0, W, 520))
        sess.pt("click", "cc.wifi.net:Café Sonne")
        st = wait_ps(sess, lambda s: any(n["name"] == "Café Sonne" and n["connected"] for n in s["hw"]["networks"]), 6)
        check("an open network joins without a sheet", st["cc"]["page"] == "wifi" and any(n["name"] == "Café Sonne" and n["connected"] for n in st["hw"]["networks"]))
        sess.mocksys("SetApStrength", "Nachbar", 90)
        st = wait_ps(sess, lambda s: any(n["name"] == "Nachbar" and n["strength"] > 0.85 for n in s["hw"]["networks"]))
        check("signal strength changes are pushed into the list", any(n["name"] == "Nachbar" and n["strength"] > 0.85 for n in st["hw"]["networks"]))
        warns = warnings(sess)
        check("zero warnings in the Wi-Fi run", not warns, "\n".join(warns[:10]))
    finally:
        sess.stop()


# =================================================================================================
def test_notifications():
    print("== notifications: our server with plasmashell in the session", flush=True)
    W, H = 1280, 800
    sess = full_session("notif", W, H, plasma=True)
    try:
        names = sess.bus_names()
        owner = sess.gdbus("--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus", "--method",
                           "org.freedesktop.DBus.GetConnectionUnixProcessID", "org.freedesktop.Notifications")
        m = re.search(r"uint32 (\d+)", owner)
        pid = int(m.group(1)) if m else 0
        check("plasmashell runs (desktop only) and does not claim org.freedesktop.Notifications",
              "org.kde.plasmashell" in names and pid in children_of(sess.shell.pid),
              f"owner pid {pid} ({open(f'/proc/{pid}/cmdline').read().replace(chr(0), ' ') if pid else ''}), shell {sess.shell.pid}")
        # plain
        r = notify(sess, "-a", "Mail", "-i", "mail-message-new", "Anna Berger", "Kommst du heute Abend zum Essen? Ich habe einen Tisch reserviert.")
        st = wait_ps(sess, lambda s: s["banners"])
        b = st["banners"][0] if st["banners"] else {}
        check("notify-send: a plain notification shows as a banner (title, body, app)",
              r.returncode == 0 and b.get("summary") == "Anna Berger" and "Tisch" in b.get("body", "") and b.get("app") == "Mail", json.dumps(b, ensure_ascii=False))
        # image
        img = os.path.join(sess.tmp, "photo.png")
        make_art(img)
        notify(sess, "-a", "Fotos", "-h", f"string:image-path:{img}", "Neues Foto", "Sonnenuntergang am See")
        st = wait_ps(sess, lambda s: any(x["summary"] == "Neues Foto" for x in s["banners"]))
        b = [x for x in st["banners"] if x["summary"] == "Neues Foto"]
        check("with an image (image-path)", b and b[0]["image"].endswith("photo.png"), json.dumps(b))
        p = sess.run(NOTIFY + ["--app", "Chat", "--summary", "Lena", "--body", "Bild", "--image-data", "--desktop-entry", "org.kde.neochat"], wait=True)
        st = wait_ps(sess, lambda s: any(x["summary"] == "Lena" for x in s["banners"]))
        b = [x for x in st["banners"] if x["summary"] == "Lena"]
        check("with an image (raw image-data)", b and b[0]["image"].startswith("image://"), json.dumps(b))
        # actions
        p = sess.run(["notify-send", "-a", "Kalender", "-A", "later=Später", "-A", "open=Öffnen", "--wait", "Termin", "Zahnarzt um 15 Uhr"], wait=False)
        st = wait_ps(sess, lambda s: any(x["summary"] == "Termin" for x in s["banners"]))
        b = [x for x in st["banners"] if x["summary"] == "Termin"][0]
        check("with actions: buttons for each", [a["text"] for a in b["actions"]] == ["Später", "Öffnen"], json.dumps(b["actions"], ensure_ascii=False))
        sess.pt("notifSet", b["key"], "action", "later")
        try:
            out = p.communicate(timeout=6)[0].strip()
        except subprocess.TimeoutExpired:
            out = ""
        check("an action button reaches the app (ActionInvoked)", out == "later", out)
        time.sleep(1.0)
        sess.save_evidence(sess.screenshot(), "banners-stack-light-1.0x.png", crop=(W - 440, 0, W, 470))
        # replacing in place, with progress
        r = notify(sess, "-a", "Dateien", "-p", "-h", "int:value:10", "Kopieren", "3 Objekte werden kopiert")
        nid = r.stdout.strip()
        st = wait_ps(sess, lambda s: any(x["summary"] == "Kopieren" for x in s["banners"]))
        key = [x for x in st["banners"] if x["summary"] == "Kopieren"][0]["key"]
        notify(sess, "-a", "Dateien", "-r", nid, "-h", "int:value:70", "Kopieren", "3 Objekte werden kopiert")
        st = wait_ps(sess, lambda s: any(x["summary"] == "Kopieren" and x["progress"] == 70 for x in s["banners"]))
        same = [x for x in st["banners"] if x["summary"] == "Kopieren"]
        check("replacing (replaces_id) updates the same banner in place, progress 10 → 70",
              len(same) == 1 and same[0]["key"] == key and same[0]["progress"] == 70, json.dumps(same))
        # urgent ones stay; normal ones leave after ~5 s and are kept in Notification Centre
        notify(sess, "-a", "System", "-u", "critical", "Akku fast leer", "Bitte das Netzteil anschließen.")
        wait_ps(sess, lambda s: any(x["summary"] == "Akku fast leer" for x in s["banners"]))
        time.sleep(7.0)
        st = sess.pstate()
        check("critical stays on screen; normal banners leave after ~5 s", [x["summary"] for x in st["banners"]] == ["Akku fast leer"],
              json.dumps([x["summary"] for x in st["banners"]], ensure_ascii=False))
        check("… and everything is in the history", st["notifications"]["count"] >= 5, json.dumps(st["notifications"]["groups"], ensure_ascii=False))
        sess.pt("notifSet", [x for x in st["banners"]][0]["key"], "remove", "")
        # grouping: three from one app stack into one banner and one group
        for i in range(3):
            notify(sess, "-a", "Nachrichten", "-h", "string:desktop-entry:org.kde.neochat", f"Tom {i + 1}", f"Nachricht Nummer {i + 1}")
            time.sleep(0.3)
        st = wait_ps(sess, lambda s: any(x["summary"] == "Tom 3" for x in s["banners"]))
        tom = [x for x in st["banners"] if x["summary"].startswith("Tom")]
        g = [x for x in st["notifications"]["groups"] if x["key"] == "org.kde.neochat"]
        check("one app's banners stack (newest in front, two behind); grouped by app in the history",
              len(tom) == 1 and tom[0]["stacked"] == 2 and g and g[0]["count"] >= 3, json.dumps(tom) + json.dumps(g))
        time.sleep(0.8)
        sess.save_evidence(sess.screenshot(), "banners-grouped-light-1.0x.png", crop=(W - 440, 0, W, 300))
        # default action brings the window forward through the bridge
        sess.ctl({"cmd": "open", "window": {"id": "w-files", "appId": "org.kde.dolphin", "title": "Downloads", "x": 100, "y": 100, "w": 600, "h": 400}})
        sess.ctl({"cmd": "open", "window": {"id": "w-other", "appId": "org.kde.kate", "title": "Notizen", "x": 200, "y": 150, "w": 600, "h": 400}})
        time.sleep(0.5)
        sess.ctl({"cmd": "calls"})
        p = sess.run(NOTIFY + ["--app", "Dateien", "--summary", "Download fertig", "--body", "bericht.pdf", "--desktop-entry", "org.kde.dolphin",
                               "--action", "default=Öffnen", "--wait", "8"], wait=False)
        p.stdout.readline()
        st = wait_ps(sess, lambda s: any(x["summary"] == "Download fertig" for x in s["banners"]))
        b = [x for x in st["banners"] if x["summary"] == "Download fertig"][0]
        sess.pt("notifSet", b["key"], "activate", "")
        line = p.stdout.readline().strip()
        calls = sess.ctl({"cmd": "calls"})
        check("click → default action (ActionInvoked 'default') and the app's window activated through the bridge",
              '"default"' in line and any(c["method"] == "window.activate" and c["params"].get("id") == "w-files" for c in calls), line + json.dumps(calls)[:300])
        # Do Not Disturb, full screen, locked screen
        sess.pt("hideBanners")
        sess.settings_set("panels.focus.until", -1)
        wait_ps(sess, lambda s: s["notifications"]["dnd"])
        notify(sess, "-a", "Mail", "Leise", "Kommt nur in die Mitteilungszentrale")
        notify(sess, "-a", "System", "-u", "critical", "Wichtig", "Kommt trotzdem")
        st = wait_ps(sess, lambda s: any(x["summary"] == "Wichtig" for x in s["banners"]))
        hist = [x for g in st["notifications"]["groups"] for x in g["summaries"]]
        check("Do Not Disturb: no banner (critical still), but kept in the history",
              [x["summary"] for x in st["banners"]] == ["Wichtig"] and "Leise" in hist, json.dumps([x["summary"] for x in st["banners"]]))
        sess.settings_set("panels.focus.until", 0)
        sess.pt("hideBanners")
        sess.ctl({"cmd": "set", "id": "w-other", "changes": {"fullscreen": True, "x": 0, "y": 0, "w": W, "h": H}})
        sess.ctl({"cmd": "activate", "id": "w-other"})
        time.sleep(0.5)
        notify(sess, "-a", "Mail", "Im Vollbild", "kein Banner")
        time.sleep(1.0)
        check("a full-screen app in front: no banner", not sess.pstate()["banners"])
        sess.ctl({"cmd": "set", "id": "w-other", "changes": {"fullscreen": False}})
        sess.mocksess("SetLocked", True)
        wait_ps(sess, lambda s: s["hw"]["locked"])
        notify(sess, "-a", "Mail", "Gesperrt", "Privat")
        time.sleep(1.0)
        check("screen locked: nothing shown", not sess.pstate()["banners"])
        sess.mocksess("SetLocked", False)
        wait_ps(sess, lambda s: not s["hw"]["locked"])
        # per-app muting from the banner's context menu (our glass menu)
        notify(sess, "-a", "Werbung", "Angebot", "Nur heute!")
        st = wait_ps(sess, lambda s: any(x["summary"] == "Angebot" for x in s["banners"]))
        b = [x for x in st["banners"] if x["summary"] == "Angebot"][0]
        sess.pt("notifSet", b["key"], "menu", "")
        time.sleep(0.5)
        mst = sess.state()
        items = mst["levels"][0]["items"] if mst.get("levels") else []
        check("context menu: clear, clear app, mute app", any("stummschalten" in i for i in items) and any(i.startswith("Löschen") for i in items),
              json.dumps(items, ensure_ascii=False))
        sess.save_evidence(sess.screenshot(), "banner-context-menu-light-1.0x.png", crop=(W - 520, 0, W, 360))
        idx = [i for i, t in enumerate(items) if "stummschalten" in t][0]
        for _ in range(len([t for t in items[:idx + 1] if not t.startswith("-")])):
            sess.ipc("test", "key", "down", "")
        sess.ipc("test", "key", "return", "")
        st = wait_ps(sess, lambda s: "werbung" in s["notifications"]["muted"])
        sess.pt("hideBanners")
        notify(sess, "-a", "Werbung", "Noch ein Angebot", "…")
        time.sleep(1.0)
        st = sess.pstate()
        check("muted app: no banners, still collected", "werbung" in st["notifications"]["muted"] and not st["banners"]
              and any("Noch ein Angebot" in g["summaries"] for g in st["notifications"]["groups"]), json.dumps(st["notifications"]["muted"]))
        # inline reply (KDE's inline-reply extension)
        p = sess.run(NOTIFY + ["--app", "Nachrichten", "--summary", "Lisa", "--body", "Treffen wir uns um 8?", "--reply", "Antwort …",
                               "--desktop-entry", "org.kde.neochat", "--wait", "8"], wait=False)
        p.stdout.readline()
        st = wait_ps(sess, lambda s: any(x["summary"] == "Lisa" for x in s["banners"]))
        b = [x for x in st["banners"] if x["summary"] == "Lisa"][0]
        check("inline reply offered", b["reply"], json.dumps(b))
        sess.pt("notifSet", b["key"], "reply", "Ja, bis später!")
        line = p.stdout.readline().strip()
        check("inline reply reaches the app (NotificationReplied)", "Ja, bis später!" in json.loads(line).get("replied", "") if line else False, line)
        # Notification Centre
        sess.pt("hideBanners")
        sess.ipc("shell", "request", "panels", "toggle-notifications", "", "")
        st = wait_ps(sess, lambda s: s.get("nc", {}).get("open"))
        time.sleep(1.0)
        check("Notification Centre opens from the clock request; widgets and groups",
              "nc.clearAll" in st["nc"]["controls"] and st["open"].get("notifications") == "Virtual-0", json.dumps(st.get("nc"))[:400])
        sess.save_evidence(sess.screenshot(), "notification-centre-groups-light-1.0x.jpg", crop=(W - 440, 0, W, H))
        groups = st["notifications"]["groups"]
        n0 = st["notifications"]["count"]
        # restart: the history survives within the session
        sess.stop_proc(sess.shell)
        sess.start_shell(bridge=False)
        sess.wait_ready()
        st = wait_ps(sess, lambda s: s["notifications"]["count"] > 0 and s["helper"]["notifyOwner"].get("mine"), 10)
        check("history survives a shell restart (session runtime dir)", st["notifications"]["count"] == n0, f"{st['notifications']['count']} vs {n0}")
        check("after the restart our shell owns the notification service again", st["helper"]["notifyOwner"].get("mine") is True, json.dumps(st["helper"]))
        sess.ipc("shell", "request", "panels", "show-notifications", "", "")
        st = wait_ps(sess, lambda s: s.get("nc", {}).get("open"))
        sess.pt("click", "nc.clearAll")
        st = wait_ps(sess, lambda s: s["notifications"]["count"] == 0)
        check("Clear All empties it", st["notifications"]["count"] == 0)
        close_all(sess)
        warns = warnings(sess)
        check("zero warnings in the notifications run", not warns, "\n".join(warns[:10]))
        results["notifications_groups"] = len(groups)
    finally:
        sess.stop()


# =================================================================================================
def test_hud():
    print("== HUD: Plasma's OSD replaced by ours (real plasmashell)", flush=True)
    W, H = 1280, 800
    sess = full_session("hud", W, H, plasma=True)
    try:
        plasma_log = open(os.path.join(sess.tmp, "plasma.log")).read()
        base = sess.screenshot()
        osd = ["--dest", "org.kde.plasmashell", "--object-path", "/org/kde/osdService", "--method"]
        for kind, method, args in (("volume", "org.kde.osdService.volumeChanged", ["45", "100"]),
                                   ("brightness", "org.kde.osdService.brightnessChanged", ["60"]),
                                   ("kbd", "org.kde.osdService.keyboardBrightnessChanged", ["2"])):
            sess.gdbus(*osd, method, *args)
            st = wait_ps(sess, lambda s: s.get("hud", {}).get("kind") == kind and s["hud"]["fade"] > 0.99, 4)
            check(f"{kind}: plasmashell's OSD call shows our HUD", st.get("hud", {}).get("kind") == kind, json.dumps(st.get("hud")))
            img = sess.screenshot()
            # Plasma draws its OSD centred in the lower half; ours is top right
            lower = np.abs(img[int(H * 0.55):int(H * 0.85), int(W * 0.3):int(W * 0.7), :3].astype(int) - base[int(H * 0.55):int(H * 0.85), int(W * 0.3):int(W * 0.7), :3].astype(int)).mean()
            check(f"{kind}: Plasma's own OSD does not appear", lower < 2.0, f"mean change {lower:.2f}")
            sess.save_evidence(img, f"hud-{kind}-light-1.0x.png", crop=(W - 400, 0, W, 160))
            wait_ps(sess, lambda s: "hud:Virtual-0" not in s["windows"], 5)
        st = sess.pstate()
        check("the HUD goes away by itself (window unmapped)", "hud:Virtual-0" not in st["windows"])
        # the level follows live changes while shown (holding the key)
        sess.gdbus(*osd, "org.kde.osdService.volumeChanged", "45", "100")
        wait_ps(sess, lambda s: s.get("hud", {}).get("kind") == "volume")
        sess.wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", "0.25")
        st = wait_ps(sess, lambda s: abs(s.get("hud", {}).get("level", 0) - 0.25) < 0.02, 3)
        check("HUD level follows the real volume", abs(st.get("hud", {}).get("level", 0) - 0.25) < 0.02, json.dumps(st.get("hud")))
        sess.gdbus(*osd, "org.kde.osdService.kbdLayoutChanged", "Deutsch")
        st = wait_ps(sess, lambda s: s.get("hud", {}).get("kind") == "text", 3)
        check("other Plasma OSDs (keyboard layout) show as a text HUD", st.get("hud", {}).get("title") == "Deutsch", json.dumps(st.get("hud")))
        # dark
        sess.write_settings({"appearance": {"theme": "dark", "glass": 0.3}})
        wait_ps(sess, lambda s: s["theme"] == "dark")
        for kind, method, args in (("volume", "org.kde.osdService.volumeChanged", ["60", "100"]), ("brightness", "org.kde.osdService.brightnessChanged", ["40"])):
            sess.gdbus(*osd, method, *args)
            wait_ps(sess, lambda s: s.get("hud", {}).get("kind") == kind and s["hud"]["fade"] > 0.99, 4)
            time.sleep(0.6)
            sess.save_evidence(sess.screenshot(), f"hud-{kind}-dark-1.0x.png", crop=(W - 400, 0, W, 160))
        check("plasmashell loaded our OSD replacement (no Plasma OSD window was created)",
              "Failed to load OSD" not in plasma_log and "Failed to create OSD" not in open(os.path.join(sess.tmp, "plasma.log")).read())
        warns = warnings(sess)
        check("zero warnings in the HUD run", not warns, "\n".join(warns[:10]))
    finally:
        sess.stop()


# =================================================================================================
def test_absent():
    print("== absent hardware: no Wi-Fi, Bluetooth, battery, backlight, keyboard light, audio, player", flush=True)
    W, H = 1280, 800
    sess = full_session("absent", W, H, media=False, audio=False, system_opts=("--no-wifi", "--no-bluetooth", "--no-battery"),
                        session_opts=("--no-backlight", "--no-kbd"))
    try:
        st = open_cc(sess)
        time.sleep(0.8)
        c = st["cc"]["controls"]
        gone = [x for x in ("cc.wifi", "cc.bt", "cc.display", "cc.kbd", "cc.sound", "cc.media.toggle") if x in c]
        check("absent hardware takes its control away", not gone, str(gone))
        check("what remains is useful: appearance switch, focus, energy mode", all(x in c for x in ("cc.appearance", "cc.focus", "cc.energy.open")), str(c))
        sess.save_evidence(sess.screenshot(), "cc-absent-hardware-light-1.0x.png", crop=(W - 420, 0, W, 460))
        for page in ("wifi", "bluetooth", "sound", "energy", "media", "display"):
            sess.pt("page", page)
            time.sleep(0.4)
        st = sess.pstate()
        check("expanded modules open calmly without their hardware", st["cc"]["page"] == "display")
        sess.pt("page", "main")
        sess.run(["notify-send", "-a", "Test", "Hallo", "Ohne Akku"])
        time.sleep(0.6)
        sess.ipc("shell", "request", "panels", "show-notifications", "", "")
        time.sleep(1.0)
        st = sess.pstate()
        check("Notification Centre without battery or player: no battery or media widget", "nc.media.toggle" not in st["nc"]["controls"])
        known = ("pipewire", '"org.bluez"')       # Quickshell's own notes that PipeWire / BlueZ are not there
        warns = warnings(sess, known)
        check("no warnings besides the absent PipeWire and BlueZ", not warns, "\n".join(warns[:10]))
    finally:
        sess.stop()


# =================================================================================================
def shoot_set(sess, W, H, tag):
    """Control Center closed → opening → open, expanded modules, banners, Notification Centre"""
    crop_cc = (W - 420, 0, W, 520)
    sess.save_evidence(sess.screenshot(), f"cc-closed-{tag}.png", crop=(W - 420, 0, W, 200))
    sess.ipc("shell", "request", "panels", "show-control-center", "", "")
    time.sleep(0.05)
    sess.save_evidence(sess.screenshot(), f"cc-opening-{tag}.png", crop=crop_cc)
    wait_ps(sess, lambda s: s["cc"]["t"] >= 0.999)
    time.sleep(0.8)
    sess.save_evidence(sess.screenshot(), f"cc-open-{tag}.png", crop=crop_cc)
    for page in ("wifi", "sound"):
        sess.pt("page", page)
        time.sleep(0.9)
        sess.save_evidence(sess.screenshot(), f"cc-{page}-{tag}.png", crop=crop_cc)
    close_all(sess)
    for i, (app, icon, title, body) in enumerate((("Mail", "mail-message-new", "Anna Berger", "Kommst du heute Abend zum Essen?"),
                                                  ("Kalender", "office-calendar", "Zahnarzt", "Heute um 15:00 · Praxis Dr. Weiß"),
                                                  ("Nachrichten", "internet-chat", "Tom", "Ich bin gleich da!"))):
        sess.run(NOTIFY + ["--app", app, "--icon", icon, "--summary", title, "--body", body] + (["--image-data"] if i == 2 else []))
        time.sleep(0.25)
    time.sleep(1.2)
    sess.save_evidence(sess.screenshot(), f"banners-{tag}.png", crop=(W - 440, 0, W, 360))
    sess.pt("hideBanners")
    sess.ipc("shell", "request", "panels", "show-notifications", "", "")
    time.sleep(1.2)
    sess.save_evidence(sess.screenshot(), f"notification-centre-{tag}.jpg", crop=(W - 440, 0, W, H))
    close_all(sess)
    sess.pt("clearAll")


def test_looks():
    print("== looks: light/dark, 1.0/1.6, reduce transparency/motion, no glass effect", flush=True)
    for theme in ("light", "dark"):
        W, H = 1280, 800
        sess = full_session("looks-" + theme, W, H, settings={"appearance": {"theme": theme, "glass": 0.3}})
        try:
            sess.mocksys("SetApStrength", "Nachbar", 60)
            shoot_set(sess, W, H, f"{theme}-1.0x")
            warns = warnings(sess)
            check(f"{theme}: zero warnings while drawing everything", not warns, "\n".join(warns[:10]))
        finally:
            sess.stop()
    # 1.6 on the 2880×1800 panel
    sess = full_session("looks-16", 1800, 1125, scale=1.6)
    try:
        img_w = sess.screenshot().shape[1]
        open_cc(sess)
        time.sleep(0.8)
        sess.save_evidence(sess.screenshot(), "cc-open-light-1.6x.png", crop=(2880 - 660, 0, 2880, 800))
        close_all(sess)
        sess.run(NOTIFY + ["--app", "Mail", "--summary", "Anna Berger", "--body", "Kommst du heute Abend zum Essen?"])
        time.sleep(1.0)
        sess.save_evidence(sess.screenshot(), "banner-light-1.6x.png", crop=(2880 - 700, 0, 2880, 260))
        sess.ipc("panelstest", "hud", "volume", 40)
        time.sleep(0.6)
        sess.save_evidence(sess.screenshot(), "hud-volume-light-1.6x.png", crop=(2880 - 640, 0, 2880, 240))
        check("1.6×: rendered at 2880 device px wide", img_w == 2880, str(img_w))
        warns = warnings(sess)
        check("1.6×: zero warnings", not warns, "\n".join(warns[:10]))
    finally:
        sess.stop()
    # accessibility
    sess = full_session("looks-a11y", 1280, 800, settings={"appearance": {"theme": "light", "glass": 0.3, "reduceTransparency": True},
                                                           "accessibility": {"reduceMotion": True}})
    try:
        sess.ipc("shell", "request", "panels", "show-control-center", "", "")
        time.sleep(0.05)
        st = sess.pstate()
        check("Reduce Motion: Control Center does not grow, it appears in place (fade only)", st.get("cc", {}).get("t") == 1, json.dumps(st.get("cc", {}).get("t")))
        time.sleep(0.6)
        img = sess.screenshot()
        sess.save_evidence(img, "cc-reduce-transparency-light-1.0x.png", crop=(1280 - 420, 0, 1280, 460))
        patch = img[40:300, 1280 - 16:1280 - 11, :3].astype(float)      # the panel's right padding
        check("Reduce Transparency: the panel is opaque (uniform over the busy wallpaper)", patch.std(axis=(0, 1)).mean() < 12, f"std {patch.std(axis=(0, 1)).mean():.1f}")
    finally:
        sess.stop()
    # without the glass effect
    sess = full_session("looks-fallback", 1280, 800, glass=False)
    try:
        open_cc(sess)
        time.sleep(0.6)
        sess.save_evidence(sess.screenshot(), "cc-fallback-no-effect-light-1.0x.png", crop=(1280 - 420, 0, 1280, 460))
        close_all(sess)
        sess.run(NOTIFY + ["--app", "Mail", "--summary", "Ohne Glas", "--body", "Die Ersatzfläche ist lesbar."])
        time.sleep(0.9)
        sess.save_evidence(sess.screenshot(), "banner-fallback-no-effect-light-1.0x.png", crop=(1280 - 440, 0, 1280, 200))
        warns = warnings(sess, ("pipewire",))
        check("no glass effect: everything still draws (fallback), zero warnings", not warns, "\n".join(warns[:10]))
    finally:
        sess.stop()


# =================================================================================================
def test_idle():
    print("== idle: nothing shown → no frames, no wake-ups", flush=True)
    sess = full_session("idle", 1280, 800, media=False)
    try:
        time.sleep(2.0)
        r = measure_idle(sess, 5.0, "idle_panels_closed")
        check("everything closed: no frames presented in 5 s", r["frames"] == 0, json.dumps(r))
        check("everything closed: shell + helpers < 2 wake-ups/s, < 20 ms CPU in 5 s", r["wakeups"] < 10 and r["cpu_ms"] < 20, json.dumps(r))
        open_cc(sess)
        time.sleep(0.6)
        close_all(sess)
        sess.run(NOTIFY + ["--app", "Mail", "--summary", "Kurz", "--body", "…"])
        time.sleep(7.0)
        sess.ipc("panelstest", "hud", "volume", 40)
        time.sleep(3.5)
        st = sess.pstate()
        check("after a banner and a HUD every panel surface is gone", not st["windows"], json.dumps(st["windows"]))
        r = measure_idle(sess, 5.0, "idle_after_panels")
        check("idle again afterwards: no frames, no wake-ups", r["frames"] == 0 and r["wakeups"] < 10 and r["cpu_ms"] < 20, json.dumps(r))
        # an open Control Center with nothing changing is still idle (no timers, no animation)
        open_cc(sess)
        time.sleep(1.5)
        r = measure_idle(sess, 4.0, "idle_cc_open")
        check("Control Center open and untouched: no frames", r["frames"] == 0 and r["wakeups"] < 10, json.dumps(r))
        close_all(sess)
    finally:
        sess.stop()


SECTIONS = {"static": test_static, "cc": test_cc, "wifi": test_wifi, "notifications": test_notifications, "hud": test_hud,
            "absent": test_absent, "looks": test_looks, "idle": test_idle}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SECTIONS)
    for name in wanted:
        try:
            SECTIONS[name]()
        except Exception as e:  # a crashed section is a failure, the others still run
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    os.makedirs(ps.EVIDENCE, exist_ok=True)
    out = os.path.join(ps.EVIDENCE, "results.json")
    old = json.load(open(out)) if os.path.exists(out) else {}
    old.update(results)
    old["last_run"] = {"sections": wanted, "failures": failures, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    json.dump(old, open(out, "w"), indent=1)
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
