#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mac keyboard tests: headless KWin 6.8 with the German layout, the kristall_keyboard plugin and
the real bridge; the owner's physical keys played through org_kde_kwin_fake_input (KWin's real
input pipeline). Logging clients record exactly what each kind of application receives:
a native Wayland app, an XWayland app, a terminal-class window, a Wine game window; a real foot
terminal shows what reaches the program behind it. Writes the chord table to
tests/evidence/keyboard-table.txt. Sections: table altgr bridge system terminal live failsafe."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.dirname(HERE)
REPO = os.path.dirname(SETUP)
sys.path.insert(0, os.path.join(REPO, "kwin", "bridge", "tests", "support"))
import harness as bh  # noqa: E402

BUILD = os.environ.get("KRISTALL_SETUP_BUILD", "/tmp/kristall-setup-build")
EVIDENCE = os.path.join(HERE, "evidence")
failures = []
ROWS = []

# evdev codes (linux/input-event-codes.h), named by the German key legend where it differs
K = {"esc": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11, "ß": 12, "´": 13,
     "backspace": 14, "tab": 15, "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "z": 21, "u": 22, "i": 23, "o": 24,
     "p": 25, "ü": 26, "+": 27, "enter": 28, "ctrl": 29, "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35, "j": 36,
     "k": 37, "l": 38, "ö": 39, "ä": 40, "^": 41, "shift": 42, "#": 43, "y": 44, "x": 45, "c": 46, "v": 47, "b": 48,
     "n": 49, "m": 50, ",": 51, ".": 52, "-": 53, "rshift": 54, "alt": 56, "space": 57, "f4": 62, "home": 102, "up": 103,
     "left": 105, "right": 106, "end": 107, "down": 108, "delete": 111, "altgr": 100, "win": 125, "<": 86, "rctrl": 97}
# the physical keys by their role on the owner's keyboard
CMD, OPT = "alt", "win"
MODBITS = [(4, "Ctrl"), (8, "Alt"), (64, "Meta"), (1, "Shift"), (128, "AltGr")]
MODSYMS = {"Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Super_L", "Super_R", "Shift_L", "Shift_R",
           "ISO_Level3_Shift", "ISO_Next_Group", "Hyper_L", "Mode_switch"}


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(name)
    return ok


def info(msg):
    print("INFO " + msg, flush=True)


def wait_until(pred, timeout=5.0, step=0.05):
    return bh.wait_until(pred, timeout, step)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)


