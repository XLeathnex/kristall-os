# SPDX-License-Identifier: GPL-3.0-or-later
"""Root-side levers against fake hardware: power limits, charge limit, boot/revert, status, doctor,
generator and udev helper. Runs `kristall-power` as a subprocess with KRISTALL_POWER_ROOT pointing
at a fixture tree, exactly as tuned/systemd would run it."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
POWER = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fixtures  # noqa: E402

W = 1_000_000
MSR, MMIO = "intel-rapl:0", "intel-rapl-mmio:0"


class Machine:
    def __init__(self, personality, on_battery=False, percent=64):
        self.root = tempfile.mkdtemp(prefix=f"kp-{personality}-")
        self.personality = personality
        self.faults = fixtures.build(self.root, personality, on_battery, percent)
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)

    def env(self, **extra):
        e = dict(os.environ)
        e.update(KRISTALL_POWER_ROOT=self.root, KRISTALL_POWER_LIB=os.path.join(POWER, "lib"),
                 KRISTALL_POWER_FAULTS=self.faults, KRISTALL_POWER_NO_SYSTEMD="1", KRISTALL_POWER_SETTLE="0,0",
                 KRISTALL_POWER_NO_EXEC="1", HOME=self.home, XDG_RUNTIME_DIR=os.path.join(self.root, "run-user"),
                 XDG_STATE_HOME=os.path.join(self.home, ".local/state"), LANG="de_DE.UTF-8")
        e.update(extra)
        return e

    def run(self, *args, check=True, **extra):
        p = subprocess.run([sys.executable, os.path.join(POWER, "bin", "kristall-power"), *args],
                           capture_output=True, text=True, env=self.env(**extra), timeout=60)
        if check and p.returncode != 0:
            raise AssertionError(f"kristall-power {' '.join(args)} -> {p.returncode}\n{p.stdout}\n{p.stderr}")
        return p

    def uw(self, zone, idx):
        return fixtures.read_uw(self.root, zone, idx)

    def limits(self, zone):
        return self.uw(zone, 0) / W, self.uw(zone, 1) / W

    def read(self, rel):
        with open(os.path.join(self.root, rel.lstrip("/"))) as f:
            return f.read().strip()

    def write(self, rel, value):
        fixtures._w(self.root, rel, value)

    def set_fault(self, rel, fault):
        with open(self.faults) as f:
            d = json.load(f)
        if fault is None:
            d.pop(rel, None)
        else:
            d[rel] = fault
        with open(self.faults, "w") as f:
            json.dump(d, f)

    def events(self):
        p = os.path.join(self.root, "var/lib/kristall/power/events.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f]

    def applied(self):
        with open(os.path.join(self.root, "run/kristall-power/applied.json")) as f:
            return json.load(f)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


# expected (PL1, PL2) in W for a 45/115 W firmware
EXPECT_45_115 = {
    "kristall-quiet": (20.0, 45.0), "kristall-quiet-battery": (15.0, 35.0),
    "kristall-balanced": (45.0, 90.0), "kristall-balanced-battery": (28.0, 55.0),
    "kristall-performance": (45.0, 115.0), "kristall-performance-battery": (45.0, 115.0),
}


class PowerLimits(unittest.TestCase):
    def setUp(self):
        self.m = None

    def tearDown(self):
        if self.m:
            self.m.cleanup()

    def hook(self, profile, action="start"):
        fixtures.set_active_profile(self.m.root, profile)
        return self.m.run("tuned-hook", action, profile)

    def test_every_mode_on_thin_oled(self):
        self.m = Machine("thin-oled")
        order = ["kristall-quiet", "kristall-balanced-battery", "kristall-performance", "kristall-quiet-battery",
                 "kristall-balanced", "kristall-performance-battery", "kristall-quiet"]
        for prof in order:
            self.hook(prof)
            for zone in (MSR, MMIO):
                self.assertEqual(self.m.limits(zone), EXPECT_45_115[prof], f"{prof} {zone}")
            for r in self.m.applied()["rapl"]:
                self.assertEqual(r["status"], "applied", r)
                self.assertLessEqual(r["target_uw"], r["baseline_uw"])
        # peak power (constraint 2) is never touched
        self.assertEqual(self.m.uw(MSR, 2), 200 * W)
        self.assertEqual(self.m.applied()["platform_profile"]["expected"], "quiet")
        # tuned "stop" gives the firmware values back
        self.hook("kristall-quiet", "stop")
        self.assertEqual(self.m.limits(MSR), (45.0, 115.0))
        self.assertEqual(self.m.limits(MMIO), (45.0, 115.0))

    def test_relative_to_firmware_and_floor(self):
        self.m = Machine("lcd60-nopp")  # firmware 35/90 W
        self.hook("kristall-quiet-battery")
        # PL1 = max(min(35, 15, 0.35*35=12.25), floor 12) = 12.25 ; PL2 = min(90, 35, 36) = 35
        self.assertEqual(self.m.limits(MSR), (12.25, 35.0))
        self.hook("kristall-balanced")
        self.assertEqual(self.m.limits(MSR), (35.0, 90.0))  # never above the firmware's own 35 W
        self.m.write("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw", 10 * W)  # firmware sets 10 W
        self.hook("kristall-quiet")
        self.assertEqual(self.m.uw(MSR, 0), 10 * W, "below the floor: leave the firmware value alone")

    def test_reported_maximum_is_respected(self):
        self.m = Machine("thin-oled")
        self.m.write("/sys/class/powercap/intel-rapl:0/constraint_1_max_power_uw", 60 * W)
        self.hook("kristall-balanced")
        self.assertEqual(self.m.uw(MSR, 1), 60 * W)

    def test_locked_by_firmware(self):
        self.m = Machine("locked")
        p = self.hook("kristall-quiet")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.m.limits(MSR), (55.0, 115.0), "locked limits are not changed")
        st = {r["lever"]: r["status"] for r in self.m.applied()["rapl"]}
        self.assertEqual(st, {f"rapl:{MSR}:pl1": "locked", f"rapl:{MSR}:pl2": "locked"})
        self.assertFalse(self.m.applied()["platform_profile"]["supported"])

    def test_firmware_resets_on_resume_and_plug(self):
        self.m = Machine("reset-on-resume")   # MSR 45/115, MMIO 64/115
        self.hook("kristall-quiet")
        self.assertEqual(self.m.limits(MSR), (20.0, 45.0))
        self.assertEqual(self.m.limits(MMIO), (20.0, 45.0))   # min(64, 20, 28.8)
        # resume: firmware writes its defaults back into both interfaces
        fixtures.write_uw(self.m.root, MSR, 0, 45 * W)
        fixtures.write_uw(self.m.root, MSR, 1, 115 * W)
        fixtures.write_uw(self.m.root, MMIO, 0, 64 * W)
        self.m.run("reapply", "--settle")
        self.assertEqual(self.m.limits(MSR), (20.0, 45.0))
        self.assertEqual(self.m.limits(MMIO), (20.0, 45.0))
        drift = [e for e in self.m.events() if e["ev"] == "drift"]
        self.assertGreaterEqual(len(drift), 3)
        # unplug: EC programs a new, lower sustained limit into MMIO -> that is its new opinion
        fixtures.set_power(self.m.root, True)
        fixtures.write_uw(self.m.root, MMIO, 0, 35 * W)
        self.hook("kristall-quiet-battery")
        self.assertEqual(self.m.limits(MMIO)[0], 12.25)    # 0.35 x 35 W, above the 12 W floor
        self.hook("kristall-performance-battery")
        self.assertEqual(self.m.limits(MMIO), (35.0, 115.0))   # firmware's current values, not 64
        self.assertEqual(self.m.limits(MSR), (45.0, 115.0))

    def test_hardware_rounding_is_not_drift(self):
        self.m = Machine("thin-oled")
        self.m.set_fault("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw", {"readback": 20_125_000})
        self.hook("kristall-quiet")
        self.assertEqual(self.m.uw(MSR, 0), 20_125_000)
        self.m.set_fault("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw", None)
        self.m.run("reapply")
        self.assertFalse([e for e in self.m.events() if e["ev"] == "drift"])
        self.hook("kristall-performance")
        self.assertEqual(self.m.limits(MSR), (45.0, 115.0))

    def test_write_error_is_reported_not_fatal(self):
        self.m = Machine("thin-oled")
        self.m.set_fault("/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw", {"errno": 5})
        self.assertEqual(self.hook("kristall-quiet").returncode, 0)
        st = {r["lever"]: r for r in self.m.applied()["rapl"]}
        self.assertEqual(st[f"rapl:{MMIO}:pl2"]["status"], "failed")
        self.assertEqual(st[f"rapl:{MSR}:pl2"]["status"], "applied")

    def test_desktop_and_unknown_profiles(self):
        self.m = Machine("desktop")
        self.hook("kristall-balanced")
        self.assertEqual(self.m.limits(MSR), (45.0, 90.0))
        fixtures.set_active_profile(self.m.root, "balanced")  # a stock tuned profile: we do nothing
        self.m.run("tuned-hook", "start", "balanced", check=False)
        self.m.run("reapply")
        self.m.run("revert")
        self.assertEqual(self.m.limits(MSR), (65.0, 150.0))

    def test_live_session_changes_nothing(self):
        self.m = Machine("thin-oled")
        self.m.write("/proc/cmdline", "BOOT_IMAGE=x rd.live.image quiet")
        self.hook("kristall-quiet")
        self.assertEqual(self.m.limits(MSR), (45.0, 115.0))

    def test_boot_records_baseline_and_revert(self):
        self.m = Machine("thin-oled")
        self.m.run("boot")
        self.hook("kristall-quiet")
        self.m.run("revert")
        self.assertEqual(self.m.limits(MSR), (45.0, 115.0))
        self.assertTrue(any(e["ev"] == "boot" for e in self.m.events()))
        # while kristall-power.service is stopped, tuned switches and plug events change nothing
        self.hook("kristall-quiet-battery")
        self.m.run("reapply", "--settle")
        self.assertEqual(self.m.limits(MSR), (45.0, 115.0))
        self.m.run("boot")                      # service started again
        self.hook("kristall-quiet-battery")
        self.assertEqual(self.m.limits(MSR), (15.0, 35.0))


class ChargeLimit(unittest.TestCase):
    def tearDown(self):
        self.m.cleanup()

    BAT = "/sys/class/power_supply/BAT0/"

    def test_thresholds(self):
        self.m = Machine("thin-oled")
        self.m.run("charge-limit", "80")
        self.assertEqual((self.m.read(self.BAT + "charge_control_end_threshold"), self.m.read(self.BAT + "charge_control_start_threshold")), ("80", "75"))
        self.m.run("charge-limit", "90")
        self.assertEqual((self.m.read(self.BAT + "charge_control_end_threshold"), self.m.read(self.BAT + "charge_control_start_threshold")), ("90", "85"))
        self.m.run("charge-limit", "100")
        self.assertEqual((self.m.read(self.BAT + "charge_control_end_threshold"), self.m.read(self.BAT + "charge_control_start_threshold")), ("100", "95"))
        self.assertEqual(self.m.read("/var/lib/kristall/power/charge-limit"), "100")

    def test_out_of_range_rejected(self):
        self.m = Machine("thin-oled")
        for bad in ("30", "101", "abc", "80.5", "-80", "0x50", " "):
            p = self.m.run("charge-limit", bad, check=False)
            self.assertEqual(p.returncode, 2, bad)
            self.assertEqual(self.m.read(self.BAT + "charge_control_end_threshold"), "100", bad)

    def test_order_keeps_start_below_end(self):
        self.m = Machine("thin-oled")
        # a driver that refuses start >= end: make the end write fail if done first
        self.m.run("charge-limit", "60")
        self.assertEqual(self.m.read(self.BAT + "charge_control_start_threshold"), "55")

    def test_unsupported_and_desktop(self):
        self.m = Machine("lcd60-nopp")
        p = self.m.run("charge-limit", "80", "--json")
        self.assertEqual(json.loads(p.stdout)[0]["status"], "unsupported")
        self.m.cleanup()
        self.m = Machine("desktop")
        p = self.m.run("charge-limit", "80", "--json")
        self.assertEqual(json.loads(p.stdout)[0]["status"], "not-applicable")

    def test_long_life(self):
        self.m = Machine("longlife")
        self.m.run("charge-limit", "80")
        self.assertEqual(self.m.read(self.BAT + "charge_types"), "Long_Life")
        self.m.run("charge-limit", "100")
        self.assertEqual(self.m.read(self.BAT + "charge_types"), "Standard")

    def test_driver_error(self):
        self.m = Machine("thin-oled")
        self.m.set_fault(self.BAT + "charge_control_end_threshold", {"errno": 22})
        p = self.m.run("charge-limit", "80", "--json", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)[0]["status"], "failed")

    def test_boot_reapplies_stored_limit_and_revert_keeps_it(self):
        self.m = Machine("thin-oled")
        self.m.run("charge-limit", "80")
        self.m.write(self.BAT + "charge_control_end_threshold", 100)   # firmware forgot at power-off
        self.m.write(self.BAT + "charge_control_start_threshold", 95)
        self.m.run("boot")
        self.assertEqual(self.m.read(self.BAT + "charge_control_end_threshold"), "80")
        self.m.run("revert")
        self.assertEqual(self.m.read(self.BAT + "charge_control_end_threshold"), "80", "service stop keeps the owner's limit")
        self.m.run("revert", "--charge")
        self.assertEqual(self.m.read(self.BAT + "charge_control_end_threshold"), "100")


class StatusDoctor(unittest.TestCase):
    def test_status_all_personalities(self):
        for pers in fixtures.PERSONALITIES:
            m = Machine(pers, on_battery=pers != "desktop", percent=37)
            try:
                st = json.loads(m.run("status", "--json").stdout)
                self.assertEqual(st["schema"], 1)
                self.assertIn(st["mode"], ("quiet", "balanced", "performance"))
                if pers == "desktop":
                    self.assertEqual(st["power_source"], "none")
                    self.assertIsNone(st["battery"])
                else:
                    self.assertEqual(st["power_source"], "battery")
                    self.assertEqual(st["battery"]["percent"], 37, "mouse battery must be ignored")
                    self.assertEqual(st["battery"]["health_percent"], 92.1)
                    self.assertEqual(st["draw"], {"watts": 7.4, "source": "battery"})
                    self.assertGreater(st["battery"]["time_to_empty_s"], 0)
                self.assertEqual(st["temperatures"]["cpu_package"], 52.0)
                txt = m.run("status").stdout
                self.assertIn("Modus:", txt)
            finally:
                m.cleanup()

    def test_doctor_all_personalities(self):
        valid = {"applied", "unsupported", "locked", "failed", "not-applicable", "skipped", "unknown", "warning", "reverted"}
        for pers in fixtures.PERSONALITIES:
            m = Machine(pers)
            try:
                fixtures.set_active_profile(m.root, "kristall-quiet")
                m.run("tuned-hook", "start", "kristall-quiet")
                p = m.run("doctor", "--local", "--json", "--idle-seconds", "0.2")
                rep = json.loads(p.stdout)
                self.assertNotIn("SECRET-SERIAL", p.stdout)
                levers = {lv["lever"]: lv for lv in rep["levers"]}
                for lv in rep["levers"]:
                    self.assertIn(lv["status"], valid, lv)
                for name in ("epp", "platform-profile", "charge-limit", "deep-idle", "usb-autosuspend", "pci-runtime-pm",
                             "refresh-rate", "glass-quality", "automatic-mode", "zram", "nmi-watchdog-off"):
                    self.assertIn(name, levers, f"{pers}: {name}")
                if pers == "locked":
                    self.assertEqual(levers[f"rapl:{MSR}:pl1"]["status"], "locked")
                if pers == "desktop":
                    self.assertEqual(levers["charge-limit"]["status"], "not-applicable")
                    self.assertEqual(levers["background-on-e-cores"]["status"], "not-applicable")
                if pers == "lcd60-nopp":
                    self.assertEqual(levers["platform-profile"]["status"], "unsupported")
                    self.assertEqual(levers["charge-limit"]["status"], "unsupported")
                if pers == "thin-oled":
                    self.assertEqual(levers[f"rapl:{MMIO}:pl1"]["status"], "applied")
                    # EPP is tuned's job; the fixture still holds the old value -> reported as failed
                    self.assertEqual(levers["epp"]["status"], "failed")
                    self.assertEqual(levers["usb-autosuspend"]["status"], "failed")   # webcam still 'on'
                    self.assertEqual(rep["graphics"]["cards"][0]["connectors"][0]["edid"]["timings"][0]["refresh_hz"], 60.0)
                with open(os.path.join(m.home, ".local/state/kristall/power/doctor.txt")) as fh:
                    txt = fh.read()
                self.assertIn("Kristall Energie-Diagnose", txt)
                self.assertIn("Kristall power diagnosis", txt)
                self.assertEqual(oct(os.stat(os.path.join(m.home, ".local/state/kristall/power/doctor.json")).st_mode & 0o777), "0o600")
            finally:
                m.cleanup()


class Helpers(unittest.TestCase):
    def test_ecore_generator(self):
        for pers, want in (("thin-oled", "AllowedCPUs=12-19"), ("desktop", None)):
            m = Machine(pers)
            out = os.path.join(m.root, "gen")
            os.makedirs(out)
            subprocess.run([os.path.join(POWER, "systemd/system-generators/kristall-power-ecores"), out, out, out],
                           env=dict(os.environ, KRISTALL_POWER_SYSFS=os.path.join(m.root, "sys")), check=True)
            f = os.path.join(out, "kristall-background.slice.d/50-kristall-ecores.conf")
            if want:
                with open(f) as fh:
                    self.assertIn(want, fh.read())
            else:
                self.assertFalse(os.path.exists(f))
            m.cleanup()

    def test_ecore_generator_rejects_garbage(self):
        m = Machine("thin-oled")
        m.write("/sys/devices/cpu_atom/cpus", "12-19; rm -rf /")
        out = os.path.join(m.root, "gen")
        os.makedirs(out)
        subprocess.run([os.path.join(POWER, "systemd/system-generators/kristall-power-ecores"), out],
                       env=dict(os.environ, KRISTALL_POWER_SYSFS=os.path.join(m.root, "sys")), check=True)
        self.assertFalse(os.path.exists(os.path.join(out, "kristall-background.slice.d")))
        m.cleanup()

    def test_usb_autosuspend_helper(self):
        m = Machine("thin-oled")
        helper = os.path.join(POWER, "libexec/usb-autosuspend")
        dev = os.path.join(m.root, "sys/bus/usb/devices")
        subprocess.run([helper, os.path.join(dev, "3-6")], check=True)          # webcam
        self.assertEqual(m.read("/sys/bus/usb/devices/3-6/power/control"), "auto")
        subprocess.run([helper, os.path.join(dev, "3-1")], check=True)          # HID: untouched
        self.assertEqual(m.read("/sys/bus/usb/devices/3-1/power/control"), "on")
        subprocess.run([helper, os.path.join(dev, "missing")], check=True)      # never fails
        m.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
