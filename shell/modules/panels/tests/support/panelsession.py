# SPDX-License-Identifier: GPL-3.0-or-later
# Test session for the panels module: shell-core's ShellSession (headless KWin with the glass
# effect, mock bridge, settings) plus the panels' own mocks (richer NetworkManager/BlueZ on the
# private system bus, PowerDevil brightness, screen locker and a music player on the session bus),
# a second audio sink and a microphone source, a real plasmashell, and the owner's real input.
import ast
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PANELS = os.path.dirname(os.path.dirname(HERE))
SHELL = os.path.dirname(os.path.dirname(PANELS))
REPO = os.path.dirname(SHELL)
sys.path.insert(0, os.path.join(SHELL, "tests", "support"))
import shellsession as ss  # noqa: E402
from shellsession import wait_until  # noqa: E402,F401

EVIDENCE = os.path.join(PANELS, "tests", "evidence")
BUILD = os.environ.get("KRISTALL_PANELS_BUILD", "/tmp/kristall-panels-build")

# evdev key codes for the owner's keyboard
KEY = {"esc": 1, "tab": 15, "enter": 28, "space": 57, "left": 105, "right": 106, "up": 103, "down": 108, "shift": 42}
BTN_LEFT, BTN_RIGHT = 0x110, 0x111


