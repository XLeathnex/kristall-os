# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake bootc / flatpak / busctl / systemctl / notify-send / gdbus for the image tool tests.

Every fake logs its argv to $MOCK_DIR/calls.log and keeps its state in $MOCK_DIR, so tests can
arrange a scenario (e.g. "a newer image is in the registry") and assert on what was called.
"""
import json
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOTFS_BIN = os.path.join(HERE, "..", "rootfs", "usr", "bin")

FAKE = r'''#!__PYTHON__
import json, os, subprocess, sys
M = os.environ["MOCK_DIR"]
name = os.path.basename(sys.argv[0]); args = sys.argv[1:]
with open(os.path.join(M, "calls.log"), "a") as f:
    f.write(json.dumps([name] + args) + "\n")
def path(n): return os.path.join(M, n)
def load(n, d=None):
    try:
        with open(path(n)) as f: return json.load(f)
    except (OSError, ValueError): return d
def save(n, v):
    with open(path(n), "w") as f: json.dump(v, f)
def lines(n):
    try:
        with open(path(n)) as f: return [l.strip() for l in f if l.strip()]
    except OSError: return []
def exists(n): return os.path.exists(path(n))

if name == "bootc":
    st = load("bootc-status.json")
    if st is None:
        print("error: not a bootc system", file=sys.stderr); sys.exit(1)
    s = st["status"]; booted = s.get("booted"); remote = load("remote.json")
    if args[:1] == ["status"]:
        print(json.dumps(st)); sys.exit(0)
    if args[:1] == ["upgrade"]:
        if exists("fail-upgrade"):
            print("error: fetching manifest: connection refused", file=sys.stderr); sys.exit(1)
        if "--check" in args:
            if remote: booted["cachedUpdate"] = {"version": remote["version"], "imageDigest": remote["digest"], "timestamp": None}
            save("bootc-status.json", st); sys.exit(0)
        if remote and remote["digest"] != booted["image"]["imageDigest"]:
            s["staged"] = {"image": {"image": booted["image"]["image"], "version": remote["version"],
                           "imageDigest": remote["digest"], "timestamp": None}, "pinned": False,
                           "downloadOnly": False}
            booted["cachedUpdate"] = {"version": remote["version"], "imageDigest": remote["digest"]}
        save("bootc-status.json", st); sys.exit(0)
    if args[:1] == ["rollback"]:
        if not s.get("rollback"): print("No rollback available", file=sys.stderr); sys.exit(1)
        s["rollbackQueued"] = not s.get("rollbackQueued", False); s["staged"] = None
        save("bootc-status.json", st); sys.exit(0)
    sys.exit(2)

if name == "flatpak":
    installed = lines("flatpak-installed")
    if args[:1] == ["remote-ls"]:
        for l in lines("flatpak-updates"): print(l)
        sys.exit(0)
    if args[:1] == ["update"]:
        sys.exit(int(lines("flatpak-update-rc")[0]) if lines("flatpak-update-rc") else 0)
    if args[:1] in (["uninstall"], ["remote-add"], ["override"]):
        sys.exit(0)
    if args[:1] == ["info"]:
        sys.exit(0 if args[-1] in installed else 1)
    if args[:1] == ["list"]:
        for l in lines("flatpak-runtimes"): print(l)
        sys.exit(0)
    if args[:1] == ["install"]:
        ref = args[-1]; app = ref.split("/")[1] if ref.count("/") >= 2 else ref
        if app in lines("flatpak-fail"):
            print("error: Unable to load summary from remote flathub", file=sys.stderr); sys.exit(1)
        with open(path("flatpak-installed"), "a") as f: f.write(app + "\n")
        sys.exit(0)
    sys.exit(2)

if name == "busctl":
    prop = args[-1]
    v = lines("nm-" + prop)
    if exists("no-nm"): sys.exit(1)
    print("u %s" % (v[0] if v else "4")); sys.exit(0)

if name == "systemctl":
    if args[:1] == ["start"]:
        unit = args[-1]
        cmd = {"kristall-update-check.service": ["check"], "kristall-update-apply.service": ["apply"],
               "kristall-update-rollback.service": ["rollback"],
               "kristall-update-rollback-cancel.service": ["rollback", "--cancel"]}.get(unit)
        if cmd is None: sys.exit(0)
        if exists("deny-" + unit):
            print("Failed to start %s: Access denied" % unit, file=sys.stderr); sys.exit(4)
        env = dict(os.environ, KRISTALL_UPDATE_FORCE_ROOT="1")
        r = subprocess.run([sys.executable, os.environ["KRISTALL_UPDATE_TOOL"]] + cmd, env=env,
                           stdout=subprocess.DEVNULL)
        sys.exit(r.returncode)
    sys.exit(0)

if name == "notify-send":
    a = lines("notify-action")
    if a: print(a[0])
    sys.exit(0)

if name in ("gdbus", "rpm"):
    sys.exit(int(lines(name + "-rc")[0]) if lines(name + "-rc") else 0)
'''

FAKES = ("bootc", "flatpak", "busctl", "systemctl", "notify-send", "gdbus", "rpm")


class Sandbox:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.mock = os.path.join(self.root, "mock")
        self.bin = os.path.join(self.root, "bin")
        self.power = os.path.join(self.root, "power")
        os.makedirs(self.mock)
        os.makedirs(self.bin)
        os.makedirs(self.power)
        src = FAKE.replace("__PYTHON__", sys.executable)
        for n in FAKES:
            p = os.path.join(self.bin, n)
            with open(p, "w") as f:
                f.write(src)
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        self.env = {
            "PATH": self.bin + ":/usr/bin:/bin",
            "MOCK_DIR": self.mock,
            "HOME": os.path.join(self.root, "home"),
            "XDG_RUNTIME_DIR": os.path.join(self.root, "run-user"),
            "LANG": "en_US.UTF-8",
            "KRISTALL_UPDATE_TOOL": os.path.join(ROOTFS_BIN, "kristall-update"),
            "KRISTALL_UPDATE_STATE_DIR": os.path.join(self.root, "var", "update"),
            "KRISTALL_UPDATE_RUN_DIR": os.path.join(self.root, "run", "update"),
            "KRISTALL_UPDATE_CONFIG": os.path.join(self.root, "etc", "update.json"),
            "KRISTALL_POWER_SUPPLY_DIR": self.power,
            "KRISTALL_APPS_STATE_DIR": os.path.join(self.root, "var", "apps"),
            "KRISTALL_DRM_DIR": os.path.join(self.root, "drm"),
            "KRISTALL_APPS_NO_SYSTEMCTL": "1",
        }
        os.makedirs(self.env["XDG_RUNTIME_DIR"])

    def cleanup(self):
        self.tmp.cleanup()

    def put(self, name, content):
        with open(os.path.join(self.mock, name), "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))

    def get(self, name):
        with open(os.path.join(self.mock, name)) as f:
            return json.load(f)

    def calls(self, prog=None):
        try:
            with open(os.path.join(self.mock, "calls.log")) as f:
                out = [json.loads(l) for l in f]
        except OSError:
            return []
        return [c for c in out if prog is None or c[0] == prog]

    def battery(self, percent, on_ac):
        for dev, attrs in (("BAT0", {"type": "Battery", "capacity": str(percent), "scope": "System"}),
                           ("AC", {"type": "Mains", "online": "1" if on_ac else "0"}),
                           ("hidpp_battery_0", {"type": "Battery", "capacity": "3", "scope": "Device"})):
            d = os.path.join(self.power, dev)
            os.makedirs(d, exist_ok=True)
            for k, v in attrs.items():
                with open(os.path.join(d, k), "w") as f:
                    f.write(v + "\n")


def bootc_status(version="45.20261101.1", digest="sha256:aaa", rollback=True):
    img = {"image": "ghcr.io/owner/kristall-os:latest", "transport": "registry"}
    st = {"apiVersion": "org.containers.bootc/v1", "kind": "BootcHost",
          "status": {"booted": {"image": {"image": img, "version": version, "imageDigest": digest,
                                          "timestamp": "2026-11-01T04:00:00Z"},
                                "cachedUpdate": None, "pinned": False, "downloadOnly": False},
                     "staged": None, "rollback": None, "rollbackQueued": False}}
    if rollback:
        st["status"]["rollback"] = {"image": {"image": img, "version": "45.20261020.1",
                                              "imageDigest": "sha256:old", "timestamp": None},
                                    "pinned": False}
    return st
