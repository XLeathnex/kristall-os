# SPDX-License-Identifier: GPL-3.0-or-later
# Test session for the shell-apps modules (dock, search, apps, switcher): shell-core's ShellSession
# (headless KWin + glass effect) plus the REAL bridge plugin (kwin/bridge), the owner's hands
# (org_kde_kwin_fake_input: real pointer/keyboard through KWin's input pipeline), optional global
# shortcuts (KWin's in-process kglobalaccel reading our system-wide files from XDG_CONFIG_DIRS /
# XDG_DATA_DIRS, like /etc/xdg and /usr/share on the image), fake desktop entries, and helpers.
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DOCK = os.path.dirname(os.path.dirname(HERE))
MODULES = os.path.dirname(DOCK)
SHELL = os.path.dirname(MODULES)
REPO = os.path.dirname(SHELL)
sys.path.insert(0, os.path.join(SHELL, "tests", "support"))
import shellsession as ss  # noqa: E402

_spec = importlib.util.spec_from_file_location("bridge_harness", os.path.join(REPO, "kwin", "bridge", "tests", "support", "harness.py"))
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)

BRIDGE_BUILD = os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp/kristall-bridge-build")
BRIDGE_PLUGINS = os.path.join(BRIDGE_BUILD, "plugins")
wait_until = ss.wait_until

# Linux input key codes (input-event-codes.h)
KEY = {"esc": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11, "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "z": 21, "u": 22, "i": 23, "o": 24, "p": 25,
       "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38, "y": 44, "x": 45, "c": 46,
       "v": 47, "b": 48, "n": 49, "m": 50, "tab": 15, "enter": 28, "return": 28, "space": 57, "backspace": 14,
       "leftctrl": 29, "leftshift": 42, "leftalt": 56, "leftmeta": 125, "up": 103, "down": 108, "left": 105, "right": 106,
       "grave": 41, "102nd": 86, "minus": 12, "equal": 13, "comma": 51, "dot": 52, "slash": 53, "f3": 61}
BTN_LEFT, BTN_RIGHT = 0x110, 0x111


