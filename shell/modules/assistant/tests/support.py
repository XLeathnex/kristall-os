# SPDX-License-Identifier: GPL-3.0-or-later
"""Test session for the assistant UI: shell-core's ShellSession (headless KWin with the glass effect,
mock bridge, settings) plus the real assistant daemon in demo mode on the session's socket, an event
recorder on that socket, the owner's real input (org_kde_kwin_fake_input) and helpers."""
import json
import os
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.dirname(HERE)
SHELL = os.path.dirname(os.path.dirname(MODULE))
REPO = os.path.dirname(SHELL)
sys.path.insert(0, os.path.join(SHELL, "tests", "support"))
import shellsession as ss  # noqa: E402
from shellsession import wait_until  # noqa: E402,F401

EVIDENCE = os.path.join(HERE, "evidence")
BRIDGE_BUILD = os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp/kristall-bridge-build")
OWNER = os.path.join(BRIDGE_BUILD, "bin", "owner")
CORE = os.path.join(REPO, "assistant", "core")

# evdev key codes for the owner's keyboard
KEY = {"esc": 1, "tab": 15, "return": 28, "space": 57, "left": 105, "right": 106, "up": 103, "down": 108,
       "leftshift": 42, "leftctrl": 29, "backspace": 14}
for i, ch in enumerate("qwertyuiop"):
    KEY[ch] = 16 + i
for i, ch in enumerate("asdfghjkl"):
    KEY[ch] = 30 + i
for i, ch in enumerate("zxcvbnm"):
    KEY[ch] = 44 + i