class KeySession(bh.Session):
    """the bridge harness + our plugin, the image's system-wide shortcut files, test shortcuts"""

    def __init__(self, broken=False, settings=None, shortcuts=True, guard=None, **kw):
        plugins = os.path.join(BUILD, "plugins-broken" if broken else "plugins")
        super().__init__(layout="de", xwayland=True, plugins=plugins,
                         kwinrc_extra="[Plugins]\nkristall_keyboardEnabled=true\n", **kw)
        self.shortcuts = shortcuts
        self.shotlog = os.path.join(self.tmp, "shortcuts.log")
        self.sysconf = os.path.join(self.tmp, "sysconf")
        dropins = os.path.join(self.tmp, "settings.d")
        os.makedirs(dropins)
        shutil.copy(os.path.join(SETUP, "data", "50-setup.json"), os.path.join(dropins, "50-setup.json"))
        with open(os.path.join(self.tmp, "defaults.json"), "w") as f:
            f.write("{}")
        self.settings_file = os.path.join(self.config, "kristall", "settings.json")
        write_json(self.settings_file, settings or {})
        self.extra_env.update({"KRISTALL_SETTINGS_DROPIN_DIRS": dropins, "KRISTALL_SETTINGS_DEFAULTS": os.path.join(self.tmp, "defaults.json"),
                               "QT_LOGGING_RULES": "kristall.keyboard.debug=true;kristall.bridge.debug=false",
                               "XDG_CONFIG_DIRS": os.path.join(self.sysconf, "etc", "xdg") + ":/etc/xdg",
                               "XDG_DATA_DIRS": os.path.join(self.sysconf, "usr", "share") + ":/usr/share"})
        self._sysconf()
        if guard:
            os.makedirs(os.path.join(self.runtime, "kristall"), mode=0o700, exist_ok=True)
            now = int(time.time())
            with open(os.path.join(self.runtime, "kristall", "keyboard.guard"), "w") as f:
                f.write("".join(f"{now - i}\n" for i in range(guard)))

    def _sysconf(self):
        etc = os.path.join(self.sysconf, "etc", "xdg")
        share = os.path.join(self.sysconf, "usr", "share")
        os.makedirs(etc)
        os.makedirs(os.path.join(share, "kglobalaccel"))
        sw = os.path.join(REPO, "shell", "modules", "switcher")
        merge = os.path.join(REPO, "shell", "image", "merge-ini")  # shell-core's helper, as the image uses it
        if True:  # the image's switcher configuration (Meta+Tab = apps)
            for name in ("kwinrc", "kglobalshortcutsrc"):
                subprocess.run([sys.executable, merge, os.path.join(etc, name), os.path.join(sw, "kwin", name)], check=True)
            os.makedirs(os.path.join(share, "kwin", "tabbox"))
            shutil.copytree(os.path.join(sw, "kwin", "tabbox", "org.kristall.switcher"), os.path.join(share, "kwin", "tabbox", "org.kristall.switcher"))
        log = os.path.join(self.tmp, "logshortcut")
        with open(log, "w") as f:
            f.write(f"#!/bin/sh\necho \"$1\" >> {self.shotlog}\n")
        os.chmod(log, 0o755)
        acts = [("Search", "Meta+Space", "search"), ("ShotScreen", "Shift+Print", "screenshot-screen"),
                ("ShotRegion", "Meta+Shift+Print", "screenshot-region"), ("ShotTool", "Print", "screenshot-tool"),
                ("Emoji", "Meta+.", "emoji"), ("Assistant", "Alt+Space", "assistant")]
        with open(os.path.join(share, "kglobalaccel", "org.kristall.keytest.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Kristall key test\nExec=%s none\nActions=%s\n" % (log, ";".join(a for a, _, _ in acts)))
            for a, keys, word in acts:
                f.write(f"\n[Desktop Action {a}]\nName={a}\nExec={log} {word}\nX-KDE-Shortcuts={keys}\n")
        # the stock owners of the same keys (Spectacle: the Print chords, the emoji picker: Meta+.,
        # KRunner: Alt+Space) would race the logger for them, and whichever kglobalaccel registers
        # first wins: shadow their shortcut files with key-less ones
        for stock in ("org.kde.spectacle.desktop", "org.kde.plasma.emojier.desktop", "org.kde.krunner.desktop"):
            for d in ("kglobalaccel", "applications"):
                os.makedirs(os.path.join(share, d), exist_ok=True)
                with open(os.path.join(share, d, stock), "w") as f:
                    f.write("[Desktop Entry]\nType=Application\nName=shadowed by the key test\nExec=true\nNoDisplay=true\n")

    def start(self, wait_bridge=True):
        if not self.shortcuts:
            return super().start(wait_bridge)
        orig = bh.KWIN
        wrapper = os.path.join(self.tmp, "kwin-with-shortcuts")
        with open(wrapper, "w") as f:
            f.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = --no-global-shortcuts ] || set -- "$@" "$a"; shift; done\nexec %s "$@"\n' % orig)
        os.chmod(wrapper, 0o755)
        bh.KWIN = wrapper
        try:
            return super().start(wait_bridge)
        finally:
            bh.KWIN = orig

    def status(self):
        try:
            with open(os.path.join(self.runtime, "kristall", "keyboard.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def shortcuts_seen(self):
        try:
            with open(self.shotlog) as f:
                return [l.strip() for l in f if l.strip()]
        except OSError:
            return []

    def xkeylog(self, title, klass):
        return self.spawn([os.path.join(BUILD, "bin", "xkeylog"), title, klass], "x-" + title)

    # the owner's hands
    def press(self, name, down):
        self.default_owner.key(K[name], down)

    def chord(self, *names):
        for n in names:
            self.press(n, True)
        for n in reversed(names):
            self.press(n, False)
        time.sleep(0.12)


def keys_received(proc, mark):
    """the non-modifier key presses a logging client saw since mark, as 'Ctrl+Shift+c' strings"""
    out = []
    for e in proc.since(mark):
        if e.get("ev") != "key" or e.get("state") != 1 or e.get("sym") in MODSYMS:
            continue
        mods = [n for bit, n in MODBITS if e["mods"] & bit]
        out.append("+".join(mods + [e["sym"]]))
    return " ".join(out) if out else "—"


def text_received(proc, mark):
    return "".join(e.get("utf8", "") for e in proc.since(mark) if e.get("ev") == "key" and e.get("state") == 1)


def focus(s, b, win):
    b.call("window.activate", id=win["id"])
    wait_until(lambda: next((w for w in b.call("window.list")["windows"] if w["id"] == win["id"] and w["active"]), None), 3)
    time.sleep(0.15)


def open_clients(s, b):
    """native app, XWayland app, terminal-class app, Wine game (XWayland, *.exe)"""
    s.wlprobe("--title", "native", "--app-id", "org.kde.kate", "--size", "300x200", name="native")
    s.wlprobe("--title", "terminal", "--app-id", "org.kde.konsole", "--size", "300x200", name="terminal")
    s.xkeylog("x11", "xkeylog")
    s.xkeylog("game", "RobloxStudioBeta.exe")
    wins = {}
    for t in ("native", "terminal", "x11", "game"):
        w = bh.window_by_title(b, t, 15)
        if not w:
            raise RuntimeError(f"window {t} did not appear")
        wins[t] = w
    procs = {p.name: p for p in s.procs}
    clients = {"native": procs["native"], "terminal": procs["terminal"], "x11": procs["x-x11"], "game": procs["x-game"]}
    return wins, clients


# ------------------------------------------------------------------------------------------ table

CHORDS = [
    # (label, keys, expectation for native/x11, terminal, game)
    ("⌘C copy", (CMD, "c"), "Ctrl+c", "Ctrl+Shift+C", "Alt+c"),
    ("⌘V paste", (CMD, "v"), "Ctrl+v", "Ctrl+Shift+V", "Alt+v"),
    ("⌘X cut", (CMD, "x"), "Ctrl+x", "Ctrl+Shift+X", "Alt+x"),
    ("⌘Z undo (key labelled Z)", (CMD, "z"), "Ctrl+z", "Ctrl+Shift+Z", "Alt+z"),
    ("⇧⌘Z redo", (CMD, "shift", "z"), "Ctrl+Shift+Z", "Ctrl+Shift+Z", "Alt+Shift+Z"),
    ("⌘A select all", (CMD, "a"), "Ctrl+a", "Ctrl+Shift+A", "Alt+a"),
    ("⌘S save", (CMD, "s"), "Ctrl+s", "Ctrl+Shift+S", "Alt+s"),
    ("⌘Q quit", (CMD, "q"), "Ctrl+q", "Ctrl+Shift+Q", "Alt+q"),
    ("⌘W close window", (CMD, "w"), "Ctrl+w", "Ctrl+Shift+W", "Alt+w"),
    ("⌘T new tab", (CMD, "t"), "Ctrl+t", "Ctrl+Shift+T", "Alt+t"),
    ("⌘F find", (CMD, "f"), "Ctrl+f", "Ctrl+Shift+F", "Alt+f"),
    ("⌘N new", (CMD, "n"), "Ctrl+n", "Ctrl+Shift+N", "Alt+n"),
    ("⌘, settings (KDE app: Ctrl+Shift+,)", (CMD, ","), "Ctrl+comma", "Ctrl+comma", "Alt+comma"),
    ("⌘← line start", (CMD, "left"), "Home", "Home", "Alt+Left"),
    ("⌘→ line end", (CMD, "right"), "End", "End", "Alt+Right"),
    ("⇧⌘← select to line start", (CMD, "shift", "left"), "Shift+Home", "Shift+Home", "Alt+Shift+Left"),
    ("⌘↑ document start", (CMD, "up"), "Ctrl+Home", "Ctrl+Home", "Alt+Up"),
    ("⌘↓ document end", (CMD, "down"), "Ctrl+End", "Ctrl+End", "Alt+Down"),
    ("⌘⌫ delete to line start", (CMD, "backspace"), "Shift+Home BackSpace", "Ctrl+u", "Alt+BackSpace"),
    ("⌥← word left", (OPT, "left"), "Ctrl+Left", "Ctrl+Left", "stock"),
    ("⌥→ word right", (OPT, "right"), "Ctrl+Right", "Ctrl+Right", "stock"),
    ("⇧⌥← select word left", (OPT, "shift", "left"), "Ctrl+Shift+Left", "Ctrl+Shift+Left", "stock"),
    ("⌥⌫ delete word", (OPT, "backspace"), "Ctrl+BackSpace", "Ctrl+BackSpace", "stock"),
    ("⌥E (Windows key + E)", (OPT, "e"), "Alt+e", "Alt+e", "stock"),
    ("⌃C (physical Control)", ("ctrl", "c"), "Ctrl+c", "Ctrl+c", "Ctrl+c"),
    ("⌃⌥Entf (Ctrl first: as printed)", ("ctrl", CMD, "delete"), "Ctrl+Alt+Delete", "Ctrl+Alt+Delete", "Ctrl+Alt+Delete"),
    ("letters z y ü (no modifier)", ("z",), "z", "z", "z"),
]



def stock_game_reference():
    """what the Wine game window gets for the same physical keys with the mapping OFF (a stock PC)"""
    ref = {}
    with KeySession(name="keys-stock", settings={"keyboard": {"macShortcuts": False}}) as s:
        b = s.bridge()
        wait_until(lambda: s.status().get("reason") == "off", 5)
        wins, clients = open_clients(s, b)
        for label, keys, _a, _t, w_game in CHORDS:
            if w_game != "stock":
                continue
            focus(s, b, wins["game"])
            m = clients["game"].mark()
            s.chord(*keys)
            time.sleep(0.1)
            ref[label] = keys_received(clients["game"], m)
    return ref


def test_table():
    print("== chord table: native, XWayland, terminal, Wine game (German layout, mapping on)", flush=True)
    stock = stock_game_reference()
    info("stock PC keys in the game window (mapping off): " + json.dumps(stock, ensure_ascii=False))
    with KeySession(name="keys-table") as s:
        b = s.bridge()
        st = wait_until(lambda: s.status().get("active"), 5)
        check("plugin loaded, devices taken over, status active", bool(st), json.dumps(s.status()))
        wins, clients = open_clients(s, b)
        for label, keys, w_app, w_term, w_game in CHORDS:
            row = [label, "+".join(keys)]
            for which, want in (("native", w_app), ("x11", w_app), ("terminal", w_term), ("game", w_game)):
                if label.startswith("⌘,"):
                    # KDE apps (our probes carry org.kde.* ids) take Control+Shift+Comma (on German keys: semicolon)
                    want = "Ctrl+Shift+semicolon" if which in ("native", "terminal") else ("Ctrl+comma" if which == "x11" else "Alt+comma")
                if label.startswith("letters"):
                    want = "z"
                if want == "stock":
                    want = stock[label]       # identical to a PC without the mapping (Win+← tiles in KWin)
                focus(s, b, wins[which])
                p = clients[which]
                m = p.mark()
                s.chord(*keys)
                time.sleep(0.1)
                got = keys_received(p, m)
                ok = got == want
                row.append(got + ("" if ok else f"  (expected {want})"))
                check(f"{label} → {which}: {got}", ok, "" if ok else f"expected {want}")
            ROWS.append(row)
        # nothing stuck: a plain key after all chords arrives without modifiers everywhere
        for which in ("native", "x11", "terminal", "game"):
            focus(s, b, wins[which])
            m = clients[which].mark()
            s.chord("k")
            check(f"no stuck modifier afterwards ({which})", keys_received(clients[which], m) == "k", keys_received(clients[which], m))


# ------------------------------------------------------------------------------------------ AltGr

LEVELS = [  # every key of the German main block: unshifted, Shift, AltGr where printed
    "^", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "ß", "´", "q", "w", "e", "r", "t", "z", "u", "i", "o", "p", "ü", "+",
    "a", "s", "d", "f", "g", "h", "j", "k", "l", "ö", "ä", "#", "<", "y", "x", "c", "v", "b", "n", "m", ",", ".", "-"]
ALTGR = {"q": "@", "e": "€", "7": "{", "8": "[", "9": "]", "0": "}", "ß": "\\", "<": "|", "+": "~", "m": "µ", "2": "²", "3": "³"}


def type_all(s, p):
    seq = []
    for k in LEVELS:
        m = p.mark()
        s.chord(k)
        seq.append(("", k, keys_received(p, m), text_received(p, m)))
        m = p.mark()
        s.chord("shift", k)
        seq.append(("⇧", k, keys_received(p, m), text_received(p, m)))
        m = p.mark()
        s.chord("altgr", k)
        seq.append(("AltGr", k, keys_received(p, m), text_received(p, m)))
    return seq


def test_altgr():
    print("== every printed character, all levels, with the mapping on vs. stock (mapping off)", flush=True)
    results = {}
    for mode in ("on", "off"):
        with KeySession(name=f"keys-altgr-{mode}", settings={"keyboard": {"macShortcuts": mode == "on"}}, shortcuts=False) as s:
            b = s.bridge()
            wait_until(lambda: s.status().get("running"), 5)
            check(f"status reports mapping {mode}", s.status().get("reason") == mode, json.dumps(s.status()))
            wins, clients = open_clients(s, b)
            for which in ("native", "x11", "terminal"):
                focus(s, b, wins[which])
                results[(mode, which)] = type_all(s, clients[which])
    for which in ("native", "x11", "terminal"):
        on, off = results[("on", which)], results[("off", which)]
        diffs = [(a, b) for a, b in zip(on, off) if a[2] != b[2] or a[3] != b[3]]
        check(f"{which}: all {len(on)} key/level combinations identical with the mapping on and off", not diffs, str(diffs[:5]))
        for lvl, k, keys, text in on:
            if lvl == "AltGr" and k in ALTGR:
                check(f"{which}: AltGr+{k} types {ALTGR[k]}", text == ALTGR[k], f"got {text!r} ({keys})")
    os.makedirs(EVIDENCE, exist_ok=True)
    with open(os.path.join(EVIDENCE, "keyboard-altgr.txt"), "w") as f:
        f.write("German layout, mapping ON — what each client typed (key: plain / Shift / AltGr)\n")
        for which in ("native", "x11", "terminal"):
            on = results[("on", which)]
            f.write(f"\n[{which}]\n")
            for i in range(0, len(on), 3):
                f.write(f"{on[i][1]:>3}: {on[i][3] or on[i][2]!s:6} {on[i + 1][3] or on[i + 1][2]!s:6} {on[i + 2][3] or on[i + 2][2]!s}\n")


# ------------------------------------------------------------------------------------------ bridge

SENTENCE = "Schöne Grüße, läuft's? @home €5 {x} [y] \\ | ~ 😀"


def test_bridge():
    print("== the assistant's injected typing (bridge agent.text/agent.key) while the mapping is on", flush=True)
    with KeySession(name="keys-bridge", shortcuts=False) as s:
        b = s.bridge()
        wait_until(lambda: s.status().get("active"), 5)
        wins, clients = open_clients(s, b)
        def key(a, which, chord, want):
            """agent.key into one window: delivered on the first attempt, also to an X11 window the
            bridge has just (re)activated (the bridge orders X focus and keys since 2026-11-17)"""
            p = clients[which]
            m = p.mark()
            a.key(chord, window_id=wins[which]["id"])
            got = wait_until(lambda: keys_received(p, m) if keys_received(p, m) != "—" else None, 1.5) or "—"
            check(f"agent.key {chord} arrives as {want}, untranslated ({which})", got == want, got)

        with b.agent_session("typing") as a:
            for which in ("native", "x11"):
                # keys first (independent of the text paths), then the sentence
                key(a, which, "ctrl+c", "Ctrl+c")
                key(a, which, "alt+f", "Alt+f")
                p = clients[which]
                m = p.mark()
                r = a.text(SENTENCE, window_id=wins[which]["id"])
                time.sleep(0.4)
                got = text_received(p, m)
                if which == "native":
                    check("agent.text German sentence arrives intact (native)", got == SENTENCE, repr(got))
                else:
                    # an X11 app gets the characters of the layout as keys and the emoji through the
                    # clipboard + Ctrl+V (bridge contract); that Ctrl+V must arrive untranslated too
                    got = wait_until(lambda: text_received(p, m) if text_received(p, m).startswith(SENTENCE[:-1]) else None, 3) or text_received(p, m)
                    check("agent.text German sentence arrives intact as keys (x11)", got.startswith(SENTENCE[:-1]), repr(got))
                    ok = wait_until(lambda: keys_received(p, m).endswith("Ctrl+v"), 3)
                    check("…and the emoji via the bridge's clipboard path, its Ctrl+V untranslated (x11)",
                          "clipboard" in r.get("paths", []) and bool(ok), f"{r.get('paths')} {keys_received(p, m)[-20:]}")


# ------------------------------------------------------------------------------------------ system chords

def test_system():
    print("== system chords: Search, switcher, window actions, screenshots (global shortcuts on)", flush=True)
    with KeySession(name="keys-system") as s:
        b = s.bridge()
        wait_until(lambda: s.status().get("active"), 5)
        wins, clients = open_clients(s, b)
        time.sleep(1.5)  # kglobalaccel reads the shortcut files
        comps = subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.kglobalaccel", "--object-path", "/kglobalaccel",
                                "--method", "org.kde.KGlobalAccel.allComponents"], capture_output=True, text=True).stdout
        check("no stock owner competes for the test's keys (Spectacle, emoji picker, KRunner)",
              "keytest" in comps and not any(c in comps for c in ("spectacle", "emojier", "krunner")), comps.strip()[:300])
        focus(s, b, wins["native"])
        for keys, word in (((CMD, "space"), "search"), ((CMD, "shift", "3"), "screenshot-screen"), ((CMD, "shift", "4"), "screenshot-region"),
                           ((CMD, "shift", "5"), "screenshot-tool"), (("ctrl", CMD, "space"), "emoji"), ((OPT, "space"), "assistant")):
            n = len(s.shortcuts_seen())
            m = clients["native"].mark()
            s.chord(*keys)
            ok = wait_until(lambda: len(s.shortcuts_seen()) > n, 3)
            seen = s.shortcuts_seen()[n:]
            check(f"{'+'.join(keys)} → global shortcut '{word}'", bool(ok) and seen == [word], str(seen))
            check(f"{'+'.join(keys)}: the app received nothing", keys_received(clients["native"], m) == "—", keys_received(clients["native"], m))
            ROWS.append([f"system: {word}", "+".join(keys), f"global shortcut '{word}'" if seen == [word] else str(seen), "", "", ""])
        # ⌘Tab: KWin's switcher (Meta+Tab in the image's kglobalshortcutsrc), held Command = held Meta
        focus(s, b, wins["x11"])
        focus(s, b, wins["native"])
        s.press(CMD, True)
        s.press("tab", True)
        s.press("tab", False)
        time.sleep(0.4)
        s.press(CMD, False)
        act = wait_until(lambda: next((w["title"] for w in b.call("window.list")["windows"] if w["active"]), None) == "x11", 3)
        check("⌘Tab (quick) switches to the previous app", bool(act), str([w["title"] for w in b.call("window.list")["windows"] if w["active"]]))
        ROWS.append(["⌘Tab app switcher", "alt+tab", "KWin switcher (Meta+Tab)" if act else "no switch", "", "", ""])
        # ⌘M minimises, ⌘H hides the app, ⌃⌘F full screen
        focus(s, b, wins["native"])
        s.chord(CMD, "m")
        ok = wait_until(lambda: next((w for w in b.call("window.list")["windows"] if w["id"] == wins["native"]["id"] and w["minimized"]), None), 3)
        check("⌘M minimises the front window", bool(ok))
        b.call("window.activate", id=wins["native"]["id"])
        time.sleep(0.3)
        focus(s, b, wins["terminal"])
        s.chord(CMD, "h")
        ok = wait_until(lambda: next((w for w in b.call("window.list")["windows"] if w["id"] == wins["terminal"]["id"] and w["minimized"]), None), 3)
        check("⌘H hides the front app", bool(ok))
        b.call("window.activate", id=wins["terminal"]["id"])
        focus(s, b, wins["native"])
        s.chord("ctrl", CMD, "f")
        ok = wait_until(lambda: next((w for w in b.call("window.list")["windows"] if w["id"] == wins["native"]["id"] and w["fullscreen"]), None), 3)
        check("⌃⌘F makes the front window full screen", bool(ok))
        ROWS.append(["⌘M / ⌘H / ⌃⌘F", "", "minimise / hide app / full screen (KWin)", "", "", ""])
        # in the Wine game Command is Alt again (Alt+Space = the assistant's own shortcut)
        b.call("window.setFullscreen", id=wins["native"]["id"], value=False)
        focus(s, b, wins["game"])
        n = len(s.shortcuts_seen())
        s.chord(CMD, "space")
        time.sleep(0.6)
        check("in the Wine game ⌘Space is Alt+Space (PC keys), not Search", "search" not in s.shortcuts_seen()[n:], str(s.shortcuts_seen()[n:]))


