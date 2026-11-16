# SPDX-License-Identifier: GPL-3.0-or-later
"""A headless KWin session in the dev container (virtual backend, llvmpipe), following
kwin/glass/README.md: an LD_PRELOAD shim for /dev/udmabuf and a capability-free copy of
kwin_wayland.  Must run under dbus-run-session.  Optionally loads a built kristall-bridge."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
BUILD = os.environ.get("KRISTALL_HANDS_BUILD", "/tmp/kristall-hands-build")


def prepare() -> None:
    os.makedirs(BUILD, exist_ok=True)
    shim = os.path.join(BUILD, "fake_udmabuf.so")
    if not os.path.exists(shim):
        subprocess.run(["gcc", "-shared", "-fPIC", "-O2", "-o", shim,
                        os.path.join(REPO, "kwin/glass/tests/support/fake_udmabuf.c"), "-ldl"], check=True)
    kw = os.path.join(BUILD, "kwin_wayland")
    if not os.path.exists(kw):
        shutil.copy("/usr/bin/kwin_wayland", kw)


class Session:
    def __init__(self, width=1280, height=800, scale=1.0, plugin_path=None, bridge_dev=True, name="hands"):
        prepare()
        self.tmp = tempfile.mkdtemp(prefix=f"kristall-{name}-")
        self.run = os.path.join(self.tmp, "run")
        os.makedirs(self.run, mode=0o700)
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.config)
        self.width, self.height, self.scale = width, height, scale
        self.plugin_path = plugin_path
        self.bridge_dev = bridge_dev
        self.wayland = f"wl-{name}"
        self.procs: list[subprocess.Popen] = []
        self.kwin = None
        with open(os.path.join(self.config, "kwinrc"), "w") as f:
            f.write("[Compositing]\nAnimationSpeed=0\n")
            if plugin_path:
                f.write("[Plugins]\nkristall_bridgeEnabled=true\n")

    def env(self, **extra) -> dict:
        e = dict(os.environ)
        e.update({"XDG_RUNTIME_DIR": self.run, "XDG_CONFIG_HOME": self.config, "WAYLAND_DISPLAY": self.wayland,
                  "QT_QPA_PLATFORM": "wayland", "KWIN_DISABLE_VULKAN": "1", "QT_QUICK_BACKEND": "software"})
        if self.plugin_path:
            e["QT_PLUGIN_PATH"] = self.plugin_path + os.pathsep + e.get("QT_PLUGIN_PATH", "")
        if self.bridge_dev:
            e["KRISTALL_BRIDGE_DEV"] = "1"
        e.update(extra)
        return e

    def start(self):
        e = self.env(LD_PRELOAD=os.path.join(BUILD, "fake_udmabuf.so"))
        args = [os.path.join(BUILD, "kwin_wayland"), "--virtual", "--width", str(self.width), "--height",
                str(self.height), "--no-lockscreen", "--no-global-shortcuts", "--socket", self.wayland]
        self.kwin_log = open(os.path.join(self.tmp, "kwin.log"), "w")
        self.kwin = subprocess.Popen(args, env=e, stdout=self.kwin_log, stderr=subprocess.STDOUT)
        end = time.monotonic() + 30
        while time.monotonic() < end:
            if self.kwin.poll() is not None:
                raise RuntimeError("kwin exited: " + self.log()[-2000:])
            if os.path.exists(os.path.join(self.run, self.wayland)):
                time.sleep(0.5)
                if self.scale != 1.0:
                    subprocess.run(["kscreen-doctor", f"output.Virtual-0.scale.{self.scale}"], env=self.env(),
                                   capture_output=True, timeout=30)
                    time.sleep(1.0)
                return self
            time.sleep(0.1)
        raise RuntimeError("kwin did not start: " + self.log()[-2000:])

    def log(self) -> str:
        try:
            with open(os.path.join(self.tmp, "kwin.log")) as f:
                return f.read()
        except OSError:
            return ""

    def app(self, args: list[str], name: str | None = None, **extra) -> subprocess.Popen:
        logf = open(os.path.join(self.tmp, f"{name or os.path.basename(args[0])}.log"), "w")
        p = subprocess.Popen(args, env=self.env(**extra), stdout=logf, stderr=subprocess.STDOUT)
        self.procs.append(p)
        return p

    def stop(self):
        for p in self.procs + ([self.kwin] if self.kwin else []):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()
