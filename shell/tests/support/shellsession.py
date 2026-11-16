# SPDX-License-Identifier: GPL-3.0-or-later
# Shell test session: the glass component's headless KWin harness (kwin/glass/tests/support) plus
# everything the shell needs around it — mock bridge, settings tool and defaults, update status,
# apps manifest — and helpers to drive the shell over IPC and take screenshots.
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SHELL = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(SHELL)
sys.path.insert(0, os.path.join(REPO, "kwin", "glass", "tests", "support"))
sys.path.insert(0, HERE)
import harness  # noqa: E402
import mockbridge  # noqa: E402
from harness import wait_until, log  # noqa: E402,F401

EVIDENCE = os.path.join(SHELL, "tests", "evidence")


class ShellSession(harness.Session):
    def __init__(self, glass=True, settings=None, lang="de_DE", **kw):
        settings = settings or {"appearance": {"theme": "light", "glass": 0.3}}
        super().__init__(settings=settings, **kw)
        self.glass = glass
        self.lang = lang
        if not glass:
            with open(os.path.join(self.config, "kwinrc"), "w") as f:
                f.write("[Plugins]\nkristall_glassEnabled=false\nblurEnabled=false\n[Compositing]\nAnimationSpeed=0\n")
        self.bridge_path = os.path.join(self.runtime, "kristall", "bridge.sock")
        self.update_dir = os.path.join(self.tmp, "update")
        os.makedirs(self.update_dir)
        self.bridge = None
        self.shell = None

    def start_system(self):
        """private 'system' bus with mock UPower, power profiles and BlueZ (mocksystem.py)"""
        sock = os.path.join(self.tmp, "system_bus")
        self.system_address = "unix:path=" + sock
        p = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", "--address=" + self.system_address],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        wait_until(lambda: os.path.exists(sock), 5)
        m = subprocess.Popen([sys.executable, os.path.join(HERE, "mocksystem.py"), self.system_address],
                             stdout=subprocess.PIPE, stderr=open(os.path.join(self.tmp, "mocksystem.log"), "w"), text=True)
        self.procs.append(m)
        if m.stdout.readline().strip() != "ready":
            raise RuntimeError("mock system services did not start")
        return self.system_address

    def mock(self, method, signature, *args):
        """call org.kristall.Mock.<method> on the private system bus"""
        r = subprocess.run(["gdbus", "call", "--address", self.system_address, "--dest", "org.kristall.Mock",
                            "--object-path", "/org/kristall/Mock", "--method", "org.kristall.Mock." + method] + [(str(a).lower() if isinstance(a, bool) else str(a)) for a in args],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)

    def start_audio(self):
        """PipeWire + WirePlumber with one null sink ("Built-in speakers (mock)")"""
        conf = os.path.join(self.config, "pipewire", "pipewire.conf.d")
        os.makedirs(conf, exist_ok=True)
        with open(os.path.join(conf, "50-null-sink.conf"), "w") as f:
            f.write('context.objects = [ { factory = adapter args = { factory.name = support.null-audio-sink '
                    'node.name = "kristall-mock-speakers" node.description = "Lautsprecher (Test)" media.class = "Audio/Sink" '
                    'object.linger = true audio.position = [ FL FR ] } } ]\n')
        env = self.env()
        for cmd in (["pipewire"], ["wireplumber"]):
            self.procs.append(subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL,
                                               stderr=open(os.path.join(self.tmp, cmd[0] + ".log"), "w")))
            time.sleep(0.8)

    def wpctl(self, *args):
        return subprocess.run(["wpctl"] + list(args), env=self.env(), capture_output=True, text=True, timeout=10).stdout

    def shell_env(self, extra=None):
        e = {
            "PATH": os.path.join(REPO, "image", "rootfs", "usr", "bin") + ":" + os.environ.get("PATH", "/usr/bin"),
            "KRISTALL_SETTINGS_DROPIN_DIRS": os.path.join(self.tmp, "settings.d"),
            "KRISTALL_SETTINGS_DEFAULTS": os.path.join(self.tmp, "defaults.json"),
            "KRISTALL_APPS_MANIFEST": os.path.join(REPO, "image", "apps", "apps.json"),
            "KRISTALL_UPDATE_STATE_DIR": self.update_dir,
            "KRISTALL_UPDATE_CMD": os.path.join(HERE, "mock-kristall-update"),
            "KRISTALL_BRIDGE_SOCKET": self.bridge_path,
            "KRISTALL_SHELL_TEST": "1",
            "LANG": "C.UTF-8", "KRISTALL_LANG": self.lang,
            "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
            "XDG_DATA_HOME": os.path.join(self.tmp, "data"),
            "XDG_CACHE_HOME": os.path.join(self.tmp, "cache"),
            "QT_QPA_PLATFORMTHEME": "",
        }
        if getattr(self, "system_address", None):
            e["DBUS_SYSTEM_BUS_ADDRESS"] = self.system_address
        e.update(extra or {})
        return e

    def start_shell(self, extra_env=None, bridge=True, path=None):
        dropins = os.path.join(self.tmp, "settings.d")
        os.makedirs(dropins, exist_ok=True)
        with open(os.path.join(dropins, "50-shell.json"), "w") as f:
            f.write(open(os.path.join(SHELL, "image", "settings.json")).read())
        with open(os.path.join(self.tmp, "defaults.json"), "w") as f:
            f.write("{}")
        if bridge and self.bridge is None:
            self.bridge = mockbridge.MockBridge(self.bridge_path, outputs=[
                {"name": f"Virtual-{i}", "x": 0, "y": 0, "w": self.width, "h": self.height, "scale": self.scale,
                 "refresh": 60.0, "internal": i == 0, "primary": i == 0} for i in range(self.outputs)]).start()
        self.shell_path = path or SHELL
        self.shell = self.quickshell(self.shell_path, self.shell_env(extra_env), name="shell")
        return self.shell

    def shell_log(self):
        try:
            with open(os.path.join(self.tmp, "shell.log"), errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def ipc(self, target, fn, *args, timeout=10):
        env = self.env()
        env.update(self.shell_env())
        r = subprocess.run(["quickshell", "ipc", "-p", self.shell_path, "call", target, fn] + [str(a) for a in args],
                           env=env, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"ipc {target}.{fn} failed: {r.stdout} {r.stderr}")
        return r.stdout.strip()

    def rects(self, output=""):
        """bar items in tracking order; retried while the bar is (re)building"""
        for _ in range(20):
            try:
                r = json.loads(self.ipc("test", "itemRects", output) or "[]")
                if r:
                    return r
            except ValueError:
                pass
            time.sleep(0.25)
        raise RuntimeError("no bar items:\n" + self.shell_log()[-1500:])

    def state(self, output=""):
        return json.loads(self.ipc("test", "state", output))

    def wait_ready(self, timeout=20):
        def ready():
            try:
                st = self.state()
                return st if st.get("bar") else None
            except Exception:
                return None
        st = wait_until(ready, timeout, 0.5)
        if not st:
            raise RuntimeError("shell did not become ready:\n" + self.shell_log()[-3000:])
        return st

    def ctl(self, cmd):
        return mockbridge.ctl(self.bridge_path, cmd)

    def save(self, img, name, crop=None, quality=None):
        from PIL import Image
        im = Image.fromarray(img)
        if crop:
            im = im.crop(crop)
        os.makedirs(EVIDENCE, exist_ok=True)
        path = os.path.join(EVIDENCE, name)
        if name.endswith(".jpg"):
            im.convert("RGB").save(path, quality=quality or 86, optimize=True)
        else:
            im.save(path, optimize=True)
        return path


def warnings_in(log_text):
    """QML/Quickshell warnings in a shell log (lines Quickshell prints with WARN/ERROR)."""
    bad = []
    for line in log_text.splitlines():
        if ("WARN" in line or "ERROR" in line or "CRITICAL" in line) and "fd limit" not in line:
            bad.append(line)
    return bad