class Recorder:
    """A second client on assistant.sock that records every event with its receive time (ms)."""

    def __init__(self, path):
        self.path = path
        self.events = []
        self.lock = threading.Lock()
        self.stop_flag = False
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        while not self.stop_flag:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self.path)
                s.sendall(b'{"type":"hello","client":"ui-test-recorder","role":"control"}\n')
                buf = b""
                s.settimeout(0.5)
                while not self.stop_flag:
                    try:
                        d = s.recv(65536)
                    except socket.timeout:
                        continue
                    if not d:
                        break
                    buf += d
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            ev = json.loads(line)
                        except ValueError:
                            continue
                        ev["_recv"] = time.time() * 1000.0
                        with self.lock:
                            self.events.append(ev)
                s.close()
            except OSError:
                time.sleep(0.2)

    def of(self, typ):
        with self.lock:
            return [e for e in self.events if e.get("type") == typ]

    def mark(self):
        with self.lock:
            return len(self.events)

    def since(self, m):
        with self.lock:
            return list(self.events[m:])

    def wait(self, pred, timeout=10, since=0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                for e in self.events[since:]:
                    if pred(e):
                        return e
            time.sleep(0.03)
        return None

    def close(self):
        self.stop_flag = True


class Owner:
    """The owner's real keyboard and pointer through KWin's fake-input protocol."""

    def __init__(self, env):
        self.p = subprocess.Popen([OWNER], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        if self.p.stdout.readline().strip() != "ready":
            raise RuntimeError("owner: fake input not available")

    def cmd(self, c):
        self.p.stdin.write(c + "\n")
        self.p.stdin.flush()
        self.p.stdout.readline()

    def move(self, x, y):
        self.cmd(f"move {x} {y}")

    def click(self, x, y, button=272):
        self.move(x, y)
        time.sleep(0.05)
        self.cmd(f"button {button} 1")
        time.sleep(0.04)
        self.cmd(f"button {button} 0")

    def key(self, name, mods=()):
        for m in mods:
            self.cmd(f"key {KEY[m]} 1")
        self.cmd(f"key {KEY[name]} 1")
        time.sleep(0.02)
        self.cmd(f"key {KEY[name]} 0")
        for m in reversed(mods):
            self.cmd(f"key {KEY[m]} 0")
        time.sleep(0.03)

    def type(self, text):
        for ch in text:
            if ch == " ":
                self.key("space")
            elif ch.isupper():
                self.key(ch.lower(), mods=("leftshift",))
            else:
                self.key(ch)

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(3)
        except Exception:
            self.p.kill()


class AssistantSession(ss.ShellSession):
    def __init__(self, gl=True, lang="de_DE", ui_settings=None, global_shortcuts=False, **kw):
        super().__init__(lang=lang, **kw)
        self.global_shortcuts = global_shortcuts
        self.sysconf = None
        if global_shortcuts:
            # the image's system-wide shortcut file, found through XDG_DATA_DIRS like /usr/share
            self.sysconf = os.path.join(self.tmp, "sysconf")
            os.makedirs(os.path.join(self.sysconf, "usr", "share", "kglobalaccel"))
            import shutil
            shutil.copy(os.path.join(MODULE, "kglobalaccel", "org.kristall.assistant.desktop"),
                        os.path.join(self.sysconf, "usr", "share", "kglobalaccel"))
            # the image's KRunner hand-over (image/install.sh merges it into /etc/xdg/kglobalshortcutsrc):
            # KRunner keeps Alt+F2 and Search, Alt+Space is free for the assistant
            os.makedirs(os.path.join(self.sysconf, "etc", "xdg"))
            for d in (os.path.join(self.sysconf, "etc", "xdg"), self.config):
                # (also in the user's file: kglobalacceld in the headless KWin did not pick up the
                # XDG_CONFIG_DIRS copy here; the image's /etc/xdg path stays unverified)
                with open(os.path.join(d, "kglobalshortcutsrc"), "w") as f:
                    f.write("[services][org.kde.krunner.desktop]\n_launch=Alt+F2\\tSearch\n")
        self.gl = gl
        self.ui_settings = ui_settings
        self.daemon = None
        self.recorder = None
        self.owner = None
        self.sock_path = os.path.join(self.runtime, "kristall", "assistant.sock")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home, exist_ok=True)

    def env(self):
        e = super().env()
        if getattr(self, "global_shortcuts", False):
            e["XDG_DATA_DIRS"] = os.path.join(self.sysconf, "usr", "share") + ":/usr/local/share:/usr/share"
            e["XDG_CONFIG_DIRS"] = os.path.join(self.sysconf, "etc", "xdg") + ":/etc/xdg"
            # kristall-shellctl (the shortcut's Exec, run by KWin) must reach the shell under test
            e["PATH"] = os.path.join(SHELL, "bin") + ":" + e.get("PATH", "/usr/bin")
            e["KRISTALL_SHELL_DIR"] = os.path.join(self.tmp, "shellroot")
            if os.environ.get("KRISTALL_DEBUG_ACCEL"):
                e["QT_LOGGING_RULES"] = "kf.globalaccel*=true"
        return e

    def start(self, wait_glass=True):
        if not self.global_shortcuts:
            return super().start(wait_glass=wait_glass)
        # the harness starts KWin with --no-global-shortcuts: drop that flag for shortcut tests
        orig = ss.harness.KWIN
        wrapper = os.path.join(self.tmp, "kwin-with-shortcuts")
        with open(wrapper, "w") as f:
            f.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = --no-global-shortcuts ] || set -- "$@" "$a"; shift; done\nexec %s "$@"\n' % orig)
        os.chmod(wrapper, 0o755)
        ss.harness.KWIN = wrapper
        try:
            return super().start(wait_glass=wait_glass)
        finally:
            ss.harness.KWIN = orig

    # ---- daemon -------------------------------------------------------------------------------
    def daemon_env(self, speed=1.0):
        e = self.env()
        e.update({"PYTHONPATH": CORE, "PYTHONDONTWRITEBYTECODE": "1", "HOME": self.home,
                  "KRISTALL_DEMO_SPEED": str(speed), "KRISTALL_ASSISTANT_SOCKET": self.sock_path,
                  "XDG_DATA_HOME": os.path.join(self.tmp, "data"), "XDG_STATE_HOME": os.path.join(self.tmp, "state")})
        e.update(self.shell_env())
        return e

    def start_daemon(self, speed=1.0, auto=False, wait=True):
        args = [sys.executable, "-m", "kristall_assistant.daemon", "--demo"]
        if auto:
            args.append("--demo-auto")
        self.daemon_log = open(os.path.join(self.tmp, "daemon.log"), "a")
        self.daemon = subprocess.Popen(args, env=self.daemon_env(speed), stdout=self.daemon_log, stderr=subprocess.STDOUT)
        if wait:
            if not wait_until(lambda: os.path.exists(self.sock_path), 10):
                raise RuntimeError("daemon socket did not appear")
        if self.recorder is None:
            self.recorder = Recorder(self.sock_path)
        return self.daemon

    def stop_daemon(self, kill=False):
        if self.daemon and self.daemon.poll() is None:
            if kill:
                self.daemon.kill()
            else:
                self.daemon.terminate()
            self.daemon.wait(5)
        self.daemon = None

    def actl(self, *args, speed=1.0):
        r = subprocess.run([sys.executable, "-m", "kristall_assistant.ctl"] + [str(a) for a in args], env=self.daemon_env(speed),
                           capture_output=True, text=True, timeout=15)
        return r.stdout

    def send(self, obj):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.sock_path)
        s.sendall(b'{"type":"hello","client":"ui-test","role":"tool"}\n' + (json.dumps(obj) + "\n").encode())
        time.sleep(0.05)
        s.close()

    # ---- shell ---------------------------------------------------------------------------------
    def make_shell_root(self, modules=("assistant",)):
        """A private shell root: shell-core as it is, but only the given modules (other components'
        modules are being built concurrently and are not this suite's subject)."""
        root = os.path.join(self.tmp, "shellroot")
        if os.path.exists(root):
            return root
        os.makedirs(os.path.join(root, "modules"))
        for name in os.listdir(SHELL):
            if name in ("modules", "modules.list", "tests"):
                continue
            os.symlink(os.path.join(SHELL, name), os.path.join(root, name))
        for m in modules:
            os.symlink(os.path.join(SHELL, "modules", m), os.path.join(root, "modules", m))
        with open(os.path.join(root, "modules.list"), "w") as f:
            f.write("\n".join(modules) + "\n")
        return root

    def start_assistant_shell(self, bridge=True, extra_env=None, modules=("assistant",)):
        dropins = os.path.join(self.tmp, "settings.d")
        os.makedirs(dropins, exist_ok=True)
        with open(os.path.join(MODULE, "image", "settings.json")) as f:
            ui = json.load(f)
        if self.ui_settings:
            ui["assistant"]["ui"].update(self.ui_settings)
        with open(os.path.join(dropins, "60-assistant-ui.json"), "w") as f:
            json.dump(ui, f)
        env = {"KRISTALL_ASSISTANT_SOCKET": self.sock_path}
        if self.gl:
            env["QT_QUICK_BACKEND"] = ""
        env.update(extra_env or {})
        p = self.start_shell(extra_env=env, bridge=bridge, path=self.make_shell_root(modules))
        self.wait_ready()
        return p

    def ast(self):
        return json.loads(self.ipc("assistant-test", "state"))

    def rects(self, output=""):
        return json.loads(self.ipc("assistant-test", "rects", output))

    def request(self, action, arg=""):
        return self.ipc("assistant-test", "request", action, arg)

    def wait_ast(self, pred, timeout=10.0):
        last = [None]

        def f():
            try:
                st = self.ast()
            except Exception:
                return None
            last[0] = st
            return st if pred(st) else None
        return wait_until(f, timeout, 0.1) or last[0]

    def start_owner(self):
        if self.owner is None:
            self.owner = Owner(self.env())
        return self.owner

    def stop(self, keep=False):
        if self.shell is not None and self.shell.poll() is not None:
            print(f"INFO shell process exited with {self.shell.returncode}; log tail:", flush=True)
            print("\n".join(self.shell_log().splitlines()[-40:]), flush=True)
            for root, _d, files in os.walk(os.path.join(self.runtime, "quickshell")):
                for f in files:
                    if "crash" in root or "crash" in f:
                        print("INFO crash file", os.path.join(root, f), flush=True)
                        try:
                            print(open(os.path.join(root, f), errors="replace").read()[-3000:], flush=True)
                        except OSError:
                            pass
        if self.recorder:
            self.recorder.close()
        if self.owner:
            self.owner.close()
        self.stop_daemon()
        super().stop(keep=keep)


