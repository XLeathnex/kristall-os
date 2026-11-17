#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Kristall's pages in KDE System Settings — the real `systemsettings` with our modules, in the
headless session with the shell around it. Every page is opened, operated with the owner's
pointer where it matters, and checked against the real setting / the (mocked) command it must run;
outside changes must show on the open page. Sections: pages actions looks."""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import setupsession as S  # noqa: E402
from PIL import Image  # noqa: E402

EVIDENCE = os.path.join(HERE, "evidence")
ROOT = os.path.join(S.BUILD, "settings-root")
failures, results = [], {}
check, info = S.A.check_factory(failures, results)
wait_until = S.wait_until
PAGES = os.environ.get("KRISTALL_PAGES", "about,update,assistant,appearance,dock,notifications,energy,keyboard").split(",")


class SettingsSession(S.SetupSession):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.update_calls = os.path.join(self.update_dir, "calls.log")
        self.perm_file = os.path.join(self.config, "kristall", "assistant", "permissions.json")

    def app_env(self):
        e = super().app_env()
        e.update(self.shell_env())
        qt = os.path.join(ROOT, "usr", "lib64", "qt6")
        e["QT_PLUGIN_PATH"] = os.path.join(qt, "plugins") + ":" + e.get("QT_PLUGIN_PATH", "")
        e["QML_IMPORT_PATH"] = os.path.join(qt, "qml")
        e["XDG_DATA_DIRS"] = os.path.join(ROOT, "usr", "share") + ":" + e.get("XDG_DATA_DIRS", "/usr/share")
        e["QT_QPA_PLATFORM"] = "wayland"
        e["KRISTALL_SHELLCTL"] = os.path.join(S.REPO, "shell", "bin", "kristall-shellctl")
        e["KRISTALL_SHELL_DIR"] = os.path.join(S.REPO, "shell")
        e["LANG"] = "de_DE.UTF-8" if self.lang.startswith("de") else "en_US.UTF-8"
        e["LANGUAGE"] = self.lang.split("_")[0]
        e["KRISTALL_LANG"] = self.lang
        e["QT_LOGGING_RULES"] = "qt.qml.typeresolution.cycle=false;kf.kirigami.platform=false"
        e["KRISTALL_SETTINGS_TEST_DIR"] = self.testdir
        return e

    @property
    def testdir(self):
        return os.path.join(self.tmp, "settings-test")

    def q(self, name, timeout=5.0):
        """where the control is (global logical px) and what it shows"""
        os.makedirs(self.testdir, exist_ok=True)
        ans = os.path.join(self.testdir, "answer.json")
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if os.path.exists(ans):
                os.remove(ans)
            with open(os.path.join(self.testdir, "query.tmp"), "w") as f:
                f.write(name)
            os.replace(os.path.join(self.testdir, "query.tmp"), os.path.join(self.testdir, "query"))
            if wait_until(lambda: os.path.exists(ans), 1.5, 0.05):
                try:
                    a = json.load(open(ans))
                except ValueError:
                    continue
                if "x" in a:
                    w = next((w for w in self.windows() if w["normal"] and "systemsettings" in w["appId"]), None)
                    c = w["content"] if w else {"x": 0, "y": 0}
                    a["gx"], a["gy"] = c["x"] + a["x"], c["y"] + a["y"]
                    return a
            time.sleep(0.2)
        return None

    def press(self, name):
        a = self.q(name)
        if not a:
            raise RuntimeError(f"no control {name} on the page")
        win = next((w for w in self.windows() if w["normal"] and "systemsettings" in w["appId"]), None)
        bottom = win["content"]["y"] + win["content"]["h"] - 20 if win else 10000
        for _ in range(12):           # below the visible part of the page: scroll it into view with the wheel
            if a["gy"] + a["h"] < bottom:
                break
            self.move(win["content"]["x"] + win["content"]["w"] * 0.65, win["content"]["y"] + win["content"]["h"] / 2)
            self.owner_proc._cmd("axis 0 60")
            for _ in range(10):       # the page scrolls smoothly: wait until it stops
                time.sleep(0.25)
                b = self.q(name) or a
                if b["gy"] == a["gy"]:
                    break
                a = b
        self.click(a["gx"] + a["w"] / 2, a["gy"] + a["h"] / 2)
        time.sleep(0.5)
        return self.q(name) or a

    def kset(self, path, value):
        env = self.env()
        env.update(self.shell_env())
        subprocess.run([os.path.join(S.REPO, "image", "rootfs", "usr", "bin", "kristall-settings"), "set", path, json.dumps(value)], env=env, timeout=10)

    def open_page(self, page):
        log = open(os.path.join(self.tmp, f"systemsettings-{page}.log"), "w")
        p = subprocess.Popen(["systemsettings", f"kcm_kristall_{page}"], env=self.app_env(), stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(p)
        w = wait_until(lambda: next((w for w in self.windows() if w["normal"] and "systemsettings" in w["appId"]), None), 20, 0.3)
        if w:
            self.bridge_client().call("window.setGeometry", id=w["id"], x=120, y=50, w=1040, h=700)
        time.sleep(2.5)
        return p, w

    def close_settings(self, p):
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
        if p in self.procs:
            self.procs.remove(p)
        time.sleep(0.5)

    def page_log(self, page):
        try:
            return open(os.path.join(self.tmp, f"systemsettings-{page}.log"), errors="replace").read()
        except OSError:
            return ""


def shot(s, name, w):
    img = Image.fromarray(s.screenshot())
    if w:
        img = img.crop((100, 30, 1180, 770))
    os.makedirs(EVIDENCE, exist_ok=True)
    img.convert("RGB").save(os.path.join(EVIDENCE, name), quality=78, optimize=True)


def qml_errors(log):
    return [l for l in log.splitlines() if ("main.qml:" in l or "kristall" in l or "kcms/" in l or "qrc:/kcm" in l) and ("Error" in l or "error" in l or "TypeError" in l or "ReferenceError" in l or "Unable to assign" in l or "is not a type" in l)]


def sysconf():
    """/etc/xdg as the image has it: our restrictions (developer pages hidden) merged into kdeglobals"""
    import tempfile
    root = tempfile.mkdtemp(prefix="kristall-settings-sysconf-")
    os.makedirs(os.path.join(root, "etc", "xdg"))
    os.makedirs(os.path.join(root, "usr", "share"))
    subprocess.run([sys.executable, os.path.join(S.REPO, "shell", "image", "merge-ini"), os.path.join(root, "etc", "xdg", "kdeglobals"),
                    os.path.join(S.SETUP, "data", "xdg", "kdeglobals")], check=True)
    return root


def session(name, lang="de_DE", theme="light", **kw):
    s = SettingsSession(name=name, lang=lang, settings={"appearance": {"theme": theme, "glass": 0.3}, "setup": {"done": True}}, sysconf=sysconf(), **kw)
    s.start()
    from test_setup import calm_wallpaper
    bg = os.path.join(s.tmp, "bg.png")
    Image.fromarray(calm_wallpaper(s.width, s.height, theme == "dark")).save(bg)
    s.background(bg)
    s.start_shell()
    s.wait_st(lambda st: st.get("liveChecked"), 15)
    return s


def test_looks():
    for theme in ("light", "dark"):
        print(f"== every page, {theme}, German", flush=True)
        s = session(f"settings-looks-{theme}", theme=theme)
        try:
            if theme == "light":
                # "System Settings …" from the menu bar: one window, our pages first, developer pages hidden
                log = open(os.path.join(s.tmp, "systemsettings-start.log"), "w")
                p = subprocess.Popen(["systemsettings"], env=s.app_env(), stdout=log, stderr=subprocess.STDOUT)
                s.procs.append(p)
                w = wait_until(lambda: next((w for w in s.windows() if w["normal"] and "systemsettings" in w["appId"]), None), 20, 0.3)
                check("System Settings starts without a module (the menu bar's 'System Settings …')", bool(w))
                if w:
                    s.bridge_client().call("window.setGeometry", id=w["id"], x=120, y=30, w=1040, h=760)
                time.sleep(3)
                img = Image.fromarray(s.screenshot()).crop((100, 10, 1180, 800))
                img.convert("RGB").save(os.path.join(EVIDENCE, "settings-start-light-de.jpg"), quality=78)
                s.close_settings(p)
            for page in PAGES:
                p, w = s.open_page(page)
                check(f"{theme}: System Settings opens our page {page}", bool(w))
                shot(s, f"settings-{page}-{theme}-de.jpg", w)
                errs = qml_errors(s.page_log(page))
                check(f"{theme}: page {page} loads without QML errors", not errs, "\n".join(errs[:6]))
                s.close_settings(p)
        finally:
            s.stop()


def test_actions():
    print("== every page changes the real setting / runs the right command, and follows outside changes", flush=True)
    s = session("settings-actions", account="success", account_start="signed_out")
    try:
        p, w = s.open_page("appearance")
        s.press("appearance.theme.dark")
        check("Appearance: click Dark → appearance.theme = dark", wait_until(lambda: s.setting("appearance.theme") == "dark", 4))
        s.press("appearance.accent.green")
        check("Appearance: click green → appearance.accent = green", wait_until(lambda: s.setting("appearance.accent") == "green", 4))
        s.press("appearance.reduceTransparency")
        check("Appearance: Reduce transparency → appearance.reduceTransparency = true", wait_until(lambda: s.setting("appearance.reduceTransparency") is True, 4))
        s.kset("appearance.theme", "light")
        s.kset("appearance.glass", 0.9)
        ok = wait_until(lambda: (s.q("appearance.theme.light") or {}).get("checked") is True, 5)
        check("Appearance: an outside change (theme light) shows on the open page", bool(ok))
        ok = wait_until(lambda: abs((s.q("appearance.glass") or {}).get("value", 0) - 0.9) < 0.01, 5)
        check("Appearance: outside glass 0.9 moves the slider", bool(ok))
        s.close_settings(p)

        p, w = s.open_page("dock")
        s.press("dock.autoHide")
        check("Dock: auto-hide → dock.autoHide = true", wait_until(lambda: s.setting("dock.autoHide") is True, 4))
        s.press("bar.showBatteryPercentage")
        check("Menu bar: battery percentage → bar.showBatteryPercentage = true", wait_until(lambda: s.setting("bar.showBatteryPercentage") is True, 4))
        s.kset("dock.size", 64)
        check("Dock: outside size 64 shows on the slider", bool(wait_until(lambda: (s.q("dock.size") or {}).get("value") == 64, 5)))
        s.close_settings(p)

        p, w = s.open_page("notifications")
        s.press("notifications.dnd")
        check("Notifications: Do Not Disturb → panels.focus.until = -1", wait_until(lambda: s.setting("panels.focus.until") == -1, 4))
        s.kset("panels.focus.until", 0)
        check("Notifications: switched off elsewhere → the switch follows", bool(wait_until(lambda: (s.q("notifications.dnd") or {}).get("checked") is False, 5)))
        s.close_settings(p)

        p, w = s.open_page("keyboard")
        s.press("keyboard.mac")
        check("Keyboard: switch off → keyboard.macShortcuts = false, commandKey = ''",
              wait_until(lambda: s.setting("keyboard.macShortcuts") is False and s.setting("keyboard.commandKey") == "", 4))
        ok = wait_until(lambda: (lambda k: k and k.get("reason") == "off")(s.st().get("keyboard")), 5)
        check("Keyboard: the plugin follows live (status off)", bool(ok))
        s.kset("keyboard.macShortcuts", True)
        check("Keyboard: switched on elsewhere → the switch follows", bool(wait_until(lambda: (s.q("keyboard.mac") or {}).get("checked") is True, 5)))
        s.close_settings(p)

        with open(os.path.join(s.runtime, "kristall", "power.json"), "w") as f:
            json.dump({"schema": 1, "automatic": True, "manual": None, "reason": "auto-battery", "hold": "power-saver",
                       "mode": "power-saver", "on_battery": True, "percent": 76}, f)
        p, w = s.open_page("energy")
        ok = wait_until(lambda: "leise im Akkubetrieb" in ((s.q("energy.modeNote") or {}).get("text") or ""), 6)
        check("Energy: hold reason auto-battery reads 'Automatisch · leise im Akkubetrieb'", bool(ok), str(s.q("energy.modeNote")))
        s.press("energy.batteryBase")
        s.tap("down")
        s.tap("enter")
        check("Energy: On battery → Ausgewogen writes power.batteryBase = balanced", wait_until(lambda: s.setting("power.batteryBase") == "balanced", 4), str(s.setting("power.batteryBase")))
        s.kset("power.batteryBase", "quiet")
        check("Energy: battery base changed elsewhere → the choice follows", bool(wait_until(lambda: (s.q("energy.batteryBase") or {}).get("currentIndex") == 0, 5)))
        s.press("energy.limit")
        check("Energy: Protect battery → power.chargeLimit = 80", wait_until(lambda: s.setting("power.chargeLimit") == 80, 4))
        s.press("energy.check")
        ok = wait_until(lambda: "21" in ((s.q("energy.summary") or {}).get("text") or ""), 10)
        check("Energy: Check Now runs kristall-power doctor and shows the summary", bool(ok), str(s.q("energy.summary")))
        time.sleep(0.5)
        from test_setup import shot as _shot  # noqa: F401
        img = Image.fromarray(s.screenshot()).crop((100, 30, 1180, 770))
        img.convert("RGB").save(os.path.join(EVIDENCE, "settings-energy-report-light-de.jpg"), quality=78)
        s.press("energy.save")
        desk = os.path.join(s.home, "Desktop")
        files = wait_until(lambda: [f for f in os.listdir(desk) if f.startswith("Kristall-Bericht-")] if os.path.isdir(desk) else None, 5)
        check("Energy: Save Report → one click, a file on the desktop", bool(files), str(files))
        if files:
            d = json.load(open(os.path.join(desk, files[0])))
            check("Energy: the saved report is a valid doctor report (JSON, kind kristall-power-doctor)", d.get("kind") == "kristall-power-doctor" and d.get("schema") == 1)
        calls = open(os.path.join(s.tmp, "power-calls.log")).read()
        check("Energy: kristall-power doctor --json --out … was called", "doctor --json --out" in calls, calls[-200:])
        s.close_settings(p)

        st = {"schema": 1, "state": "restart-required", "bootc": True, "booted": {"version": "45.20261115.3"}, "staged": {"version": "45.20261116.1"},
              "rollback": {"version": "45.20261114.2"}, "can_rollback": True, "rollback_queued": False, "last_check": "2026-11-16T09:12:03Z"}
        with open(os.path.join(s.update_dir, "status.json"), "w") as f:
            json.dump(st, f)
        p, w = s.open_page("update")
        ok = wait_until(lambda: "Neustart" in ((s.q("update.headline") or {}).get("text") or ""), 6)
        check("Update: 'Update bereit – Neustart zum Abschließen.'", bool(ok), str(s.q("update.headline")))
        img = Image.fromarray(s.screenshot()).crop((100, 30, 1180, 770))
        img.convert("RGB").save(os.path.join(EVIDENCE, "settings-update-restart-light-de.jpg"), quality=78)
        s.press("update.restart")
        check("Update: Restart Now → kristall-update restart", wait_until(lambda: "restart" in open(s.update_calls).read() if os.path.exists(s.update_calls) else False, 4))
        s.press("update.rollback")
        s.press("update.rollbackConfirm")
        check("Update: Return to previous version (confirmed) → kristall-update rollback --json",
              wait_until(lambda: "rollback --json" in open(s.update_calls).read(), 4), open(s.update_calls).read())
        st.update(state="rollback-queued", rollback_queued=True)
        with open(os.path.join(s.update_dir, "status.json.tmp"), "w") as f:
            json.dump(st, f)
        os.replace(os.path.join(s.update_dir, "status.json.tmp"), os.path.join(s.update_dir, "status.json"))
        ok = wait_until(lambda: "vorherige Version" in ((s.q("update.headline") or {}).get("text") or ""), 6)
        check("Update: a queued rollback (outside change) shows at once", bool(ok), str(s.q("update.headline")))
        s.press("update.rollbackCancel")
        check("Update: Don't return after all → kristall-update rollback --cancel --json",
              wait_until(lambda: "rollback --cancel --json" in open(s.update_calls).read(), 4))
        s.close_settings(p)

        os.makedirs(os.path.dirname(s.perm_file), exist_ok=True)
        with open(s.perm_file, "w") as f:
            json.dump({"version": 1, "always": {"files.delete": {"since": 1, "label": None}, "shell.run:git": {"since": 2}}}, f)
        p, w = s.open_page("assistant")
        ok = wait_until(lambda: (s.q("assistant.account") or {}).get("text") == "Nicht angemeldet", 6)
        check("Assistant: shows 'Nicht angemeldet' from the account command", bool(ok), str(s.q("assistant.account")))
        img = Image.fromarray(s.screenshot()).crop((100, 30, 1180, 770))
        img.convert("RGB").save(os.path.join(EVIDENCE, "settings-assistant-grants-light-de.jpg"), quality=78)
        s.press("assistant.revoke.files.delete")
        d = json.load(open(s.perm_file))
        check("Assistant: 'Ask again' removes the always-allow grant (permissions.json rewritten)", "files.delete" not in d["always"] and "shell.run:git" in d["always"], json.dumps(d))
        check("Assistant: the file stays private (mode 0600)", (os.stat(s.perm_file).st_mode & 0o777) == 0o600, oct(os.stat(s.perm_file).st_mode))
        s.press("assistant.enabled")
        check("Assistant: master switch off → assistant.enabled = false", wait_until(lambda: s.setting("assistant.enabled") is False, 4))
        check("Assistant: accessibility choice is behind 'Erweitert'", s.q("assistant.accessibility", 1.5) is None)
        s.press("assistant.advanced")
        a = s.q("assistant.accessibility")
        check("Assistant: 'Erweitert' shows the accessibility interface choice (default: always on)", bool(a) and a.get("currentIndex") == 0, str(a))
        s.kset("assistant.hands.accessibility", "on_demand")
        check("Assistant: changed elsewhere → 'Nur wenn nötig' shows", bool(wait_until(lambda: (s.q("assistant.accessibility") or {}).get("currentIndex") == 1, 5)))
        img = Image.fromarray(s.screenshot()).crop((100, 30, 1180, 770))
        img.convert("RGB").save(os.path.join(EVIDENCE, "settings-assistant-advanced-light-de.jpg"), quality=78)
        s.press("assistant.enabled")
        s.kset("assistant.name", "Luna")
        check("Assistant: renamed elsewhere → the name field follows", bool(wait_until(lambda: (s.q("assistant.name") or {}).get("text") == "Luna", 5)))
        s.press("assistant.signin")
        st2 = s.wait_st(lambda st: st["open"] and st["mode"] == "signin", 8)
        check("Assistant: Sign in opens the Setup Assistant's sign-in sheet (one implementation)", bool(st2 and st2["mode"] == "signin"), json.dumps(st2)[:200] if st2 else "")
        s.close_settings(p)

        p, w = s.open_page("about")
        ok = wait_until(lambda: len((s.q("about.processor") or {}).get("text") or "") > 3, 6)
        check("About: processor, memory, graphics, storage filled in", bool(ok) and "GB" in (s.q("about.memory") or {}).get("text", ""))
        s.close_settings(p)
    finally:
        s.stop()


SECTIONS = {"looks": test_looks, "actions": test_actions}

if __name__ == "__main__":
    want = sys.argv[1:] or list(SECTIONS)
    for name in want:
        try:
            SECTIONS[name]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
