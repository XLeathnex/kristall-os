# SPDX-License-Identifier: GPL-3.0-or-later
"""Tier 1 (direct actions) against mocked services: fake D-Bus, fake wpctl/kwriteconfig6/wl-clipboard,
the real kristall-settings, a mock bridge."""
import json
import os
import time
import unittest

from support.env import Env, appsmod, dbus  # noqa: F401  (env sets sys.path)
from kristall_hands import reminders, safety
from kristall_hands.server import dropin


class Tier1(unittest.TestCase):
    def setUp(self):
        self.e = Env(scale=1.0, width=1800, height=1125)

    def tearDown(self):
        self.e.close()

    def t(self, tool, **a):
        return self.e.text(self.e.call(tool, **a))

    # ------------------------------------------------------------------ apps
    def test_open_app_german_fuzzy(self):
        cases = {
            "öffne den Rechner": "org.kde.kcalc.desktop",
            "mach Blender auf": "org.blender.Blender.desktop",
            "Taschenrechner": "org.kde.kcalc.desktop",
            "Dateien": "org.kde.dolphin.desktop",
            "den Browser": "org.mozilla.firefox.desktop",
            "Einstellungen": "systemsettings.desktop",
            "Systemeinstellungen öffnen": "systemsettings.desktop",
            "Blendr": "org.blender.Blender.desktop",
            "Roblox Studio": "org.vinegarhq.Vinegar.desktop",
            "Musik": "org.kde.elisa.desktop",
            "Texteditor": "org.kde.kwrite.desktop",
            "Kate": "org.kde.kate.desktop",
            "starte bitte Steam": "com.valvesoftware.Steam.desktop",
            "open the calculator": "org.kde.kcalc.desktop",
            "Terminal": "org.kde.konsole.desktop",
        }
        for q, want in cases.items():
            self.e.launched.clear()
            self.e.bridge.windows.clear()
            out = self.t("open_app", name=q)
            self.assertEqual(self.e.launched and self.e.launched[0][0], want, f"{q!r}: {out}")

    def test_open_app_not_found_and_not_installed(self):
        out = self.t("open_app", name="Photoshop")
        self.assertIn("can't find an app", out)
        out = self.t("open_app", name="Bildbetrachter")      # in the manifest, not installed here
        self.assertIn("not installed", out)
        self.assertEqual(self.e.launched, [])

    def test_open_app_already_running_activates(self):
        b = self.e.bridge
        b.add_window("{k1}", "org.kde.kcalc", "KCalc", 100, 100, 400, 500, minimized=True)
        b.add_window("{k2}", "org.kde.kate", "Unbenannt — Kate", 0, 0, 900, 700, active=True)
        out = self.t("open_app", name="Rechner")
        self.assertEqual(self.e.launched, [])
        self.assertIn("already open", out)
        self.assertTrue(b.win("{k1}")["active"])
        self.assertFalse(b.win("{k1}")["minimized"])

    def test_open_app_waits_for_window(self):
        b = self.e.bridge

        def appear(app):
            import threading
            threading.Timer(0.3, lambda: b.add_window("{new}", "org.kde.kate", "Unbenannt — Kate", 50, 50, 800, 600,
                                                      active=True, pid=5001)).start()
        self.e.on_launch = appear
        out = self.t("open_app", name="Kate")
        self.assertIn("is open and in front", out)
        self.assertIn("Unbenannt — Kate", out)
        self.assertIn("<screen-content-", out)   # titles are framed as screen content

    def test_open_targets(self):
        os.makedirs(os.path.join(self.e.home, "Dokumente"))
        out = self.t("open", target="~/Dokumente")
        self.assertEqual(self.e.launched[-1][0], "org.kde.dolphin.desktop", out)
        self.assertTrue(self.e.launched[-1][1][0].startswith("file://"))
        self.t("open", target="https://example.org/a?b=1")
        self.assertEqual(self.e.launched[-1], ("org.mozilla.firefox.desktop", ["https://example.org/a?b=1"]))
        self.assertIn("don't open", self.t("open", target="javascript:alert(1)"))
        self.assertIn("no file", self.t("open", target="~/gibtsnicht.txt"))
        os.makedirs(os.path.join(self.e.home, ".claude"))
        self.assertIn("off limits", self.t("open", target="~/.claude"))
        exe = os.path.join(self.e.home, "run.sh")
        with open(exe, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(exe, 0o755)
        self.assertIn("is a program", self.t("open", target="~/run.sh"))

    # ------------------------------------------------------------------ accessibility from the session start
    def _generator(self, settings: dict) -> list[str]:
        import subprocess
        os.makedirs(os.path.dirname(self.e.settings_user), exist_ok=True)
        with open(self.e.settings_user, "w") as f:
            json.dump(settings, f)
        gen = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kristall-accessibility-env")
        r = subprocess.run([gen], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def test_accessibility_environment_generator(self):
        """hands.md §5: apps start with accessibility on while the assistant is enabled (default)"""
        on = ["QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1", "GNOME_ACCESSIBILITY=1", "ACCESSIBILITY_ENABLED=1"]
        self.assertEqual(self._generator({}), on, "defaults: assistant enabled, mode always")
        self.assertEqual(self._generator({"assistant": {"enabled": False}}), [])
        self.assertEqual(self._generator({"assistant": {"hands": {"accessibility": "on_demand"}}}), [])
        self.assertEqual(self._generator({"assistant": {"hands": {"accessibility": "off"}}}), [])
        os.environ["KRISTALL_SETTINGS_BIN"] = "/nonexistent"          # never fails, prints nothing
        self.assertEqual(self._generator({}), [])

    def test_session_start_sets_bus_status(self):
        from kristall_hands.__main__ import session_start
        status = {"IsEnabled": False, "ScreenReaderEnabled": False}
        self.e.session_bus.add("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", status)
        bus = self.e.session_bus

        def is_enabled():
            return bus.get("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled")
        session_start()
        self.assertTrue(is_enabled(), "assistant enabled + mode always: on from the start")
        self.assertFalse(bus.get("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "ScreenReaderEnabled"))
        os.makedirs(os.path.dirname(self.e.settings_user), exist_ok=True)
        for settings in ({"assistant": {"enabled": False}}, {"assistant": {"hands": {"accessibility": "on_demand"}}}):
            with open(self.e.settings_user, "w") as f:
                json.dump(settings, f)
            session_start()
            self.assertFalse(is_enabled(), settings)

    # ------------------------------------------------------------------ windows
    def test_windows(self):
        b = self.e.bridge
        b.add_window("{a}", "org.kde.kate", "Notizen — Kate", 10, 10, 800, 600, active=True)
        b.add_window("{b}", "org.mozilla.firefox", "Wetter — Firefox", 300, 200, 900, 700)
        out = self.t("list_windows")
        self.assertIn("w1", out)
        self.assertIn("Notizen — Kate", out)
        self.t("window", action="side_by_side", window="Kate", other="firefox")
        self.assertEqual({k: b.win("{a}")[k] for k in "xywh"}, {"x": 0, "y": 0, "w": 900, "h": 1125})
        self.assertEqual({k: b.win("{b}")[k] for k in "xywh"}, {"x": 900, "y": 0, "w": 900, "h": 1125})
        self.t("window", action="minimize", window="w2")
        self.assertTrue(b.win("{b}")["minimized"])
        self.t("window", action="activate", window="Firefox")
        self.assertTrue(b.win("{b}")["active"])
        self.assertFalse(b.win("{b}")["minimized"])
        self.t("window", action="move_resize", window="kate", x=5, y=6, w=700, h=500)
        self.assertEqual(b.last("window.setGeometry"), {"id": "{a}", "x": 5, "y": 6, "w": 700, "h": 500})
        self.t("window", action="close", window="Wetter")
        self.assertIsNone(b.win("{b}"))
        self.assertIn("can't find an open window", self.t("window", action="close", window="Blender"))

    def test_window_arrangement_uses_work_area(self):
        """bridge.md workArea: halves and side by side stay inside what the menu bar and Dock leave
        free, and follow a live change of the reservation"""
        b = self.e.bridge
        b.outputs[0]["workArea"] = {"x": 0, "y": 30, "w": 1800, "h": 1029}   # bar 30, Dock 66
        b.add_window("{a}", "org.kde.kate", "Notizen — Kate", 10, 10, 800, 600, active=True)
        b.add_window("{b}", "org.mozilla.firefox", "Wetter — Firefox", 300, 200, 900, 700)
        self.t("window", action="left_half", window="Kate")
        self.assertEqual({k: b.win("{a}")[k] for k in "xywh"}, {"x": 0, "y": 30, "w": 900, "h": 1029})
        self.t("window", action="right_half", window="Firefox")
        self.assertEqual({k: b.win("{b}")[k] for k in "xywh"}, {"x": 900, "y": 30, "w": 900, "h": 1029})
        # the Dock hides automatically: the bridge sends outputs.changed with the larger work area
        b.outputs[0]["workArea"] = {"x": 0, "y": 30, "w": 1800, "h": 1095}
        b.emit("outputs", "outputs.changed", {"outputs": b.outputs})
        time.sleep(0.2)
        self.t("window", action="side_by_side", window="Kate", other="firefox")
        self.assertEqual({k: b.win("{a}")[k] for k in "xywh"}, {"x": 0, "y": 30, "w": 900, "h": 1095})
        self.assertEqual({k: b.win("{b}")[k] for k in "xywh"}, {"x": 900, "y": 30, "w": 900, "h": 1095})
        self.t("window", action="center", window="Kate")
        g = b.win("{a}")
        self.assertEqual((g["x"], g["y"]), (450, 30 + (1095 - 1095) // 2))

    # ------------------------------------------------------------------ sound and screen
    def test_volume(self):
        self.assertIn("40%", self.t("volume", change=-10))
        self.assertIn("70%", self.t("volume", level=70))
        self.assertIn("muted", self.t("volume", mute=True))
        out = self.t("volume", change=10)        # changing the level unmutes
        self.assertIn("80%", out)
        self.assertNotIn("muted", out)
        self.assertIn("100%", self.t("volume", change=90))   # clamped
        self.assertIn("Microphone: 80%", self.t("volume", device="microphone"))
        calls = self.e.fake_state()["calls"]
        self.assertIn(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "0.40"], calls)

    def test_brightness(self):
        bus = self.e.session_bus
        sets = []
        bus.add("org.kde.ScreenBrightness", "/org/kde/ScreenBrightness", "org.kde.ScreenBrightness",
                {"DisplaysDBusNames": ["display1", "display0"]})
        bus.add("org.kde.ScreenBrightness", "/org/kde/ScreenBrightness/display0", "org.kde.ScreenBrightness.Display",
                {"Label": "Built-in Screen", "IsInternal": True, "MaxBrightness": 1000, "Brightness": 500},
                SetBrightness=lambda v, f: sets.append(("d0", v, f)))
        bus.add("org.kde.ScreenBrightness", "/org/kde/ScreenBrightness/display1", "org.kde.ScreenBrightness.Display",
                {"Label": "DELL", "IsInternal": False, "MaxBrightness": 100, "Brightness": 80},
                SetBrightness=lambda v, f: sets.append(("d1", v, f)))
        out = self.t("brightness", change=10)
        self.assertEqual(sets, [("d0", 600, 0)], out)
        self.assertIn("60%", out)
        self.t("brightness", level=0)
        self.assertEqual(sets[-1], ("d0", 10, 0))     # never fully black
        sets.clear()
        self.t("brightness", level=50, all_displays=True)
        self.assertEqual(sorted(sets), [("d0", 500, 0), ("d1", 50, 0)])

    def test_brightness_unavailable(self):
        out = self.t("brightness", change=10)
        self.assertIn("not available", out)

    # ------------------------------------------------------------------ network
    def _nm(self):
        bus = self.e.system_bus
        NM = "org.freedesktop.NetworkManager"
        state = {"active": None, "activated": []}
        bus.add(NM, "/org/freedesktop/NetworkManager", NM, {"WirelessEnabled": True, "WirelessHardwareEnabled": True},
                GetDevices=lambda: (["/dev/eth", "/dev/wl"],),
                ActivateConnection=lambda c, d, s: state["activated"].append(c) or ("/active/1",),
                AddAndActivateConnection=lambda s, d, ap: state["activated"].append(ap) or ("/c/new", "/active/2"))
        bus.add(NM, "/dev/eth", f"{NM}.Device", {"DeviceType": 1})
        bus.add(NM, "/dev/wl", f"{NM}.Device", {"DeviceType": 2}, Disconnect=lambda: None)
        aps = {"/ap/1": ("Zuhause", 80, 0x188), "/ap/2": ("Café Frei", 60, 0), "/ap/3": ("Nachbar", 30, 0x188),
               "/ap/4": ("Zuhause", 40, 0x188)}
        bus.add(NM, "/dev/wl", f"{NM}.Device.Wireless", {"ActiveAccessPoint": "/ap/1"},
                GetAllAccessPoints=lambda: (list(aps),), RequestScan=lambda o: None)
        for p, (ssid, st, rsn) in aps.items():
            bus.add(NM, p, f"{NM}.AccessPoint", {"Ssid": list(ssid.encode()), "Strength": st, "RsnFlags": rsn,
                                                 "WpaFlags": 0, "Flags": 1 if rsn else 0})
        bus.add(NM, "/org/freedesktop/NetworkManager/Settings", f"{NM}.Settings", {},
                ListConnections=lambda: (["/c/1"],))
        bus.add(NM, "/c/1", f"{NM}.Settings.Connection", {},
                GetSettings=lambda: ({"802-11-wireless": {"ssid": list(b"Zuhause")}},))
        return state

    def test_wifi(self):
        state = self._nm()
        out = self.t("wifi", action="status")
        self.assertIn("Wi-Fi is on", out)
        self.assertIn("connected to Zuhause (signal 80%)", out)
        out = self.t("wifi", action="list")
        self.assertIn("Zuhause — 80% (saved)", out)
        self.assertIn("Café Frei — 60% (open, no password)", out)
        self.assertEqual(out.count("Zuhause"), 1)
        self.t("wifi", action="connect", network="Zuhause")
        self.assertEqual(state["activated"], ["/c/1"])
        out = self.t("wifi", action="connect", network="Nachbar")
        self.assertIn("needs a password", out)
        self.t("wifi", action="connect", network="Café Frei")
        self.assertEqual(state["activated"][-1], "/ap/2")
        self.t("wifi", action="off")
        self.assertFalse(self.e.system_bus.get("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                                               "org.freedesktop.NetworkManager", "WirelessEnabled"))

    def test_wifi_unavailable(self):
        self.assertIn("not available", self.t("wifi", action="status"))

    def test_bluetooth(self):
        bus = self.e.system_bus
        calls = []
        objs = {"/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": False}},
                "/org/bluez/hci0/dev_1": {"org.bluez.Device1": {"Alias": "Sony Kopfhörer", "Paired": True, "Connected": False}},
                "/org/bluez/hci0/dev_2": {"org.bluez.Device1": {"Alias": "Fremdes Gerät", "Paired": False}}}
        bus.add("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", {}, GetManagedObjects=lambda: (objs,))
        bus.add("org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", {"Powered": False})
        bus.add("org.bluez", "/org/bluez/hci0/dev_1", "org.bluez.Device1", {},
                Connect=lambda: calls.append("connect"), Disconnect=lambda: calls.append("disconnect"))
        out = self.t("bluetooth", action="list")
        self.assertIn("1 paired", out)
        self.assertIn("Sony Kopfhörer", out)
        self.t("bluetooth", action="connect", device="kopfhorer")
        self.assertEqual(calls, ["connect"])
        self.assertTrue(bus.get("org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered"))
        self.assertIn("No paired device", self.t("bluetooth", action="connect", device="Lautsprecher"))

    # ------------------------------------------------------------------ look and feel
    def test_appearance_writes_settings(self):
        out = self.t("appearance", theme="dark", glass=0.75)
        self.assertIn("theme dark", out)
        with open(self.e.settings_user) as f:
            user = json.load(f)
        self.assertEqual(user["appearance"], {"theme": "dark", "glass": 0.75})

    def test_dnd_and_night_light(self):
        # one source of truth: panels.focus.until (0 off, -1 until switched off, else ms since the epoch)
        def until():
            with open(self.e.settings_user) as f:
                return json.load(f)["panels"]["focus"]["until"]
        before = time.time() * 1000
        out = self.t("do_not_disturb", on=True, minutes=30)
        self.assertIn("30 minutes", out)
        self.assertTrue(before + 30 * 60000 - 1000 <= until() <= time.time() * 1000 + 30 * 60000 + 1000, until())
        self.t("do_not_disturb", on=True)
        self.assertEqual(until(), -1)
        self.t("do_not_disturb", on=False)
        self.assertEqual(until(), 0)
        self.assertFalse([c for c in self.e.fake_state().get("calls", []) if "plasmanotifyrc" in c],
                         "Plasma's own Do Not Disturb keys are not written any more")
        bus = self.e.session_bus
        bus.add("org.kde.KWin", "/KWin", "org.kde.KWin", {}, reconfigure=lambda: None)
        bus.add("org.kde.KWin", "/org/kde/KWin/NightLight", "org.kde.KWin.NightLight",
                {"available": True, "enabled": True, "currentTemperature": 4500})
        out = self.t("night_light", on=True)
        self.assertIn("Night Light is on", out)
        self.assertIn(["kwriteconfig6", "--file", "kwinrc", "--group", "NightColor", "--key", "Active", "--type", "bool",
                       "--notify", "true"], self.e.fake_state()["calls"])
        self.assertTrue(bus.methods("reconfigure"))

    def test_power_mode(self):
        bus = self.e.system_bus
        bus.add("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
                "org.freedesktop.UPower.PowerProfiles", {"ActiveProfile": "balanced"})
        self.assertIn("Ausgewogen", self.t("power_mode"))
        self.assertIn("Leise", self.t("power_mode", mode="quiet"))
        self.assertEqual(bus.get("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
                                 "org.freedesktop.UPower.PowerProfiles", "ActiveProfile"), "power-saver")

    def test_power_mode_through_kristall_power(self):
        """power.md §7.1: the fourth choice `auto`, manual choices and the reading come from kristall-power"""
        self.e.fake_tool("kristall-power")
        st = self.e.fake_state()
        st["power"] = {"reachable": True, "status": {
            "schema": 1, "mode": "quiet", "power_source": "battery",
            "automatic": {"enabled": True, "manual": None, "reason": "auto", "hold": None}}}
        self.e.write_state(st)
        out = self.t("power_mode")
        self.assertIn("Automatisch", out)
        self.assertIn("Leise", out)
        out = self.t("power_mode", mode="performance")
        self.assertIn(["kristall-power", "mode", "performance"], self.e.fake_state()["calls"])
        self.assertIn("Leistung", out)
        self.assertIn("chosen manually", out)
        out = self.t("power_mode", mode="auto")
        self.assertIn(["kristall-power", "mode", "auto"], self.e.fake_state()["calls"])
        self.assertIn("Automatisch", out)
        # the session daemon is not running: auto cannot work, manual choices fall back to the PPD API
        st = self.e.fake_state()
        st["power"]["reachable"] = False
        self.e.write_state(st)
        self.assertIn("not available", self.t("power_mode", mode="auto"))
        bus = self.e.system_bus
        bus.add("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
                "org.freedesktop.UPower.PowerProfiles", {"ActiveProfile": "balanced"})
        self.assertIn("Leise", self.t("power_mode", mode="quiet"))
        self.assertEqual(bus.get("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
                                 "org.freedesktop.UPower.PowerProfiles", "ActiveProfile"), "power-saver")

    def test_power_mode_auto_without_kristall_power(self):
        self.assertIn("not available", self.t("power_mode", mode="auto"))

    def test_power_mode_legacy_name(self):
        bus = self.e.system_bus
        bus.add("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles",
                {"ActiveProfile": "balanced"})
        self.assertIn("Leistung", self.t("power_mode", mode="performance"))

    # ------------------------------------------------------------------ media and session
    def test_media(self):
        bus = self.e.session_bus
        calls = []
        for n, st, title in (("org.mpris.MediaPlayer2.elisa", "Paused", "Alt"),
                             ("org.mpris.MediaPlayer2.firefox.instance_1_2", "Playing", "Lo-fi beats")):
            bus.add(n, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
                    {"PlaybackStatus": st, "Metadata": {"xesam:title": title, "xesam:artist": ["X"]}},
                    Pause=lambda n=n: calls.append((n, "Pause")), Next=lambda n=n: calls.append((n, "Next")),
                    PlayPause=lambda n=n: calls.append((n, "PlayPause")))
        out = self.t("media", action="pause")
        self.assertEqual(calls, [("org.mpris.MediaPlayer2.firefox.instance_1_2", "Pause")])
        self.assertIn("Lo-fi beats", out)
        self.t("media", action="next", player="Elisa")
        self.assertEqual(calls[-1], ("org.mpris.MediaPlayer2.elisa", "Next"))

    def test_media_none(self):
        self.assertIn("No music or video player", self.t("media", action="toggle"))

    def test_lock_and_sleep(self):
        locks = []
        self.e.session_bus.objects[("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver")]["methods"]["Lock"] = lambda: locks.append(1)
        self.t("lock_or_sleep", action="lock")
        self.assertEqual(locks, [1])
        sus = []
        self.e.system_bus.add("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", {},
                              CanSuspend=lambda: "yes", Suspend=lambda i: sus.append(i))
        self.t("lock_or_sleep", action="sleep")
        self.assertEqual(sus, [False])

    def test_system_status(self):
        self.e.system_bus.add("org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice",
                              "org.freedesktop.UPower.Device",
                              {"IsPresent": True, "Percentage": 63.0, "State": 2, "TimeToEmpty": 3 * 3600 + 20 * 60})
        out = self.t("system_status")
        self.assertIn("Battery 63% (on battery, 3 h 20 min left)", out)
        self.assertIn("Volume: 50%", out)
        self.assertIn("Memory:", out)

    def test_system_status_from_kristall_power(self):
        """battery, draw and temperatures come from `kristall-power status --json` (power.md §7.2)"""
        self.e.fake_tool("kristall-power")
        st = self.e.fake_state()
        st["power"] = {"reachable": True, "status": {
            "schema": 1, "mode": "quiet", "power_source": "battery",
            "automatic": {"enabled": True, "manual": None, "reason": "auto"},
            "battery": {"percent": 64, "status": "Discharging", "health_percent": 92.1, "time_to_empty_s": 28654,
                        "time_to_full_s": None, "power_w": 7.4},
            "charge_limit": {"supported": True, "value": 80},
            "draw": {"watts": 7.4, "source": "battery"},
            "temperatures": {"cpu_package": 52.0, "nvme": 38.9}, "fans": {"thinkpad/fan1": 0}}}
        self.e.write_state(st)
        out = self.t("system_status")
        self.assertIn("Battery 64% (on battery, 7 h 57 min left), health 92%, charging stops at 80%", out)
        self.assertIn("Power draw: 7.4 W", out)
        self.assertIn("CPU temperature: 52 °C", out)
        self.assertIn("Fans: off", out)
        self.assertIn("Power mode: Automatisch (automatic) — now Leise (quiet)", out)
        self.assertEqual([c for c in self.e.fake_state()["calls"] if c[0] == "kristall-power"],
                         [["kristall-power", "status", "--json"]], "one status call")

    # ------------------------------------------------------------------ clipboard, notifications, files
    def test_clipboard(self):
        self.assertIn("Copied 11", self.t("clipboard", action="set", text="Hallo Welt!"))
        out = self.t("clipboard", action="get")
        self.assertIn("Hallo Welt!", out)
        self.assertIn("<screen-content-", out)
        st = self.e.fake_state()
        st["clip"] = "mein key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
        self.e.write_state(st)
        out = self.t("clipboard", action="get")
        self.assertNotIn("abcdefghijklmnop", out)
        self.assertIn("[hidden key", out)
        st["cliptypes"] = ["text/plain", "x-kde-passwordManagerHint"]
        self.e.write_state(st)
        self.assertIn("password manager", self.t("clipboard", action="get"))

    def test_notify_and_reveal(self):
        bus = self.e.session_bus
        got = []
        bus.add("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", {},
                Notify=lambda *a: got.append(a) or 7)
        self.t("notify", title="Tee ist fertig", body="Viel Spaß")
        self.assertEqual(got[0][3:5], ("Tee ist fertig", "Viel Spaß"))
        shown = []
        bus.add("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1", {},
                ShowItems=lambda uris, sid: shown.append(uris))
        p = os.path.join(self.e.home, "Bild 1.png")
        open(p, "w").close()
        self.t("reveal_in_files", path="~/Bild 1.png")
        self.assertEqual(shown, [["file://" + p.replace(" ", "%20")]])

    def test_trash(self):
        try:
            import gi  # noqa: F401
        except ImportError:
            self.skipTest("python3-gobject not available on this host")
        p = os.path.join(self.e.home, "alt.txt")
        with open(p, "w") as f:
            f.write("x")
        out = self.t("move_to_trash", paths=["~/alt.txt", "~/gibtsnicht", "~/.claude/x"])
        self.assertFalse(os.path.exists(p), out)
        self.assertIn("Moved 1", out)
        self.assertIn("not allowed", out)
        self.assertTrue(os.listdir(os.path.join(self.e.data, "Trash/files")))

    # ------------------------------------------------------------------ timers
    def test_timers(self):
        bus = self.e.session_bus
        started, stopped = [], []
        bus.add("org.freedesktop.systemd1", "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager", {},
                StartTransientUnit=lambda name, mode, props, aux: started.append((name, dict(props), aux)) or ("/job/1",),
                StopUnit=lambda name, mode: stopped.append(name) or ("/job/2",))
        notes = []
        bus.add("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", {},
                Notify=lambda *a: notes.append(a) or 1)
        out = self.t("timer", action="set", kind="timer", in_seconds=300, text="Nudeln")
        self.assertIn("in 5 min", out)
        name, props, aux = started[-1]
        self.assertTrue(name.startswith("kristall-reminder-") and name.endswith(".timer"))
        self.assertEqual(props["AccuracyUSec"], 1_000_000)
        exec_start = dict(aux[0][1])["ExecStart"]
        self.assertEqual(exec_start[0][1][-2], "fire")
        rid = exec_start[0][1][-1]
        self.t("timer", action="set", kind="alarm", at="07:30", text="Aufstehen", repeat="weekdays")
        out = self.t("timer", action="list")
        self.assertIn("Nudeln", out)
        self.assertIn("repeats weekdays", out)
        # firing delivers a notification and removes the one-shot timer
        reminders.fire(rid)
        self.assertEqual(notes[-1][3], "Timer")
        self.assertEqual(notes[-1][4], "Nudeln")
        self.assertNotIn("Nudeln", self.t("timer", action="list"))
        self.assertIn("Cancelled 1", self.t("timer", action="cancel", which="aufstehen"))
        self.assertTrue(stopped)
        self.assertIn("No timers", self.t("timer", action="list"))

    def test_rearm_fires_missed(self):
        bus = self.e.session_bus
        started = []
        bus.add("org.freedesktop.systemd1", "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager", {},
                StartTransientUnit=lambda *a: started.append(a[0]) or ("/j",), StopUnit=lambda *a: ("/j",))
        notes = []
        bus.add("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", {},
                Notify=lambda *a: notes.append(a) or 1)
        with reminders.locked_store() as d:
            d["items"] = [{"id": "old1", "kind": "reminder", "text": "Mama anrufen", "at": time.time() - 3600},
                          {"id": "new1", "kind": "reminder", "text": "Später", "at": time.time() + 3600}]
        reminders.rearm_all()
        self.assertEqual(started, ["kristall-reminder-new1.timer"])
        self.assertIn("verpasst", notes[0][4])

    def test_timer_parse(self):
        import datetime as dt
        now = dt.datetime(2026, 11, 15, 21, 0)
        self.assertEqual(reminders.parse_when("07:30", None, now), dt.datetime(2026, 11, 16, 7, 30))
        self.assertEqual(reminders.parse_when("22.15", None, now), dt.datetime(2026, 11, 15, 22, 15))
        self.assertEqual(reminders.parse_when("2026-12-24T18:00", None, now), dt.datetime(2026, 12, 24, 18, 0))
        nxt = reminders.next_repeat(dt.datetime(2026, 11, 14, 7, 30), "weekdays", now)   # Sat -> Mon
        self.assertEqual(nxt, dt.datetime(2026, 11, 16, 7, 30))


class Declarations(unittest.TestCase):
    def setUp(self):
        self.e = Env(bridge=False, daemon=False)

    def tearDown(self):
        self.e.close()

    def test_every_tool_declared(self):
        for name, t in self.e.reg.tools.items():
            self.assertTrue(t.description and len(t.description) < 700, name)
            self.assertIn(t.risk, ("read", "reversible"), name)
            self.assertTrue(t.label and t.label.get("de"), name)
        for name in ("click", "drag", "type_text", "press_keys", "ui_act"):
            props = self.e.reg.tools[name].schema["properties"]
            self.assertIn("risk", props, name)
            self.assertIn("intent", props, name)
            self.assertIn("purchase", props["risk"]["enum"])

    def test_dropin_matches_registry(self):
        d = dropin(self.e.reg)
        self.assertEqual(d["mcpServers"]["hands"]["command"], "/usr/bin/kristall-hands")
        self.assertEqual(set(d["kristall"]["hands"]["tools"]) - {"*"}, set(self.e.reg.tools))
        self.assertEqual(d["kristall"]["hands"]["tools"]["*"], {"risk": "ask"})
        # the daemon's own loader accepts it (assistant/core/kristall_assistant/brain/mcp_config.py)
        import importlib.util
        import sys
        core = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "core")
        if os.path.isdir(os.path.join(core, "kristall_assistant")):
            sys.path.insert(0, core)
            try:
                spec = importlib.util.find_spec("kristall_assistant.brain.mcp_config")
                if spec is None:
                    raise ImportError
                from kristall_assistant.brain import mcp_config
            except ImportError:
                self.skipTest("assistant-core not importable here")
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                with open(os.path.join(td, "50-hands.json"), "w") as f:
                    json.dump(d, f)
                setup = mcp_config.load([__import__("pathlib").Path(td)])
            self.assertIn("hands", setup.servers)
            self.assertEqual(setup.decls["hands"]["click"].risk, "reversible")
            self.assertEqual(setup.decls["hands"]["screenshot"].risk, "read")
            self.assertIn("hands", setup.event_publishers)

    def test_defaults_file_matches_code(self):
        from kristall_hands.config import DEFAULTS
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data/settings-hands.json")) as f:
            self.assertEqual(json.load(f)["assistant"]["hands"], DEFAULTS)


class Safety(unittest.TestCase):
    def test_mask_secrets(self):
        m = safety.mask_secrets
        self.assertIn("[card number ending 1111]", m("Karte 4111 1111 1111 1111 bitte"))
        self.assertEqual(m("Telefon 0176 1234 5678"), "Telefon 0176 1234 5678")
        self.assertIn("[hidden key ghp_", m("token ghp_abcdefghijklmnopqrstuvwxyz1234"))
        self.assertIn("[hidden private key]", m("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"))
        self.assertEqual(m("/home/user/Dokumente/Urlaubsfotos/2026/Gardasee"), "/home/user/Dokumente/Urlaubsfotos/2026/Gardasee")
        self.assertIn("hidden secret-looking", m("x A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1 y"))

    def test_auth_windows(self):
        prot = ["org.kde.polkit-kde-authentication-agent-1"]
        self.assertTrue(safety.is_auth_window({"appId": "org.kde.polkit-kde-authentication-agent-1", "title": "x"}, prot))
        self.assertTrue(safety.is_auth_window({"appId": "foo", "title": "Legitimierung erforderlich"}, prot))
        self.assertTrue(safety.is_auth_window({"appId": "firefox", "title": "Passwort eingeben"}, prot))
        self.assertFalse(safety.is_auth_window({"appId": "org.kde.kate", "title": "Einkaufsliste — Kate"}, prot))


if __name__ == "__main__":
    unittest.main()