class Owner:
    """the owner's mouse and keyboard through KWin's fake-input protocol (real input pipeline)"""
    def __init__(self, env):
        self.p = subprocess.Popen([os.path.join(BUILD, "owner")], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        line = self.p.stdout.readline().strip()
        if line != "ready":
            raise RuntimeError("owner input client did not start: " + line)

    def cmd(self, c):
        self.p.stdin.write(c + "\n")
        self.p.stdin.flush()
        self.p.stdout.readline()

    def move(self, x, y):
        self.cmd(f"move {x} {y}")

    def click(self, x, y, button=BTN_LEFT):
        self.move(x, y)
        time.sleep(0.05)
        self.cmd(f"button {button} 1")
        time.sleep(0.03)
        self.cmd(f"button {button} 0")

    def key(self, name):
        code = KEY[name]
        self.cmd(f"key {code} 1")
        time.sleep(0.02)
        self.cmd(f"key {code} 0")

    def close(self):
        self.p.terminate()


class PanelsSession(ss.ShellSession):
    def start_shell(self, extra_env=None, bridge=True, path=None):
        dropins = os.path.join(self.tmp, "settings.d")
        os.makedirs(dropins, exist_ok=True)
        shutil.copy(os.path.join(PANELS, "image", "settings.json"), os.path.join(dropins, "50-panels.json"))
        if path is None:
            path = self.isolated_shell()
        env = {"QS_ICON_THEME": "breeze", "KRISTALL_POWER_CMD": os.path.join(HERE, "mock-kristall-power"), "KRISTALL_POWER_LOG": os.path.join(self.tmp, "power-calls.log")}
        env.update(extra_env or {})
        return super().start_shell(extra_env=env, bridge=bridge, path=path)

    def isolated_shell(self):
        """a copy of the shell with only this module enabled (other agents' modules in progress
        must not decide our results)"""
        dst = os.path.join(self.tmp, "shell")
        if not os.path.exists(dst):
            shutil.copytree(SHELL, dst, ignore=lambda d, names: [n for n in names if n in ("tests", "__pycache__", ".scratch")
                                                                  or (os.path.basename(d) == "modules" and n != "panels")])
            with open(os.path.join(dst, "modules.list"), "w") as f:
                f.write("panels\n")
        return dst

    def wait_panels(self, timeout=20):
        def ready():
            try:
                st = self.pstate()
                return st if st["helper"]["ready"] else None
            except Exception:
                return None
        st = wait_until(ready, timeout, 0.5)
        if not st:
            raise RuntimeError("panels did not become ready:\n" + self.shell_log()[-3000:])
        return st

    def start_system(self, *opts):
        sock = os.path.join(self.tmp, "system_bus")
        self.system_address = "unix:path=" + sock
        p = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", "--address=" + self.system_address],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        wait_until(lambda: os.path.exists(sock), 5)
        m = subprocess.Popen([sys.executable, os.path.join(HERE, "panelsystem.py"), self.system_address] + list(opts),
                             stdout=subprocess.PIPE, stderr=open(os.path.join(self.tmp, "panelsystem.log"), "w"), text=True)
        self.procs.append(m)
        if m.stdout.readline().strip() != "ready":
            raise RuntimeError("mock system services did not start: " + open(os.path.join(self.tmp, "panelsystem.log")).read())
        return self.system_address

    def start_session_mocks(self, *opts):
        m = subprocess.Popen([sys.executable, os.path.join(HERE, "mocksession.py")] + list(opts), env=self.env(),
                             stdout=subprocess.PIPE, stderr=open(os.path.join(self.tmp, "mocksession.log"), "w"), text=True)
        self.procs.append(m)
        if m.stdout.readline().strip() != "ready":
            raise RuntimeError("mock session services did not start")

    def start_audio(self, extra_sink=True, mic=True):
        conf = os.path.join(self.config, "pipewire", "pipewire.conf.d")
        os.makedirs(conf, exist_ok=True)
        objs = ['{ factory = adapter args = { factory.name = support.null-audio-sink node.name = "kristall-mock-speakers" '
                'node.description = "Lautsprecher (Test)" media.class = "Audio/Sink" object.linger = true audio.position = [ FL FR ] priority.session = 2000 } }']
        if extra_sink:
            objs.append('{ factory = adapter args = { factory.name = support.null-audio-sink node.name = "kristall-mock-headphones" '
                        'node.description = "Kopfhörer (Test)" media.class = "Audio/Sink" object.linger = true audio.position = [ FL FR ] priority.session = 1000 } }')
        if mic:
            objs.append('{ factory = adapter args = { factory.name = support.null-audio-sink node.name = "kristall-mock-mic" '
                        'node.description = "Mikrofon (Test)" media.class = "Audio/Source/Virtual" object.linger = true audio.position = [ MONO ] } }')
        with open(os.path.join(conf, "50-null-sink.conf"), "w") as f:
            f.write("context.objects = [ " + " ".join(objs) + " ]\n")
        env = self.env()
        for cmd in (["pipewire"], ["wireplumber"]):
            self.procs.append(subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL,
                                               stderr=open(os.path.join(self.tmp, cmd[0] + ".log"), "w")))
            time.sleep(0.8)

    def record(self, app="Rekorder"):
        """a capture stream from the microphone (what an app recording sound looks like): a
        pipewire client running the loopback module, capture side named like an app"""
        conf = os.path.join(self.tmp, "recorder.conf")
        with open(conf, "w") as f:
            f.write('context.properties = { log.level = 0 }\n'
                    'context.spa-libs = { audio.convert.* = audioconvert/libspa-audioconvert support.* = support/libspa-support }\n'
                    'context.modules = [ { name = libpipewire-module-protocol-native } { name = libpipewire-module-client-node } '
                    '{ name = libpipewire-module-adapter } { name = libpipewire-module-loopback args = { '
                    f'capture.props = {{ node.name = "{app}" node.description = "{app}" application.name = "{app}" target.object = "kristall-mock-mic" stream.dont-remix = true audio.channels = 1 audio.position = [ MONO ] }} '
                    'playback.props = { node.name = "kristall-recorder-out" node.passive = true media.class = "Audio/Source" audio.channels = 1 audio.position = [ MONO ] } } } ]\n')
        p = subprocess.Popen(["pipewire", "-c", conf], env=self.env(), stdout=subprocess.DEVNULL,
                             stderr=open(os.path.join(self.tmp, "recorder.log"), "w"))
        self.procs.append(p)
        return p

    def start_plasma(self, override=True):
        """plasmashell with the Kristall layout (desktop only) and, unless override=False, the
        panels' OSD replacement on QML_IMPORT_PATH (what the unit drop-in does)"""
        data = os.path.join(self.tmp, "share")
        conf = os.path.join(self.tmp, "xdg")
        os.makedirs(os.path.join(data, "plasma", "look-and-feel"), exist_ok=True)
        dst = os.path.join(data, "plasma", "look-and-feel", "org.kristall.desktop")
        if not os.path.exists(dst):
            shutil.copytree(os.path.join(SHELL, "plasma", "look-and-feel", "org.kristall.desktop"), dst)
        os.makedirs(conf, exist_ok=True)
        shutil.copy(os.path.join(SHELL, "plasma", "xdg", "kdeglobals"), conf)
        env = self.env()
        env["QT_QPA_PLATFORM"] = "wayland"
        env["XDG_DATA_DIRS"] = data + ":/usr/share"
        env["XDG_CONFIG_DIRS"] = conf + ":/etc/xdg"
        if override:
            env["QML_IMPORT_PATH"] = os.path.join(PANELS, "plasma", "osd")
        self.procs.append(subprocess.Popen(["/usr/libexec/kactivitymanagerd"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1.5)
        self.plasma = subprocess.Popen(["plasmashell", "--no-respawn"], env=env, stdout=open(os.path.join(self.tmp, "plasma.log"), "w"),
                                       stderr=subprocess.STDOUT)
        self.procs.append(self.plasma)
        ok = wait_until(lambda: "org.kde.plasmashell" in self.bus_names(), 30, 0.5)
        time.sleep(6)
        return ok

    def bus_names(self):
        r = subprocess.run(["busctl", "--user", "list", "--no-pager", "--no-legend"], env=self.env(), capture_output=True, text=True)
        return r.stdout

    def gdbus(self, *args, system=False):
        bus = ["--address", self.system_address] if system else ["--session"]
        r = subprocess.run(["gdbus", "call"] + bus + list(args), env=self.env(), capture_output=True, text=True, timeout=15)
        return (r.stdout + r.stderr).strip()

    def mocksys(self, method, *args):
        return self.gdbus("--dest", "org.kristall.Mock", "--object-path", "/org/kristall/Mock", "--method", "org.kristall.Mock." + method,
                          *[(str(a).lower() if isinstance(a, bool) else str(a)) for a in args], system=True)

    def mocksess(self, method, *args):
        return self.gdbus("--dest", "org.kristall.MockSession", "--object-path", "/org/kristall/MockSession",
                          "--method", "org.kristall.MockSession." + method, *[(str(a).lower() if isinstance(a, bool) else str(a)) for a in args])

    def calls(self, system=True):
        out = self.mocksys("Calls") if system else self.mocksess("Calls")
        try:
            return json.loads(ast.literal_eval(out)[0])     # gdbus prints ('[...]',)
        except (ValueError, SyntaxError):
            return []

    def owner(self):
        env = self.env()
        return Owner(env)

    def pt(self, fn, *args):
        return self.ipc("panelstest", fn, *args)

    def pstate(self):
        return json.loads(self.pt("state"))

    def run(self, argv, wait=True, timeout=15):
        env = self.env()
        env.update(self.shell_env())
        if wait:
            return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
        p = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.procs.append(p)
        return p

    def settings_set(self, path, value):
        env = self.env()
        env.update(self.shell_env())
        subprocess.run(["kristall-settings", "set", path, json.dumps(value)], env=env, check=True)

    def save_evidence(self, img, name, crop=None, quality=None):
        from PIL import Image
        im = Image.fromarray(img)
        if crop:
            im = im.crop(crop)
        os.makedirs(EVIDENCE, exist_ok=True)
        path = os.path.join(EVIDENCE, name)
        if name.endswith(".jpg"):
            im.convert("RGB").save(path, quality=quality or 82, optimize=True)
        else:
            im.save(path, optimize=True)
        return path
