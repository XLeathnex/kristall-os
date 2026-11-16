# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end test of `kristall-power session` on two private D-Bus buses with fake UPower,
tuned-ppd, logind, GameMode, systemd user manager and PowerDevil brightness services, a fake
kscreen-doctor, a fake glass socket and the real kristall-settings. Needs python3-dbus, GLib and
dbus-daemon (the dev container); skipped elsewhere."""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
POWER = os.path.dirname(HERE)
REPO = os.path.dirname(POWER)
sys.path.insert(0, HERE)
import fixtures  # noqa: E402

try:
    import dbus  # noqa: F401
    HAVE = bool(shutil.which("dbus-daemon"))
except ImportError:
    HAVE = False

SETTINGS_TOOL = os.path.join(REPO, "image/rootfs/usr/bin/kristall-settings")


def start_bus(tmp, name):
    p = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, text=True,
                         cwd=tmp)
    addr = p.stdout.readline().strip()
    return p, addr


class GlassServer(threading.Thread):
    def __init__(self, path):
        super().__init__(daemon=True)
        self.path = path
        self.lines = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(4)

    def run(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            c.sendall(b'{"event":"hello","server":"kristall-glass","protocol":1,"state":"active","quality":"high"}\n')
            buf = b""
            while True:
                try:
                    d = c.recv(4096)
                except OSError:
                    break
                if not d:
                    break
                buf += d
                while b"\n" in buf:
                    ln, buf = buf.split(b"\n", 1)
                    self.lines.append(json.loads(ln))

    def hints(self):
        return [m["qualityHint"] for m in self.lines if m.get("op") == "config"]


@unittest.skipUnless(HAVE and os.path.exists(SETTINGS_TOOL), "needs python3-dbus, dbus-daemon and image/ kristall-settings")
class SessionDaemon(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kp-session-")
        self.procs = []
        self.sysp, self.sysaddr = start_bus(self.tmp, "system")
        self.sesp, self.sesaddr = start_bus(self.tmp, "session")
        self.procs += [self.sysp, self.sesp]
        ready = os.path.join(self.tmp, "ready")
        self.fakes = subprocess.Popen([sys.executable, os.path.join(HERE, "fakes/fake_services.py"), self.sysaddr, self.sesaddr, ready])
        self.procs.append(self.fakes)
        self.wait(lambda: os.path.exists(ready), "fake services")
        # fake machine (cgroup cpu.stat, power supplies for fallbacks)
        self.root = os.path.join(self.tmp, "root")
        fixtures.build(self.root, "thin-oled")
        self.cg = "/user.slice/user-1000.slice/user@1000.service/app.slice/app-flatpak-org.blender.Blender-42.scope"
        self.usage = 0
        self.write_usage()
        # tools
        bin_dir = os.path.join(self.tmp, "bin")
        shutil.copytree(os.path.join(HERE, "fakes/bin"), bin_dir)
        os.symlink(SETTINGS_TOOL, os.path.join(bin_dir, "kristall-settings"))
        self.kscreen_state = os.path.join(self.tmp, "kscreen.json")
        self.kscreen_log = os.path.join(self.tmp, "kscreen.log")
        modes = [{"id": "1", "name": "a", "size": {"width": 2880, "height": 1800}, "refreshRate": 120.0},
                 {"id": "2", "name": "b", "size": {"width": 2880, "height": 1800}, "refreshRate": 60.0}]
        with open(self.kscreen_state, "w") as f:
            json.dump({"outputs": [{"id": 1, "name": "eDP-1", "type": 7, "connected": True, "enabled": True,
                                    "currentModeId": "1", "modes": modes, "vrrPolicy": 2}]}, f)
        dropins = os.path.join(self.tmp, "settings.d")
        os.makedirs(dropins)
        shutil.copy(os.path.join(POWER, "config/50-power.json"), dropins)
        defaults = os.path.join(self.tmp, "defaults.json")
        with open(defaults, "w") as f:
            f.write("{}\n")
        self.runtime = os.path.join(self.tmp, "runtime")
        os.makedirs(os.path.join(self.runtime, "kristall"), mode=0o700)
        self.env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=self.sysaddr, DBUS_SESSION_BUS_ADDRESS=self.sesaddr,
                        PATH=bin_dir + ":" + os.environ.get("PATH", "/usr/bin"), XDG_RUNTIME_DIR=self.runtime,
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"), XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                        KRISTALL_SETTINGS_DEFAULTS=defaults, KRISTALL_SETTINGS_DROPIN_DIRS=dropins,
                        KRISTALL_POWER_ROOT=self.root, KRISTALL_POWER_LIB=os.path.join(POWER, "lib"),
                        KRISTALL_POWER_TEST_FAST="1", KSCREEN_FAKE_STATE=self.kscreen_state, KSCREEN_FAKE_LOG=self.kscreen_log,
                        SYSTEMCTL_FAKE_LOG=os.path.join(self.tmp, "systemctl.log"), XDG_SESSION_ID="1")
        self.log = open(os.path.join(self.tmp, "daemon.log"), "w")
        cmd = [sys.executable, os.path.join(POWER, "bin/kristall-power"), "session"]
        if os.environ.get("KP_DEBUG_IDLE"):
            cmd = [sys.executable, os.path.join(HERE, "fakes/trace_daemon.py")]
        self.daemon = subprocess.Popen(cmd,
                                       env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        self.procs.insert(0, self.daemon)

    def tearDown(self):
        for p in (self.sysp, self.sesp):
            p.stdout.close()
        for p in self.procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        self.log.close()
        if os.environ.get("KEEP_TMP") != "1":
            shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def write_usage(self):
        fixtures._w(self.root, "/sys/fs/cgroup" + self.cg + "/cpu.stat", f"usage_usec {self.usage}\nuser_usec 0\n")

    def wait(self, cond, what, timeout=12):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = cond()
                if last:
                    return last
            except Exception as e:  # noqa: BLE001
                last = e
            time.sleep(0.1)
        dl = ""
        if hasattr(self, "log"):
            self.log.flush()
            with open(self.log.name) as f:
                dl = f.read()[-4000:]
        self.fail(f"timeout waiting for {what} (last: {last})\n--- daemon log ---\n{dl}")

    @staticmethod
    def read(path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    def wakeups(self, seconds):
        def cs():
            n = 0
            for t in os.listdir(f"/proc/{self.daemon.pid}/task"):
                txt = self.read(f"/proc/{self.daemon.pid}/task/{t}/status")
                n += sum(int(ln.split()[1]) for ln in txt.splitlines() if "ctxt_switches" in ln)
            return n
        a = cs()
        time.sleep(seconds)
        return cs() - a

    def ctl(self, method, *args):
        import dbus as d
        bus = d.bus.BusConnection(self.sesaddr)
        try:
            return bus.get_object("org.test.Control", "/org/test/Control").get_dbus_method(method, "org.test.Control")(*args)
        finally:
            bus.close()

    def ppd(self):
        return json.loads(self.ctl("State"))

    def session_state(self):
        with open(os.path.join(self.runtime, "kristall/power.json")) as f:
            return json.load(f)

    def kscreen_sets(self):
        if not os.path.exists(self.kscreen_log):
            return []
        with open(self.kscreen_log) as f:
            return f.read().split()

    # the scenario
    def test_full_day(self):
        # 1. start on mains with yesterday's manual Leise left in tuned-ppd: automatic resets to Ausgewogen
        self.wait(lambda: self.ppd()["active"] == "balanced", "base balanced at start")
        st = self.wait(lambda: self.session_state(), "session state file")
        self.assertTrue(st["automatic"])
        self.assertEqual(oct(os.stat(os.path.join(self.runtime, "kristall/power.json")).st_mode & 0o777), "0o600")
        # 2. the glass effect appears after the daemon: inotify connects, hint "high" on mains
        glass = GlassServer(os.path.join(self.runtime, "kristall/glass.sock"))
        glass.start()
        self.wait(lambda: glass.hints() == ["high"], "glass hint high")
        self.assertEqual(glass.lines[0], {"op": "hello", "client": "kristall-power"})
        time.sleep(1.5)
        self.assertEqual(self.kscreen_sets(), [], "on mains at 120 Hz nothing changes")
        # 3. a game registers with GameMode on mains -> performance hold
        self.ctl("Game", True)
        self.wait(lambda: self.ppd()["holds"] == [["performance", "auto-game", "kristall-power"]], "performance hold")
        self.assertEqual(self.ppd()["active"], "performance")
        # 4. unplug during the game: Leistung released, Leise on battery (power.batteryBase "quiet"),
        #    glass efficient, display untouched while the game runs
        self.ctl("SetOnBattery", True)
        self.wait(lambda: self.ppd()["active"] == "power-saver" and self.ppd()["holds"] == [["power-saver", "auto-battery", "kristall-power"]],
                  "Leise hold on unplug")
        self.assertEqual(self.session_state()["reason"], "auto-battery")
        self.wait(lambda: glass.hints()[-1] == "efficient", "glass efficient on battery")
        time.sleep(2)
        self.assertEqual(self.kscreen_sets(), [], "no mode change under a running game")
        self.assertEqual(self.ppd()["brightness"], 300, "no dimming under a running game")
        # 5. the game ends: 60 Hz and slight dimming on battery
        self.ctl("Game", False)
        self.wait(lambda: self.kscreen_sets() == ["output.eDP-1.mode.2"], "60 Hz on battery")
        self.wait(lambda: self.ppd()["brightness"] == 255, "dim to 85 %")
        self.assertEqual(self.ppd()["brightness_calls"][-1], [255, 1], "no OSD for automatic dimming")
        # 6. the owner picks Leise by hand; replugging keeps it
        self.ctl("OwnerSetProfile", "power-saver")
        self.wait(lambda: (self.session_state().get("manual") or {}).get("mode") == "quiet", "manual quiet")
        self.ctl("SetOnBattery", False)
        self.wait(lambda: self.kscreen_sets()[-1:] == ["output.eDP-1.mode.1"], "120 Hz on mains")
        self.wait(lambda: self.ppd()["brightness"] == 300, "brightness restored")
        time.sleep(1)
        self.assertEqual(self.ppd()["active"], "power-saver", "manual Leise survives replug")
        self.assertEqual(glass.hints()[-1], "efficient", "Leise keeps glass efficient on mains")
        # 7. back to automatic through the CLI
        subprocess.run([sys.executable, os.path.join(POWER, "bin/kristall-power"), "mode", "auto"], env=self.env, check=True)
        self.wait(lambda: self.ppd()["active"] == "balanced", "automatic again")
        self.wait(lambda: glass.hints()[-1] == "high", "glass high again")
        # 8. Blender starts and renders: boost after two busy samples, release after six calm ones
        self.ctl("AddUnit", "app-flatpak-org.blender.Blender-42.scope", self.cg)
        self.wait(lambda: self.session_state().get("sampling"), "sampling starts with a heavy app on mains")
        t_end = time.time() + 4
        while time.time() < t_end:
            self.usage += 1_200_000      # 12 logical CPUs busy (~0.1 s steps)
            self.write_usage()
            time.sleep(0.1)
        self.wait(lambda: self.ppd()["holds"] == [["performance", "auto-heavy-app", "kristall-power"]], "render boost")
        self.wait(lambda: not self.ppd()["holds"], "release after the render", timeout=15)
        self.ctl("RemoveUnit", "app-flatpak-org.blender.Blender-42.scope")
        self.wait(lambda: not self.session_state().get("sampling"), "sampling stops when the app quits")
        # 9. owner sets an 80 % charge limit in settings -> the root unit is started
        subprocess.run(["kristall-settings", "set", "power.chargeLimit", "80"], env=self.env, check=True)
        self.wait(lambda: "start --no-block kristall-power-charge@80.service" in self.read(self.env["SYSTEMCTL_FAKE_LOG"]),
                  "charge-limit unit started")
        # 10. suspend / resume and low battery
        self.ctl("SetOnBattery", True)
        self.ctl("Sleep", True)
        self.ctl("SetPercent", 15.0)
        self.ctl("Sleep", False)
        # with the quiet battery base the Leise hold placed on unplugging stays (re-placing it would
        # flip tuned's profile for nothing); only the reason says low battery now
        self.wait(lambda: [h[0] for h in self.ppd()["holds"]] == ["power-saver"]
                  and self.session_state().get("reason") == "auto-low-battery", "low-battery Leise")
        self.ctl("SetOnBattery", False)
        self.wait(lambda: not self.ppd()["holds"] and self.ppd()["active"] == "balanced", "charger lifts low-battery mode")
        # 10b. power.batteryBase "balanced" (for owners who prefer speed) applies live
        subprocess.run(["kristall-settings", "set", "power.batteryBase", '"balanced"'], env=self.env, check=True)
        self.ctl("SetPercent", 60.0)
        self.ctl("SetOnBattery", True)
        time.sleep(1.5)
        self.assertEqual((self.ppd()["active"], self.ppd()["holds"]), ("balanced", []), "Ausgewogen on battery")
        subprocess.run(["kristall-settings", "set", "power.batteryBase", '"quiet"'], env=self.env, check=True)
        self.wait(lambda: self.ppd()["holds"] == [["power-saver", "auto-battery", "kristall-power"]], "Leise again")
        self.ctl("SetOnBattery", False)
        self.wait(lambda: not self.ppd()["holds"] and self.ppd()["active"] == "balanced", "mains: Ausgewogen")
        # 11. turning automatic off in settings: nothing is changed any more
        subprocess.run(["kristall-settings", "set", "power.automatic", "false"], env=self.env, check=True)
        self.wait(lambda: self.session_state()["automatic"] is False, "automatic off")
        self.ctl("Game", True)
        time.sleep(1.5)
        self.assertEqual(self.ppd()["holds"], [])
        # 12. idle means idle: screen locked, no heavy app -> the daemon does not wake up at all
        self.ctl("Game", False)
        self.ctl("Lock", True)
        time.sleep(5)   # let the one-shot follow-ups of the last actions run (verify 3.5 s, display debounce)
        self.assertLessEqual(self.wakeups(4), 2, "the session daemon must sleep while nothing happens")
        # the owner-invisible log recorded the day
        with open(os.path.join(self.tmp, "state/kristall/power/log.jsonl")) as f:
            evs = [json.loads(x)["ev"] for x in f]
        for ev in ("start", "hold", "release", "manual", "refresh", "dim", "undim", "glass", "suspend", "resume",
                   "heavy-app-start", "workload", "charge-limit-request", "automatic"):
            self.assertIn(ev, evs)
        self.assertIsNone(self.daemon.poll(), "daemon still running")


if __name__ == "__main__":
    unittest.main(verbosity=2)
