# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic mode: the decision logic of the session daemon, free of D-Bus so it can be tested.

Model (docs/contracts/power.md §3):
* The owner's three modes are the power-profiles-daemon profiles (tuned-ppd). tuned-ppd already
  maps each one to an AC or a battery tuned profile, so "Ausgewogen" on battery is quieter by itself.
* Automatic (power.automatic, default on): base profile Ausgewogen, plus temporary *holds*
  (the standard PPD HoldProfile API): on battery Leise from the start (power.batteryBase "quiet",
  the default: silent and cool; bursts stay, so it remains responsive) — with batteryBase
  "balanced" Leise only when the battery is low —, and on mains Leistung while a game or a busy
  heavy app runs. Holds are released automatically when their reason ends, and tuned-ppd drops them
  if the daemon dies (the machine then simply runs Ausgewogen).
* A mode the owner picks (shell, assistant, Fn-key) is a *manual choice*: it wins at once (tuned-ppd
  itself cancels all holds when a profile is set) and automatic stays out of the way until the
  owner chooses "Automatisch" again, the login session ends, or one exception: a Leistung chosen
  on mains pauses while on battery (unplugging must not leave the machine roaring; it runs
  Ausgewogen-on-battery, the faster battery choice, because the owner asked for speed) and resumes
  when power returns. A choice made on battery is kept on battery.
