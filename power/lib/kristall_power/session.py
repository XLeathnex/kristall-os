# SPDX-License-Identifier: GPL-3.0-or-later
"""kristall-power-session: the per-user, event-driven part of the power component.

Runs as the systemd user service kristall-power-session.service in the graphical session. It
* runs automatic mode (auto.Controller) against tuned-ppd's D-Bus API,
* sends the glass effect its quality hint (glass contract §4 `config`),
* lowers/raises the internal panel's refresh rate with the power source,
* dims the internal display slightly on battery (and restores it if the owner did not touch it),
* asks the root side to apply the owner's charge limit,
* keeps the owner-invisible battery/thermal log.

Idle means idle: it blocks in the GLib main loop on D-Bus signals, a settings watch pipe and an
inotify directory watch. Timers exist only while there is something to measure: 10 s samples
while a heavy app runs on mains in automatic mode, 60 s thermal-log samples while the screen is
unlocked (written to the log only under load), and one-shot debounces.
"""
import json
import os
import socket
import subprocess
import sys
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import Gio, GLib

from . import auto, display, hw, logbook, paths, policy, sysfs, workload

PPD_NAMES = [("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
              "org.freedesktop.UPower.PowerProfiles"),
             ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")]
UPOWER = ("org.freedesktop.UPower", "/org/freedesktop/UPower")
DEVICE_IFACE = "org.freedesktop.UPower.Device"
LOGIN1 = ("org.freedesktop.login1", "/org/freedesktop/login1")
GAMEMODE = ("com.feralinteractive.GameMode", "/com/feralinteractive/GameMode", "com.feralinteractive.GameMode")
SYSTEMD = ("org.freedesktop.systemd1", "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager")
BRIGHT = ("org.kde.ScreenBrightness", "/org/kde/ScreenBrightness")
OWN_NAME = "org.kristall.Power1"
OWN_PATH = "/org/kristall/Power1"
PROPS = "org.freedesktop.DBus.Properties"

DEFAULTS = {"automatic": True, "batteryBase": "quiet", "batteryRefreshRate": "auto", "dimOnBattery": True,
            "chargeLimit": 100, "heavyApps": policy.DEFAULT_HEAVY_APPS, "lowBatteryQuiet": True}


def journal(msg):
    print(msg, file=sys.stderr, flush=True)


class DBusPPD(auto.PPD):
    def __init__(self, bus):
        self.bus = bus
        self.name = None

    def _find(self):
        for name, path, iface in PPD_NAMES:
            try:
                if self.bus.name_has_owner(name):
                    return name, path, iface
            except dbus.DBusException:
                pass
        return None

    def _obj(self):
        f = self._find()
        if not f:
            raise RuntimeError("power-profiles service not on the bus")
        return self.bus.get_object(f[0], f[1], introspect=False), f[2]

    def available(self):
        return self._find() is not None

    def active_profile(self):
        o, iface = self._obj()
        return str(o.Get(iface, "ActiveProfile", dbus_interface=PROPS))

    def set_profile(self, profile):
        o, iface = self._obj()
        o.Set(iface, "ActiveProfile", dbus.String(profile), dbus_interface=PROPS)

    def hold(self, profile, reason):
        o, iface = self._obj()
        return int(o.HoldProfile(profile, reason, auto.APP_ID, dbus_interface=iface))

    def release(self, cookie):
        o, iface = self._obj()
        o.ReleaseProfile(dbus.UInt32(cookie), dbus_interface=iface)

    def holds(self):
        o, iface = self._obj()
        return [dict((str(k), str(v)) for k, v in h.items())
                for h in o.Get(iface, "ActiveProfileHolds", dbus_interface=PROPS)]


class PowerService(dbus.service.Object):
    """org.kristall.Power1 on the session bus (used by `kristall-power mode auto` and status)."""

    def __init__(self, bus, daemon):
        self.daemon = daemon
        super().__init__(dbus.service.BusName(OWN_NAME, bus), OWN_PATH)

    @dbus.service.method(OWN_NAME, in_signature="", out_signature="")
    def ResumeAutomatic(self):
        self.daemon.ctl.resume_automatic()

    @dbus.service.method(OWN_NAME, in_signature="", out_signature="s")
    def GetState(self):
        return json.dumps(self.daemon.state())

    @dbus.service.signal(OWN_NAME, signature="s")
    def StateChanged(self, state_json):
        pass


class Daemon:
    def __init__(self):
        DBusGMainLoop(set_as_default=True)
        self.loop = GLib.MainLoop()
        self.sysbus = dbus.SystemBus()
        self.sesbus = dbus.SessionBus()
        self.log_path = os.path.join(paths.user_state_dir(), "log.jsonl")
        self.state_path = paths.session_state_file()
        self.persist_path = os.path.join(paths.user_state_dir(), "session.json")
        self.persist = sysfs.read_json(self.persist_path, {}) or {}
        self.settings = dict(DEFAULTS)
        self.settings_loaded = False
        self.ppd = DBusPPD(self.sysbus)
        self.ctl = auto.Controller(self.ppd, log=self.log, on_change=self.changed)
        self.work = auto.Workload()
        self.sampler = workload.Sampler()
        self.heavy_units = {}            # unit -> (app, cgroup)
        self.game_count = 0
        self.sample_timer = None
        self.log_timer = None
        self.cpu_prev = None
        self.locked = False
        self.glass = None
        self.glass_hint_sent = None
        self.glass_retry = None
        self.display_timer = None
        self.display_key = None
        self.verify_timer = None
        self.refresh = {"managed": None, "panel": None}
        self.dim = self.persist.get("dim")       # {"display", "before", "set"} while dimmed
        self.charge_requested = None
        self.service = None
        self.last_state_json = None
        self._in_changed = False
        self._changed_again = False

    # ------------------------------------------------------------------ logging / state
    def log(self, ev, **kw):
        rec = logbook.append(self.log_path, ev, **kw)
        journal(f"{ev} {json.dumps({k: v for k, v in rec.items() if k not in ('t', 'ev')}, sort_keys=True)}")

    def state(self):
        s = self.ctl.snapshot()
        s.update({"schema": 1, "time": logbook.now_iso(), "mode": self.ctl.effective_mode(),
                  "glass_hint": self.glass_hint_sent, "glass_connected": self.glass is not None,
                  "refresh": self.refresh, "dimmed": bool(self.dim), "game_clients": self.game_count,
                  "heavy_apps_running": sorted({a for a, _ in self.heavy_units.values()}),
                  "sampling": self.sample_timer is not None})
        return s

    def changed(self):
        """Called after anything that may change what we do or show (re-entrant safe)."""
        if self._in_changed:
            self._changed_again = True
            return
        self._in_changed = True
        try:
            while True:
                self._changed_again = False
                self.update_sampling()
                self.update_glass()
                self.schedule_display()
                if not self._changed_again:
                    break
        finally:
            self._in_changed = False
        if self.verify_timer is None and time.monotonic() - self.ctl.last_op < auto.TRANSIENT_S:
            self.verify_timer = GLib.timeout_add(int(auto.TRANSIENT_S * 1000) + 500, self._verify)
        st = self.state()
        cmp = json.dumps({k: v for k, v in st.items() if k != "time"}, sort_keys=True)
        if cmp != self.last_state_json:
            self.last_state_json = cmp
            try:
                sysfs.write_json_atomic(self.state_path, st, mode=0o600)
            except OSError:
                pass
            if self.service:
                self.service.StateChanged(json.dumps(st))

    def _verify(self):
        self.verify_timer = None
        self.ctl.verify()
        self.changed()
        return False

    def save_persist(self):
        self.persist["dim"] = self.dim
        try:
            sysfs.write_json_atomic(self.persist_path, self.persist, mode=0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ settings
    def start_settings_watch(self):
        try:
            self.settings_proc = subprocess.Popen(
                ["kristall-settings", "watch", "--full", "--initial", "power"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            journal("kristall-settings not available: using built-in defaults")
            self.apply_settings({})
            return
        GLib.io_add_watch(self.settings_proc.stdout, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._settings_line)

    def _settings_line(self, src, cond):
        line = src.readline()
        if not line:
            journal("settings watch ended; keeping last settings")
            return False
        try:
            doc = json.loads(line).get("settings", {})
        except ValueError:
            return True
        self.apply_settings(doc.get("power") if isinstance(doc.get("power"), dict) else {})
        return True

    def apply_settings(self, power):
        s = dict(DEFAULTS)
        for k, v in (power or {}).items():
            if k == "chargeLimit" and isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer():
                s[k] = int(v)
            elif k == "heavyApps" and isinstance(v, list):
                s[k] = [str(x) for x in v if isinstance(x, str)]
            elif k == "batteryRefreshRate" and v in ("auto", "max"):
                s[k] = v
            elif k == "batteryBase" and v in policy.BATTERY_BASES:
                s[k] = v
            elif k in DEFAULTS and type(v) is type(DEFAULTS[k]) and k not in ("chargeLimit", "heavyApps", "batteryRefreshRate", "batteryBase"):
                s[k] = v
            elif k in DEFAULTS:
                journal(f"setting power.{k}: ignoring invalid value {v!r}")
                if k == "chargeLimit":
                    s[k] = None     # keep whatever limit is applied now
        self.settings = s
        first = not self.settings_loaded
        self.settings_loaded = True
        self.ctl.low_battery_enabled = bool(s["lowBatteryQuiet"])
        if first:
            self.ctl.battery_base = s["batteryBase"]
            self.ctl.automatic = bool(s["automatic"])
            self.ctl.start()
        else:
            self.ctl.battery_base = s["batteryBase"]
            self.ctl.set_automatic(bool(s["automatic"]))
            self.ctl.reconcile("settings")
        self.ensure_charge_limit()
        self.rescan_units()
        self.changed()

    # ------------------------------------------------------------------ power source (UPower)
    def upower_init(self):
        self.sysbus.add_signal_receiver(self._upower_props, "PropertiesChanged", PROPS, UPOWER[0], UPOWER[1])
        self.sysbus.add_signal_receiver(self._display_device_props, "PropertiesChanged", PROPS, UPOWER[0],
                                        "/org/freedesktop/UPower/devices/DisplayDevice")
        self.read_power(initial=True)

    def read_power(self, initial=False):
        on_battery, percent, has_battery = None, None, False
        try:
            up = self.sysbus.get_object(*UPOWER, introspect=False)
            on_battery = bool(up.Get("org.freedesktop.UPower", "OnBattery", dbus_interface=PROPS))
            dd = self.sysbus.get_object(UPOWER[0], "/org/freedesktop/UPower/devices/DisplayDevice", introspect=False)
            props = dd.GetAll(DEVICE_IFACE, dbus_interface=PROPS)
            if int(props.get("Type", 0)) == 2 and bool(props.get("IsPresent", False)):
                has_battery = True
                percent = int(round(float(props.get("Percentage", 0))))
        except dbus.DBusException:
            on_battery = hw.on_battery()
            bats = hw.system_batteries()
            has_battery = bool(bats)
            percent = hw.battery_info(bats[0])["percent"] if bats else None
        prev = (self.ctl.on_battery, self.ctl.percent)
        self.ctl.percent = percent
        self.ctl.set_power(bool(on_battery), has_battery)
        self.ctl.set_percent(percent)
        if initial or prev[0] != self.ctl.on_battery:
            self.on_source_change(initial)
        elif prev[1] != percent and percent is not None and self.ctl.on_battery:
            self.log("battery", percent=percent, **self.battery_extra())

    def battery_extra(self):
        bats = hw.system_batteries()
        if not bats:
            return {}
        b = hw.battery_info(bats[0])
        return {"power_w": b["power_w"], "tte_s": b["time_to_empty_s"], "temps": hw.temperatures() or None}

    def _upower_props(self, iface, changed, invalidated):
        if "OnBattery" in changed:
            self.read_power()

    def _display_device_props(self, iface, changed, invalidated):
        if "Percentage" in changed or "State" in changed or "IsPresent" in changed:
            self.read_power()

    def on_source_change(self, initial):
        if not initial:
            self.work.reset()
            self.sampler.reset()
        self.changed()

    # ------------------------------------------------------------------ tuned-ppd
    def ppd_init(self):
        for name, path, iface in PPD_NAMES[:1]:
            self.sysbus.add_signal_receiver(self._ppd_props, "PropertiesChanged", PROPS, name, path)
            self.sysbus.add_signal_receiver(self._ppd_released, "ProfileReleased", iface, name, path)
            self.sysbus.watch_name_owner(name, self._ppd_owner)

    def _ppd_props(self, iface, changed, invalidated):
        if "ActiveProfile" in changed:
            prof = str(changed["ActiveProfile"])
            self.log("profile", profile=prof)
            self.ctl.profile_changed(prof)
            self.changed()

    def _ppd_released(self, cookie):
        self.ctl.hold_released(int(cookie))

    def _ppd_owner(self, owner):
        if owner and self.settings_loaded:
            self.log("ppd-appeared")
            self.ctl.ppd_restarted()

    # ------------------------------------------------------------------ logind
    def logind_init(self):
        self.sysbus.add_signal_receiver(self._prepare_for_sleep, "PrepareForSleep",
                                        "org.freedesktop.login1.Manager", LOGIN1[0], LOGIN1[1])
        sid = os.environ.get("XDG_SESSION_ID")
        try:
            mgr = self.sysbus.get_object(*LOGIN1, introspect=False)
            path = mgr.GetSession(sid, dbus_interface="org.freedesktop.login1.Manager") if sid else \
                mgr.GetSessionByPID(dbus.UInt32(os.getpid()), dbus_interface="org.freedesktop.login1.Manager")
            self.sysbus.add_signal_receiver(self._session_props, "PropertiesChanged", PROPS, LOGIN1[0], str(path))
            sess = self.sysbus.get_object(LOGIN1[0], path, introspect=False)
            self.locked = bool(sess.Get("org.freedesktop.login1.Session", "LockedHint", dbus_interface=PROPS))
        except dbus.DBusException as e:
            journal(f"logind session not found ({e.get_dbus_name()}); lock state unknown")

    def _session_props(self, iface, changed, invalidated):
        if "LockedHint" in changed:
            self.locked = bool(changed["LockedHint"])
            self.log("lock", locked=self.locked)
            self.update_log_sampling()

    def _prepare_for_sleep(self, going):
        if going:
            self.log("suspend", percent=self.ctl.percent)
            self.stop_timer("sample_timer")
            self.stop_timer("log_timer")
        else:
            self.log("resume", percent=self.ctl.percent)
            self.sampler.reset()
            self.read_power()
            self.ctl.resumed()
            self.update_log_sampling()

    # ------------------------------------------------------------------ apps and games
    def systemd_init(self):
        try:
            mgr = self.sesbus.get_object(SYSTEMD[0], SYSTEMD[1], introspect=False)
            mgr.Subscribe(dbus_interface=SYSTEMD[2])
            self.sesbus.add_signal_receiver(self._unit_new, "UnitNew", SYSTEMD[2], SYSTEMD[0], SYSTEMD[1])
            self.sesbus.add_signal_receiver(self._unit_removed, "UnitRemoved", SYSTEMD[2], SYSTEMD[0], SYSTEMD[1])
        except dbus.DBusException as e:
            journal(f"systemd user manager unavailable: {e}")

    def rescan_units(self):
        self.heavy_units = {}
        try:
            mgr = self.sesbus.get_object(SYSTEMD[0], SYSTEMD[1], introspect=False)
            for u in mgr.ListUnits(dbus_interface=SYSTEMD[2]):
                if str(u[3]) == "active":
                    self._consider_unit(str(u[0]), str(u[6]))
        except dbus.DBusException:
            pass

    def _consider_unit(self, unit, path):
        app = workload.app_of_unit(unit)
        if not app or not workload.matches(app, self.settings["heavyApps"]):
            return False
        try:
            obj = self.sesbus.get_object(SYSTEMD[0], path, introspect=False)
            iface = "org.freedesktop.systemd1.Scope" if unit.endswith(".scope") else "org.freedesktop.systemd1.Service"
            cg = str(obj.Get(iface, "ControlGroup", dbus_interface=PROPS))
        except dbus.DBusException:
            return False
        self.heavy_units[unit] = (app, cg)
        return True

    def _unit_new(self, unit, path):
        if self._consider_unit(str(unit), str(path)):
            self.log("heavy-app-start", app=self.heavy_units[str(unit)][0])
            self.changed()

    def _unit_removed(self, unit, path):
        if str(unit) in self.heavy_units:
            app = self.heavy_units.pop(str(unit))[0]
            self.log("heavy-app-stop", app=app)
            if not any(a == app for a, _ in self.heavy_units.values()) and self.ctl.heavy == app:
                self.work.reset()
                self.ctl.set_heavy(None)
            self.changed()

    def gamemode_init(self):
        self.sesbus.add_signal_receiver(self._game_signal, None, GAMEMODE[2], GAMEMODE[0], GAMEMODE[1],
                                        member_keyword="member")
        self.sesbus.watch_name_owner(GAMEMODE[0], self._gamemode_owner)

    def _gamemode_owner(self, owner):
        self.game_count = 0
        if owner:
            try:
                o = self.sesbus.get_object(GAMEMODE[0], GAMEMODE[1], introspect=False)
                self.game_count = int(o.Get(GAMEMODE[2], "ClientCount", dbus_interface=PROPS))
            except dbus.DBusException:
                pass
        self.ctl.set_game(self.game_count > 0)
        self.changed()

    def _game_signal(self, *args, member=None):
        if member not in ("GameRegistered", "GameUnregistered"):
            return
        try:
            o = self.sesbus.get_object(GAMEMODE[0], GAMEMODE[1], introspect=False)
            self.game_count = int(o.Get(GAMEMODE[2], "ClientCount", dbus_interface=PROPS))
        except dbus.DBusException:
            self.game_count = max(0, self.game_count + (1 if member == "GameRegistered" else -1))
        self.ctl.set_game(self.game_count > 0)
        self.changed()

    # ------------------------------------------------------------------ timers (only when needed)
    def stop_timer(self, attr):
        t = getattr(self, attr)
        if t is not None:
            GLib.source_remove(t)
            setattr(self, attr, None)

    def update_sampling(self):
        need = (self.ctl.automatic and not self.ctl.override and not self.ctl.on_battery
                and bool(self.heavy_units))
        if need and self.sample_timer is None:
            self.sampler.reset()
            self.sampler.sample(self.heavy_units)
            self.sample_timer = GLib.timeout_add_seconds(policy.SAMPLE_SECONDS, self._sample)
        elif not need and self.sample_timer is not None:
            self.stop_timer("sample_timer")
            self.work.reset()
            if self.ctl.heavy:
                self.ctl.set_heavy(None)

    def _sample(self):
        cores, gpu = self.sampler.sample(self.heavy_units)
        app = self.work.sample(cores, gpu)
        if app != self.ctl.heavy:
            self.log("workload", app=app, cores={k: round(v, 2) for k, v in cores.items()},
                     gpu_busy=None if gpu is None else round(gpu, 2))
            self.ctl.set_heavy(app)
        return True

    def update_log_sampling(self):
        """The thermal log samples once a minute while the screen is unlocked (someone is using
        the machine) and writes only when the machine is under load; locked or asleep: no timer."""
        if self.locked:
            self.stop_timer("log_timer")
        elif self.log_timer is None:
            self.cpu_prev = workload.system_cpu_busy(None)[1]
            self.log_timer = GLib.timeout_add_seconds(policy.LOG_SAMPLE_SECONDS, self._log_sample)

    def _log_sample(self):
        busy, self.cpu_prev = workload.system_cpu_busy(self.cpu_prev)
        temps = hw.temperatures()
        hot = (temps.get("cpu_package") or 0) >= 80
        loaded = (busy or 0) >= 0.25 or hot or self.ctl.heavy or self.game_count
        if loaded:
            bat = self.battery_extra()
            self.log("sample", cpu_busy=None if busy is None else round(busy, 3), temps=temps or None,
                     fans=hw.fans() or None, mode=self.ctl.effective_mode(), on_battery=self.ctl.on_battery,
                     power_w=bat.get("power_w"), heavy=self.ctl.heavy, games=self.game_count or None)
        return True

    # ------------------------------------------------------------------ glass quality hint
    def glass_init(self):
        d = os.path.dirname(paths.glass_socket())
        os.makedirs(d, mode=0o700, exist_ok=True)
        self.glass_mon = Gio.File.new_for_path(d).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.glass_mon.connect("changed", self._glass_dir_event)
        self.glass_connect()

    def _glass_dir_event(self, mon, f, other, ev):
        if f.get_basename() == os.path.basename(paths.glass_socket()) and ev in (
                Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.CHANGES_DONE_HINT):
            if self.glass is None:
                self.glass_connect()

    def glass_connect(self, attempt=0):
        self.glass_retry = None
        path = paths.glass_socket()
        if self.glass is not None or not os.path.exists(path):
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(path)
        except OSError:
            s.close()
            if attempt < 6:  # stale socket or KWin still starting: a few backed-off tries, then wait for inotify
                self.glass_retry = GLib.timeout_add(int(min(0.25 * 2 ** attempt, 8) * 1000),
                                                    lambda: self.glass_connect(attempt + 1))
            return False
        s.setblocking(False)
        self.glass = s
        self.glass_hint_sent = None
        self.glass_buf = b""
        GLib.io_add_watch(s.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._glass_io)
        self._glass_send({"op": "hello", "client": "kristall-power"})
        self.update_glass()
        return False

    def _glass_send(self, obj):
        if self.glass is None:
            return False
        try:
            self.glass.sendall((json.dumps(obj) + "\n").encode())
            return True
        except OSError:
            self._glass_closed()
            return False

    def _glass_io(self, fd, cond):
        try:
            data = self.glass.recv(65536) if self.glass else b""
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:
            self._glass_closed()
            return False
        return True   # replies (hello/state) are not needed; reading keeps the server's queue empty

    def _glass_closed(self):
        if self.glass is not None:
            try:
                self.glass.close()
            except OSError:
                pass
        self.glass = None
        self.glass_hint_sent = None
        if self.glass_retry is None:
            self.glass_retry = GLib.timeout_add(500, lambda: self.glass_connect(1))

    def update_glass(self):
        hint = policy.glass_hint(self.ctl.effective_mode(), self.ctl.on_battery)
        if self.glass is not None and hint != self.glass_hint_sent:
            if self._glass_send({"op": "config", "qualityHint": hint}):
                self.glass_hint_sent = hint
                self.log("glass", hint=hint)

    # ------------------------------------------------------------------ display: refresh + dimming
    def schedule_display(self):
        if self.display_timer is None:
            self.display_timer = GLib.timeout_add_seconds(policy.SOURCE_DEBOUNCE_S, self._display_now)

    def _display_now(self):
        self.display_timer = None
        if self.game_count:
            return False      # never change the panel under a running game; re-evaluated when it ends
        key = (self.ctl.on_battery, self.ctl.effective_mode(), self.settings["batteryRefreshRate"],
               self.settings["dimOnBattery"])
        if key == self.display_key:
            return False      # nothing relevant changed: do not even ask KScreen
        self.display_key = key
        self.ensure_refresh()
        self.ensure_dim()
        return False

    def ensure_refresh(self):
        target = policy.refresh_policy(self.ctl.effective_mode(), self.ctl.on_battery,
                                       self.settings["batteryRefreshRate"])
        cfg = display.kscreen_json()
        outs = display.internal_outputs(cfg)
        if not outs:
            self.refresh = {"managed": False, "reason": "no internal panel visible to KScreen", "target": target}
            return
        o = outs[0]
        desc = display.describe(o)
        last = self.persist.get("refresh_mode")
        if self.persist.get("refresh_owner"):
            self.refresh = {"managed": False, "reason": "owner chose a refresh rate", "panel": desc, "target": target}
            return
        if display.owner_managed(o, last) and last is not None:
            self.persist["refresh_owner"] = True
            self.save_persist()
            self.log("refresh-owner", panel=desc)
            self.refresh = {"managed": False, "reason": "owner chose a refresh rate", "panel": desc, "target": target}
            return
        pick = display.choose(o, target)
        if pick:
            ok, out = display.set_mode(o["name"], pick[0])
            self.log("refresh", output=o["name"], to_hz=pick[1], target=target, ok=ok, detail=None if ok else out)
            if ok:
                self.persist["refresh_mode"] = pick[0]
                self.save_persist()
                desc = display.describe(dict(o, currentModeId=pick[0])) or desc
        elif last is None:
            self.persist["refresh_mode"] = str(o.get("currentModeId"))
            self.save_persist()
        self.refresh = {"managed": True, "panel": desc, "target": target}

    def _brightness_display(self):
        try:
            root = self.sesbus.get_object(*BRIGHT, introspect=False)
            for name in root.Get("org.kde.ScreenBrightness", "DisplaysDBusNames", dbus_interface=PROPS):
                o = self.sesbus.get_object(BRIGHT[0], f"{BRIGHT[1]}/{name}", introspect=False)
                if bool(o.Get("org.kde.ScreenBrightness.Display", "IsInternal", dbus_interface=PROPS)):
                    return str(name), o
        except dbus.DBusException:
            pass
        return None, None

    def ensure_dim(self):
        if self.game_count:
            return
        name, o = self._brightness_display()
        if o is None:
            return
        P = "org.kde.ScreenBrightness.Display"
        try:
            cur = int(o.Get(P, "Brightness", dbus_interface=PROPS))
            mx = int(o.Get(P, "MaxBrightness", dbus_interface=PROPS))
            if self.ctl.on_battery and self.settings["dimOnBattery"] and not self.dim:
                if mx > 0 and cur > 0.25 * mx:
                    new = max(int(round(cur * 0.85)), int(0.25 * mx))
                    o.SetBrightness(dbus.Int32(new), dbus.UInt32(1), dbus_interface=P)   # 1 = no OSD
                    self.dim = {"display": name, "before": cur, "set": new}
                    self.log("dim", before=cur, after=new, max=mx)
            elif not self.ctl.on_battery and self.dim:
                if cur == self.dim["set"]:
                    o.SetBrightness(dbus.Int32(self.dim["before"]), dbus.UInt32(1), dbus_interface=P)
                    self.log("undim", to=self.dim["before"])
                else:
                    self.log("undim-skipped", reason="owner changed brightness", now=cur)
                self.dim = None
            self.save_persist()
        except dbus.DBusException as e:
            journal(f"brightness: {e}")

    # ------------------------------------------------------------------ charge limit
    def ensure_charge_limit(self):
        want = self.settings.get("chargeLimit")
        if not isinstance(want, int):
            return
        if not 50 <= want <= 100 or want == self.charge_requested:
            return
        applied = (sysfs.read_json(os.path.join(paths.RUN_DIR, "charge.json"), {}) or {}).get("limit")
        stored = sysfs.read(os.path.join(paths.STATE_DIR, "charge-limit"))
        current = applied if applied is not None else (int(stored) if stored and stored.isdigit() else 100)
        self.charge_requested = want
        if current == want or not hw.system_batteries():
            return
        self.log("charge-limit-request", limit=want)
        subprocess.Popen(["systemctl", "start", "--no-block", f"kristall-power-charge@{want}.service"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ------------------------------------------------------------------ run
    def run(self):
        try:
            self.service = PowerService(self.sesbus, self)
        except dbus.DBusException as e:
            journal(f"cannot own {OWN_NAME}: {e}")
        self.upower_init()
        self.ppd_init()
        self.logind_init()
        self.systemd_init()
        self.gamemode_init()
        self.start_settings_watch()
        self.glass_init()
        self.update_log_sampling()
        self.log("start", on_battery=self.ctl.on_battery, percent=self.ctl.percent)
        self.loop.run()


def main():
    Daemon().run()
    return 0
