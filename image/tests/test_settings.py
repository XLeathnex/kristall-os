# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for /usr/bin/kristall-settings (image/rootfs/usr/bin/kristall-settings)."""
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "bin", "kristall-settings")


class Env:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.defaults = os.path.join(root, "share", "settings.json")
        self.dropin = os.path.join(root, "share", "settings.d")
        self.etc = os.path.join(root, "etc", "settings.d")
        self.config = os.path.join(root, "config")
        os.makedirs(self.dropin)
        os.makedirs(self.config)
        self.env = dict(os.environ)
        self.env.update({
            "KRISTALL_SETTINGS_DEFAULTS": self.defaults,
            "KRISTALL_SETTINGS_DROPIN_DIRS": self.dropin + ":" + self.etc,
            "XDG_CONFIG_HOME": self.config,
        })
        self.env.pop("KRISTALL_SETTINGS_FILE", None)

    @property
    def user_file(self):
        return os.path.join(self.config, "kristall", "settings.json")

    def write(self, path, doc):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))

    def run(self, *args, check=True):
        p = subprocess.run([sys.executable, TOOL] + list(args), env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        if check and p.returncode != 0:
            raise AssertionError("exit %d: %s" % (p.returncode, p.stderr))
        return p

    def get(self, *args):
        return json.loads(self.run("get", *args).stdout)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.e.write(self.e.defaults, {"appearance": {"theme": "auto", "glass": 0.3,
                                                      "accent": "#0a84ff"}})
        self.e.write(os.path.join(self.e.dropin, "20-dock.json"), {"dock": {"size": 48, "magnify": True}})
        self.e.write(os.path.join(self.e.dropin, "10-power.json"), {"power": {"mode": "auto"},
                                                                    "appearance": {"glass": 0.5}})

    def tearDown(self):
        self.e.tmp.cleanup()

    def test_merge_order_dropins_sorted_then_user(self):
        self.assertEqual(self.e.get("appearance.glass"), 0.5)  # 10-power overrides settings.json
        self.e.write(self.e.user_file, {"appearance": {"glass": 0.9}})
        self.assertEqual(self.e.get("appearance.glass"), 0.9)
        # key by key: untouched siblings keep their defaults
        self.assertEqual(self.e.get("appearance.theme"), "auto")
        self.assertEqual(self.e.get("dock"), {"size": 48, "magnify": True})

    def test_etc_dropins_come_after_usr(self):
        self.e.write(os.path.join(self.e.etc, "50-admin.json"), {"dock": {"size": 64}})
        self.assertEqual(self.e.get("dock.size"), 64)

    def test_get_whole_document_and_layers(self):
        self.e.run("set", "dock.size", "40")
        doc = self.e.get()
        self.assertEqual(doc["dock"]["size"], 40)
        self.assertEqual(self.e.get("--user"), {"dock": {"size": 40}})
        self.assertEqual(self.e.get("--defaults", "dock.size"), 48)

    def test_missing_path_exit_1(self):
        p = self.e.run("get", "nope.nothing", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, "")

    def test_set_types_and_atomic_file(self):
        self.e.run("set", "appearance.theme", '"dark"')
        self.e.run("set", "appearance.accent", "--string", check=False)  # usage error below
        self.e.run("set", "--string", "assistant.name", "Kristall")
        self.e.run("set", "bar.items", '["clock","wifi"]')
        self.assertEqual(self.e.get("appearance.theme"), "dark")
        self.assertEqual(self.e.get("assistant.name"), "Kristall")
        self.assertEqual(self.e.get("bar.items.1"), "wifi")
        with open(self.e.user_file) as f:
            json.load(f)
        self.assertEqual(oct(os.stat(self.e.user_file).st_mode & 0o777), "0o600")
        leftovers = [n for n in os.listdir(os.path.dirname(self.e.user_file)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_set_rejects_non_json(self):
        p = self.e.run("set", "appearance.theme", "dark", check=False)
        self.assertEqual(p.returncode, 3)
        self.assertIn("--string", p.stderr)

    def test_invalid_path(self):
        p = self.e.run("get", "a..b", check=False)
        self.assertEqual(p.returncode, 2)
        p = self.e.run("set", "a.b c", "1", check=False)
        self.assertEqual(p.returncode, 2)

    def test_unset_restores_default_and_prunes(self):
        self.e.run("set", "dock.size", "40")
        self.e.run("unset", "dock.size")
        self.assertEqual(self.e.get("dock.size"), 48)
        self.assertEqual(self.e.get("--user"), {})

    def test_corrupt_user_file_is_survivable(self):
        self.e.write(self.e.user_file, "{not json")
        p = self.e.run("get", "appearance.theme")
        self.assertEqual(json.loads(p.stdout), "auto")
        self.assertIn("invalid JSON", p.stderr)
        self.e.run("set", "appearance.theme", '"light"')
        self.assertEqual(self.e.get("appearance.theme"), "light")
        broken = [n for n in os.listdir(os.path.dirname(self.e.user_file)) if ".broken-" in n]
        self.assertEqual(len(broken), 1)

    def test_corrupt_dropin_is_ignored_but_check_defaults_fails(self):
        self.e.write(os.path.join(self.e.dropin, "30-bad.json"), "[1,2")
        self.assertEqual(self.e.get("dock.size"), 48)
        p = self.e.run("check-defaults", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("ERROR", p.stdout)

    def test_check_defaults_ownership(self):
        """settings.md "Ownership": a drop-in NN-<component>.json sets only keys its component owns;
        a shared top-level key (assistant) is owned at the second level."""
        os.remove(os.path.join(self.e.dropin, "10-power.json"))   # its appearance key is not power's
        self.e.write(os.path.join(self.e.dropin, "50-assistant-core.json"), {"assistant": {"name": "Kristall", "voice": {}}})
        self.e.write(os.path.join(self.e.dropin, "50-assistant-hands.json"), {"assistant": {"hands": {"cursor": {}}}})
        self.e.write(os.path.join(self.e.dropin, "60-assistant-ui.json"), {"assistant": {"ui": {"holdMs": 350}}})
        self.e.write(os.path.join(self.e.dropin, "50-power.json"), {"power": {"automatic": True}})
        self.e.write(os.path.join(self.e.etc, "10-admin.json"), {"power": {"automatic": False}, "anything": 1})
        p = self.e.run("check-defaults", check=False)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("WARN", p.stdout.replace("20-dock", ""), p.stdout)   # 20-dock: dock owns dock
        # a component setting another component's key fails the check (and the image build)
        self.e.write(os.path.join(self.e.dropin, "70-assistant-hands.json"), {"assistant": {"name": "X"}})
        p = self.e.run("check-defaults", check=False)
        self.assertEqual(p.returncode, 3)
        self.assertIn("'assistant.name' is owned by 'assistant-core', not by 'assistant-hands'", p.stdout)
        os.remove(os.path.join(self.e.dropin, "70-assistant-hands.json"))
        self.e.write(os.path.join(self.e.dropin, "50-power.json"), {"power": {}, "appearance": {"glass": 1}})
        p = self.e.run("check-defaults", check=False)
        self.assertEqual(p.returncode, 3)
        self.assertIn("'appearance' is owned by 'shell', not by 'power'", p.stdout)
        # a shared key must be an object; an undeclared key only warns
        self.e.write(os.path.join(self.e.dropin, "50-power.json"), {"power": {}})
        self.e.write(os.path.join(self.e.dropin, "50-assistant-core.json"), {"assistant": "nope"})
        p = self.e.run("check-defaults", check=False)
        self.assertEqual(p.returncode, 3)
        self.e.write(os.path.join(self.e.dropin, "50-assistant-core.json"), {"assistant": {}})
        self.e.write(os.path.join(self.e.dropin, "50-newthing.json"), {"newthing": {}})
        p = self.e.run("check-defaults", check=False)
        self.assertEqual(p.returncode, 0)
        self.assertIn("'newthing' has no declared owner", p.stdout)

    def test_owners_table_matches_the_contract(self):
        """Every row of the ownership table in docs/contracts/settings.md is what the checker enforces."""
        import re
        owners = json.loads(self.e.run("owners").stdout)
        doc = open(os.path.join(HERE, "..", "..", "docs", "contracts", "settings.md"), encoding="utf-8").read()
        section = doc.split("### Ownership", 1)[1].split("\n## ", 1)[0]
        rows = re.findall(r"^\| `([a-z]+)(?:\.([a-z*]+))?` \| `([a-z-]+)` \|", section, re.M)
        self.assertTrue(rows)
        flat = {}
        for top, val in owners.items():
            if isinstance(val, dict):
                for k, o in val.items():
                    flat[(top, k)] = o
            else:
                flat[(top, "")] = val
        self.assertEqual({(t, k): o for t, k, o in rows}, flat)

    def test_concurrent_writers_lose_nothing(self):
        n = 12
        procs = [subprocess.Popen([sys.executable, TOOL, "set", "dock.k%d" % i, str(i)], env=self.e.env)
                 for i in range(n)]
        for p in procs:
            self.assertEqual(p.wait(timeout=30), 0)
        user = self.e.get("--user")
        self.assertEqual(sorted(user["dock"].keys()), sorted("k%d" % i for i in range(n)))

    def test_startup_is_fast(self):
        t = time.monotonic()
        for _ in range(5):
            self.e.run("get", "appearance.theme")
        per_call = (time.monotonic() - t) / 5
        self.assertLess(per_call, 0.5, "kristall-settings get took %.3fs" % per_call)


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.e.write(self.e.defaults, {"appearance": {"theme": "auto", "glass": 0.3}})
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.terminate()
            p.wait(timeout=5)
            p.stdout.close()
            p.stderr.close()
        self.e.tmp.cleanup()

    def watch(self, *args):
        p = subprocess.Popen([sys.executable, TOOL, "watch"] + list(args), env=self.e.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        time.sleep(0.4)  # let it arm inotify
        return p

    def read_lines(self, p, n, timeout=5.0):
        lines, end = [], time.monotonic() + timeout
        while len(lines) < n and time.monotonic() < end:
            r, _, _ = select.select([p.stdout], [], [], end - time.monotonic())
            if r:
                line = p.stdout.readline()
                if not line:
                    break
                lines.append(json.loads(line))
        return lines

    def assert_quiet(self, p, wait=0.6):
        r, _, _ = select.select([p.stdout], [], [], wait)
        self.assertFalse(r, "watch printed something although nothing changed")

    def test_emits_one_line_per_change(self):
        p = self.watch()
        self.e.run("set", "appearance.theme", '"dark"')
        self.assertEqual(self.read_lines(p, 1), [{"path": "appearance.theme", "value": "dark"}])
        self.e.run("set", "appearance.theme", '"dark"')  # same value: no file write, no event
        self.assert_quiet(p)
        self.e.run("unset", "appearance.theme")
        self.assertEqual(self.read_lines(p, 1), [{"path": "appearance.theme", "value": "auto"}])

    def test_filter_and_removed(self):
        p = self.watch("dock")
        self.e.run("set", "appearance.glass", "0.8")
        self.e.run("set", "dock.size", "50")
        self.assertEqual(self.read_lines(p, 1), [{"path": "dock.size", "value": 50}])
        self.e.run("unset", "dock")
        self.assertEqual(self.read_lines(p, 1), [{"path": "dock.size", "value": None, "removed": True}])

    def test_initial_and_full(self):
        p = self.watch("--full", "--initial")
        first = self.read_lines(p, 1)[0]
        self.assertEqual(first["settings"]["appearance"]["theme"], "auto")
        self.e.run("set", "appearance.theme", '"light"')
        second = self.read_lines(p, 1)[0]
        self.assertEqual(second["settings"]["appearance"]["theme"], "light")

    def test_user_dir_created_later_and_dropin_change(self):
        # The watcher creates ~/.config/kristall itself; a new drop-in default is picked up live.
        p = self.watch("power")
        self.e.write(os.path.join(self.e.dropin, "40-power.json"), {"power": {"mode": "quiet"}})
        self.assertEqual(self.read_lines(p, 1), [{"path": "power.mode", "value": "quiet"}])

    def test_external_editor_style_rename(self):
        p = self.watch()
        tmp = self.e.user_file + ".swp"
        self.e.write(tmp, {"appearance": {"glass": 1.0}})
        os.replace(tmp, self.e.user_file)
        self.assertEqual(self.read_lines(p, 1), [{"path": "appearance.glass", "value": 1.0}])

    def test_no_cpu_while_idle(self):
        p = self.watch()
        try:
            with open("/proc/%d/stat" % p.pid) as f:
                before = f.read().split()
            time.sleep(1.5)
            with open("/proc/%d/stat" % p.pid) as f:
                after = f.read().split()
        except FileNotFoundError:
            self.skipTest("no /proc")
        ticks = (int(after[13]) + int(after[14])) - (int(before[13]) + int(before[14]))
        self.assertLessEqual(ticks, 1, "watch used CPU while nothing changed (polling?)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