# ------------------------------------------------------------------------------------------ real terminal

def test_terminal():
    print("== a real terminal (foot): ⌘C copies, ⌃C interrupts, ⌘V pastes", flush=True)
    with KeySession(name="keys-foot", shortcuts=False) as s:
        b = s.bridge()
        wait_until(lambda: s.status().get("active"), 5)
        out = os.path.join(s.tmp, "tty.jsonl")
        s.spawn(["foot", "--app-id", "foot", "--title", "foot", "-o", "main.font=monospace:size=10", sys.executable, os.path.join(HERE, "clients", "ttylog.py"), out], "foot")
        w = bh.window_by_title(b, "foot", 15)
        if not check("foot started", bool(w)):
            return
        wait_until(lambda: os.path.exists(out), 10)
        focus(s, b, w)

        def tty():
            with open(out) as f:
                return [json.loads(l) for l in f if l.strip()]
        n = len(tty())
        s.chord("ctrl", "c")
        time.sleep(0.3)
        got = "".join(e.get("hex", "") for e in tty()[n:])
        check("physical ⌃C reaches the program as 0x03 (interrupt)", got == "03", got)
        n = len(tty())
        s.chord(CMD, "c")
        time.sleep(0.3)
        got = "".join(e.get("hex", "") for e in tty()[n:])
        check("⌘C does not send an interrupt (it is the terminal's copy, Ctrl+Shift+C)", got == "", got)
        subprocess.run(["wl-copy", "kristall-paste"], env=s.env(), timeout=5)
        time.sleep(0.3)
        n = len(tty())
        s.chord(CMD, "v")
        time.sleep(0.6)
        got = "".join(e.get("text", "") for e in tty()[n:])
        check("⌘V pastes the clipboard into the program", "kristall-paste" in got, repr(got))
        ROWS.append(["foot (real terminal)", "ctrl+c / alt+c / alt+v", "0x03 / nothing / paste", "", "", ""])


