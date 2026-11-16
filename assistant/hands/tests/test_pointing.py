# SPDX-License-Identifier: GPL-3.0-or-later
"""Tier 3 (seeing and pointing) against the mock bridge: exact coordinate mapping at output
scale 1.0 and 1.6 with synthetic images, typing, keys, owner priority, Escape, lock screen,
protected windows, fail-soft without the bridge, and the agent-cursor choreography."""
import base64
import time
import unittest

from support.env import Env
from support import png
from kristall_hands.core import CANCELLED_BY_OWNER, NO_BRIDGE
from kristall_hands.safety import AUTH_MSG, LOCKED_MSG

RED, GREEN, BLUE = (230, 30, 30), (30, 200, 60), (40, 90, 240)


def image_of(res):
    for p in res.parts:
        if p["type"] == "image":
            return png.decode(base64.b64decode(p["data"]))
    raise AssertionError("no image in result")


class Mapping(unittest.TestCase):
    def run_case(self, scale):
        e = Env(scale=scale, width=1800, height=1125)
        try:
            b = e.bridge
            b.add_window("{win}", "org.kde.kate", "Kate", 300, 200, 400, 300, active=True)
            b.markers = [((700, 400, 20, 20), RED), ((330, 260, 8, 8), GREEN), ((1500, 1000, 3, 3), BLUE)]
            report = {}
            # 1) whole screen, downscaled to fit 1280x800
            res = e.call("screenshot", target="screen")
            img = image_of(res)
            self.assertLessEqual(img[0], 1280)
            self.assertLessEqual(img[1], 800)
            cx, cy = png.find_color(img, RED)
            px, py = round(cx), round(cy)
            e.call("click", x=px, y=py)
            p = b.last("agent.pointer")
            s = e.hands  # noqa: F841
            shot = e.reg.tools["screenshot"]  # noqa: F841
            sc_meta = next(iter(m for k, m in self._screen(e).shots.items() if k.startswith("s")))
            exp_x = sc_meta["ox"] + px / sc_meta["sx"]
            exp_y = sc_meta["oy"] + py / sc_meta["sy"]
            self.assertAlmostEqual(p["x"], exp_x, places=9)
            self.assertAlmostEqual(p["y"], exp_y, places=9)
            self.assertLessEqual(abs(p["x"] - 710), 1 / sc_meta["sx"] + 1e-9)
            self.assertLessEqual(abs(p["y"] - 410), 1 / sc_meta["sy"] + 1e-9)
            report["screen"] = (img[0], img[1], round(sc_meta["sx"], 4), round(p["x"] - 710, 3), round(p["y"] - 410, 3))
            # 2) a small window: not downscaled, image px per logical px = output scale
            res = e.call("screenshot", window="Kate")
            img = image_of(res)
            self.assertEqual((img[0], img[1]), (round(400 * scale), round(300 * scale)))
            gx, gy = png.find_color(img, GREEN)
            e.call("click", x=round(gx), y=round(gy))
            p = b.last("agent.pointer")
            self.assertLessEqual(abs(p["x"] - 334), 1 / scale + 1e-9)
            self.assertLessEqual(abs(p["y"] - 264), 1 / scale + 1e-9)
            report["window"] = (img[0], img[1], scale, round(p["x"] - 334, 3), round(p["y"] - 264, 3))
            # 3) zoom on the tiny blue marker of the screen shot, then click inside the zoom image
            e.call("screenshot", target="screen")
            sid = self._screen(e).last_shot
            meta = self._screen(e).shots[sid]
            bx0, by0 = (1480 - meta["ox"]) * meta["sx"], (980 - meta["oy"]) * meta["sy"]
            bx1, by1 = (1530 - meta["ox"]) * meta["sx"], (1030 - meta["oy"]) * meta["sy"]
            res = e.call("zoom", x0=bx0, y0=by0, x1=bx1, y1=by1)
            zimg = image_of(res)
            zid = [k for k in self._screen(e).shots if k.startswith("z")][-1]
            zx, zy = png.find_color(zimg, BLUE)
            e.call("click", x=round(zx), y=round(zy), image=zid)
            p = b.last("agent.pointer")
            zmeta = self._screen(e).shots[zid]
            self.assertLessEqual(abs(p["x"] - 1501.5), 1 / zmeta["sx"] + 1e-9)
            self.assertLessEqual(abs(p["y"] - 1001.5), 1 / zmeta["sy"] + 1e-9)
            report["zoom"] = (zimg[0], zimg[1], round(zmeta["sx"], 4), round(p["x"] - 1501.5, 3), round(p["y"] - 1001.5, 3))
            # out-of-image coordinates are refused
            self.assertIn("outside image", e.text(e.call("click", x=5000, y=10)))
            print(f"\n   scale {scale}: (image w, h, image px per logical px, error x, error y) {report}")
        finally:
            e.close()

    @staticmethod
    def _screen(e):
        # the Screen instance is captured in the tool closures; reach it through one of them
        fn = e.reg.tools["screenshot"].fn
        for cell in fn.__closure__ or ():
            if type(cell.cell_contents).__name__ == "Screen":
                return cell.cell_contents
        raise AssertionError("screen not found")

    def test_scale_1_0(self):
        self.run_case(1.0)

    def test_scale_1_6(self):
        self.run_case(1.6)


