# SPDX-License-Identifier: GPL-3.0-or-later
# Test harness for kristall-bridge: a headless KWin (virtual backend, llvmpipe) with the bridge
# plugin, logging test clients, an "owner" that drives KWin's real input pipeline through
# org_kde_kwin_fake_input, and a bridge client. Runs inside kristall-devenv under dbus-run-session.
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(BRIDGE_DIR, "python"))
from kristall_bridge import Bridge, BridgeError  # noqa: E402,F401

BUILD = os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp/kristall-bridge-build")
BIN = os.path.join(BUILD, "bin")
KWIN = os.path.join(BUILD, "kwin_wayland")
SHIM = os.path.join(BUILD, "fake_udmabuf.so")

_counter = [0]


def log(*a):
    print("    ", *a, flush=True)


def wait_until(pred, timeout=5.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()


class Proc:
    """A test client whose stdout is JSON lines (non-JSON lines are kept as {"raw": ...})."""

    def __init__(self, args, env, name, logdir, merge_stderr=False):
        self.name = name
        self.events = []
        self._lock = threading.Lock()
        self._errlog = open(os.path.join(logdir, f"{name}.stderr"), "w")
        self.p = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT if merge_stderr else self._errlog, text=True, bufsize=1,
                                  errors="replace")
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        for line in self.p.stdout:
            line = line.rstrip("\n")
            try:
                ev = json.loads(line)
            except ValueError:
                ev = {"raw": line}
            with self._lock:
                self.events.append(ev)

    def snapshot(self):
        with self._lock:
            return list(self.events)

    def mark(self):
        with self._lock:
            return len(self.events)

    def since(self, mark):
        with self._lock:
            return list(self.events[mark:])

    def wait(self, pred, timeout=5.0, since=0):
        if isinstance(pred, str):
            name = pred
            pred = lambda e: e.get("ev") == name  # noqa: E731
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for e in self.since(since):
                if pred(e):
                    return e
            time.sleep(0.02)
        return None

    def send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def alive(self):
        return self.p.poll() is None

    def stop(self, sig=signal.SIGTERM):
        if self.p.poll() is None:
            self.p.send_signal(sig)
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        self._errlog.close()


class Owner(Proc):
    """The owner's hands: real pointer and keyboard events through KWin's input pipeline."""

    def __init__(self, env, logdir):
        super().__init__([os.path.join(BIN, "owner")], env, "owner", logdir)
        if not wait_until(lambda: any(e.get("raw") == "ready" for e in self.snapshot()), 10):
            raise RuntimeError("owner tool did not start")

    def _cmd(self, line):
        n = sum(1 for e in self.snapshot() if e.get("raw") == "ok")
        self.send(line)
        if not wait_until(lambda: sum(1 for e in self.snapshot() if e.get("raw") == "ok") > n, 5):
            raise RuntimeError(f"owner command timed out: {line}")
        time.sleep(0.03)

    def move(self, x, y):
        self._cmd(f"move {x} {y}")

    def button(self, code, pressed):
        self._cmd(f"button {code} {1 if pressed else 0}")

    def key(self, code, pressed):
        self._cmd(f"key {code} {1 if pressed else 0}")


BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
KEY_ESC, KEY_LEFTSHIFT = 1, 42


