# SPDX-License-Identifier: GPL-3.0-or-later
"""Test environment: temporary XDG dirs with desktop entries, the real app manifest, the real
kristall-settings, fake command-line tools, a fake D-Bus, a mock bridge and a mock daemon."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HANDS = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(os.path.dirname(HANDS))
sys.path.insert(0, HANDS)
sys.path.insert(0, os.path.dirname(HERE))

from kristall_hands import apps as appsmod, dbus  # noqa: E402
from kristall_hands.apps import AppIndex  # noqa: E402
from kristall_hands.bridge import Bridge  # noqa: E402
from kristall_hands.config import Settings  # noqa: E402
from kristall_hands.core import Hands  # noqa: E402
from kristall_hands.link import Link  # noqa: E402
from kristall_hands.server import build  # noqa: E402
from kristall_hands.tooling import Context, HandsError, Result  # noqa: E402
from support.fakebus import FakeBus  # noqa: E402
from support.mock_bridge import MockBridge  # noqa: E402
from support.mock_daemon import MockDaemon  # noqa: E402

DESKTOP = {
    "org.kde.kcalc.desktop": "[Desktop Entry]\nType=Application\nName=KCalc\nName[de]=KCalc\nGenericName=Scientific Calculator\n"
                             "GenericName[de]=Wissenschaftlicher Taschenrechner\nExec=kcalc\nKeywords=calc;calculator;math;\n",
    "org.blender.Blender.desktop": "[Desktop Entry]\nType=Application\nName=Blender\nGenericName=3D modeler\n"
                                   "GenericName[de]=3D-Modellierer\nExec=/usr/bin/flatpak run org.blender.Blender %f\n",
    "org.mozilla.firefox.desktop": "[Desktop Entry]\nType=Application\nName=Firefox\nGenericName=Web Browser\n"
                                   "GenericName[de]=Webbrowser\nExec=firefox %u\nStartupWMClass=firefox\n",
    "org.kde.dolphin.desktop": "[Desktop Entry]\nType=Application\nName=Dolphin\nGenericName=File Manager\n"
                               "GenericName[de]=Dateiverwaltung\nExec=dolphin %u\n",
    "org.kde.kate.desktop": "[Desktop Entry]\nType=Application\nName=Kate\nGenericName=Advanced Text Editor\n"
                            "GenericName[de]=Erweiterter Texteditor\nExec=kate -b %U\n",
    "org.kde.kwrite.desktop": "[Desktop Entry]\nType=Application\nName=KWrite\nGenericName=Text Editor\n"
                              "GenericName[de]=Texteditor\nExec=kwrite %U\n",
    "org.kde.konsole.desktop": "[Desktop Entry]\nType=Application\nName=Konsole\nGenericName=Terminal\nExec=konsole\n",
    "systemsettings.desktop": "[Desktop Entry]\nType=Application\nName=System Settings\nName[de]=Systemeinstellungen\nExec=systemsettings\n",
    "kcm_kwin_effects.desktop": "[Desktop Entry]\nType=Application\nName=Desktop Effects\nName[de]=Arbeitsflächen-Effekte\nExec=systemsettings kcm_kwin_effects\nNoDisplay=true\n",
    "com.valvesoftware.Steam.desktop": "[Desktop Entry]\nType=Application\nName=Steam\nExec=flatpak run com.valvesoftware.Steam\n",
    "org.kde.elisa.desktop": "[Desktop Entry]\nType=Application\nName=Elisa\nGenericName=Music Player\nGenericName[de]=Musikwiedergabe\nExec=elisa\n",
    "org.vinegarhq.Vinegar.desktop": "[Desktop Entry]\nType=Application\nName=Vinegar\nGenericName=Roblox Studio launcher\nExec=vinegar\n",
}

FAKE_TOOL = r'''#!/usr/bin/env python3
import json, os, sys
state_file = os.environ["FAKE_STATE"]
try:
    st = json.load(open(state_file))
except Exception:
    st = {}
for k, v in {"volume": 0.5, "muted": False, "mic": 0.8, "micmuted": False, "calls": [], "clip": "", "cliptypes": []}.items():
    st.setdefault(k, v)
name = os.path.basename(sys.argv[0]); a = sys.argv[1:]
st["calls"].append([name] + a)
out = ""
if name == "wpctl":
    mic = "SOURCE" in " ".join(a)
    vk, mk = ("mic", "micmuted") if mic else ("volume", "muted")
    if a[0] == "get-volume":
        out = "Volume: %.2f%s\n" % (st[vk], " [MUTED]" if st[mk] else "")
    elif a[0] == "set-volume":
        v = a[-1]
        st[vk] = float(v)
    elif a[0] == "set-mute":
        st[mk] = (not st[mk]) if a[-1] == "toggle" else a[-1] == "1"
elif name == "wl-paste":
    if "--list-types" in a:
        out = "\n".join(st["cliptypes"]) + "\n"
    else:
        out = st["clip"]
elif name == "wl-copy":
    st["clip"] = sys.stdin.read(); st["cliptypes"] = ["text/plain;charset=utf-8"]
elif name == "kristall-power":
    # power.md §7.1/§7.2: `status --json`, `mode auto|quiet|balanced|performance`
    ps = st.setdefault("power", {"reachable": True, "status": {}})
    if a[:1] == ["mode"]:
        if not ps["reachable"]:
            json.dump(st, open(state_file, "w")); sys.stderr.write("session daemon unreachable\n"); sys.exit(1)
        auto = ps["status"].setdefault("automatic", {"enabled": True, "manual": None, "reason": "auto"})
        if a[1] == "auto":
            auto.update(manual=None, reason="auto")
        else:
            auto.update(manual={"mode": a[1], "on_battery": False, "since": "now"}, reason="manual")
            ps["status"]["mode"] = a[1]
    elif a[:1] == ["status"]:
        out = json.dumps(ps["status"]) + "\n"
json.dump(st, open(state_file, "w"))
sys.stdout.write(out)
'''


class Env:
    def __init__(self, *, scale=1.6, bridge=True, daemon=True, width=1800, height=1125, capabilities=None):
        self.tmp = tempfile.mkdtemp(prefix="kristall-hands-test-")
        self.run = os.path.join(self.tmp, "run")
        os.makedirs(os.path.join(self.run, "kristall"), mode=0o700)
        self.home = os.path.join(self.tmp, "home")
        self.data = os.path.join(self.home, ".local/share")
        self.config = os.path.join(self.home, ".config")
        self.sys_data = os.path.join(self.tmp, "usr/share")
        apps_dir = os.path.join(self.sys_data, "applications")
        os.makedirs(apps_dir)
        os.makedirs(self.config)
        os.makedirs(self.data)
        for name, text in DESKTOP.items():
            with open(os.path.join(apps_dir, name), "w") as f:
                f.write(text)
        self.manifest = os.path.join(REPO, "image/apps/apps.json")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for tool in ("wpctl", "wl-paste", "wl-copy"):
            p = os.path.join(self.bin, tool)
            with open(p, "w") as f:
                f.write(FAKE_TOOL)
            os.chmod(p, 0o755)
        # kwriteconfig6: record the call
        p = os.path.join(self.bin, "kwriteconfig6")
        with open(p, "w") as f:
            f.write(FAKE_TOOL)
        os.chmod(p, 0o755)
        self.state = os.path.join(self.tmp, "fake-state.json")
        self.settings_user = os.path.join(self.config, "kristall/settings.json")
        dropins = os.path.join(self.tmp, "settings.d")
        os.makedirs(dropins)
        shutil.copy(os.path.join(HANDS, "data/settings-hands.json"), os.path.join(dropins, "50-assistant-hands.json"))
        self.env_backup = dict(os.environ)
        os.environ.update({
            "XDG_RUNTIME_DIR": self.run, "HOME": self.home, "XDG_DATA_HOME": self.data,
            "XDG_CONFIG_HOME": self.config, "XDG_DATA_DIRS": self.sys_data,
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""), "FAKE_STATE": self.state,
            "KRISTALL_SETTINGS_BIN": os.path.join(REPO, "image/rootfs/usr/bin/kristall-settings"),
            "KRISTALL_SETTINGS_FILE": self.settings_user, "KRISTALL_SETTINGS_DROPIN_DIRS": dropins,
            "KRISTALL_SETTINGS_DEFAULTS": os.path.join(self.tmp, "defaults.json"),
            "KRISTALL_APPS_MANIFEST": self.manifest, "KRISTALL_HANDS_LOG_STDERR": "1",
        })
        with open(os.environ["KRISTALL_SETTINGS_DEFAULTS"], "w") as f:
            f.write("{}")
        self.session_bus = FakeBus()
        self.system_bus = FakeBus()
        dbus.install("session", self.session_bus)
        dbus.install("system", self.system_bus)
        self.session_bus.add("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver",
                             GetActive=lambda: False, Lock=lambda: None)
        self.bridge = MockBridge(os.path.join(self.run, "kristall/bridge.sock"), scale=scale, width=width, height=height,
                                 capabilities=capabilities) if bridge else None
        if self.bridge:
            self.bridge.start()
        self.daemon = MockDaemon(os.path.join(self.run, "kristall/assistant.sock")).start() if daemon else None
        self.launched: list = []
        self._orig_launch = appsmod.launch

        def fake_launch(app, uris=None, env=None):
            self.launched.append((app.desktop_id, list(uris or [])))
            pid = 5000 + len(self.launched)
            if self.bridge and self.on_launch:
                self.on_launch(app)
            elif self.bridge and not uris:
                # the app's window appears right away
                self.bridge.add_window("{L%d}" % pid, app.stem, app.name, 40, 40, 900, 700, active=True, pid=pid)
            return [pid]
        self.on_launch = None
        appsmod.launch = fake_launch
        self.hands = Hands(bridge=Bridge(), link=Link(), settings=Settings(), apps=AppIndex(self.manifest))
        self.hands.apps.default_for = lambda kind, value: {"https": "org.mozilla.firefox.desktop",
                                                           "inode/directory": "org.kde.dolphin.desktop"}.get(value)
        self.reg, _, self.a11y = build(self.hands)

    def call(self, tool, **args) -> Result:
        t = self.reg.tools[tool]
        problem = t.validate(args)
        if problem:
            return Result.error(problem)
        try:
            return t.fn(Context(1, tool), **args)
        except HandsError as e:
            return Result.error(e.message)

    @staticmethod
    def text(res: Result) -> str:
        return "\n".join(p.get("text", "") for p in res.parts if p["type"] == "text")

    def fake_tool(self, name: str) -> None:
        """Put another fake command on PATH (handled by FAKE_TOOL)."""
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(FAKE_TOOL)
        os.chmod(p, 0o755)

    def fake_state(self) -> dict:
        try:
            with open(self.state) as f:
                return json.load(f)
        except OSError:
            return {}

    def write_state(self, st: dict) -> None:
        with open(self.state, "w") as f:
            json.dump(st, f)

    def close(self):
        appsmod.launch = self._orig_launch
        try:
            self.hands.finish_work()
        except Exception:
            pass
        self.hands.bridge.close()
        self.hands.link.close()
        if self.bridge:
            self.bridge.stop()
        if self.daemon:
            self.daemon.stop()
        os.environ.clear()
        os.environ.update(self.env_backup)
        shutil.rmtree(self.tmp, ignore_errors=True)