class Input(unittest.TestCase):
    def setUp(self):
        self.e = Env(scale=1.6)
        self.b = self.e.bridge
        self.b.add_window("{k}", "org.kde.kate", "Einkaufsliste — Kate", 100, 100, 900, 700, active=True)

    def tearDown(self):
        self.e.close()

    def t(self, tool, **a):
        return self.e.text(self.e.call(tool, **a))

    def test_type_unicode_and_keys(self):
        text = "Grüße aus der Straße – 5 € 🙂 @home"
        out = self.t("type_text", text=text, enter=True, intent="Schreibe Einkaufsliste")
        self.assertIn("Typed", out)
        self.assertEqual(self.b.last("agent.text")["windowId"], "{k}")
        self.assertEqual(self.b.last("agent.text")["text"], text + "\n")
        self.t("press_keys", keys="Strg+S")
        self.assertEqual(self.b.last("agent.key")["keys"], "ctrl+s")
        self.t("press_keys", keys="ctrl + shift + T")
        self.assertEqual(self.b.last("agent.key")["keys"], "ctrl+shift+t")
        self.t("press_keys", keys="Bild_ab", repeat=3)
        self.assertEqual([m for m in self.b.methods() if m == "agent.key"].__len__(), 5)
        self.assertIn("not a key chord", self.t("press_keys", keys="s+ctrl"))

    def test_text_in_one_call(self):
        self.t("type_text", text="Einkauf\r\n- Milch\tx", enter=True)
        seq = [(m, p.get("text") or p.get("keys")) for _, m, p in self.b.calls if m in ("agent.text", "agent.key")]
        self.assertEqual(seq, [("agent.text", "Einkauf\n- Milch\tx\n")])
        out = [m for _, m in self.e.daemon.cursor_events() if m.get("output")]
        self.assertNotIn("\n", out[-1]["output"])

    def test_multiline_text_paths_old_bridge(self):
        """bridge.md agent.text "Order": an older bridge (no orderedText) gets multi-line text on the
        key paths only (the mock bridge here advertises the original capability list)"""
        self.t("type_text", text="Zeile 1\nZeile 2")
        self.assertEqual(self.b.last("agent.text")["paths"], ["keymap", "temporaryKeymap", "clipboard"])
        self.t("type_text", text="eine Zeile")
        self.assertNotIn("paths", self.b.last("agent.text"))

    def test_session_bracketing_and_turn_end(self):
        self.e.call("screenshot")
        self.e.call("click", x=100, y=100, intent="Klicke auf Datei")
        self.assertEqual(self.b.methods().count("agent.begin"), 1)
        self.e.call("type_text", text="Milch")
        self.assertEqual(self.b.methods().count("agent.begin"), 1)       # one session for the whole task
        self.e.daemon.broadcast({"type": "turn_finished", "turn_id": "t1", "outcome": "completed", "error_code": None})
        deadline = time.monotonic() + 2
        while "agent.end" not in self.b.methods() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIn("agent.end", self.b.methods())
        self.assertIsNone(self.b.session)

    def test_owner_busy(self):
        self.e.call("screenshot")
        self.b.busy_next = 1
        out = self.t("click", x=50, y=50)
        self.assertIn("Clicked", out)                                   # waited and retried once
        self.b.busy_next = 3
        self.assertIn("using the mouse", self.t("click", x=50, y=50))

    def test_session_expiry_is_transparent(self):
        self.e.call("screenshot")
        self.e.call("click", x=50, y=50)
        self.b.session = None                     # the bridge ended it (120 s idle); token now refused
        self.b.emit("agent", "agent.state", {"active": False, "label": "timeout"})
        self.assertIn("Clicked", self.t("click", x=60, y=60))
        self.assertEqual(self.b.methods().count("agent.begin"), 2)

    def test_dismissed_popup_and_window_id(self):
        self.e.call("screenshot", window="Kate")
        self.b.on_call = lambda m, p: ({"target": {"windowId": "{k}", "appId": "org.kde.kate"}, "dismissedPopups": True}
                                       if m == "agent.pointer" else None)
        out = self.t("click", x=20, y=20)
        self.assertIn("only closed an open menu", out)
        self.assertEqual(self.b.last("agent.pointer")["windowId"], "{k}")   # clicks on a window shot name the window

    def test_escape_cancels(self):
        self.e.call("screenshot")
        self.e.call("click", x=50, y=50)
        self.b.escape()
        time.sleep(0.1)
        self.assertEqual(self.t("click", x=60, y=60), CANCELLED_BY_OWNER)
        self.assertEqual(self.t("type_text", text="x"), CANCELLED_BY_OWNER)
        hides = [m for _, m in self.e.daemon.cursor_events() if m.get("visible") is False]
        self.assertTrue(hides)
        # a new turn clears the cancellation
        self.e.daemon.broadcast({"type": "turn_started", "turn_id": "t2", "input": "text", "source": "x", "text": "", "speak": False})
        time.sleep(0.1)
        self.assertIn("Clicked", self.t("click", x=60, y=60))

    def test_locked_screen(self):
        self.e.session_bus.objects[("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver")]["methods"]["GetActive"] = lambda: True
        for tool, args in (("screenshot", {}), ("click", {"x": 1, "y": 1}), ("type_text", {"text": "a"}),
                           ("ui_tree", {}), ("list_windows", {}), ("press_keys", {"keys": "return"})):
            self.assertEqual(self.t(tool, **args), LOCKED_MSG, tool)
        self.assertNotIn("agent.text", self.b.methods())

    def test_auth_prompts_refused(self):
        self.b.add_window("{p}", "org.kde.polkit-kde-authentication-agent-1", "Legitimierung erforderlich",
                          500, 300, 500, 300, active=True)
        self.assertEqual(self.t("type_text", text="hunter2"), AUTH_MSG)
        self.assertEqual(self.t("press_keys", keys="return"), AUTH_MSG)
        self.assertIn("password or security app", self.t("screenshot"))
        self.e.call("screenshot", target="screen")
        self.assertIn("password", self.t("click", x=600, y=330))
        self.assertNotIn("agent.text", self.b.methods())
        self.assertNotIn("agent.pointer", self.b.methods())
        # a browser window titled like a password prompt
        self.b.add_window("{f}", "org.mozilla.firefox", "Passwort eingeben – Bank", 0, 0, 900, 900, active=True)
        self.assertEqual(self.t("type_text", text="geheim", window="firefox"), AUTH_MSG)

    def test_denied(self):
        self.b.deny_privileged = True
        self.assertIn("refused", self.t("screenshot"))