# ------------------------------------------------------------------------------------------ live switch, fail-safe

def test_live():
    print("== switching live: setting off → stock keys at once, on → Mac keys", flush=True)
    with KeySession(name="keys-live", shortcuts=False) as s:
        b = s.bridge()
        wait_until(lambda: s.status().get("active"), 5)
        wins, clients = open_clients(s, b)
        focus(s, b, wins["native"])
        p = clients["native"]
        m = p.mark()
        s.chord(CMD, "c")
        check("on: ⌘C → Ctrl+c", keys_received(p, m) == "Ctrl+c", keys_received(p, m))
        write_json(s.settings_file, {"keyboard": {"macShortcuts": False}})
        ok = wait_until(lambda: s.status().get("reason") == "off", 3)
        check("status follows the setting within moments", bool(ok), json.dumps(s.status()))
        m = p.mark()
        s.chord(CMD, "c")
        check("off: the same keys give Alt+c (stock PC keyboard)", keys_received(p, m) == "Alt+c", keys_received(p, m))
        m = p.mark()
        s.chord(OPT, "left")
        check("off: Windows key + ← is Meta+Left", keys_received(p, m) == "Meta+Left", keys_received(p, m))
        # switched while Command is held: the release still balances
        s.press(CMD, True)
        write_json(s.settings_file, {"keyboard": {"macShortcuts": True}})
        wait_until(lambda: s.status().get("reason") == "on", 3)
        s.press(CMD, False)
        m = p.mark()
        s.chord("k")
        check("no stuck modifier after switching while a key was held", keys_received(p, m) == "k", keys_received(p, m))
        m = p.mark()
        s.chord(CMD, "c")
        check("on again: ⌘C → Ctrl+c", keys_received(p, m) == "Ctrl+c", keys_received(p, m))


