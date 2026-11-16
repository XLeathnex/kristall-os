# SPDX-License-Identifier: GPL-3.0-or-later
"""Refresh-rate choice on KScreen output descriptions (kscreen-doctor -j format) and EDID parsing."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

import fixtures  # noqa: E402
from kristall_power import display, hw, policy  # noqa: E402


def mode(mid, w, h, hz):
    return {"id": str(mid), "name": f"{w}x{h}@{hz}", "size": {"width": w, "height": h}, "refreshRate": hz}


def output(name, typ, modes, cur, connected=True, enabled=True, vrr=2):
    return {"id": 1, "name": name, "type": typ, "connected": connected, "enabled": enabled,
            "currentModeId": str(cur), "modes": modes, "vrrPolicy": vrr}


OLED = output("eDP-1", 7, [mode(1, 2880, 1800, 120.0), mode(2, 2880, 1800, 60.001), mode(3, 1920, 1200, 120.0),
                           mode(4, 1920, 1200, 60.0), mode(5, 2880, 1800, 48.0)], 1)
LCD = output("eDP-1", 7, [mode(1, 1920, 1200, 60.0), mode(2, 1280, 800, 60.0)], 1)
HDMI = output("HDMI-A-1", 6, [mode(10, 2560, 1440, 144.0), mode(11, 2560, 1440, 60.0)], 10)


class Refresh(unittest.TestCase):
    def test_internal_only(self):
        outs = display.internal_outputs({"outputs": [HDMI, OLED]})
        self.assertEqual([o["name"] for o in outs], ["eDP-1"])
        self.assertEqual(display.internal_outputs({"outputs": [dict(OLED, type=0, name="eDP-2")]})[0]["name"], "eDP-2")
        self.assertEqual(display.internal_outputs({"outputs": [dict(OLED, enabled=False)]}), [])
        self.assertEqual(display.internal_outputs(None), [])

    def test_oled_120(self):
        self.assertEqual(display.choose(OLED, "low"), ("2", 60.0))           # same resolution, >= 59 Hz, never 48
        self.assertIsNone(display.choose(OLED, "max"))                       # already at 120
        at60 = dict(OLED, currentModeId="2")
        self.assertEqual(display.choose(at60, "max"), ("1", 120.0))
        self.assertIsNone(display.choose(at60, "low"))
        d = display.describe(OLED)
        self.assertEqual((d["refresh_hz"], d["available_hz"], d["vrr_policy"]), (120.0, [48.0, 60.0, 120.0], "automatic"))

    def test_lcd_single_rate_never_touched(self):
        self.assertIsNone(display.choose(LCD, "low"))
        self.assertIsNone(display.choose(LCD, "max"))

    def test_scaled_resolution_keeps_resolution(self):
        o = dict(OLED, currentModeId="3")
        self.assertEqual(display.choose(o, "low"), ("4", 60.0))

    def test_owner_choice_detection(self):
        o = output("eDP-1", 7, [mode(1, 2880, 1800, 120.0), mode(2, 2880, 1800, 90.0), mode(3, 2880, 1800, 60.0)], 2)
        self.assertTrue(display.owner_managed(o, "3"))       # 90 Hz: not ours, not max
        self.assertFalse(display.owner_managed(dict(o, currentModeId="3"), "3"))
        self.assertFalse(display.owner_managed(dict(o, currentModeId="1"), "3"))

    def test_policy(self):
        self.assertEqual(policy.refresh_policy("balanced", False, "auto"), "max")
        self.assertEqual(policy.refresh_policy("balanced", True, "auto"), "low")
        self.assertEqual(policy.refresh_policy("quiet", True, "auto"), "low")
        self.assertEqual(policy.refresh_policy("performance", True, "auto"), "max")
        self.assertEqual(policy.refresh_policy("quiet", True, "max"), "max")
        self.assertEqual(policy.glass_hint("balanced", False), "high")
        self.assertEqual(policy.glass_hint("quiet", False), "efficient")
        self.assertEqual(policy.glass_hint("performance", True), "efficient")


class Edid(unittest.TestCase):
    def test_parse(self):
        e = hw.parse_edid(fixtures.edid(2880, 1800, 60, vendor="SDC", name="ATNA60"))
        self.assertEqual((e["vendor"], e["name"]), ("SDC", "ATNA60"))
        self.assertEqual(e["timings"][0], {"width": 2880, "height": 1800, "refresh_hz": 60.0})
        self.assertIsNone(hw.parse_edid(b"\x00" * 128))
        self.assertIsNone(hw.parse_edid(b""))


class Rapl(unittest.TestCase):
    def test_targets(self):
        W = 1_000_000
        cap = policy.RAPL_CAPS[("quiet", False)]
        self.assertEqual(policy.rapl_target_uw(cap["pl1"], 45 * W, 0, "pl1"), 20 * W)
        self.assertEqual(policy.rapl_target_uw(cap["pl1"], 25 * W, 0, "pl1"), 12 * W)       # 0.45x25=11.25 -> floor
        self.assertEqual(policy.rapl_target_uw(cap["pl1"], 8 * W, 0, "pl1"), 8 * W)         # never above firmware
        self.assertEqual(policy.rapl_target_uw(cap["pl2"], 115 * W, 40 * W, "pl2"), 40 * W)  # reported max
        self.assertEqual(policy.rapl_target_uw(None, 115 * W, 0, "pl2"), 115 * W)
        self.assertIsNone(policy.rapl_target_uw(cap["pl1"], 0, 0, "pl1"))
        for key, caps in policy.RAPL_CAPS.items():
            for base in (10, 25, 35, 45, 55, 65, 80, 115, 157):
                for which in ("pl1", "pl2"):
                    t = policy.rapl_target_uw(caps[which] if caps else None, base * W, 0, which)
                    self.assertLessEqual(t, base * W, (key, base, which))
                    self.assertTrue(t >= policy.FLOOR_W[which] * W or t == base * W, (key, base, which))


if __name__ == "__main__":
    unittest.main(verbosity=2)
