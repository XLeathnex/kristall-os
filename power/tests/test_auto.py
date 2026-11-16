# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic mode against a fake tuned-ppd that reproduces tuned 2.28's controller semantics
(tuned/ppd/controller.py): setting ActiveProfile cancels all holds and becomes the base profile;
power-saver holds beat performance holds; releasing the last hold returns to the base; signals
arrive after the D-Bus call returned (we queue them and deliver them with pump())."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from kristall_power import auto, policy  # noqa: E402


class FakePPD(auto.PPD):
    def __init__(self):
        self.base = "balanced"
        self.active = "balanced"
        self.hold_map = {}      # cookie -> (profile, app)
        self.next_cookie = 100
        self.queue = []
        self.up = True
        self.ctl = None
        self.calls = []

    # tuned-ppd internals
    def _switch(self, profile):
        if profile != self.active:
            self.active = profile
            self.queue.append(("profile", profile))

    def _effective(self):
        return "power-saver" if any(p == "power-saver" for p, _ in self.hold_map.values()) else "performance"

    def _cancel_all(self):
        for c in list(self.hold_map):
            del self.hold_map[c]
            self.queue.append(("released", c))

    # API used by the controller
    def available(self):
        return self.up

    def active_profile(self):
        if not self.up:
            raise RuntimeError("gone")
        return self.active

    def set_profile(self, profile, by="kristall"):
        self.calls.append(("set", profile, by))
        self._cancel_all()
        self._switch(profile)
        self.base = profile

    def hold(self, profile, reason, app=auto.APP_ID):
        self.calls.append(("hold", profile, app))
        c = self.next_cookie
        self.next_cookie += 1
        self.hold_map[c] = (profile, app)
        self._switch(self._effective())
        return c

    def release(self, cookie):
        self.calls.append(("release", cookie))
        if cookie not in self.hold_map:
            raise RuntimeError("no such hold")
        del self.hold_map[cookie]
        self.queue.append(("released", cookie))
        self._switch(self._effective() if self.hold_map else self.base)

    def holds(self):
        return [{"Profile": p, "ApplicationId": a} for p, a in self.hold_map.values()]

    # test helpers
    def owner_sets(self, profile):
        """The shell/assistant/Fn-key sets a profile (another D-Bus client)."""
        self.set_profile(profile, by="owner")

    def restart(self):
        self.hold_map.clear()
        self.queue.clear()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class AutoTest(unittest.TestCase):
    def setUp(self):
        self.ppd = FakePPD()
        self.clock = Clock()
        self.events = []
        self.ctl = auto.Controller(self.ppd, clock=self.clock, log=lambda ev, **kw: self.events.append((ev, kw)))
        self.ppd.ctl = self.ctl

    def pump(self, advance=0.0):
        """Deliver queued D-Bus signals, then let time pass (and the daemon's verify() run)."""
        while self.ppd.queue:
            kind, val = self.ppd.queue.pop(0)
            if kind == "profile":
                self.ctl.profile_changed(val)
            else:
                self.ctl.hold_released(val)
        if advance:
            self.clock.t += advance
            self.ctl.verify()
            while self.ppd.queue:
                kind, val = self.ppd.queue.pop(0)
                (self.ctl.profile_changed if kind == "profile" else self.ctl.hold_released)(val)

    def start(self, on_battery=False, percent=80):
        self.ctl.set_power(on_battery)
        self.ctl.set_percent(percent)
        self.ctl.start()
        self.pump(5)

    def owner(self, profile):
        self.clock.t += 10
        self.ppd.owner_sets(profile)
        self.pump(5)

    def mine(self):
        return [p for p, a in self.ppd.hold_map.values() if a == auto.APP_ID]

    # ------------------------------------------------------------------ basic automatic behaviour
    def test_start_resets_previous_manual_choice(self):
        self.ppd.base = self.ppd.active = "power-saver"     # left over from yesterday
        self.start()
        self.assertEqual(self.ppd.active, "balanced")
        self.assertIsNone(self.ctl.override)

    def test_game_on_mains_gets_performance_then_released(self):
        self.start()
        self.ctl.set_game(True)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")
        self.assertEqual(self.mine(), ["performance"])
        self.assertEqual(self.ppd.base, "balanced", "a hold never changes the owner's base mode")
        self.ctl.set_game(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.assertEqual(self.mine(), [])
        self.assertIsNone(self.ctl.override)

    def test_game_on_battery_gets_no_boost(self):
        self.start(on_battery=True)
        self.ctl.set_game(True)
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver", "on battery automatic means Leise, games included")
        self.assertEqual(self.ctl.reason, "auto-battery")

    # ------------------------------------------------------------------ battery base (power.batteryBase)
    def test_battery_means_quiet_from_the_start(self):
        """Default: unplugged, automatic is Leise at once (a hold; the base stays Ausgewogen), and on
        mains it is Ausgewogen again."""
        self.start()
        self.assertEqual(self.ppd.active, "balanced")
        self.ctl.set_power(True)            # unplug at 80 %
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver")
        self.assertEqual(self.mine(), ["power-saver"])
        self.assertEqual(self.ppd.base, "balanced", "a hold: if the daemon dies tuned-ppd falls back to Ausgewogen")
        self.assertEqual(self.ctl.reason, "auto-battery")
        self.assertIsNone(self.ctl.override, "our own hold is not a manual choice")
        self.ctl.set_power(False)           # replug
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.assertEqual(self.mine(), [])
        self.assertEqual(self.ctl.reason, "auto")

    def test_start_on_battery_is_quiet(self):
        self.start(on_battery=True, percent=90)
        self.assertEqual(self.ppd.active, "power-saver")
        self.assertEqual(self.ctl.snapshot()["hold"], "power-saver")

    def test_battery_base_balanced_for_owners_who_prefer_speed(self):
        """power.batteryBase = "balanced": automatic on battery is Ausgewogen(-battery) until the
        battery is low; switching the setting applies at once."""
        self.start(on_battery=True, percent=60)
        self.assertEqual(self.ppd.active, "power-saver")
        self.ctl.set_battery_base("balanced")
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.assertEqual(self.mine(), [])
        self.assertIsNone(self.ctl.override, "releasing our hold is not a manual choice")
        self.ctl.set_percent(18)
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver")
        self.assertEqual(self.ctl.reason, "auto-low-battery")
        self.ctl.set_percent(30)
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.ctl.set_battery_base("quiet")
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver")
        self.ctl.set_battery_base("nonsense")     # invalid -> the default
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver")

    def test_manual_choice_on_battery_beats_quiet_base(self):
        self.start(on_battery=True)
        self.owner("balanced")              # the owner wants Ausgewogen although unplugged
        self.assertEqual(self.ctl.override["mode"], "balanced")
        self.assertEqual(self.ppd.active, "balanced")
        self.assertEqual(self.mine(), [])
        self.ctl.set_percent(50)
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced", "automatic stays out of the way")
        self.ctl.resume_automatic()
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver")

    def test_unplug_during_game_and_replug(self):
        self.start()
        self.ctl.set_game(True)
        self.pump(5)
        self.ctl.set_power(True)            # unplug
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver", "unplugging must not leave the machine roaring: Leise")
        self.assertEqual(self.mine(), ["power-saver"])
        self.assertIsNone(self.ctl.override, "our own release is not a manual choice")
        self.ctl.set_power(False)           # replug, game still running
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")

    def test_heavy_app_boost(self):
        self.start()
        self.ctl.set_heavy("org.blender.Blender")
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")
        self.ctl.set_heavy(None)
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")

    # ------------------------------------------------------------------ manual choices
    def test_manual_choice_during_hold_wins_and_sticks(self):
        self.start()
        self.ctl.set_game(True)
        self.pump(5)
        self.owner("power-saver")                       # owner wants quiet during the game
        self.assertEqual(self.ppd.active, "power-saver")
        self.assertEqual(self.ctl.override["mode"], "quiet")
        self.assertEqual(self.mine(), [])
        self.ctl.set_game(False)
        self.ctl.set_game(True)
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver", "automatic does not fight the owner")
        self.ctl.set_power(True)
        self.pump(5)
        self.ctl.set_power(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver", "quiet survives unplug/replug")
        self.ctl.resume_automatic()
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance", "back to automatic: the running game gets its boost")
        self.assertIsNone(self.ctl.override)

    def test_owner_picks_the_held_profile(self):
        """Hold performance active, owner taps Leistung: tuned-ppd cancels our hold without any
        ActiveProfile change; the ProfileReleased signal tells us it was the owner."""
        self.start()
        self.ctl.set_game(True)
        self.pump(5)
        self.owner("performance")
        self.assertEqual(self.ctl.override["mode"], "performance")
        self.ctl.set_game(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance", "the owner's Leistung stays after the game")

    def test_manual_performance_on_mains_pauses_on_battery(self):
        self.start()
        self.owner("performance")
        self.ctl.set_power(True)
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.assertIsNotNone(self.ctl.override, "paused, not forgotten")
        self.ctl.set_power(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance", "replug resumes the owner's Leistung")

    def test_manual_performance_chosen_on_battery_stays(self):
        self.start(on_battery=True)
        self.owner("performance")
        self.ctl.set_percent(50)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")
        self.ctl.set_power(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")
        self.ctl.set_power(True)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")

    def test_manual_choice_during_hold_is_seen_at_once(self):
        self.start()
        self.ctl.set_game(True)             # our hold call ...
        self.ppd.owner_sets("power-saver")  # ... and the owner, a moment later: ProfileReleased tells
        self.pump(0)
        self.assertEqual(self.ctl.override["mode"], "quiet")

    def test_manual_choice_right_after_our_call_is_caught_by_verify(self):
        self.ppd.base = self.ppd.active = "performance"
        self.ctl.start()                    # we set balanced at time t ...
        self.ppd.owner_sets("power-saver")  # ... and the owner picks Leise within the transient window
        self.pump(0)
        self.assertIsNone(self.ctl.override, "ignored as transient at first")
        self.pump(5)                        # the daemon's verify() timer
        self.assertEqual(self.ctl.override["mode"], "quiet")
        self.assertEqual(self.ppd.active, "power-saver")

    def test_external_hold_is_not_a_manual_choice(self):
        self.start()
        self.clock.t += 10
        self.ppd.hold("performance", "render", app="org.example.Other")
        self.pump(5)
        self.assertIsNone(self.ctl.override)

    # ------------------------------------------------------------------ battery level
    def test_low_battery_thresholds_with_hysteresis(self):
        """With the quiet battery base the mode is Leise anyway; only the reason shows low battery."""
        self.start(on_battery=True, percent=30)
        for pct, why in ((21, "auto-battery"), (20, "auto-low-battery"), (24, "auto-low-battery"),
                         (25, "auto-battery"), (19, "auto-low-battery")):
            self.ctl.set_percent(pct)
            self.pump(5)
            self.assertEqual((self.ppd.active, self.ctl.reason), ("power-saver", why), f"{pct} %")
            self.assertEqual(len(self.mine()), 1)
        self.ctl.set_power(False)           # plug in at 19 %
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.assertEqual(self.mine(), [])

    def test_low_battery_thresholds_with_balanced_base(self):
        self.ctl.battery_base = "balanced"
        self.start(on_battery=True, percent=30)
        for pct, want in ((21, "balanced"), (20, "power-saver"), (22, "power-saver"), (24, "power-saver"),
                          (25, "balanced"), (19, "power-saver")):
            self.ctl.set_percent(pct)
            self.pump(5)
            self.assertEqual(self.ppd.active, want, f"{pct} %")
        self.ctl.set_power(False)           # plug in at 19 %
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.assertEqual(self.mine(), [])

    def test_low_battery_setting_off(self):
        self.ctl.battery_base = "balanced"
        self.start(on_battery=True, percent=10)
        self.assertEqual(self.ppd.active, "power-saver")
        self.ctl.set_low_battery_enabled(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.ctl.set_battery_base("quiet")      # lowBatteryQuiet matters only with the balanced base
        self.pump(5)
        self.assertEqual((self.ppd.active, self.ctl.reason), ("power-saver", "auto-battery"))

    def test_low_battery_respects_manual_choice(self):
        self.start(on_battery=True, percent=50)
        self.owner("balanced")              # no visible change, no override
        self.owner("performance")
        self.ctl.set_percent(15)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")

    # ------------------------------------------------------------------ suspend, restarts, settings
    def test_resume_after_unplugged_while_asleep(self):
        self.start()
        self.ctl.set_game(True)
        self.pump(5)
        self.ctl.set_power(True)     # state read after resume
        self.ctl.resumed()
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver")
        self.assertEqual(self.mine(), ["power-saver"], "the game's Leistung hold is gone, Leise on battery")

    def test_ppd_restart_regains_hold(self):
        self.start()
        self.ctl.set_heavy("blender")
        self.pump(5)
        self.ppd.restart()          # holds lost, ActiveProfile back to base
        self.ppd.active = self.ppd.base
        self.ctl.ppd_restarted()
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance")
        self.assertEqual(len(self.mine()), 1)

    def test_ppd_absent(self):
        self.ppd.up = False
        self.start()
        self.ctl.set_game(True)
        self.assertEqual(self.ppd.calls, [])

    def test_automatic_off_and_on(self):
        self.start()
        self.ctl.set_game(True)
        self.pump(5)
        self.ctl.set_automatic(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "balanced")
        self.ctl.set_heavy("blender")
        self.owner("power-saver")
        self.ctl.set_power(True)
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver", "with automatic off nothing is changed for the owner")
        self.owner("balanced")
        self.assertEqual(self.ppd.active, "balanced", "with automatic off the battery base does not apply")
        self.ctl.set_automatic(True)
        self.pump(5)
        self.assertEqual(self.ppd.active, "power-saver", "automatic again, on battery: Leise")
        self.ctl.set_power(False)
        self.pump(5)
        self.assertEqual(self.ppd.active, "performance", "on mains with the busy heavy app from before: Leistung")

    def test_nothing_before_start(self):
        self.ctl.set_power(True)
        self.ctl.set_game(True)
        self.assertEqual(self.ppd.calls, [])


class WorkloadTest(unittest.TestCase):
    def test_hysteresis(self):
        w = auto.Workload()
        self.assertIsNone(w.sample({"blender": 12.0}, 0.1))
        self.assertEqual(w.sample({"blender": 12.0}, 0.1), "blender")
        for _ in range(policy.BOOST_OFF_SAMPLES - 1):
            self.assertEqual(w.sample({"blender": 0.2}, 0.0), "blender")
        self.assertIsNone(w.sample({"blender": 0.2}, 0.0))

    def test_gpu_bound_game(self):
        w = auto.Workload()
        w.sample({"steam": 1.2}, 0.85)
        self.assertEqual(w.sample({"steam": 1.2}, 0.85), "steam")

    def test_idle_steam_or_video_does_not_boost(self):
        w = auto.Workload()
        for _ in range(10):
            self.assertIsNone(w.sample({"steam": 0.05}, 0.9))     # GPU busy from a video, Steam idle
            self.assertIsNone(w.sample({"blender": 2.0}, 0.1))    # modelling, not rendering

    def test_app_gone(self):
        w = auto.Workload()
        w.sample({"blender": 8}, None)
        w.sample({"blender": 8}, None)
        self.assertIsNone(w.sample({}, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