def test_failsafe():
    print("== fail-safe: a plugin that cannot start, and the crash guard → stock keys", flush=True)
    with KeySession(name="keys-broken", broken=True, shortcuts=False) as s:
        b = s.bridge()
        time.sleep(1.0)
        st = s.status()
        check("broken plugin: KWin runs without it (status not-loaded)", st.get("reason") == "not-loaded" and not st.get("active"), json.dumps(st))
        wins, clients = open_clients(s, b)
        focus(s, b, wins["native"])
        m = clients["native"].mark()
        s.chord(CMD, "c")
        s.chord("altgr", "q")
        got = keys_received(clients["native"], m)
        check("broken plugin: keys are stock (Alt+c, AltGr+q = @)", got == "Alt+c AltGr+at", got)
    with KeySession(name="keys-guard", guard=3, shortcuts=False) as s:
        b = s.bridge()
        wait_until(lambda: s.status().get("reason"), 5)
        st = s.status()
        check("crash guard (3 recent compositor starts): status crash-guard, not active", st.get("reason") == "crash-guard" and not st.get("active"), json.dumps(st))
        wins, clients = open_clients(s, b)
        focus(s, b, wins["native"])
        m = clients["native"].mark()
        s.chord(CMD, "c")
        check("crash guard: keys are stock", keys_received(clients["native"], m) == "Alt+c", keys_received(clients["native"], m))


def write_table():
    if not ROWS:
        return
    os.makedirs(EVIDENCE, exist_ok=True)
    head = ["chord (Mac)", "physical keys", "native Wayland app", "XWayland app", "terminal", "Wine game (*.exe)"]
    widths = [max(len(str(r[i])) if i < len(r) else 0 for r in ROWS + [head]) for i in range(len(head))]
    with open(os.path.join(EVIDENCE, "keyboard-table.txt"), "w") as f:
        f.write("Kristall Mac keyboard — what each client received (headless KWin 6.8.3, German layout, physical keys via fake input).\n")
        f.write("Physical: alt = the key beside the space bar (Command), win = Windows key (Option), altgr = right Alt.\n\n")
        for r in [head] + ROWS:
            f.write("  ".join(str(r[i] if i < len(r) else "").ljust(widths[i]) for i in range(len(head))).rstrip() + "\n")


SECTIONS = {"table": test_table, "altgr": test_altgr, "bridge": test_bridge, "system": test_system, "terminal": test_terminal,
            "live": test_live, "failsafe": test_failsafe}

if __name__ == "__main__":
    want = sys.argv[1:] or list(SECTIONS)
    for name in want:
        try:
            SECTIONS[name]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    if "table" in want:
        write_table()
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
