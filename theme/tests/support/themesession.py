# SPDX-License-Identifier: GPL-3.0-or-later
"""Theme test session: the shell's test session (headless KWin with the glass effect, the real
bridge, the Kristall shell's menu bar) plus the theme as installed by theme/image/install.sh into
a staging root, so applications see our system-wide defaults exactly as on the image:

  STAGE/etc/xdg      -> XDG_CONFIG_DIRS (first)       (kdeglobals, kwinrc, … merged by install.sh)
  STAGE/usr/share    -> XDG_DATA_DIRS (after the lock-screen overlay, before /usr/share)
  STAGE/usr/lib64/qt6/plugins -> QT_PLUGIN_PATH        (the decoration)
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
THEME = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(THEME)
sys.path.insert(0, os.path.join(REPO, "shell", "tests", "support"))
sys.path.insert(0, os.path.join(REPO, "kwin", "glass", "tests", "support"))
import shellsession as ss  # noqa: E402
import harness  # noqa: E402
from harness import wait_until  # noqa: E402,F401

STAGE = os.environ.get("KRISTALL_THEME_STAGE", "/tmp/kristall-theme-stage")
BUILD = os.environ.get("KRISTALL_THEME_BUILD", "/tmp/kristall-theme-build")
EVIDENCE = os.path.join(THEME, "tests", "evidence")
BRIDGE_PLUGINS = os.path.join(os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp/kristall-bridge-build"), "plugins")
OWNER = os.path.join(os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp/kristall-bridge-build"), "bin", "owner")


def stage_paths():
    usr = os.path.join(STAGE, "usr")
    plug = os.path.join(usr, "lib64", "qt6", "plugins")
    return {
        "etc": os.path.join(STAGE, "etc"),
        "share": os.path.join(usr, "share"),
        "lib": os.path.join(usr, "lib", "kristall", "theme"),
        "plugins": plug,
        "overlay": os.path.join(usr, "share", "kristall", "theme", "overlay"),
        "bin": os.path.join(usr, "bin"),
    }


class ThemeSession(ss.ShellSession):
    def __init__(self, scale=1.0, mode="light", accent="blue", decoration=True, overlay=True, name=None,
                 width=1280, height=800, glass=True, bridge=True, extra_plugins=None, **kw):
        P = stage_paths()
        plugin_path = [harness.PLUGINS]
        if bridge and os.path.exists(os.path.join(BRIDGE_PLUGINS, "kwin", "plugins", "kristall_bridge.so")):
            plugin_path.append(BRIDGE_PLUGINS)
        if decoration:
            plugin_path.append(P["plugins"])
        plugin_path += extra_plugins or []
        env = {"QT_PLUGIN_PATH": ":".join(plugin_path), "KRISTALL_BRIDGE_DEV": "1",
               # KWin scripts' print() (used to list windows) is a debug message
               "QT_LOGGING_RULES": "kwin_scripting.debug=true;js.debug=true;qml.debug=true"}
        env.update(self.desktop_env(overlay))
        super().__init__(width=width, height=height, scale=scale, glass=glass, name=name,
                         settings={"appearance": {"theme": mode, "accent": accent, "glass": 0.3}}, env=env, **kw)
        self.mode, self.accent = mode, accent
        self.real_bridge = bridge and len(plugin_path) > 1
        with open(os.path.join(self.config, "kwinrc"), "a") as f:
            f.write("\n[Plugins]\nkristall_glassEnabled=%s\nkristall_bridgeEnabled=%s\n" %
                    ("true" if glass else "false", "true" if self.real_bridge else "false"))
        self.apps = []

    @staticmethod
    def desktop_env(overlay=True):
        P = stage_paths()
        data = ([P["overlay"]] if overlay else []) + [P["share"], "/usr/share"]
        return {
            "XDG_CONFIG_DIRS": os.path.join(P["etc"], "xdg") + ":/etc/xdg",
            "XDG_DATA_DIRS": ":".join(data),
            "XDG_CURRENT_DESKTOP": "KDE",
            "XDG_SESSION_DESKTOP": "KDE",
            "KDE_FULL_SESSION": "true",
            "KDE_SESSION_VERSION": "6",
            "QT_QPA_PLATFORMTHEME": "kde",
            "KRISTALL_THEME_LIB": P["lib"],
            "KRISTALL_THEME_TOKENS": os.path.join(P["share"], "kristall", "theme", "tokens.json"),
            "GTK_CSD": "1",
            # as /usr/lib/environment.d/50-kristall-theme.conf sets it on the image
            "GTK_PATH": os.path.join(STAGE, "usr", "lib64", "gtk-3.0"),
            "GTK_MODULES": "kristall-reload-gtk-module",
        }

    def start(self, *a, **kw):
        r = super().start(*a, **kw)
        # services the session bus starts on demand (portals, kded helpers) must find the display
        # and our configuration, as in a real session where Plasma updates the activation env
        e = self.app_env()
        keys = ["WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS", "XDG_DATA_DIRS", "XDG_DATA_HOME",
                "XDG_CURRENT_DESKTOP", "KDE_FULL_SESSION", "KDE_SESSION_VERSION", "QT_QPA_PLATFORMTHEME", "QT_QPA_PLATFORM", "GDK_BACKEND"]
        subprocess.run(["dbus-update-activation-environment"] + [f"{k}={e[k]}" for k in keys if k in e],
                       env=e, capture_output=True)
        return r

    # ---------------------------------------------------------------- environment for clients
    def app_env(self, extra=None):
        e = self.env()
        e.update(self.shell_env())
        e.update(self.desktop_env())
        e.update({"QT_QPA_PLATFORM": "wayland", "GDK_BACKEND": "wayland", "LANG": "C.UTF-8",
                  "QT_SCALE_FACTOR_ROUNDING_POLICY": "PassThrough", "MOZ_ENABLE_WAYLAND": "1",
                  "NO_AT_BRIDGE": "1", "PATH": os.path.join(stage_paths()["bin"]) + ":" + self.shell_env()["PATH"]})
        e.update(extra or {})
        return e

    def launch(self, cmd, name=None, extra=None):
        name = name or os.path.basename(cmd[0])
        logf = open(os.path.join(self.tmp, f"app-{name}.log"), "w")
        p = subprocess.Popen(cmd, env=self.app_env(extra), stdout=logf, stderr=subprocess.STDOUT)
        self.procs.append(p)
        self.apps.append(p)
        return p

    def run(self, cmd, timeout=60, extra=None):
        return subprocess.run(cmd, env=self.app_env(extra), capture_output=True, text=True, timeout=timeout)

    def appearance(self, *args, timeout=60):
        P = stage_paths()
        return self.run([sys.executable, os.path.join(P["lib"], "kristall-appearance")] + list(args), timeout=timeout)

    def settings(self, path, value):
        return self.run(["kristall-settings", "set", path, json.dumps(value)])

    def start_kded(self):
        """kded6 (appmenu registrar, GTK config sync, look-and-feel auto switcher)"""
        return self.launch(["kded6"], name="kded6")

    def start_portal(self):
        self.launch(["/usr/libexec/xdg-desktop-portal-kde"], name="portal-kde")
        return self.launch(["/usr/libexec/xdg-desktop-portal", "-r"], name="portal")

    def start_desktop(self):
        """plasmashell draws the real wallpaper from our package (light/dark images follow the scheme)"""
        self.launch(["/usr/libexec/kactivitymanagerd"], name="kactivitymanagerd")
        time.sleep(1.5)
        return self.launch(["plasmashell", "--no-respawn"], name="plasmashell")

    # ---------------------------------------------------------------- input (fake owner)
    def owner(self):
        if not hasattr(self, "_owner"):
            self._owner = subprocess.Popen([OWNER], env=self.app_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            self.procs.append(self._owner)
        return self._owner

    def input(self, *cmds):
        o = self.owner()
        for c in cmds:
            o.stdin.write(c + "\n")
            o.stdin.flush()
            o.stdout.readline()

    def move(self, x, y):
        self.input(f"move {x} {y}", "sync")

    def click(self, x, y, button=0x110):
        self.input(f"move {x} {y}", f"button {button} 1", f"button {button} 0", "sync")

    def key(self, code):
        self.input(f"key {code} 1", f"key {code} 0", "sync")

    # ---------------------------------------------------------------- KWin window queries
    def kwin_windows(self):
        """[(caption, x, y, w, h, active)] through KWin's scripting D-Bus API"""
        script = os.path.join(self.tmp, "list.js")
        with open(script, "w") as f:
            f.write("var out=[];var ws=workspace.windowList();for(var i=0;i<ws.length;i++){var w=ws[i];"
                    "if(!w.normalWindow||w.frameGeometry.width<20)continue;var g=w.frameGeometry;"
                    "out.push(JSON.stringify({c:w.caption,x:g.x,y:g.y,w:g.width,h:g.height,a:w.active,id:w.internalId.toString(),cls:w.resourceClass}));}"
                    "print('WINDOWS['+out.join(',')+']');")
        e = self.app_env()
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                            "--method", "org.kde.kwin.Scripting.loadScript", script, "kristall-list"], env=e, capture_output=True, text=True)
        sid = r.stdout.strip().strip("(),")
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", f"/Scripting/Script{sid}",
                        "--method", "org.kde.kwin.Script.run"], env=e, capture_output=True, text=True)
        time.sleep(0.4)
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                        "--method", "org.kde.kwin.Scripting.unloadScript", "kristall-list"], env=e, capture_output=True, text=True)
        txt = open(os.path.join(self.tmp, "kwin.log"), errors="replace").read()
        i = txt.rfind("WINDOWS[")
        if i < 0:
            return []
        j = txt.index("]", i)
        try:
            return json.loads("[" + txt[i + 8:j] + "]")
        except ValueError:
            return []

    def kwin_script(self, body, name="kristall-script"):
        script = os.path.join(self.tmp, name + ".js")
        with open(script, "w") as f:
            f.write(body)
        e = self.app_env()
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                            "--method", "org.kde.kwin.Scripting.loadScript", script, name], env=e, capture_output=True, text=True)
        sid = r.stdout.strip().strip("(),")
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", f"/Scripting/Script{sid}",
                        "--method", "org.kde.kwin.Script.run"], env=e, capture_output=True, text=True)
        time.sleep(0.3)
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                        "--method", "org.kde.kwin.Scripting.unloadScript", name], env=e, capture_output=True, text=True)

    def place(self, caption_part, x, y, w, h, activate=True):
        self.kwin_script("var ws=workspace.windowList();for(var i=0;i<ws.length;i++){var c=ws[i];"
                         f"if(c.normalWindow&&c.caption.indexOf({json.dumps(caption_part)})>=0){{"
                         f"c.frameGeometry={{x:{x},y:{y},width:{w},height:{h}}};"
                         + ("workspace.activeWindow=c;" if activate else "") + "}}", name="kristall-place")

    def wait_window(self, caption_part, timeout=20):
        return wait_until(lambda: next((w for w in self.kwin_windows() if caption_part.lower() in (w["c"] + " " + w.get("cls", "")).lower()), None), timeout, 0.7)

    def stop(self, keep=False):
        super().stop(keep)
        # services the session bus started on demand outlive it (and keep pipes open); end them
        for name in ("knighttimed", "kactivitymanagerd", "xdg-desktop-portal", "xdg-desktop-portal-kde",
                     "xdg-desktop-portal-gtk", "xdg-document-portal", "xdg-permission-store", "dconf-service", "kded6"):
            subprocess.run(["pkill", "-x", name], capture_output=True)

    def save_jpg(self, img, name, crop=None, quality=82, scale_to=None):
        from PIL import Image
        im = Image.fromarray(img)
        if crop:
            im = im.crop(crop)
        if scale_to:
            im = im.resize(scale_to, Image.LANCZOS)
        os.makedirs(EVIDENCE, exist_ok=True)
        path = os.path.join(EVIDENCE, name)
        if name.endswith(".png"):
            im.save(path, optimize=True)
        else:
            im.convert("RGB").save(path, quality=quality, optimize=True, progressive=True)
        return path


