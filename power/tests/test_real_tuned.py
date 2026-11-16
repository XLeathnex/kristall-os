# SPDX-License-Identifier: GPL-3.0-or-later
"""The real tuned 2.28 daemon and the real tuned-ppd, with power/ installed, on a private
"system" bus with a fake UPower: checks that the PPD API maps the three modes and the battery state
to the Kristall profiles, that tuned runs our [script] hook (which programs the fake RAPL limits),
that holds work, and that stopping tuned gives the firmware limits back.

Installs into the running system: only for a disposable dev container. Opt in with
KRISTALL_POWER_REAL_TUNED=1 (run.sh does this only when /.dockerenv exists)."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
POWER = os.path.dirname(HERE)
REPO = os.path.dirname(POWER)
sys.path.insert(0, HERE)
import fixtures  # noqa: E402

ENABLED = os.environ.get("KRISTALL_POWER_REAL_TUNED") == "1" and shutil.which("tuned") and os.geteuid() == 0
PPD = ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles", "org.freedesktop.UPower.PowerProfiles")
W = 1_000_000


@unittest.skipUnless(ENABLED, "set KRISTALL_POWER_REAL_TUNED=1 in a disposable container with tuned installed")
class RealTuned(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kp-tuned-")
        r = subprocess.run(["bash", os.path.join(POWER, "image/install.sh")], capture_output=True, text=True,
                           env=dict(os.environ, KRISTALL_CTX=REPO, KRISTALL_POWER_SKIP_PACKAGES="1", KRISTALL_POWER_SKIP_VERIFY="1"),
                           cwd=POWER)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.root = os.path.join(cls.tmp, "root")
        cls.faults = fixtures.build(cls.root, "thin-oled")
        cls.bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, text=True)
        cls.addr = cls.bus.stdout.readline().strip()
        cls.ses = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, text=True)
        ses_addr = cls.ses.stdout.readline().strip()
        ready = os.path.join(cls.tmp, "ready")
        cls.fakes = subprocess.Popen([sys.executable, os.path.join(HERE, "fakes/fake_services.py"), cls.addr, ses_addr, ready, "--no-ppd"])
        for _ in range(100):
            if os.path.exists(ready):
                break
            time.sleep(0.1)
        env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=cls.addr, KRISTALL_POWER_ROOT=cls.root, KRISTALL_POWER_FAULTS=cls.faults,
                   KRISTALL_POWER_NO_SYSTEMD="1", KRISTALL_POWER_SETTLE="0")
        cls.tuned_log = open(os.path.join(cls.tmp, "tuned.log"), "w")
        cls.tuned = subprocess.Popen(["tuned", "--debug"], env=env, stdout=cls.tuned_log, stderr=subprocess.STDOUT)
        cls.wait_for(lambda: cls.busctl("status", "com.redhat.tuned", check=False).returncode == 0, "tuned on the bus", 30)
        cls.ppd = subprocess.Popen(["tuned-ppd"], env=env, stdout=cls.tuned_log, stderr=subprocess.STDOUT)
        cls.wait_for(lambda: cls.get() is not None, "tuned-ppd on the bus", 30)

    @classmethod
    def tearDownClass(cls):
        for p in (cls.ppd, cls.tuned, cls.fakes, cls.bus, cls.ses):
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(20)
                except subprocess.TimeoutExpired:
                    p.kill()
        cls.bus.stdout.close()
        cls.ses.stdout.close()
        cls.tuned_log.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def busctl(cls, *args, check=True):
        return subprocess.run(["busctl", f"--address={cls.addr}", *args], capture_output=True, text=True, check=check, timeout=30)

    @classmethod
    def get(cls):
        r = cls.busctl("get-property", *PPD, "ActiveProfile", check=False)
        return json.loads(r.stdout.split(" ", 1)[1]) if r.returncode == 0 else None

    @classmethod
    def wait_for(cls, cond, what, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.2)
        cls.tuned_log.flush()
        with open(cls.tuned_log.name) as f:
            log = f.read()[-3000:]
        raise AssertionError(f"timeout: {what}\n{log}")

    def active_tuned(self):
        with open("/etc/tuned/active_profile") as f:
            return f.read().strip()

    def limits(self):
        return fixtures.read_uw(self.root, "intel-rapl:0", 0) / W, fixtures.read_uw(self.root, "intel-rapl:0", 1) / W

    def expect(self, ppd, tuned, limits):
        self.wait_for(lambda: self.get() == ppd and self.active_tuned() == tuned and self.limits() == limits,
                      f"{ppd} -> {tuned} with limits {limits} (now {self.get()}, {self.active_tuned()}, {self.limits()})")

    def test_modes_battery_holds_and_revert(self):
        self.expect("balanced", "kristall-balanced", (45.0, 90.0))
        self.busctl("set-property", *PPD, "ActiveProfile", "s", "power-saver")
        self.expect("power-saver", "kristall-quiet", (20.0, 45.0))
        self.busctl("call", "org.test.Control", "/org/test/Control", "org.test.Control", "SetOnBattery", "b", "true")
        self.expect("power-saver", "kristall-quiet-battery", (15.0, 35.0))
        self.busctl("set-property", *PPD, "ActiveProfile", "s", "balanced")
        self.expect("balanced", "kristall-balanced-battery", (28.0, 55.0))
        # a hold (what the session daemon does for games) — the busctl client exits, so tuned-ppd
        # drops the hold again when its D-Bus name vanishes: exactly the crash-safety we rely on
        self.busctl("call", *PPD, "HoldProfile", "sss", "performance", "test", "kristall-test")
        self.expect("balanced", "kristall-balanced-battery", (28.0, 55.0))
        self.busctl("call", "org.test.Control", "/org/test/Control", "org.test.Control", "SetOnBattery", "b", "false")
        self.expect("balanced", "kristall-balanced", (45.0, 90.0))
        self.busctl("set-property", *PPD, "ActiveProfile", "s", "performance")
        self.expect("performance", "kristall-performance", (45.0, 115.0))
        self.busctl("set-property", *PPD, "ActiveProfile", "s", "power-saver")
        self.expect("power-saver", "kristall-quiet", (20.0, 45.0))
        with open(os.path.join(self.root, "var/lib/kristall/power/events.jsonl")) as f:
            evs = [json.loads(x) for x in f]
        self.assertTrue(any(e["ev"] == "apply" and e.get("reason") == "tuned" for e in evs))
        # stopping tuned runs the hook's "stop": firmware limits come back
        self.ppd.send_signal(signal.SIGTERM)
        self.ppd.wait(20)
        self.tuned.send_signal(signal.SIGTERM)
        self.tuned.wait(30)
        self.assertEqual(self.limits(), (45.0, 115.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
