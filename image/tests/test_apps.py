# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for /usr/bin/kristall-apps and the app manifest image/apps/apps.json."""
import copy
import json
import os
import subprocess
import sys
import unittest

from mocks import Sandbox

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "bin", "kristall-apps")
MANIFEST = os.path.join(HERE, "..", "apps", "apps.json")
FLATPAK_ID_FILE = os.path.join(HERE, "..", "apps", "verified-flatpak-ids.txt")


def load_manifest():
    with open(MANIFEST) as f:
        return json.load(f)


class ManifestTest(unittest.TestCase):
    def validate(self, doc):
        sys.path.insert(0, os.path.dirname(TOOL))
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("kristall_apps", TOOL)
        spec = importlib.util.spec_from_loader("kristall_apps", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod.validate(doc)

    def test_shipped_manifest_is_valid(self):
        self.assertEqual(self.validate(load_manifest()), [])

    def test_owner_requirements_present(self):
        apps = {a["id"]: a for a in load_manifest()["apps"]}
        for required in ("blender", "roblox", "roblox-studio", "steam", "code", "browser", "files",
                         "text-editor", "images", "documents", "video", "music", "calculator",
                         "screenshot", "system-monitor", "archives", "app-center"):
            self.assertIn(required, apps)
        self.assertEqual(apps["app-center"]["flatpak"]["id"], "io.github.kolunmi.Bazaar")

    def test_proprietary_never_embedded(self):
        for a in load_manifest()["apps"]:
            if a.get("proprietary"):
                self.assertFalse(a.get("embed_in_iso", False), a["id"])

    def test_flatpak_ids_were_verified_on_flathub(self):
        # verified-flatpak-ids.txt records the result of image/tests/verify-flathub.sh
        with open(FLATPAK_ID_FILE) as f:
            verified = {l.split()[0] for l in f if l.strip() and not l.startswith("#")}
        for a in load_manifest()["apps"]:
            if a["kind"] == "flatpak":
                self.assertIn(a["flatpak"]["id"], verified, "not verified on Flathub")

    def test_kde_apps_name_their_window_title_suffix(self):
        # Qt appends the app's display name to every window title ("Home — Dolphin"): the KDE apps
        # we rename must say which name to replace (apps.md, product_names)
        for a in load_manifest()["apps"]:
            if a["desktop_id"].startswith("org.kde.") or a["desktop_id"] == "systemsettings.desktop":
                self.assertTrue(a.get("product_names"), a["id"])

    def test_validator_catches_mistakes(self):
        base = load_manifest()
        cases = {
            "duplicate id": lambda d: d["apps"].append(copy.deepcopy(d["apps"][0])),
            "dock gap": lambda d: d["apps"][0].__setitem__("dock", 99),
            "missing german": lambda d: d["apps"][0]["name"].pop("de"),
            "bad category": lambda d: d["apps"][0].__setitem__("category", "fun"),
            "embed proprietary": lambda d: [a.__setitem__("embed_in_iso", True)
                                            for a in d["apps"] if a.get("proprietary")],
            "hidden but docked": lambda d: d["apps"][0].__setitem__("show_in_apps", False),
            "product_names not a list": lambda d: d["apps"][0].__setitem__("product_names", "Dolphin"),
            "empty product name": lambda d: d["apps"][0].__setitem__("product_names", [""]),
        }
        for name, mutate in cases.items():
            doc = copy.deepcopy(base)
            mutate(doc)
            self.assertNotEqual(self.validate(doc), [], name)


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        self.s = Sandbox()
        self.env = dict(self.s.env, KRISTALL_APPS_MANIFEST=MANIFEST, KRISTALL_APPS_FORCE_ROOT="1")
        self.flatpaks = [a["flatpak"]["id"] for a in load_manifest()["apps"]
                         if a["kind"] == "flatpak" and a["default"]]

    def tearDown(self):
        self.s.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL] + list(args), env=self.env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)

    def status(self):
        p = self.run_tool("status", "--json")
        return json.loads(p.stdout)

    def installs(self):
        return [c[-1] for c in self.s.calls("flatpak") if c[1] == "install"]

    def test_fresh_install_in_manifest_order_with_progress(self):
        self.assertEqual(self.status()["state"], "not-started")
        p = self.run_tool("provision")
        self.assertEqual(p.returncode, 0, p.stderr)
        st = self.status()
        self.assertEqual(st["state"], "done")
        self.assertEqual((st["done"], st["total"]), (len(self.flatpaks), len(self.flatpaks)))
        # the apps in manifest order, then the runtimes/extensions of apps.json "runtimes"
        themes = ["runtime/org.gtk.Gtk3theme.adw-gtk3/x86_64/3.22", "runtime/org.gtk.Gtk3theme.adw-gtk3-dark/x86_64/3.22"]
        self.assertEqual(self.installs(), self.flatpaks + themes)
        over = [c for c in self.s.calls("flatpak") if c[1] == "override"]
        self.assertIn(["flatpak", "override", "--system", "--filesystem=host-etc:ro",
                       "io.github.kolunmi.Bazaar"], over)

    def test_embedded_apps_are_not_downloaded_again(self):
        self.s.put("flatpak-installed", "org.kde.elisa\norg.blender.Blender\n")
        self.run_tool("provision")
        self.assertNotIn("org.blender.Blender", self.installs())
        self.assertEqual(self.status()["state"], "done")

    def test_offline_then_resume(self):
        self.s.put("flatpak-installed", "org.kde.elisa\n")
        self.s.put("nm-Connectivity", "1")
        p = self.run_tool("provision")
        self.assertEqual(p.returncode, 0)
        st = self.status()
        self.assertEqual(st["state"], "waiting-for-network")
        self.assertEqual(st["done"], 1)
        self.assertEqual(self.installs(), [])
        self.s.put("nm-Connectivity", "4")
        self.run_tool("provision")
        self.assertEqual(self.status()["state"], "done")
        self.assertNotIn("org.kde.elisa", self.installs())

    def test_failure_is_retried_and_removed_apps_stay_removed(self):
        self.s.put("flatpak-fail", "com.valvesoftware.Steam\n")
        self.run_tool("provision")
        st = self.status()
        self.assertEqual(st["state"], "error")
        self.assertEqual([f["id"] for f in st["failed"]], ["steam"])
        self.assertIn("Unable to load summary", st["failed"][0]["error"])
        # Owner uninstalls Blender, Flathub recovers: Steam gets installed, Blender does not return.
        installed = [l for l in open(os.path.join(self.s.mock, "flatpak-installed")).read().split()
                     if l != "org.blender.Blender"]
        self.s.put("flatpak-installed", "\n".join(installed) + "\n")
        self.s.put("flatpak-fail", "")
        before = len(self.installs())
        self.run_tool("provision")
        self.assertEqual(self.installs()[before:], ["com.valvesoftware.Steam"])
        self.assertEqual(self.status()["state"], "done")

    def test_intel_vaapi_extension_added_on_intel(self):
        card = os.path.join(self.s.env["KRISTALL_DRM_DIR"], "card1", "device")
        os.makedirs(card)
        with open(os.path.join(card, "vendor"), "w") as f:
            f.write("0x8086\n")
        self.s.put("flatpak-runtimes", "org.freedesktop.Platform/x86_64/26.08\norg.kde.Platform/x86_64/6.11\n")
        self.run_tool("provision")
        self.assertIn("runtime/org.freedesktop.Platform.VAAPI.Intel/x86_64/26.08", self.installs())

    def test_runtime_extensions_once_and_retried(self):
        """apps.json "runtimes" (the adw-gtk3 GTK 3 themes for Flatpak apps): installed once,
        a failure is retried on the next run, an owner's removal is respected."""
        self.s.put("flatpak-fail", "org.gtk.Gtk3theme.adw-gtk3-dark\n")
        self.run_tool("provision")
        self.assertEqual(self.status()["state"], "done", "a missing theme does not fail the app provisioning")
        self.s.put("flatpak-fail", "")
        before = len(self.installs())
        self.run_tool("provision")
        self.assertEqual(self.installs()[before:], ["runtime/org.gtk.Gtk3theme.adw-gtk3-dark/x86_64/3.22"])
        before = len(self.installs())
        self.run_tool("provision")
        self.assertEqual(self.installs()[before:], [], "installed once; not re-installed after a removal")

    def test_list_filters(self):
        p = self.run_tool("list", "--dock")
        dock = [a["id"] for a in json.loads(p.stdout)["apps"]]
        self.assertEqual(dock[:2], ["files", "browser"])
        p = self.run_tool("list", "--embed", "--flatpak-ids")
        embed = p.stdout.split()
        self.assertIn("org.blender.Blender", embed)
        self.assertNotIn("com.visualstudio.code", embed)
        self.assertNotIn("org.vinegarhq.Sober", embed)

    def test_human_status(self):
        self.run_tool("provision")
        p = subprocess.run([sys.executable, TOOL, "status"], env=dict(self.env, LANG="de_DE.UTF-8"),
                           text=True, stdout=subprocess.PIPE)
        self.assertIn("Alle Apps sind installiert", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
