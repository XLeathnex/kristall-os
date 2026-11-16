# SPDX-License-Identifier: GPL-3.0-or-later
# Test harness: a headless KWin (virtual backend, llvmpipe) with the glass plugin, Quickshell
# clients, a socket client and screenshots. Runs inside the kristall-devenv container under
# dbus-run-session; see tests/run.sh.
import json
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GLASS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import kwin_screenshot  # noqa: E402

BUILD = os.environ.get("KRISTALL_GLASS_BUILD", "/tmp/kristall-glass-build")
SHIM = os.path.join(BUILD, "fake_udmabuf.so")
KWIN = os.path.join(BUILD, "kwin_wayland")  # copy without file capabilities (containers)
PLUGINS = os.path.join(BUILD, "plugins")

_counter = [0]


def log(*a):
    print("  ", *a, flush=True)


class GlassConn:
    def __init__(self, path, timeout=3.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        self.buf = b""
        self.backlog = []

    def send(self, obj):
        self.sock.sendall((json.dumps(obj, separators=(",", ":")) + "\n").encode())

    def send_raw(self, data):
        self.sock.sendall(data)

    def _read(self, timeout):
        r, _, _ = select.select([self.sock], [], [], timeout)
        if not r:
            return False
        data = self.sock.recv(1 << 20)
        if not data:
            raise ConnectionError("glass socket closed")
        self.buf += data
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            if line.strip():
                self.backlog.append(json.loads(line))
        return True

    def wait(self, pred, timeout=3.0):
        if isinstance(pred, str):
            name = pred
            pred = lambda e: e.get("event") == name  # noqa: E731
        end = time.monotonic() + timeout
        while True:
            for i, ev in enumerate(self.backlog):
                if pred(ev):
                    return self.backlog.pop(i)
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            self._read(remaining)

    def drain(self, timeout=0.2):
        end = time.monotonic() + timeout
        while self._read(max(0.0, end - time.monotonic())):
            pass
        out, self.backlog = self.backlog, []
        return out

    def status(self):
        self.send({"op": "status"})
        return self.wait("status")

    def close(self):
        self.sock.close()


class Session:
    def __init__(self, width=1280, height=800, scale=1.0, outputs=1, settings=None, env=None, name=None):
        _counter[0] += 1
        self.name = name or f"glass{_counter[0]}"
        self.width, self.height, self.scale, self.outputs = width, height, scale, outputs
        self.tmp = tempfile.mkdtemp(prefix=f"kristall-{self.name}-")
        self.runtime = os.path.join(self.tmp, "run")
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.runtime, mode=0o700)
        os.makedirs(os.path.join(self.config, "kristall"))
        with open(os.path.join(self.config, "kwinrc"), "w") as f:
            f.write("[Plugins]\nkristall_glassEnabled=true\nblurEnabled=false\n")
            f.write("[Compositing]\nAnimationSpeed=0\n")
        self.write_settings(settings or {"appearance": {"theme": "light", "glass": 0.3}})
        self.extra_env = env or {}
        self.procs = []
        self.kwin = None
        self.wayland = f"wl-{self.name}"

    @property
    def glass_socket(self):
        return os.path.join(self.runtime, "kristall", "glass.sock")

    def env(self):
        e = dict(os.environ)
        e.update({
            "XDG_RUNTIME_DIR": self.runtime,
            "XDG_CONFIG_HOME": self.config,
            "QT_PLUGIN_PATH": PLUGINS,
            "KWIN_DISABLE_VULKAN": "1",
            "QT_FORCE_STDERR_LOGGING": "1",
            "QT_MESSAGE_PATTERN": "%{category} %{message}",
            "WAYLAND_DISPLAY": self.wayland,
        })
        e.update(self.extra_env)
        return e

    def write_settings(self, settings):
        path = os.path.join(self.config, "kristall", "settings.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(settings, f)
        os.replace(tmp, path)  # atomic, as the contract requires of writers

    def start(self, wait_glass=True):
        env = self.env()
        env["LD_PRELOAD"] = SHIM
        args = [KWIN, "--virtual", "--width", str(self.width), "--height", str(self.height), "--no-lockscreen",
                "--no-global-shortcuts", "--socket", self.wayland]
        if self.scale != 1.0:
            args += ["--scale", str(self.scale)]
        if self.outputs > 1:
            args += ["--output-count", str(self.outputs)]
        self.kwin_log = open(os.path.join(self.tmp, "kwin.log"), "w")
        self.kwin = subprocess.Popen(args, env=env, stdout=self.kwin_log, stderr=subprocess.STDOUT)
        end = time.monotonic() + 30
        while time.monotonic() < end:
            if self.kwin.poll() is not None:
                raise RuntimeError(f"kwin exited with {self.kwin.returncode}; log: {self.log_text()[-2000:]}")
            if os.path.exists(os.path.join(self.runtime, self.wayland)) and (not wait_glass or os.path.exists(self.glass_socket)):
                time.sleep(0.5)
                if self.scale != 1.0:
                    self.set_scale(self.scale)
                return self
            time.sleep(0.1)
        raise RuntimeError("kwin did not come up: " + self.log_text()[-2000:])

    def set_scale(self, scale):
        # The virtual backend's --scale only multiplies the mode size; the output scale itself
        # is set through the output-management protocol, like System Settings would.
        args = ["kscreen-doctor"] + [f"output.Virtual-{i}.scale.{scale}" for i in range(self.outputs)]
        r = subprocess.run(args, env=self.env(), capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError("kscreen-doctor failed: " + r.stdout + r.stderr)
        time.sleep(1.0)

    def log_text(self):
        try:
            with open(os.path.join(self.tmp, "kwin.log")) as f:
                return f.read()
        except OSError:
            return ""

    def quickshell(self, path, env=None, name="qs"):
        e = self.env()
        e.update({"QT_QPA_PLATFORM": "wayland", "QT_QUICK_BACKEND": "software", "QT_SCALE_FACTOR_ROUNDING_POLICY": "PassThrough"})
        e.update(env or {})
        logf = open(os.path.join(self.tmp, f"{name}.log"), "w")
        p = subprocess.Popen(["quickshell", "-p", path], env=e, stdout=logf, stderr=subprocess.STDOUT)
        self.procs.append(p)
        return p

    def background(self, image):
        return self.quickshell(os.path.join(HERE, "background.qml"), {"KRISTALL_TEST_BG": image}, name="bg")

    def connect(self):
        return GlassConn(self.glass_socket)

    def screenshot(self, output=None):
        return kwin_screenshot.capture_screen(output)

    def stop_proc(self, p, sig=signal.SIGTERM):
        if p.poll() is None:
            p.send_signal(sig)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        if p in self.procs:
            self.procs.remove(p)

    def stop(self, keep=False):
        for p in list(self.procs):
            self.stop_proc(p)
        if self.kwin:
            self.stop_proc(self.kwin)
            self.kwin_log.close()
        if not keep:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def wait_until(pred, timeout=5.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()