"""
import time

from . import policy

PPD_SAVER = "power-saver"
PPD_BALANCED = "balanced"
PPD_PERF = "performance"
TRANSIENT_S = 3.0   # property changes this soon after our own call are attributed to us


class PPD:
    """Adapter interface (the daemon implements it over D-Bus; tests use a fake)."""
    def available(self) -> bool: ...
    def active_profile(self) -> str: ...
    def set_profile(self, profile: str) -> None: ...
    def hold(self, profile: str, reason: str) -> int: ...
    def release(self, cookie: int) -> None: ...
    def holds(self) -> list: ...   # [{"Profile":..., "ApplicationId":...}]


APP_ID = "kristall-power"


class Controller:
    def __init__(self, ppd, clock=time.monotonic, log=None, on_change=None):
        self.ppd = ppd
        self.clock = clock
        self._log = log or (lambda ev, **kw: None)
        self._on_change = on_change or (lambda: None)
        self.automatic = True
        self.on_battery = False
        self.has_battery = False
        self.percent = None
        self.low_latched = False
        self.game_active = False
        self.heavy = None            # name of the busy heavy app, or None
        self.override = None         # {"mode", "on_battery", "since"}
        self.cookie = None
        self.cookie_profile = None
        self.last_op = -1e9
        self.reason = "starting"
        self.started = False
        self.low_battery_enabled = True
        self.battery_base = "quiet"  # power.batteryBase: what automatic means on battery

    # ---------------------------------------------------------------- derived state
    def desired(self):
        """(base_profile, hold_profile or None, reason) — or None when not managing."""
        if not self.automatic:
            return None
        ov = self.override
        if ov:
            paused = ov["mode"] == "performance" and self.on_battery and not ov["on_battery"]
            if not paused:
                return policy.PPD_OF_MODE[ov["mode"]], None, "manual"
        base = PPD_BALANCED
        why = "manual-performance-paused-on-battery" if ov else "auto"
        if self.on_battery and self.low_latched and self.low_battery_enabled:
            return base, PPD_SAVER, "auto-low-battery"
        if self.on_battery and not ov and self.battery_base == "quiet":
            return base, PPD_SAVER, "auto-battery"
        if not self.on_battery and not ov:
            if self.game_active:
                return base, PPD_PERF, "auto-game"
            if self.heavy:
                return base, PPD_PERF, "auto-heavy-app"
        return base, None, why

    def effective_mode(self):
        try:
            return policy.MODE_OF_PPD.get(self.ppd.active_profile(), "balanced")
        except Exception:  # noqa: BLE001 - ppd vanished
            return "balanced"

    def snapshot(self):
        d = self.desired()
        return {
            "automatic": self.automatic,
            "manual": dict(self.override) if self.override else None,
            "reason": self.reason,
            "hold": self.cookie_profile if self.cookie else None,
            "desired": {"base": d[0], "hold": d[1]} if d else None,
            "on_battery": self.on_battery, "percent": self.percent, "low_battery": self.low_latched,
            "game": self.game_active, "heavy_app": self.heavy,
        }

    # ---------------------------------------------------------------- inputs
    def start(self):
        """Begin managing (after settings are known). A manual choice from an earlier login
        session is not carried over: every session starts in the owner's standing preference."""
        self.started = True
        self.override = None
        self.reconcile("start")

    def set_automatic(self, enabled: bool):
        if enabled == self.automatic:
            return
        self.automatic = enabled
        self.override = None
        if not enabled:
            self._release("automatic-off")
            self.reason = "automatic-off"
            self._log("automatic", enabled=False)
            self._on_change()
        else:
            self._log("automatic", enabled=True)
            self.reconcile("automatic-on")

    def resume_automatic(self):
        """Owner chose 'Automatisch' again."""
        self.override = None
        self.automatic = True
        self._log("manual-end", reason="owner")
        self.reconcile("owner-auto")

    def set_power(self, on_battery: bool, has_battery: bool = True):
        changed = on_battery != self.on_battery
        self.on_battery, self.has_battery = on_battery, has_battery
        self._update_low()
        if changed:
            self._log("source", on_battery=on_battery, percent=self.percent)
            self.reconcile("power-source")

    def set_percent(self, percent):
        self.percent = percent
        if self._update_low():
            self.reconcile("battery-level")

    def _update_low(self):
        before = self.low_latched
        if not self.on_battery or self.percent is None:
            self.low_latched = False
        elif self.percent <= policy.LOW_BATTERY_ON:
            self.low_latched = True
        elif self.percent >= policy.LOW_BATTERY_OFF:
            self.low_latched = False
        return before != self.low_latched

    def set_battery_base(self, base: str):
        """power.batteryBase: "quiet" (Leise on battery, default) or "balanced"."""
        base = base if base in ("quiet", "balanced") else "quiet"
        if base != self.battery_base:
            self.battery_base = base
            self.reconcile("settings")

    def set_low_battery_enabled(self, enabled: bool):
        if enabled != self.low_battery_enabled:
            self.low_battery_enabled = enabled
            self.reconcile("settings")

    def set_game(self, active: bool):
        if active != self.game_active:
            self.game_active = active
            self._log("game", active=active)
            self.reconcile("game")

    def set_heavy(self, name):
        if name != self.heavy:
            self.heavy = name
            self._log("heavy-app", app=name)
            self.reconcile("workload")

    def resumed(self):
        self.reconcile("resume")

    def ppd_restarted(self):
        """tuned-ppd (re)appeared: our old cookie is meaningless."""
        self.cookie = self.cookie_profile = None
        self.reconcile("ppd-restart")

    # ---------------------------------------------------------------- signals from tuned-ppd
    def profile_changed(self, profile):
        if not self.automatic or not self.started:
            return
        if self.clock() - self.last_op < TRANSIENT_S:
            return  # caused by our own call (or an intermediate step); verify() re-checks later
        self.verify(profile)

    def verify(self, profile=None):
        """Compare tuned-ppd's active profile with what we want; a difference nobody we know of
        explains is the owner's choice. The daemon calls this TRANSIENT_S after each of its calls."""
        if not self.automatic or not self.started:
            return
        if profile is None:
            try:
                if not self.ppd.available():
                    return
                profile = self.ppd.active_profile()
            except Exception:  # noqa: BLE001
                return
        d = self.desired()
        expect = (d[1] or d[0]) if d else None
        if profile == expect:
            return
        for h in self._safe_holds():
            if h.get("ApplicationId") != APP_ID and h.get("Profile") == profile:
                self._log("external-hold", profile=profile, app=h.get("ApplicationId"))
                return
        self._manual(profile)

    def hold_released(self, cookie):
        # Our own releases clear self.cookie before calling ReleaseProfile, so a release signal
        # for the cookie we still hold means tuned-ppd cancelled it: somebody set a profile.
        if self.cookie is None or cookie != self.cookie:
            return
        # someone set a profile (tuned-ppd cancels all holds then): a manual choice
        self.cookie = self.cookie_profile = None
        try:
            prof = self.ppd.active_profile()
        except Exception:  # noqa: BLE001
            return
        self._manual(prof)

    def _manual(self, profile):
        mode = policy.MODE_OF_PPD.get(profile)
        if not mode:
            return
        self.cookie = self.cookie_profile = None
        self.override = {"mode": mode, "on_battery": self.on_battery, "since": time.time()}
        self.reason = "manual"
        self._log("manual", mode=mode, on_battery=self.on_battery)
        self.reconcile("manual")

    # ---------------------------------------------------------------- actuation
    def _safe_holds(self):
        try:
            return self.ppd.holds() or []
        except Exception:  # noqa: BLE001
            return []

    def _release(self, why):
        if self.cookie is None:
            return
        cookie, self.cookie, self.cookie_profile = self.cookie, None, None
        self.last_op = self.clock()
        try:
            self.ppd.release(cookie)
            self._log("release", reason=why)
        except Exception as e:  # noqa: BLE001 - already gone
            self._log("release-failed", error=str(e)[:200])

    def reconcile(self, why):
        if not self.started:
            return
        d = self.desired()
        if d is None:
            self._on_change()
            return
        base, hold, reason = d
        self.reason = reason
        try:
            if not self.ppd.available():
                self.cookie = self.cookie_profile = None
                self._on_change()
                return
            # 1. base profile (only when no hold of ours sits on top of a different base)
            if hold is None or self.cookie_profile != hold:
                self._release(why)
                if self.ppd.active_profile() != base:
                    self.last_op = self.clock()
                    self.ppd.set_profile(base)      # also cancels any hold (tuned-ppd semantics)
                    self._log("set", profile=base, reason=reason, trigger=why)
            # 2. hold
            if hold is not None and self.cookie is None:
                self.last_op = self.clock()
                self.cookie = self.ppd.hold(hold, reason)
                self.cookie_profile = hold
                self._log("hold", profile=hold, reason=reason, trigger=why)
        except Exception as e:  # noqa: BLE001 - D-Bus errors must never kill the daemon
            self._log("ppd-error", error=str(e)[:200], trigger=why)
        self._on_change()