class NoBridge(unittest.TestCase):
    def test_fail_soft(self):
        e = Env(bridge=False)
        try:
            for tool, args in (("click", {"x": 1, "y": 1}), ("screenshot", {}), ("type_text", {"text": "a"}),
                               ("list_windows", {}), ("window", {"action": "close"})):
                self.assertEqual(e.text(e.call(tool, **args)), NO_BRIDGE, tool)
            out = e.text(e.call("open_app", name="Rechner"))
            self.assertIn("starting", out)
            self.assertEqual(e.launched[0][0], "org.kde.kcalc.desktop")
            self.assertIn("40%", e.text(e.call("volume", change=-10)))
        finally:
            e.close()


class Choreography(unittest.TestCase):
    def test_cursor_event_stream(self):
        e = Env(scale=1.6)
        try:
            b = e.bridge
            b.add_window("{k}", "org.kde.kate", "Kate", 100, 100, 900, 700, active=True)
            e.call("screenshot")
            t0 = time.monotonic()
            e.call("click", x=200, y=150, intent="Klicke auf „Datei“")
            e.call("click", x=600, y=500, count=2, intent="Öffne Dokument")
            e.call("type_text", text="Milch, Eier, Brot", intent="Schreibe Einkaufsliste")
            e.call("press_keys", keys="ctrl+s", intent="Speichere")
            e.daemon.broadcast({"type": "turn_finished", "turn_id": "t1", "outcome": "completed", "error_code": None})
            time.sleep(0.3)
            ev = [(t - t0, m) for t, m in e.daemon.cursor_events()]
            calls = [(t - t0, m, p) for t, m, p in b.calls if m.startswith("agent.") and m not in ("agent.begin", "agent.end")]
            lines = []
            for t, m in ev:
                f = {k: v for k, v in m.items() if k != "type"}
                lines.append(f"   {t * 1000:7.0f} ms  {f}")
            for t, m, p in calls:
                lines.append(f"   {t * 1000:7.0f} ms  bridge {m} " + (f"x={p.get('x'):.1f} y={p.get('y'):.1f}" if "x" in p else ""))
            print("\n   recorded agent_cursor stream and bridge calls:\n" + "\n".join(sorted(lines, key=lambda s: float(s.split('ms')[0]))))
            # first event: appear (no animation), visible, with a label
            self.assertTrue(ev[0][1]["visible"])
            self.assertEqual(ev[0][1]["duration_ms"], 0)
            self.assertTrue(ev[0][1].get("label"))
            # every action lands only after the glide to its target has finished
            moves = [(t, m) for t, m in ev if m.get("duration_ms") and "pulse" not in m]
            pulses = [(t, m) for t, m in ev if "pulse" in m]
            self.assertEqual([m["pulse"] for _, m in pulses][:4], ["click", "double_click", "type", "type"])
            for (tm, mv), (tp, pu) in zip(moves, pulses):
                self.assertGreaterEqual(tp - tm, mv["duration_ms"] / 1000 - 0.005)
                self.assertEqual((pu["x"], pu["y"]), (mv["x"], mv["y"]))     # pulse where the glide ended
                self.assertLessEqual(len(mv["label"]), 60)
            ptr = [(t, p) for t, m, p in calls if m == "agent.pointer"]
            for (tm, mv), (tc, p) in zip(moves, ptr):
                self.assertGreaterEqual(tc - tm, mv["duration_ms"] / 1000 - 0.005)
                self.assertAlmostEqual(p["x"], mv["x"], delta=0.06)
                self.assertAlmostEqual(p["y"], mv["y"], delta=0.06)
            for _, mv in moves:
                self.assertTrue(260 <= mv["duration_ms"] <= 800)
            # rate: never more than 60 events per second
            ts = [t for t, _ in ev]
            for a, c in zip(ts, ts[60:]):
                self.assertGreater(c - a, 1.0)
            self.assertLessEqual(len(ev), 4 * 4 + 2)                     # a few events per action, not a stream
            self.assertFalse(ev[-1][1]["visible"])                      # the cursor leaves at the end of the turn
            self.assertEqual(ev[-1][1].get("type", "agent_cursor"), "agent_cursor")
            labels = [m.get("label") for _, m in ev if m.get("label")]
            self.assertIn("Klicke auf „Datei“", labels)
            self.assertIn("Schreibe Einkaufsliste", labels)
            typed = [m for _, m in ev if m.get("pulse") == "type" and m.get("output")]
            self.assertEqual(typed[0]["output"], "Milch, Eier, Brot")
        finally:
            e.close()

    def test_linger_hides(self):
        e = Env(scale=1.0)
        try:
            e.settings_set = None
            e.hands.cursor.config = lambda: {"enabled": True, "linger_seconds": 0.3}
            e.bridge.add_window("{k}", "org.kde.kate", "Kate", 0, 0, 900, 700, active=True)
            e.call("screenshot")
            e.call("click", x=10, y=10)
            time.sleep(0.6)
            self.assertFalse(e.daemon.cursor_events()[-1][1]["visible"])
        finally:
            e.close()


class OrderedTextBridge(unittest.TestCase):
    """A current bridge (capabilities orderedText, workArea)."""

    def setUp(self):
        self.e = Env(scale=1.0, capabilities=["windows", "menus", "iconGeometry", "agentInput", "agentText",
                                               "screenshot", "orderedText", "workArea"])
        self.e.bridge.add_window("{k}", "org.kde.kate", "Brief — Kate", 100, 100, 900, 700, active=True)

    def tearDown(self):
        self.e.close()

    def test_multiline_text_uses_every_path(self):
        out = self.e.text(self.e.call("type_text", text="Liebe Grüße,\n\tJörg", enter=True))
        self.assertIn("Typed", out)
        sent = self.e.bridge.last("agent.text")
        self.assertEqual(sent["text"], "Liebe Grüße,\n\tJörg\n")
        self.assertNotIn("paths", sent, "no restriction: the bridge keeps the order on the text-input path")


if __name__ == "__main__":
    unittest.main()