def shot(sess, name, crop=None, quality=None):
    from PIL import Image
    img = None
    for _ in range(4):        # KWin's ScreenShot2 occasionally hands back an all-black frame: retry
        try:
            img = sess.screenshot("Virtual-0")
        except Exception:
            img = sess.screenshot()
        if img is not None and img[..., :3].max() > 8:
            break
        time.sleep(0.4)
    os.makedirs(EVIDENCE, exist_ok=True)
    im = Image.fromarray(img)
    if crop:
        im = im.crop(crop)
    path = os.path.join(EVIDENCE, name)
    if name.endswith(".jpg"):
        if im.size[0] * im.size[1] > 2500000:   # full 2880×1800 frames: half size is enough to judge
            im = im.resize((im.size[0] // 2, im.size[1] // 2), Image.LANCZOS)
        im.convert("RGB").save(path, quality=min(quality or 84, 72 if im.size[0] * im.size[1] > 1000000 else 84), optimize=True)
    else:
        im.save(path, optimize=True)
        if os.path.getsize(path) > 50000:        # keep the evidence small (folder < 4 MB): large crops as JPEG
            os.unlink(path)
            im.convert("RGB").save(path[:-4] + ".jpg", quality=88, optimize=True)
    return img


def grab(sess):
    """a screenshot as an array, without saving it"""
    img = shot(sess, "_grab.png")
    for ext in (".png", ".jpg"):
        try:
            os.unlink(os.path.join(EVIDENCE, "_grab" + ext))
        except OSError:
            pass
    return img


def sheet(images, cols, cell, path, quality=76):
    """a contact sheet of screenshots (each scaled to `cell`), saved as JPEG"""
    from PIL import Image
    cw, ch = cell
    rows = (len(images) + cols - 1) // cols
    out = Image.new("RGB", (cols * cw + (cols - 1) * 6, rows * ch + (rows - 1) * 6), (255, 255, 255))
    for i, img in enumerate(images):
        im = Image.fromarray(img[..., :3]) if not isinstance(img, Image.Image) else img.convert("RGB")
        out.paste(im.resize((cw, ch), Image.LANCZOS), ((i % cols) * (cw + 6), (i // cols) * (ch + 6)))
    out.save(os.path.join(EVIDENCE, path), quality=quality, optimize=True)


def wallpaper(w, h, kind="aurora"):
    """Our own generated wallpapers (no third-party art): 'aurora' — soft colour fields with fine
    detail; 'busy' — the glass suite's high-contrast stress pattern."""
    import numpy as np
    if kind == "white":
        # a white document page (a web page / text editor full screen): black lines of "text"
        img = np.full((h, w, 3), 255, np.uint8)
        rng = np.random.default_rng(7)
        y = 70
        while y < h - 40:
            x = int(w * 0.18)
            end = int(w * 0.82) - int(rng.integers(0, w // 5))
            img[y:y + 9, x:end] = (40, 40, 44)
            y += 26 if rng.random() > 0.15 else 52
        img[:48, :] = (246, 246, 248)
        img[47:48, :] = (210, 210, 214)
        return img
    if kind == "photo":
        # a busy, colourful photo-like image: many saturated soft shapes, hard-edged objects and grain
        rng = np.random.default_rng(11)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        img = np.zeros((h, w, 3), np.float32)
        img[:] = (0.12, 0.22, 0.38)
        for _ in range(70):
            cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.03, 0.22) * w
            col = rng.uniform(0, 1, 3) ** 1.6
            a = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (r * r)) * 1.6)[..., None]
            img = img * (1 - a * 0.9) + col * a * 0.9
        for _ in range(40):
            x0, y0 = int(rng.uniform(0, w)), int(rng.uniform(0, h))
            ww, hh = int(rng.uniform(8, 160)), int(rng.uniform(8, 120))
            img[y0:y0 + hh, x0:x0 + ww] = rng.uniform(0, 1, 3)
        img += rng.normal(0, 0.012, (h, w, 1))
        return (np.clip(img, 0, 1) * 255).astype(np.uint8)
    if kind == "busy":
        sys.path.insert(0, os.path.join(REPO, "kwin", "glass", "tests", "support"))
        import pattern
        return pattern.busy(w, h)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / w, yy / h
    img = np.zeros((h, w, 3), np.float32)
    img[:] = (0.05, 0.08, 0.16)
    blobs = [(0.15, 0.25, 0.35, (0.10, 0.45, 0.65)), (0.75, 0.2, 0.30, (0.55, 0.25, 0.65)),
             (0.55, 0.75, 0.40, (0.95, 0.45, 0.30)), (0.9, 0.85, 0.25, (0.95, 0.75, 0.35)),
             (0.35, 0.6, 0.22, (0.20, 0.70, 0.55))]
    for cx, cy, r, col in blobs:
        d = ((u - cx) ** 2 + ((v - cy) * h / w) ** 2) / (r * r)
        a = np.exp(-d * 2.2)[..., None]
        img = img * (1 - a * 0.85) + np.array(col, np.float32) * a * 0.85
    # ridges (mountain-like silhouettes) for detail
    for k, (base, amp, col) in enumerate([(0.72, 0.06, (0.08, 0.10, 0.22)), (0.82, 0.05, (0.04, 0.05, 0.12))]):
        ridge = base + amp * np.sin(u * (7 + 5 * k) + k) * np.cos(u * (13 + 3 * k)) + 0.015 * np.sin(u * 90)
        m = (v > ridge)[..., None]
        img = np.where(m, np.array(col, np.float32), img)
    # stars / fine detail
    rng = np.random.default_rng(3)
    n = int(w * h / 900)
    ys, xs = rng.integers(0, int(h * 0.7), n), rng.integers(0, w, n)
    img[ys, xs] = np.clip(img[ys, xs] + rng.uniform(0.2, 0.7, (n, 1)), 0, 1)
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def set_background(sess, w, h, kind="aurora"):
    from PIL import Image
    bg = os.path.join(sess.tmp, f"bg-{kind}.png")
    Image.fromarray(wallpaper(w, h, kind)).save(bg)
    return sess.background(bg)