class AppsSession(ss.ShellSession):
    def __init__(self, width=1280, height=800, scale=1.0, settings=None, global_shortcuts=False, glass=True,
                 real_bridge=True, sysconf=None, name=None, lang="de_DE", kwinrc_extra="", shell_path=None):
        plugins = ss.harness.PLUGINS + (":" + BRIDGE_PLUGINS if real_bridge else "")
        super().__init__(width=width, height=height, scale=scale, glass=glass, name=name, lang=lang,
                         settings=settings or {"appearance": {"theme": "light", "glass": 0.3}},
                         env={"QT_PLUGIN_PATH": plugins, "KRISTALL_BRIDGE_DEV": "1"})
        self.real_bridge = real_bridge
        self.ctl_shell = shell_path or SHELL        # what kristall-shellctl (run by shortcuts) talks to
        self.global_shortcuts = global_shortcuts
        with open(os.path.join(self.config, "kwinrc"), "a") as f:
            f.write("[Plugins]\nkristall_glassEnabled=%s\nkristall_bridgeEnabled=%s\n" % (str(glass).lower(), str(real_bridge).lower()))
            f.write(kwinrc_extra)
        # system-wide configuration as the image installs it (XDG_CONFIG_DIRS / XDG_DATA_DIRS)
        self.sysconf = sysconf
        self.data_home = os.path.join(self.tmp, "data")
        self.apps_dir = os.path.join(self.data_home, "applications")
        os.makedirs(self.apps_dir, exist_ok=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, "Downloads"), exist_ok=True)
        self.trash = os.path.join(self.data_home, "Trash", "files")
        os.makedirs(self.trash, exist_ok=True)
        os.makedirs(os.path.join(self.data_home, "Trash", "info"), exist_ok=True)
        self.owner_proc = None
        self._bridge = None

    def env(self):
        e = super().env()
        if self.sysconf:
            e["XDG_CONFIG_DIRS"] = os.path.join(self.sysconf, "etc", "xdg") + ":" + e.get("XDG_CONFIG_DIRS", "/etc/xdg")
            e["XDG_DATA_DIRS"] = os.path.join(self.sysconf, "usr", "share") + ":" + e.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        e["XDG_DATA_HOME"] = self.data_home
        e["HOME"] = self.home
        # kristall-shellctl (global shortcuts run it) must reach the shell under test
        e["PATH"] = os.path.join(SHELL, "bin") + ":" + os.path.join(REPO, "image", "rootfs", "usr", "bin") + ":" + e.get("PATH", "/usr/bin")
        e["KRISTALL_SHELL_DIR"] = getattr(self, "ctl_shell", SHELL)
        e["QS_ICON_THEME"] = "breeze"
        return e

    def start(self, wait_glass=True):
        if self.global_shortcuts:
            # the harness starts KWin with --no-global-shortcuts; run it without for shortcut tests
            orig = ss.harness.KWIN
            wrapper = os.path.join(self.tmp, "kwin-with-shortcuts")
            with open(wrapper, "w") as f:
                f.write('#!/bin/sh\nargs=""\nfor a in "$@"; do [ "$a" = --no-global-shortcuts ] || set -- "$@" "$a"; shift; done\nexec %s "$@"\n' % orig)
            os.chmod(wrapper, 0o755)
            ss.harness.KWIN = wrapper
            try:
                super().start(wait_glass=wait_glass)
            finally:
                ss.harness.KWIN = orig
        else:
            super().start(wait_glass=wait_glass)
        if self.real_bridge:
            wait_until(lambda: os.path.exists(self.bridge_path), 10)
        # pointer and keyboard devices exist on every real machine; fake input provides them
        self.owner_proc = bh.Owner(self.env(), self.tmp)
        self.procs.append(self.owner_proc.p)
        return self

    def shell_env(self, extra=None):
        e = super().shell_env(extra)
        e["XDG_DATA_HOME"] = self.data_home
        e["HOME"] = self.home
        e["QS_ICON_THEME"] = "breeze"
        e["QT_QPA_PLATFORMTHEME"] = ""
        if self.sysconf:
            e["XDG_DATA_DIRS"] = os.path.join(self.sysconf, "usr", "share") + ":/usr/local/share:/usr/share"
        e.update(extra or {})
        return e

    def start_shell(self, extra_env=None, path=None):
        return super().start_shell(extra_env=extra_env, bridge=not self.real_bridge, path=path or self.ctl_shell)

    # ---- the owner's hands ------------------------------------------------------------------------
    def move(self, x, y):
        self.owner_proc.move(x, y)

    def sweep(self, points, hz=120.0):
        """move the pointer through `points` at `hz` events per second (not waiting for each ack)"""
        o = self.owner_proc
        n0 = sum(1 for e in o.snapshot() if e.get("raw") == "ok")
        t = time.monotonic()
        for (x, y) in points:
            o.send(f"move {x} {y}")
            t += 1.0 / hz
            d = t - time.monotonic()
            if d > 0:
                time.sleep(d)
        wait_until(lambda: sum(1 for e in o.snapshot() if e.get("raw") == "ok") >= n0 + len(points), 10)

    def drag(self, a, b, steps=24, hz=60.0):
        self.owner_proc.move(*a)
        self.owner_proc.button(BTN_LEFT, True)
        pts = [(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps) for i in range(1, steps + 1)]
        self.sweep(pts, hz)
        time.sleep(0.15)
        self.owner_proc.button(BTN_LEFT, False)

    def click(self, x, y, button=BTN_LEFT):
        self.owner_proc.move(x, y)
        self.owner_proc.button(button, True)
        self.owner_proc.button(button, False)

    def key(self, name, pressed):
        self.owner_proc.key(KEY[name], pressed)

    def tap(self, *names):
        for n in names:
            self.key(n, True)
        for n in reversed(names):
            self.key(n, False)

    def type_text(self, text):
        for ch in text:
            if ch == " ":
                self.tap("space")
            elif ch.isupper():
                self.tap("leftshift", ch.lower())
            else:
                self.tap(ch)

    # ---- bridge ------------------------------------------------------------------------------------
    def bridge_client(self):
        if self._bridge is None:
            self._bridge = bh.Bridge(path=self.bridge_path, client="shell-apps-test")
        return self._bridge

    def windows(self):
        return self.bridge_client().call("window.list")["windows"]

    def app_windows(self, app_id):
        return [w for w in self.windows() if w["appId"] == app_id and w["normal"]]

    def kwin_script(self, js, marker="KRISTALL-PROBE", wait=1.0):
        """run a KWin script in the compositor (scripting D-Bus API); returns lines it printed with console.warn(marker …)"""
        path = os.path.join(self.tmp, "probe-%d.js" % int(time.monotonic() * 1000))
        with open(path, "w") as f:
            f.write(js)
        before = len(self.log_text())
        env = self.env()
        name = os.path.basename(path)[:-3]
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting", "--method",
                            "org.kde.kwin.Scripting.loadScript", path, name], env=env, capture_output=True, text=True, timeout=10)
        sid = r.stdout.strip().strip("()").rstrip(",").strip()
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting/Script" + sid, "--method",
                        "org.kde.kwin.Script.run"], env=env, capture_output=True, text=True, timeout=10)
        time.sleep(wait)
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting", "--method",
                        "org.kde.kwin.Scripting.unloadScript", name], env=env, capture_output=True, text=True, timeout=10)
        return [l.split(marker, 1)[1].strip() for l in self.log_text()[before:].splitlines() if marker in l]

    # ---- apps ---------------------------------------------------------------------------------------
    def desktop(self, did, name, icon="application-x-executable", exec_="true", extra=""):
        with open(os.path.join(self.apps_dir, did + ".desktop"), "w") as f:
            f.write(f"[Desktop Entry]\nType=Application\nName={name}\nExec={exec_}\nIcon={icon}\n{extra}")

    def app_env(self):
        e = self.env()
        e.update({"QT_QPA_PLATFORM": "wayland", "QT_QUICK_BACKEND": "software"})
        return e

    def dock(self):
        return json.loads(self.ipc("docktest", "state"))

    def stop(self, keep=False):
        if self._bridge:
            try:
                self._bridge.close()
            except OSError:
                pass
        super().stop(keep=keep or bool(os.environ.get("KRISTALL_KEEP")))


def check_factory(failures, results):
    def check(name, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
        if not ok:
            failures.append(name)
        return ok

    def info(msg):
        print("INFO " + msg, flush=True)
    return check, info


def proc_cpu_ms(pids):
    hz = os.sysconf("SC_CLK_TCK")
    t = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                parts = f.read().rsplit(")", 1)[1].split()
            t += int(parts[11]) + int(parts[12])
        except (OSError, IndexError):
            pass
    return t * 1000.0 / hz
