# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessibility from the start of the session (hands.md §5): apps launched *before* hands runs can
be read when the session was prepared the way the image prepares it (the environment generator's
variables + org.a11y.Status.IsEnabled at login). Firefox (the RPM the image ships) is the case that
needs it: it decides at start whether to build its accessibility tree.

Two sessions, each with Firefox started first and hands afterwards:
  prepared   generator environment + IsEnabled true from the start  -> the page's controls are read
  on_demand  the old scheme: nothing at start, hands switches IsEnabled on when it needs it
             (recorded, not asserted: tells whether Firefox follows the switch late)
Dev container only, under dbus-run-session."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HANDS = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(HANDS))
sys.path.insert(0, HANDS)
sys.path.insert(0, HERE)

from support import firefox  # noqa: E402

try:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi  # noqa: F401
    HAVE = (os.path.exists("/usr/bin/kwin_wayland") and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
            and firefox.available())
except (ImportError, ValueError):
    HAVE = False

from kristall_hands import dbus  # noqa: E402
from kristall_hands.bridge import Bridge  # noqa: E402
from kristall_hands.core import Hands  # noqa: E402
from kristall_hands.link import Link  # noqa: E402
from kristall_hands.server import build  # noqa: E402
from kristall_hands.tooling import Context, HandsError, Result  # noqa: E402


def generator_env(tmp: str) -> dict:
    """What the image's user environment generator prints with the shipped defaults."""
    dropins = os.path.join(tmp, "settings.d")
    os.makedirs(dropins, exist_ok=True)
    for src, dst in (("assistant/core/data/settings-assistant.json", "50-assistant-core.json"),
                     ("assistant/hands/data/settings-hands.json", "50-assistant-hands.json")):
        with open(os.path.join(REPO, src)) as f, open(os.path.join(dropins, dst), "w") as g:
            g.write(f.read())
    env = dict(os.environ, KRISTALL_SETTINGS_BIN=os.path.join(REPO, "image/rootfs/usr/bin/kristall-settings"),
               KRISTALL_SETTINGS_DROPIN_DIRS=dropins, KRISTALL_SETTINGS_DEFAULTS=os.path.join(tmp, "none.json"),
               KRISTALL_SETTINGS_FILE=os.path.join(tmp, "user.json"))
    out = subprocess.run([os.path.join(HANDS, "data/kristall-accessibility-env")], env=env, capture_output=True,
                         text=True, timeout=20).stdout
    return dict(line.split("=", 1) for line in out.split())


def set_bus(on: bool) -> None:
    dbus.session().set("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled", "b", on)


RESULTS = {}


@unittest.skipUnless(HAVE, "needs the dev container (KWin, AT-SPI, firefox) under dbus-run-session")
class SessionAccessibility(unittest.TestCase):
    def read_firefox(self, prepared: bool) -> str:
        from support.session import Session
        tmp = tempfile.mkdtemp(prefix="kristall-ffa11y-")
        s = Session(name="ffa11y" + ("p" if prepared else "d")).start()
        try:
            os.environ.update({"XDG_RUNTIME_DIR": s.run, "WAYLAND_DISPLAY": s.wayland,
                               "KRISTALL_HANDS_LOG_STDERR": "1", "KRISTALL_SETTINGS_BIN": "/nonexistent"})
            env = generator_env(tmp) if prepared else {}
            if prepared:
                self.assertEqual(env, {"QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1", "GNOME_ACCESSIBILITY": "1",
                                       "ACCESSIBILITY_ENABLED": "1"})
            set_bus(prepared)          # what kristall-hands-session.service does at login
            firefox.start(s, tmp, env)
            time.sleep(12)             # Firefox is up and idle before hands exists
            h = Hands(bridge=Bridge(path=os.path.join(tmp, "no-bridge.sock")),
                      link=Link(path=os.path.join(tmp, "no-daemon.sock")))
            reg, _, a = build(h)
            t = reg.tools["ui_tree"]
            text = ""
            end = time.monotonic() + 20
            while time.monotonic() < end:
                try:
                    r = t.fn(Context(1, "ui_tree"), window="Firefox", find="Bestellen")
                except HandsError as e:
                    r = Result.error(e.message)
                text = "\n".join(p["text"] for p in r.parts if p["type"] == "text")
                if "Bestellen" in text and "button" in text:
                    break
                time.sleep(1)
            a.restore()
            return text
        finally:
            s.stop()

    def test_1_firefox_started_before_hands_is_readable(self):
        text = self.read_firefox(prepared=True)
        RESULTS["prepared"] = text
        self.assertIn("Bestellen", text)
        self.assertRegex(text, r"button[^\n]*Bestellen")

    def test_2_old_scheme_for_comparison(self):
        text = self.read_firefox(prepared=False)
        RESULTS["on_demand"] = text
        readable = "Bestellen" in text and "button" in text
        print(f"\n   on_demand (Firefox started before accessibility was switched on): "
              f"{'page readable' if readable else 'page NOT readable'}", flush=True)

    @classmethod
    def tearDownClass(cls):
        for k, v in RESULTS.items():
            print(f"\n   [{k}] ui_tree find=Bestellen:\n" + "\n".join("     " + l for l in v.splitlines()[:12]), flush=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