def install_stage(decoration_so=None, fresh=True):
    """run theme/image/install.sh into STAGE (no packages, no initramfs), seeded with the files
    other components put into /etc/xdg first, so the merge is exercised"""
    if fresh and os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    P = stage_paths()
    os.makedirs(os.path.join(P["etc"], "xdg"), exist_ok=True)
    # what the glass effect and shell-core write before us (their install.sh order)
    seed = {
        "kwinrc": "[Plugins]\nkristall_glassEnabled=true\nblurEnabled=false\n",
        "kdeglobals": "[KDE]\nLookAndFeelPackage=org.kristall.desktop\n",
    }
    for name, text in seed.items():
        p = os.path.join(P["etc"], "xdg", name)
        if not os.path.exists(p):
            with open(p, "w") as f:
                f.write(text)
    # shell-core's look-and-feel package (we extend it)
    lnf = os.path.join(P["share"], "plasma", "look-and-feel")
    os.makedirs(lnf, exist_ok=True)
    if not os.path.exists(os.path.join(lnf, "org.kristall.desktop")):
        shutil.copytree(os.path.join(REPO, "shell", "plasma", "look-and-feel", "org.kristall.desktop"),
                        os.path.join(lnf, "org.kristall.desktop"))
    os.makedirs(os.path.join(STAGE, "usr", "lib64"), exist_ok=True)
    env = dict(os.environ)
    env.update({"KRISTALL_PREFIX": os.path.join(STAGE, "usr"), "KRISTALL_SYSCONFDIR": P["etc"],
                "KRISTALL_THEME_SKIP_PACKAGES": "1", "KRISTALL_THEME_SKIP_INITRAMFS": "1", "KRISTALL_CTX": REPO})
    if decoration_so:
        env["KRISTALL_THEME_DECORATION_SO"] = decoration_so
    r = subprocess.run(["bash", os.path.join(THEME, "image", "install.sh")], env=env, capture_output=True, text=True, timeout=1200)
    return r