class Session:
    def __init__(self, width=1280, height=800, scale=1.0, outputs=1, xwayland=False, lockscreen=False, locked=False, dev=True,
                 layout=None, env=None, plugins=None, name=None, kwinrc_extra="", auto_owner=True):
        _counter[0] += 1
        self.name = name or f"bridge{_counter[0]}"
        self.width, self.height, self.scale, self.outputs = width, height, scale, outputs
        self.xwayland, self.lockscreen, self.locked, self.dev = xwayland, lockscreen or locked, locked, dev
        self.tmp = tempfile.mkdtemp(prefix=f"kristall-{self.name}-")
        self.runtime = os.path.join(self.tmp, "run")
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.runtime, mode=0o700)
        os.makedirs(os.path.join(self.config, "kristall"))
        with open(os.path.join(self.config, "kwinrc"), "w") as f:
            f.write("[Plugins]\nkristall_bridgeEnabled=true\n")
            f.write("[Compositing]\nAnimationSpeed=0\n")
            f.write("[Effect-overview]\nBorderActivate=9\n")
            f.write(kwinrc_extra)
        if layout:
            with open(os.path.join(self.config, "kxkbrc"), "w") as f:
                f.write(f"[Layout]\nLayoutList={layout}\nUse=true\n")
        self.extra_env = env or {}
        self.auto_owner = auto_owner
        self.default_owner = None
        self.plugins = plugins or os.path.join(BUILD, "plugins")
        self.procs = []
        self.kwin = None
        self.wayland = f"wl-{self.name}"
        self.display = None

    @property
    def socket(self):
        return os.path.join(self.runtime, "kristall", "bridge.sock")

    def env(self):
        e = dict(os.environ)
        for k in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM", "LD_PRELOAD"):
            e.pop(k, None)
        e.update({
            "XDG_RUNTIME_DIR": self.runtime,
            "XDG_CONFIG_HOME": self.config,
            "QT_PLUGIN_PATH": self.plugins,
            "KWIN_DISABLE_VULKAN": "1",
            "QT_FORCE_STDERR_LOGGING": "1",
            "QT_LOGGING_RULES": "kristall.bridge.debug=true",
            "WAYLAND_DISPLAY": self.wayland,
            "XKB_DEFAULT_LAYOUT": "us",
        })
        if self.display:
            e["DISPLAY"] = self.display
        e.update(self.extra_env)
        return e

    def start(self, wait_bridge=True):
        env = self.env()
        env["LD_PRELOAD"] = SHIM
        if self.dev:
            env["KRISTALL_BRIDGE_DEV"] = "1"
        args = [KWIN, "--virtual", "--width", str(self.width), "--height", str(self.height), "--no-global-shortcuts",
                "--socket", self.wayland]
        if not self.lockscreen:
            args.append("--no-lockscreen")
        if self.locked:
            args.append("--lockscreen")
        if self.outputs > 1:
            args += ["--output-count", str(self.outputs)]
        before = set(os.listdir("/tmp/.X11-unix")) if os.path.isdir("/tmp/.X11-unix") else set()
        if self.xwayland:
            args.append("--xwayland")
        self.kwin_log = open(os.path.join(self.tmp, "kwin.log"), "w")
        self.kwin = subprocess.Popen(args, env=env, stdout=self.kwin_log, stderr=subprocess.STDOUT)
        end = time.monotonic() + 30
        while time.monotonic() < end:
            if self.kwin.poll() is not None:
                raise RuntimeError(f"kwin exited with {self.kwin.returncode}: {self.log_text()[-3000:]}")
            ready = os.path.exists(os.path.join(self.runtime, self.wayland))
            if ready and (not wait_bridge or os.path.exists(self.socket)):
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("kwin did not come up: " + self.log_text()[-3000:])
        if self.auto_owner and not self.locked:
            # a pointer and keyboard device exist on every real machine; fake input provides them
            self.default_owner = self.owner()
        if self.xwayland:
            new = wait_until(lambda: set(os.listdir("/tmp/.X11-unix")) - before if os.path.isdir("/tmp/.X11-unix") else None, 10)
            if new:
                self.display = ":" + sorted(new)[0].lstrip("X")
        if self.scale != 1.0:
            self.set_scale(self.scale)
        time.sleep(0.3)
        return self

    def set_scale(self, scale):
        # KWin 6.8's output configuration store overrides --scale of the virtual backend; set the
        # scale the way System Settings does (kde-output-management through kscreen-doctor)
        b = self.bridge("scale")
        b.subscribe("outputs")
        outs = b.wait_event("outputs.changed", 5)["data"]["outputs"]
        for o in outs:
            subprocess.run(["kscreen-doctor", f"output.{o['name']}.scale.{scale}"], env=self.env(), capture_output=True, timeout=20)
        ok = wait_until(lambda: (lambda e: e and all(abs(x["scale"] - scale) < 1e-6 for x in e["data"]["outputs"]))(b.wait_event("outputs.changed", 0.5)), 10)
        b.close()
        if not ok:
            raise RuntimeError(f"could not set output scale {scale}")

    def log_text(self):
        try:
            with open(os.path.join(self.tmp, "kwin.log"), errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def bridge(self, client="test", timeout=10.0):
        return Bridge(path=self.socket, client=client, timeout=timeout)

    def owner(self):
        if getattr(self, "default_owner", None):
            return self.default_owner
        o = Owner(self.env(), self.tmp)
        self.procs.append(o)
        return o

    def spawn(self, args, name, env=None, merge_stderr=False):
        e = self.env()
        e.update(env or {})
        p = Proc(args, e, name, self.tmp, merge_stderr=merge_stderr)
        self.procs.append(p)
        return p

    def wlprobe(self, *args, name="wlprobe"):
        return self.spawn([os.path.join(BIN, "wlprobe"), *args], name)

    def qtprobe(self, title="qtprobe", platform="wayland", name=None, env=None):
        e = {"QT_QPA_PLATFORM": platform, "QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR_ROUNDING_POLICY": "PassThrough"}
        e.update(env or {})
        return self.spawn([os.path.join(BIN, "qtprobe"), title], name or f"qt-{platform}", env=e)

    def stop_proc(self, p):
        p.stop()
        if p in self.procs:
            self.procs.remove(p)

    def stop(self, keep=False):
        for p in list(self.procs):
            p.stop()
        self.procs = []
        if self.kwin and self.kwin.poll() is None:
            self.kwin.send_signal(signal.SIGTERM)
            try:
                self.kwin.wait(10)
            except subprocess.TimeoutExpired:
                self.kwin.kill()
                self.kwin.wait()
        if self.kwin:
            self.kwin_log.close()
        if not keep:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop(keep=bool(os.environ.get("KRISTALL_KEEP")))


def find_window(bridge, pred, timeout=8.0):
    def look():
        for w in bridge.call("window.list")["windows"]:
            if pred(w):
                return w
        return None
    return wait_until(look, timeout)


def window_by_title(bridge, title, timeout=8.0):
    return find_window(bridge, lambda w: w["title"] == title, timeout)
