# SPDX-License-Identifier: GPL-3.0-or-later
# Test session for the Setup Assistant: the shell-apps session (headless KWin + glass effect + the
# real bridge + the owner's hands through fake input, shell/modules/dock/tests/support) with the
# whole shell from this repository, our settings defaults, fakes for the account commands,
# kristall-power and the apps status, optionally the assistant daemon in demo mode and a private
# system bus with mock NetworkManager/UPower (offline or online).
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
SETUP = os.path.dirname(TESTS)
REPO = os.path.dirname(SETUP)
sys.path.insert(0, os.path.join(REPO, "shell", "modules", "dock", "tests", "support"))
import appsession as A  # noqa: E402

wait_until = A.wait_until
CORE = os.path.join(REPO, "assistant", "core")
BUILD = os.environ.get("KRISTALL_SETUP_BUILD", "/tmp/kristall-setup-build")


class SetupSession(A.AppsSession):
    def __init__(self, lang="de_DE", settings=None, account="success", account_start="cli_missing", offline=False,
                 daemon=False, apps_state=None, force_steps="", keyboard_plugin=True, **kw):
        base = {"appearance": {"theme": "light", "glass": 0.3}}
        if settings:
            for k, v in settings.items():
                base[k] = v
        kwinrc = "[Plugins]\nkristall_keyboardEnabled=%s\n" % ("true" if keyboard_plugin else "false")
        super().__init__(lang=lang, settings=base, kwinrc_extra=kwinrc, **kw)
        self.offline = offline
        self.want_daemon = daemon
        self.daemon = None
        self.acct_dir = os.path.join(self.tmp, "account")
        os.makedirs(self.acct_dir)
        self.account, self.account_start = account, account_start
        self.apps_status = os.path.join(self.tmp, "apps-status.json")
        if apps_state:
            self.set_apps(apps_state)
        self.force_steps = force_steps
        self.sock_path = os.path.join(self.runtime, "kristall", "assistant.sock")
        self.cmdline = os.path.join(self.tmp, "cmdline")
        with open(self.cmdline, "w") as f:
            f.write("BOOT_IMAGE=/vmlinuz root=UUID=1 rw quiet\n")
        self.live_marker = os.path.join(self.tmp, "live-marker")
        with open(os.path.join(self.config, "kxkbrc"), "w") as f:     # the owner's German keyboard
            f.write("[Layout]\nLayoutList=de\nUse=true\n")

    def env(self):
        e = super().env()
        # our keyboard plugin next to glass + bridge (QT_PLUGIN_PATH from AppsSession)
        e["QT_PLUGIN_PATH"] = e.get("QT_PLUGIN_PATH", "") + ":" + os.path.join(BUILD, "plugins")
        return e

    def set_apps(self, obj):
        with open(self.apps_status + ".tmp", "w") as f:
            json.dump(obj, f)
        os.replace(self.apps_status + ".tmp", self.apps_status)

    def shell_env(self, extra=None):
        e = super().shell_env(extra)
        e.update({
            "KRISTALL_SETUP_HELPER": os.path.join(SETUP, "bin", "kristall-setup-helper"),
            "KRISTALL_ASSISTANT_ACCOUNT": os.path.join(HERE, "fake-account"),
            "KRISTALL_FAKE_ACCOUNT": self.account, "KRISTALL_FAKE_ACCOUNT_START": self.account_start,
            "KRISTALL_FAKE_ACCOUNT_DIR": self.acct_dir,
            "KRISTALL_POWER_CMD": os.path.join(HERE, "fake-power"), "KRISTALL_FAKE_POWER_DIR": self.tmp,
            "KRISTALL_APPS_STATUS": self.apps_status,
            "KRISTALL_SETUP_LIVE_MARKER": self.live_marker, "KRISTALL_SETUP_CMDLINE": self.cmdline,
            "KRISTALL_ASSISTANT_SOCKET": self.sock_path,
            "KRISTALL_SETUP_FORCE_STEPS": self.force_steps,
        })
        e.update(extra or {})
        return e

    def start_shell(self, extra_env=None, path=None):
        dropins = os.path.join(self.tmp, "settings.d")
        os.makedirs(dropins, exist_ok=True)
        shutil.copy(os.path.join(SETUP, "data", "settings.json"), os.path.join(dropins, "50-setup.json"))
        shutil.copy(os.path.join(CORE, "data", "settings-assistant.json"), os.path.join(dropins, "50-assistant-core.json"))
        power = os.path.join(REPO, "power", "config", "50-power.json")
        if os.path.exists(power):
            shutil.copy(power, os.path.join(dropins, "50-power.json"))
        return super().start_shell(extra_env=extra_env, path=path)

    def start(self, wait_glass=True):
        super().start(wait_glass=wait_glass and self.glass)
        if self.offline is not None:
            self.start_system_nm()
        if self.want_daemon:
            self.start_daemon()
        return self

    def start_system_nm(self):
        """private system bus: mock UPower/power profiles (mocksystem) + NetworkManager, offline or online"""
        sock = os.path.join(self.tmp, "system_bus")
        self.system_address = "unix:path=" + sock
        p = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", "--address=" + self.system_address],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        wait_until(lambda: os.path.exists(sock), 5)
        m = subprocess.Popen([sys.executable, os.path.join(HERE, "mocknm.py"), self.system_address, "offline" if self.offline else "online"],
                             stdout=subprocess.PIPE, stderr=open(os.path.join(self.tmp, "mocknm.log"), "w"), text=True)
        self.procs.append(m)
        if m.stdout.readline().strip() != "ready":
            raise RuntimeError("mock system services did not start")

    def start_daemon(self):
        e = self.env()
        e.update(self.shell_env())
        e.update({"PYTHONPATH": CORE, "HOME": self.home, "KRISTALL_DEMO_SPEED": "2"})
        self.daemon = subprocess.Popen([sys.executable, "-m", "kristall_assistant.daemon", "--demo"], env=e,
                                       stdout=open(os.path.join(self.tmp, "daemon.log"), "a"), stderr=subprocess.STDOUT)
        self.procs.append(self.daemon)
        wait_until(lambda: os.path.exists(self.sock_path), 10)

    # ---- the Setup Assistant ---------------------------------------------------------------------
    def st(self):
        return json.loads(self.ipc("setuptest", "state"))

    def wait_st(self, pred, timeout=6.0):
        last = [None]

        def f():
            try:
                s = self.st()
            except Exception:  # noqa: BLE001
                return None
            last[0] = s
            return s if pred(s) else None
        return wait_until(f, timeout, 0.15) or last[0]

    def rect(self, name, timeout=4.0):
        def f():
            try:
                r = self.ipc("setuptest", "rect", name)
                return json.loads(r) if r else None
            except Exception:  # noqa: BLE001
                return None
        return wait_until(f, timeout, 0.15)

    def click_named(self, name):
        r = self.rect(name)
        for _ in range(10):          # wait for the card to stop moving (height/position animate)
            time.sleep(0.15)
            r2 = self.rect(name, 1.0)
            if r2 == r:
                break
            r = r2
        if not r:
            raise RuntimeError(f"no control named {name} on screen; state {self.st()}")
        self.click(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
        time.sleep(0.25)
        return r

    def request(self, action, arg=""):
        """through kristall-shellctl, as the unit and the assistant send it"""
        env = self.env()
        env.update(self.shell_env())
        args = [os.path.join(REPO, "shell", "bin", "kristall-shellctl"), "setup", action]
        if arg:
            args.append(arg)
        return subprocess.run(args, env=env, capture_output=True, text=True, timeout=20)

    def settings(self):
        env = self.env()
        env.update(self.shell_env())
        r = subprocess.run([os.path.join(REPO, "image", "rootfs", "usr", "bin", "kristall-settings"), "get"], env=env,
                           capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout or "{}")

    def setting(self, path, default=None):
        d = self.settings()
        for p in path.split("."):
            if not isinstance(d, dict) or p not in d:
                return default
            d = d[p]
        return d