class Workload:
    """Turns 10-second samples of heavy-app CPU use and iGPU busyness into a boost decision with
    hysteresis (engage after BOOST_ON_SAMPLES busy samples, release after BOOST_OFF_SAMPLES calm)."""

    def __init__(self):
        self.busy_run = 0
        self.calm_run = 0
        self.active = None

    def sample(self, apps_cores: dict, gpu_busy):
        """apps_cores: {app: logical CPUs busy}; gpu_busy: 0..1 or None. Returns the boost app or None."""
        best = max(apps_cores.items(), key=lambda kv: kv[1], default=(None, 0.0))
        busy = best[0] is not None and (
            best[1] >= policy.BOOST_CPU_CORES or
            (gpu_busy is not None and gpu_busy >= policy.BOOST_GPU_BUSY and best[1] >= policy.BOOST_GPU_APP_CORES))
        if busy:
            self.busy_run += 1
            self.calm_run = 0
            if self.active is None and self.busy_run >= policy.BOOST_ON_SAMPLES:
                self.active = best[0]
        else:
            self.calm_run += 1
            self.busy_run = 0
            if self.active is not None and self.calm_run >= policy.BOOST_OFF_SAMPLES:
                self.active = None
        if self.active is not None and self.active not in apps_cores:
            self.active = None  # the app went away
        return self.active

    def reset(self):
        self.busy_run = self.calm_run = 0
        self.active = None
