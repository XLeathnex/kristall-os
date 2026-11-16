# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for /usr/bin/kristall-update with mocked bootc/flatpak/NetworkManager/systemd."""
import json
import os
import subprocess
import sys
import unittest

from mocks import Sandbox, bootc_status

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "bin", "kristall-update")


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.s = Sandbox()
        self.s.put("bootc-status.json", bootc_status())
        self.s.battery(80, on_ac=False)

    def tearDown(self):
        self.s.cleanup()

    def run_tool(self, *args, root=False, env=None):
        e = dict(self.s.env, KRISTALL_UPDATE_FORCE_ROOT="1" if root else "0")
        e.update(env or {})
        return subprocess.run([sys.executable, TOOL] + list(args), env=e, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)

    def status(self, root=False):
        p = self.run_tool("status", "--json", root=root)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def new_remote(self):
        self.s.put("remote.json", {"version": "45.20261115.2", "digest": "sha256:bbb"})

    # ------------------------------------------------------------------ status

    def test_status_up_to_date_as_root_and_snapshot_for_users(self):
        st = self.status(root=True)
        self.assertEqual(st["state"], "up-to-date")
        self.assertEqual(st["booted"]["version"], "45.20261101.1")
        self.assertTrue(st["can_rollback"])
        # A normal user cannot run bootc: they read the snapshot root wrote.
        self.assertEqual(self.status(root=False)["booted"]["digest"], "sha256:aaa")

    def test_status_unknown_without_snapshot(self):
        st = self.status(root=False)
        self.assertEqual(st["state"], "unknown")
        self.assertFalse(st["bootc"])

    def test_human_status_german(self):
        self.status(root=True)
        p = self.run_tool("status", env={"LANG": "de_DE.UTF-8"})
        self.assertIn("auf dem neuesten Stand", p.stdout)

    # ------------------------------------------------------------------ check / apply

    def test_check_via_polkit_unit_reports_available(self):
        self.new_remote()
        self.s.put("flatpak-updates", "org.kde.elisa\norg.blender.Blender\n")
        p = self.run_tool("check", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        st = json.loads(p.stdout)
        self.assertEqual(st["state"], "update-available")
        self.assertEqual(st["available"]["version"], "45.20261115.2")
        self.assertEqual(st["flatpak"]["updates_pending"], 2)
        self.assertIn(["systemctl", "start", "kristall-update-check.service"], self.s.calls("systemctl"))
        self.assertIsNotNone(st["last_check"])

    def test_apply_stages_and_requires_restart(self):
        self.new_remote()
        p = self.run_tool("apply", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        st = json.loads(p.stdout)
        self.assertEqual(st["state"], "restart-required")
        self.assertEqual(st["staged"]["version"], "45.20261115.2")
        self.assertIsNone(st["available"])
        self.assertIn(["flatpak", "update", "--system", "-y", "--noninteractive"], self.s.calls("flatpak"))
        # Never reboots on its own.
        self.assertNotIn(["systemctl", "reboot"], self.s.calls("systemctl"))

    def test_apply_restart_asks_plasma_first(self):
        self.new_remote()
        p = self.run_tool("apply", "--restart")
        self.assertEqual(p.returncode, 0, p.stderr)
        gd = self.s.calls("gdbus")
        self.assertTrue(gd and "org.kde.Shutdown.logoutAndReboot" in gd[-1])

    def test_check_failure_is_reported_bilingually(self):
        self.s.put("fail-upgrade", "")
        p = self.run_tool("check", "--json")
        self.assertNotEqual(p.returncode, 0)
        st = json.loads(p.stdout)
        self.assertEqual(st["state"], "error")
        self.assertEqual(st["last_error"]["code"], "download-failed")
        self.assertTrue(st["last_error"]["de"] and st["last_error"]["en"])
        self.assertIn("connection refused", st["last_error"]["detail"])

    def test_permission_denied_is_an_error_exit(self):
        self.s.put("deny-kristall-update-apply.service", "")
        p = self.run_tool("apply", "--json")
        self.assertEqual(p.returncode, 1)

    # ------------------------------------------------------------------ automatic updates

    def test_auto_updates_when_conditions_allow(self):
        self.new_remote()
        p = self.run_tool("auto", root=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.status()["state"], "restart-required")

    def test_auto_waits_on_metered(self):
        self.new_remote()
        self.s.put("nm-Metered", "1")
        self.run_tool("auto", root=True)
        st = self.status()
        self.assertEqual(st["waiting_reason"], "metered")
        self.assertEqual(self.s.calls("flatpak"), [])
        self.assertFalse(any(c[:2] == ["bootc", "upgrade"] for c in self.s.calls("bootc")))

    def test_auto_waits_on_low_battery_but_not_on_ac(self):
        self.new_remote()
        self.s.battery(20, on_ac=False)
        self.run_tool("auto", root=True)
        self.assertEqual(self.status()["waiting_reason"], "battery-low")
        self.s.battery(20, on_ac=True)
        self.run_tool("auto", root=True)
        self.assertEqual(self.status()["state"], "restart-required")

    def test_auto_offline_and_disabled(self):
        self.s.put("nm-Connectivity", "1")
        self.run_tool("auto", root=True)
        self.assertEqual(self.status()["waiting_reason"], "offline")
        os.makedirs(os.path.dirname(self.s.env["KRISTALL_UPDATE_CONFIG"]), exist_ok=True)
        with open(self.s.env["KRISTALL_UPDATE_CONFIG"], "w") as f:
            json.dump({"automatic": False}, f)
        self.run_tool("auto", root=True)
        st = self.status()
        self.assertEqual(st["waiting_reason"], "auto-disabled")
        self.assertFalse(st["automatic"])

    def test_auto_refuses_without_root(self):
        self.assertEqual(self.run_tool("auto").returncode, 2)

    # ------------------------------------------------------------------ rollback

    def test_rollback_and_cancel(self):
        p = self.run_tool("rollback", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        st = json.loads(p.stdout)
        self.assertEqual(st["state"], "rollback-queued")
        self.assertFalse(st["can_rollback"])
        # asking again does not flip it back
        self.run_tool("rollback")
        self.assertEqual(self.status()["state"], "rollback-queued")
        p = self.run_tool("rollback", "--cancel", "--json")
        self.assertEqual(json.loads(p.stdout)["state"], "up-to-date")

    def test_rollback_without_previous_version(self):
        self.s.put("bootc-status.json", bootc_status(rollback=False))
        p = self.run_tool("rollback", "--json")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)["last_error"]["code"], "no-rollback")

    # ------------------------------------------------------------------ notification

    def test_notify_once_per_login_and_restart_action(self):
        self.new_remote()
        self.run_tool("auto", root=True)
        self.s.put("notify-action", "restart\n")
        self.run_tool("notify")
        sent = self.s.calls("notify-send")
        self.assertEqual(len(sent), 1)
        self.assertIn("Update ready", sent[0])
        self.assertTrue(any("logoutAndReboot" in " ".join(c) for c in self.s.calls("gdbus")))
        self.run_tool("notify")
        self.assertEqual(len(self.s.calls("notify-send")), 1)

    def test_notify_silent_when_nothing_pending(self):
        self.status(root=True)
        self.run_tool("notify")
        self.assertEqual(self.s.calls("notify-send"), [])

    def test_usage_errors(self):
        self.assertEqual(self.run_tool("status", "--bogus").returncode, 2)
        self.assertEqual(self.run_tool("frobnicate").returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
