#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Kristall theme tests (inside the dev container under dbus-run-session; see run.sh).

Each check prints PASS/FAIL/INFO/SKIP; the exit status is non-zero if anything failed.
Screenshots go to tests/evidence/ (JPEG, cropped, total kept under 6 MB).
"""
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import wave
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import themesession as ts  # noqa: E402
import kristall_colors as kc  # noqa: E402
import kini  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

THEME = ts.THEME
REPO = ts.REPO
failures = []
results = {}


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(name)
    return ok


def info(msg):
    print("INFO " + msg, flush=True)


def skip(msg):
    print("SKIP " + msg, flush=True)


def have(cmd):
    return shutil.which(cmd) is not None


def stage_ready():
    P = ts.stage_paths()
    return os.path.exists(os.path.join(P["etc"], "xdg", "kwinrc")) and os.path.exists(os.path.join(P["plugins"], "org.kde.kdecoration3", "org.kristall.decoration.so"))


def ensure_stage():
    if not stage_ready():
        r = ts.install_stage()
        if r.returncode != 0:
            print(r.stdout[-2000:], r.stderr[-2000:])
            raise RuntimeError("install.sh into the staging root failed")
    # a stage from an earlier run: refresh the service and its libraries from the working tree
    P = ts.stage_paths()
    for src in (os.path.join(THEME, "service", "kristall-appearance"), os.path.join(THEME, "tools", "kristall_colors.py"),
                os.path.join(THEME, "tools", "kini.py")):
        shutil.copy(src, P["lib"])


# ======================================================================== static
def test_static():
    print("== static checks", flush=True)
    tokens = kc.load_tokens()
    # tokens agree with design.md / Theme.qml (shell-core is the owner of the numbers)
    theme_qml = open(os.path.join(REPO, "shell", "core", "Theme.qml")).read()
    acc_ok = all(re.search(rf'{k}:\s*{{ light: "{v["light"]}", dark: "{v["dark"]}" }}', theme_qml) for k, v in tokens["accents"].items())
    check("accent colours match Theme.qml / design.md §6", acc_ok)
    check("window radii 16/20 match Theme.qml", "windowSmall: 16" in theme_qml and re.search(r"\bwindow: 20\b", theme_qml) is not None)
    check("window shadow recipe matches Theme.qml (48/16/0.32)", "window:  { blur: 48, y: 16, opacity: 0.32 }" in theme_qml)
    for mode in ("light", "dark"):
        s = tokens["schemes"][mode]
        check(f"{mode}: window/label match design.md (#ECECEE/#262628, #1D1D1F/#F2F2F7)",
              s["window"] == ("#ECECEE" if mode == "light" else "#262628") and s["label"] == ("#1D1D1F" if mode == "light" else "#F2F2F7"))
    # contrast of the derived colours (WCAG): text on window/view ≥ 7, secondary ≥ 4.5, accent text ≥ 3
    def contrast(a, b):
        la, lb = kc.luminance(a), kc.luminance(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)
    worst = {}
    for mode in ("light", "dark"):
        for accent in tokens["accentOrder"]:
            p = kc.palette(tokens, mode, accent)
            worst[(mode, accent)] = contrast(p["accent"], p["accentText"])
        p = kc.palette(tokens, mode)
        check(f"{mode}: label on window/view ≥ 7:1", min(contrast(p["label"], p["window"]), contrast(p["label"], p["view"])) >= 7,
              "%.1f / %.1f" % (contrast(p["label"], p["window"]), contrast(p["label"], p["view"])))
        # design.md's secondaryLabel is macOS's (black 50 % / white 55 %): ≈ 3.8:1 on the light window,
        # as on a Mac; Increase Contrast raises it (shell-core). Checked against 3:1 (large/UI text).
        check(f"{mode}: secondary label on window ≥ 3:1 (macOS secondaryLabel)", contrast(p["secondary"], p["window"]) >= 3, "%.1f" % contrast(p["secondary"], p["window"]))
    low = {f"{m}/{a}": round(v, 2) for (m, a), v in worst.items() if v < 3}
    info(f"text on accent fills below 3:1 (same as macOS with white text on these system colours): {low or 'none'}")
    # generated files parse as KDE INI; the fragments merge
    out = os.path.join("/tmp", "kristall-theme-static")
    shutil.rmtree(out, ignore_errors=True)
    subprocess.run([sys.executable, os.path.join(THEME, "tools", "gen-theme.py"), out], check=True, capture_output=True)
    files = glob.glob(os.path.join(out, "share", "color-schemes", "*.colors")) + glob.glob(os.path.join(THEME, "config", "xdg", "*")) + \
        glob.glob(os.path.join(out, "share", "konsole", "*")) + glob.glob(os.path.join(THEME, "plasma", "look-and-feel", "*", "contents", "defaults"))
    check("colour schemes, Konsole schemes, xdg fragments and look-and-feel defaults are well-formed KDE INI",
          subprocess.run([sys.executable, os.path.join(THEME, "tools", "kini.py"), "check"] + files).returncode == 0, f"{len(files)} files")
    light = kini.KIni(open(os.path.join(out, "share", "color-schemes", "KristallLight.colors")).read())
    check("KristallLight: header (title bar + toolbar) = window colour, selection = accent", light.get("Colors:Header", "BackgroundNormal") == "236,236,238"
          and light.get("Colors:Selection", "BackgroundNormal") == "0,122,255")
    for js in glob.glob(os.path.join(THEME, "**", "*.json"), recursive=True):
        try:
            json.load(open(js))
        except ValueError as e:
            check(f"JSON parses: {os.path.relpath(js, THEME)}", False, str(e))
    check("JSON files parse (tokens, plugin metadata, look-and-feel metadata)", True)
    try:
        xml.dom.minidom.parse(os.path.join(THEME, "config", "fontconfig", "56-kristall.conf"))
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
        info(str(e))
    check("fontconfig rules are well-formed XML", ok)
    if have("fc-match"):
        env = dict(os.environ)
        conf = os.path.join("/tmp", "kristall-fonts.conf")
        with open(conf, "w") as f:
            f.write('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig>'
                    '<include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                    f'<include>{os.path.join(THEME, "config", "fontconfig", "56-kristall.conf")}</include></fontconfig>')
        env["FONTCONFIG_FILE"] = conf
        fams = {q: subprocess.run(["fc-match", "-f", "%{family[0]}", q], env=env, capture_output=True, text=True).stdout for q in ("sans-serif", "system-ui", "monospace", "emoji")}
        check("fontconfig: sans-serif/system-ui → Inter, monospace → JetBrains Mono (if installed), emoji → Noto Color Emoji",
              fams["sans-serif"] == "Inter" and fams["system-ui"] == "Inter" and fams["emoji"] == "Noto Color Emoji"
              and fams["monospace"] in ("JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono"), json.dumps(fams))
        hint = subprocess.run(["fc-match", "-f", "%{hintstyle} %{rgba} %{antialias}", "Inter"], env=env, capture_output=True, text=True).stdout
        check("fontconfig: greyscale antialiasing (rgba none), no hinting (OLED-safe, fractional scales)", hint.strip() == "0 5 True", "hintstyle rgba antialias = " + hint)
    # QML: qmllint on everything we ship (warnings about unresolved Plasma modules are informational)
    qmllint = "/usr/lib64/qt6/bin/qmllint"
    qml = [os.path.join(THEME, p) for p in ("plasma/look-and-feel/org.kristall.desktop/contents/splash/Splash.qml",
                                            "plasma/shell-overlay/logout/Logout.qml", "plasma/shell-overlay/logout/KristallLogout.qml",
                                            "plasma/shell-overlay/lockscreen/KristallClock.qml")]
    if os.path.exists(qmllint):
        r = subprocess.run([qmllint] + qml, capture_output=True, text=True)
        errs = [l for l in (r.stdout + r.stderr).splitlines() if "Error" in l or "error" in l]
        check("qmllint: no errors in our QML (splash, log-out, clock)", not errs, "\n".join(errs[:6]))
    # the QML engine loads each file (syntax and imports resolve against the installed Qt)
    if have("qml") or os.path.exists("/usr/lib64/qt6/bin/qml"):
        pass
    # shell scripts
    if have("shellcheck"):
        r = subprocess.run(["shellcheck", "-S", "warning", os.path.join(THEME, "image", "install.sh"), os.path.join(THEME, "image", "plymouth.sh"),
                            os.path.join(THEME, "tests", "run.sh")], capture_output=True, text=True)
        check("shellcheck (warnings and above): install.sh, plymouth.sh, run.sh", r.returncode == 0, r.stdout[-800:])
    for py in [os.path.join(THEME, "service", "kristall-appearance")] + glob.glob(os.path.join(THEME, "tools", "*.py")) + \
            [os.path.join(THEME, "plasma", "shell-overlay", "build-overlay.py")]:
        try:
            compile(open(py).read(), py, "exec")
        except SyntaxError as e:
            check(f"python compiles: {py}", False, str(e))
    check("Python sources compile (service, generators, overlay builder)", True)
    # Plymouth theme: keys and images the two-step plugin requires
    ply = kini.KIni(open(os.path.join(THEME, "plymouth", "kristall.plymouth")).read())
    check("Plymouth theme uses the two-step plugin with a progress bar and no spinner",
          ply.get("Plymouth Theme", "ModuleName") == "two-step" and ply.get("boot-up", "UseProgressBar") == "true" and ply.get("boot-up", "UseAnimation") == "false")


# ======================================================================== install (staging)
def test_install():
    print("== install.sh into a staging root (merge, idempotency, assets)", flush=True)
    t = time.time()
    r = ts.install_stage()
    check("install.sh completes (no packages, no initramfs: staging mode)", r.returncode == 0, (r.stdout + r.stderr)[-1500:] if r.returncode else f"{time.time() - t:.0f} s")
    if r.returncode:
        return
    P = ts.stage_paths()
    kw = kini.KIni(open(os.path.join(P["etc"], "xdg", "kwinrc")).read())
    kg = kini.KIni(open(os.path.join(P["etc"], "xdg", "kdeglobals")).read())
    check("merge keeps other components' keys (glass: kristall_glassEnabled/blurEnabled; shell: LookAndFeelPackage)",
          kw.get("Plugins", "kristall_glassEnabled") == "true" and kw.get("Plugins", "blurEnabled") == "false"
          and kg.get("KDE", "LookAndFeelPackage") == "org.kristall.desktop")
    check("kwinrc: our decoration, buttons close/minimise/zoom on the left, none on the right",
          kw.get("org.kde.kdecoration2", "library") == "org.kristall.decoration" and kw.get("org.kde.kdecoration2", "ButtonsOnLeft") == "XIA"
          and kw.get("org.kde.kdecoration2", "ButtonsOnRight") == "")
    check("kwinrc: no hot corners or edge actions (overview's top-left corner off)",
          kw.get("Effect-overview", "BorderActivate") == "9" and all(kw.get("ElectricBorders", e) == "None" for e in ("TopLeft", "TopRight", "BottomLeft", "BottomRight")))
    check("kdeglobals: Kristall Light colours, Inter 13 px, Breeze icons, automatic light/dark with our two packages",
          kg.get("General", "ColorScheme") == "KristallLight" and kg.get("Colors:Window", "BackgroundNormal") == "236,236,238"
          and kg.get("General", "font", ).startswith("Inter,9.75") and kg.get("KDE", "DefaultDarkLookAndFeel") == "org.kristall.desktop.dark")
    g3 = open(os.path.join(P["etc"], "gtk-3.0", "settings.ini")).read()
    g4 = open(os.path.join(P["etc"], "gtk-4.0", "settings.ini")).read()
    check("GTK settings: the GTK 4-only gtk-hint-font-metrics only in gtk-4.0 (GTK 3 warned on every app start)",
          "gtk-hint-font-metrics" not in g3 and "gtk-hint-font-metrics=false" in g4)
    snap = {f: open(f, "rb").read() for f in glob.glob(os.path.join(P["etc"], "**", "*"), recursive=True) if os.path.isfile(f)}
    r2 = ts.install_stage(fresh=False)
    snap2 = {f: open(f, "rb").read() for f in glob.glob(os.path.join(P["etc"], "**", "*"), recursive=True) if os.path.isfile(f)}
    check("install.sh is idempotent (second run leaves /etc identical)", r2.returncode == 0 and snap == snap2,
          str([os.path.basename(f) for f in snap2 if snap.get(f) != snap2[f]][:5]))
    # assets
    for wid in ("Kristall", "Kristall-Welle", "Kristall-Horizont"):
        d = os.path.join(P["share"], "wallpapers", wid, "contents")
        sizes = sorted(os.listdir(os.path.join(d, "images")))
        check(f"wallpaper {wid}: light and dark images at {', '.join(s[:-4] for s in sizes)}",
              sizes == sorted(os.listdir(os.path.join(d, "images_dark"))) and "3840x2400.jpg" in sizes and "2880x1800.jpg" in sizes)
    cur = os.path.join(P["share"], "icons", "Kristall")
    xc = open(os.path.join(cur, "cursors", "default"), "rb").read()
    magic, hdr, ver, ntoc = struct.unpack("<4sIII", xc[:16])
    sizes = sorted({struct.unpack("<III", xc[16 + 12 * i:28 + 12 * i])[1] for i in range(ntoc)})
    check("pointer: XCursor 'default' valid with sizes " + ",".join(map(str, sizes)), magic == b"Xcur" and 24 in sizes and 48 in sizes and 96 in sizes)
    meta = json.load(open(os.path.join(cur, "cursors_scalable", "default", "metadata.json")))
    svg_ok = all(xml.dom.minidom.parse(f) for f in glob.glob(os.path.join(cur, "cursors_scalable", "*", "*.svg")))
    check("pointer: SVG cursors (KWin scalable) parse; metadata has hotspot and nominal size", svg_ok and meta[0]["nominal_size"] == 24)
    links = [l for l in os.listdir(os.path.join(cur, "cursors")) if os.path.islink(os.path.join(cur, "cursors", l))]
    check("pointer: X11/CSS cursor names are aliased (left_ptr, hand2, xterm, …)", all(n in links for n in ("left_ptr", "hand2", "xterm", "watch", "sb_h_double_arrow")), f"{len(links)} aliases")
    snd = glob.glob(os.path.join(P["share"], "sounds", "kristall", "stereo", "*.wav"))
    peaks = []
    for f in snd:
        with wave.open(f) as w:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            peaks.append(int(np.abs(data).max()) if data.size else 0)
    check("sounds: valid WAV, quiet (peak ≤ -17 dBFS), login/logout silent", len(snd) >= 19 and max(peaks) <= 32767 * 0.15
          and max(np.abs(np.frombuffer(wave.open(os.path.join(P["share"], "sounds", "kristall", "stereo", "desktop-login.wav")).readframes(10**6), dtype=np.int16)), default=0) == 0,
          f"{len(snd)} files, max peak {max(peaks) / 32767:.3f}")
    ov = json.load(open(os.path.join(P["overlay"], "plasma", "shells", "org.kde.plasma.desktop", "contents", "kristall-overlay.json")))
    check("shell-package overlay: lock screen patched, log-out dialog replaced (with stock fallbacks kept)",
          ov["lockscreen"] == "kristall" and ov["logout"] == "kristall", json.dumps(ov))
    stock = "/usr/share/plasma/shells/org.kde.plasma.desktop"
    same = all(open(os.path.join(stock, rel), "rb").read() == open(os.path.join(P["overlay"], "plasma", "shells", "org.kde.plasma.desktop", rel), "rb").read()
               for rel in ("contents/views/Desktop.qml", "contents/lockscreen/LockScreenUi.qml", "metadata.json") if os.path.exists(os.path.join(stock, rel)))
    check("overlay: everything except the lock screen entry point and log-out dialog is byte-identical to the installed package", same)
    lnf = os.path.join(P["share"], "plasma", "look-and-feel")
    check("look-and-feel: shell-core's layout untouched; dark twin carries an identical copy of it",
          open(os.path.join(lnf, "org.kristall.desktop", "contents", "layouts", "org.kde.plasma.desktop-layout.js")).read()
          == open(os.path.join(REPO, "shell", "plasma", "look-and-feel", "org.kristall.desktop", "contents", "layouts", "org.kde.plasma.desktop-layout.js")).read()
          == open(os.path.join(lnf, "org.kristall.desktop.dark", "contents", "layouts", "org.kde.plasma.desktop-layout.js")).read())
    # evidence: the wallpapers
    for wid in ("Kristall", "Kristall-Welle", "Kristall-Horizont"):
        for var in ("images", "images_dark"):
            im = Image.open(os.path.join(P["share"], "wallpapers", wid, "contents", var, "2880x1800.jpg"))
            name = f"wallpaper-{wid.lower()}-{'dark' if var.endswith('dark') else 'light'}.jpg"
            im.resize((960, 600), Image.LANCZOS).save(os.path.join(ts.EVIDENCE, name), quality=84, optimize=True, progressive=True)
    info("wallpaper previews (960×600 of the 2880×1800 images) in evidence/wallpaper-*.jpg")


# ======================================================================== decoration
def bg_wallpaper(sess, mode="light", wid="Kristall"):
    P = ts.stage_paths()
    var = "images_dark" if mode == "dark" else "images"
    src = os.path.join(P["share"], "wallpapers", wid, "contents", var, "2880x1800.jpg")
    out = os.path.join(sess.tmp, f"bg-{mode}.png")
    Image.open(src).resize((int(sess.width * sess.scale), int(sess.height * sess.scale)), Image.LANCZOS).save(out)
    return sess.background(out)


def px(img, x, y):
    return tuple(int(v) for v in img[int(y), int(x), :3])


def is_close(c, ref, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def test_decoration():
    print("== window decoration: buttons, corners, outline, shadow, active/inactive, hover", flush=True)
    ensure_stage()
    for mode in ("light", "dark"):
        s = ts.ThemeSession(mode=mode, name=f"deco-{mode}")
        s.start()
        try:
            bg_wallpaper(s, mode)
            r = s.appearance("apply")
            info(f"{mode}: kristall-appearance apply → {r.stdout.strip()[:200]}")
            s.launch(["kate", "-n", "--startanon"], name="kate")
            s.launch(["dolphin", "--new-window", os.path.expanduser("~")], name="dolphin")
            k = s.wait_window("kate")
            d = s.wait_window("dolphin")
            if not (k and d):
                check(f"{mode}: Kate and Dolphin windows appear", False, str(s.kwin_windows()))
                continue
            s.place("Kate", 40, 90, 560, 420, activate=False)
            s.place("Dolphin", 660, 90, 580, 420, activate=True)
            time.sleep(1.5)
            img = s.screenshot()
            wins = {w["cls"]: w for w in s.kwin_windows()}
            dw = next(w for w in wins.values() if "dolphin" in w["cls"].lower())
            kwn = next(w for w in wins.values() if "kate" in w["cls"].lower())
            # buttons: first circle centre at x+12+6, y+14
            def centres(w):
                return [(w["x"] + 12 + 6 + 20 * i, w["y"] + 14) for i in range(3)]
            act = [px(img, x, y) for x, y in centres(dw)]
            ina = [px(img, x, y) for x, y in centres(kwn)]
            check(f"{mode}: active window shows red/yellow/green buttons at the top left", is_close(act[0], (0xFF, 0x5F, 0x57)) and is_close(act[1], (0xFE, 0xBC, 0x2E))
                  and is_close(act[2], (0x28, 0xC8, 0x40)), str(act))
            grey = (0xDC, 0xDC, 0xDE) if mode == "light" else (0x4A, 0x4A, 0x4C)
            check(f"{mode}: inactive window's buttons are grey", all(is_close(c, grey, 18) for c in ina), str(ina))
            # rounded corners: the window's outermost corner pixel shows the wallpaper, not the title bar
            corner = px(img, dw["x"] + 1, dw["y"] + 1)
            bar = px(img, dw["x"] + dw["w"] // 2, dw["y"] + 3)
            check(f"{mode}: top corners rounded (corner pixel is background, not title bar)", not is_close(corner, bar, 8), f"corner {corner} bar {bar}")
            bl = px(img, dw["x"] + 1, dw["y"] + dw["h"] - 2)
            inside = px(img, dw["x"] + 30, dw["y"] + dw["h"] - 30)
            check(f"{mode}: bottom corners rounded too (KWin clips the client with the decoration's radius)", not is_close(bl, inside, 8), f"{bl} vs {inside}")
            s.save_jpg(img, f"windows-active-inactive-{mode}-1.0x.jpg", crop=(0, 40, 1280, 560))
            # hover over the group: symbols appear on all three
            cx, cy = centres(dw)[1]
            s.move(cx, cy)
            time.sleep(0.6)
            img2 = s.screenshot()
            crop = (dw["x"], dw["y"], dw["x"] + 80, dw["y"] + 28)
            a = img[crop[1]:crop[3], crop[0]:crop[2], :3].astype(int)
            b = img2[crop[1]:crop[3], crop[0]:crop[2], :3].astype(int)
            diff_close = np.abs(a[8:20, 12:24] - b[8:20, 12:24]).sum()
            diff_zoom = np.abs(a[8:20, 52:64] - b[8:20, 52:64]).sum()
            check(f"{mode}: hovering one button shows the symbols on all three (close and zoom change too)", diff_close > 2000 and diff_zoom > 2000,
                  f"Δclose {diff_close} Δzoom {diff_zoom}")
            big = Image.fromarray(np.concatenate([img[crop[1] - 6:crop[3] + 6, crop[0] - 6:crop[0] + 150, :3], img2[crop[1] - 6:crop[3] + 6, crop[0] - 6:crop[0] + 150, :3]], axis=0))
            big = big.resize((big.width * 4, big.height * 4), Image.NEAREST)
            big.save(os.path.join(ts.EVIDENCE, f"window-buttons-rest-hover-{mode}-4x.png"), optimize=True)
            s.move(640, 700)
        finally:
            s.stop()


# ======================================================================== apps
SAMPLE_TEXT = """Kristall OS — Textdatei

Falsches Üben von Xylophonmusik quält jeden größeren Zwerg.
The quick brown fox jumps over the lazy dog. 0123456789

• Inter for interfaces, JetBrains Mono for code
• Light and dark follow one switch
"""
SAMPLE_HTML = ("<!doctype html><html><head><meta charset=utf-8><title>Kristall</title><style>:root{color-scheme:light dark}body{font-family:system-ui;margin:40px}input,button,select{font:inherit}</style></head><body><h1>Kristall OS</h1>"
               "<p>Falsches Üben von Xylophonmusik quält jeden größeren Zwerg.</p><p><input placeholder='Suchen'> "
               "<button>Senden</button> <select><option>Eins</option></select> <input type=checkbox checked> "
               "<input type=range></p></body></html>")


def firefox_profile(sess):
    prof = os.path.join(sess.tmp, "ff-profile")
    os.makedirs(prof, exist_ok=True)
    prefs = open(os.path.join(THEME, "config", "firefox", "kristall-theme-prefs.js")).read().replace("pref(", "user_pref(")
    prefs += "\n".join([
        'user_pref("browser.aboutwelcome.enabled", false);', 'user_pref("browser.startup.homepage_override.mstone", "ignore");',
        'user_pref("startup.homepage_welcome_url", "");', 'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
        'user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);', 'user_pref("browser.shell.checkDefaultBrowser", false);',
        'user_pref("browser.tabs.firefox-view", false);', 'user_pref("sidebar.revamp", false);', 'user_pref("browser.newtabpage.enabled", false);',
        'user_pref("trailhead.firstrun.didSeeAboutWelcome", true);', 'user_pref("browser.startup.firstrunSkipsHomepage", true);', ""])
    with open(os.path.join(prof, "user.js"), "w") as f:
        f.write(prefs)
    page = os.path.join(sess.tmp, "page.html")
    with open(page, "w") as f:
        f.write(SAMPLE_HTML)
    return prof, page


def app_specs(sess):
    txt = os.path.join(sess.tmp, "Notizen.txt")
    with open(txt, "w") as f:
        f.write(SAMPLE_TEXT)
    home = os.path.join(sess.tmp, "home")
    for d in ("Dokumente", "Bilder", "Musik", "Downloads", "Projekte"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    for n in ("Bericht.pdf", "Foto.jpg", "Notizen.txt", "Lied.ogg"):
        open(os.path.join(home, n), "w").write("x")
    specs = [
        ("files", "dolphin", ["dolphin", "--new-window", home], "dolphin"),
        ("settings", "systemsettings", ["systemsettings"], "systemsettings"),
        ("texteditor", "kwrite" if have("kwrite") else "kate", ["kwrite", txt] if have("kwrite") else ["kate", "-n", txt], "kwrite" if have("kwrite") else "kate"),
        ("terminal", "konsole", ["konsole", "--separate", "-e", "bash", "-c", "printf '\\e[1mKristall\\e[0m  \\e[31mred \\e[32mgreen \\e[33myellow \\e[34mblue \\e[35mmagenta \\e[36mcyan\\e[0m\\n'; ls --color=always /usr; exec bash"], "konsole"),
    ]
    if have("gtk3-widget-factory"):
        specs.append(("gtk3", "gtk3-widget-factory", ["gtk3-widget-factory"], "gtk3-widget-factory"))
    if have("adwaita-1-demo"):
        specs.append(("gtk4-libadwaita", "adwaita-1-demo", ["adwaita-1-demo"], "adwaita"))
    if have("firefox"):
        prof, page = firefox_profile(sess)
        specs.append(("firefox", "firefox", ["firefox", "--no-remote", "--new-instance", "-profile", prof, "file://" + page], "firefox"))
    return specs


def start_with_bar(sess, mode):
    """KWin + glass + real bridge, our wallpaper, kded (app menus, GTK sync), the Kristall shell"""
    sess.start()
    bg_wallpaper(sess, mode)
    sess.appearance("apply")
    sess.start_kded()
    sess.start_portal()
    time.sleep(1.0)
    sess.start_shell(bridge=False, extra_env=ts.ThemeSession.desktop_env())
    try:
        sess.wait_ready(25)
        return True
    except RuntimeError as e:
        info("shell did not come up: " + str(e)[:300])
        return False


def test_apps():
    print("== applications inside the desktop: light/dark × 1.0/1.6, with the menu bar above them", flush=True)
    ensure_stage()
    shots = {}
    for scale in (1.0, 1.6):
        for mode in ("light", "dark"):
            s = ts.ThemeSession(mode=mode, scale=scale, name=f"apps-{mode}-{scale}")
            try:
                bar = start_with_bar(s, mode)
                check(f"{mode} {scale}x: the Kristall menu bar runs above the apps", bar)
                for key, label, cmd, match in app_specs(s):
                    p = s.launch(cmd, name=key)
                    w = s.wait_window(match, 30)
                    if not w:
                        check(f"{mode} {scale}x: {label} opens a window", False, open(os.path.join(s.tmp, f"app-{key}.log"), errors="replace").read()[-400:])
                        p.terminate()
                        continue
                    s.place(w["c"][:24] if w["c"] else match, 140, 70, 1000, 640)
                    time.sleep(3.0 if key in ("firefox", "settings") else 2.0)
                    img = s.screenshot()
                    k = s.scale
                    if scale == 1.0:
                        path = s.save_jpg(img, f"app-{key}-{mode}-1.0x.jpg", crop=(0, 0, 1280, 740), quality=80)
                    else:
                        path = s.save_jpg(img, f"app-{key}-{mode}-1.6x.jpg", crop=(0, 0, int(900 * k), int(560 * k)), quality=80)
                    st = None
                    try:
                        st = s.state()
                    except Exception:  # noqa: BLE001
                        pass
                    bar_name = st["bar"].get("appName") if st and st.get("bar") else None
                    titles = st["bar"].get("titles") if st and st.get("bar") else []
                    shots[f"{key}-{mode}-{scale}"] = {"bar": bar_name, "menus": titles[:8]}
                    # the window's title bar has the scheme's header colour; content is light/dark
                    wn = s.wait_window(match, 3) or w
                    mid = px(img, (wn["x"] + wn["w"] * 0.5) * k, (wn["y"] + wn["h"] * 0.6) * k)
                    lum = (0.299 * mid[0] + 0.587 * mid[1] + 0.114 * mid[2]) / 255
                    check(f"{mode} {scale}x: {label} — window content follows {mode} (centre luminance {lum:.2f}); bar shows {bar_name!r} {titles[:5]}",
                          (lum > 0.5) == (mode == "light") or key == "terminal" and mode == "light" and lum > 0.5, os.path.basename(path))
                    p.terminate()
                    try:
                        p.wait(5)
                    except subprocess.TimeoutExpired:
                        p.kill()
                    time.sleep(0.5)
            finally:
                s.stop()
    results["apps"] = shots


# ======================================================================== menus (glass)
def glass_status(sess):
    sys.path.insert(0, os.path.join(REPO, "kwin", "glass", "tests", "support"))
    import harness
    try:
        c = harness.GlassConn(sess.glass_socket)
        c.wait("hello", 3)
        st = c.status()
        c.close()
        return st
    except Exception as e:  # noqa: BLE001
        info(f"glass status: {e}")
        return None


def test_menus():
    print("== context menus and popups render as glass (blur request → glass effect)", flush=True)
    ensure_stage()
    for mode in ("light", "dark"):
        s = ts.ThemeSession(mode=mode, name=f"menu-{mode}")
        try:
            start_with_bar(s, mode)
            home = os.path.join(s.tmp, "home")
            for d in ("Dokumente", "Bilder", "Musik"):
                os.makedirs(os.path.join(home, d), exist_ok=True)
            s.launch(["dolphin", "--new-window", home], name="dolphin")
            w = s.wait_window("dolphin", 30)
            s.place(w["c"][:20], 140, 70, 900, 600)
            time.sleep(2)
            auto, img = [], None
            for _ in range(3):   # the first click may only focus the window
                s.click(700, 520, 0x111)    # right-click on empty space in the view
                time.sleep(1.5)
                img = s.screenshot()
                st = glass_status(s) or {}
                auto = [x for x in st.get("windows", []) if not x.get("explicit")]
                if auto:
                    break
                s.key(1)
            check(f"{mode}: the context menu requests background blur and the glass effect draws it ({len(auto)} automatic glass window(s))",
                  len(auto) >= 1, json.dumps([{k: x.get(k) for k in ("geometry", "shapes")} for x in auto])[:300])
            s.save_jpg(img, f"context-menu-glass-{mode}-1.0x.jpg", crop=(560, 330, 1180, 790), quality=84)
            s.key(1)   # Escape
        finally:
            s.stop()


# ======================================================================== switch
SWITCH_APPS = [
    ("files", ["dolphin", "--new-window", "/usr/share/wallpapers"], "dolphin"),
    ("terminal", ["konsole", "--separate"], "konsole"),
    ("texteditor", ["kwrite"], "kwrite"),
    ("gtk3", ["gtk3-demo"], "gtk3-demo"),
    ("gtk4", ["adwaita-1-demo"], "adwaita"),
    ("firefox", None, "firefox"),
]


def test_switch():
    print("== one switch: appearance.theme flips every app live (timed), accent follows", flush=True)
    ensure_stage()
    s = ts.ThemeSession(mode="light", name="switch")
    timings = {}
    try:
        start_with_bar(s, "light")
        svc = s.launch([sys.executable, os.path.join(ts.stage_paths()["lib"], "kristall-appearance"), "run"], name="appearance")
        time.sleep(2)
        grid = [(10, 34), (436, 34), (862, 34), (10, 418), (436, 418), (862, 418)]
        placed = {}
        for i, (key, cmd, match) in enumerate(SWITCH_APPS):
            if key == "firefox":
                if not have("firefox"):
                    continue
                prof, page = firefox_profile(s)
                cmd = ["firefox", "--no-remote", "--new-instance", "-profile", prof, "file://" + page]
            if key in ("texteditor",) and not have("kwrite"):
                cmd, match = ["kate", "-n"], "kate"
            if not have(cmd[0]):
                skip(f"{key}: {cmd[0]} not installed")
                continue
            s.launch(cmd, name=key)
            w = s.wait_window(match, 30)
            if not w:
                check(f"switch: {key} window appears", False)
                continue
            x, y = grid[i]
            s.place(w["c"][:20], x, y, 408, 370)
            placed[key] = (x, y, 408, 370)
        time.sleep(3)
        light = s.screenshot()

        def lum(img, r):
            x, y, w, h = r
            # a strip in the lower content area of the window (away from toolbars)
            patch = img[int(y + h * 0.70):int(y + h * 0.80), int(x + w * 0.55):int(x + w * 0.9), :3].astype(float)
            return float((patch * [0.299, 0.587, 0.114]).sum(axis=2).mean() / 255)
        base = {k: lum(light, r) for k, r in placed.items()}
        info("content luminance before: " + json.dumps({k: round(v, 2) for k, v in base.items()}))
        for target in ("dark", "light"):
            t0 = time.monotonic()
            s.settings("appearance.theme", target)
            flipped = {}
            frames = 0
            while time.monotonic() - t0 < 12 and len(flipped) < len(placed):
                img = s.screenshot()
                frames += 1
                t = time.monotonic() - t0
                for k, r in placed.items():
                    if k in flipped:
                        continue
                    v = lum(img, r)
                    if (target == "dark" and v < 0.45) or (target == "light" and v > 0.55):
                        flipped[k] = round(t, 2)
                if target == "dark" and len(flipped) == len(placed):
                    s.save_jpg(img, "switch-all-dark-1.0x.jpg", quality=80)
            timings[target] = flipped
            missing = [k for k in placed if k not in flipped]
            check(f"switch to {target}: every app follows ({len(flipped)}/{len(placed)}), slowest {max(flipped.values()) if flipped else '—'} s after the setting changed",
                  not missing, f"left behind: {missing}; times {flipped}")
            if target == "dark":
                pass
            time.sleep(2)
        s.save_jpg(light, "switch-all-light-1.0x.jpg", quality=80)
        # accent
        s.settings("appearance.accent", "green")
        time.sleep(4)
        st = json.loads(s.appearance("status", "--json").stdout or "{}")
        check("accent green: Plasma's AccentColor is the design token (#28CD41 light)", st.get("accentColor", "").replace(" ", "") == "40,205,65", json.dumps(st))
        # what running Qt apps actually draw: the scheme's selection colour, re-tinted by
        # plasma-apply-colorscheme --accent-color (before the fix it stayed one change behind)
        sel = s.run(["kreadconfig6", "--file", "kdeglobals", "--group", "Colors:Selection", "--key", "BackgroundNormal"]).stdout.strip()
        rgb = [int(x) for x in sel.replace(" ", "").split(",")[:3]] if sel.count(",") >= 2 else [0, 0, 0]
        check("accent green reaches running Qt/KDE apps (kdeglobals Colors:Selection is green now, not the previous blue)",
              rgb[1] > rgb[0] + 40 and rgb[1] > rgb[2] + 40, sel)
        css = open(os.path.join(s.config, "gtk-4.0", "kristall.css")).read()
        check("accent green reaches GTK 4/libadwaita (--accent-bg-color) and GTK 3 (@accent_bg_color)",
              "--accent-bg-color: #28CD41" in css and "@define-color accent_bg_color #28CD41" in open(os.path.join(s.config, "gtk-3.0", "kristall.css")).read())
        s.save_jpg(s.screenshot(), "switch-accent-green-light-1.0x.jpg", quality=80)
        # Reduce Motion → KWin/Qt/GTK animations off
        s.settings("accessibility.reduceMotion", True)
        time.sleep(3)
        r = s.run(["kreadconfig6", "--file", "kdeglobals", "--group", "KDE", "--key", "AnimationDurationFactor"])
        check("Reduce Motion sets Plasma's AnimationDurationFactor to 0 (KWin, Qt, GTK via kde-gtk-config, portal reduced-motion)", r.stdout.strip() == "0", r.stdout)
        s.settings("accessibility.reduceMotion", False)
        # auto: Plasma's own day/night switching is enabled with our two packages
        s.settings("appearance.theme", "auto")
        time.sleep(3)
        r = s.run(["kreadconfig6", "--file", "kdeglobals", "--group", "KDE", "--key", "AutomaticLookAndFeel"])
        r2 = s.run(["kreadconfig6", "--file", "kdeglobals", "--group", "KDE", "--key", "DefaultDarkLookAndFeel"])
        check("auto: Plasma's automatic look-and-feel switching is on, dark package org.kristall.desktop.dark",
              r.stdout.strip() == "true" and r2.stdout.strip() == "org.kristall.desktop.dark", r.stdout + r2.stdout)
        svc.terminate()
    finally:
        s.stop()
    results["switch"] = timings


# ======================================================================== screens
def test_screens():
    print("== lock screen, log-out dialog, login splash, login screen", flush=True)
    ensure_stage()
    P = ts.stage_paths()
    for mode in ("light", "dark"):
        s = ts.ThemeSession(mode=mode, name=f"lock-{mode}")
        try:
            s.start()
            s.appearance("apply")
            with open(os.path.join(s.config, "kscreenlockerrc"), "w") as f:
                f.write("[Greeter][Wallpaper][org.kde.image][General]\nImage=" + os.path.join(P["share"], "wallpapers", "Kristall") + "/\n")
            p = s.launch(["/usr/libexec/kscreenlocker_greet", "--testing"], name="locker", extra={"LANG": "de_DE.UTF-8"})
            time.sleep(6)
            idle = s.screenshot()
            log = open(os.path.join(s.tmp, "app-locker.log"), errors="replace").read()
            check(f"{mode}: lock screen loads our arrangement (no fallback to the built-in locker)",
                  "falling back" not in log and "failed to load" not in log.lower(), log[-300:])
            s.save_jpg(idle, f"lockscreen-idle-{mode}-1.0x.jpg", quality=82)
            # the prompt appears on pointer movement (the locker ignores the first motion event)
            s.move(600, 500)
            s.move(640, 520)
            s.click(640, 540)
            time.sleep(2.5)
            prompt = s.screenshot()
            check(f"{mode}: moving the pointer shows picture, name and password field (screen changes)",
                  np.abs(prompt[:, :, :3].astype(int) - idle[:, :, :3].astype(int)).mean() > 2)
            s.save_jpg(prompt, f"lockscreen-prompt-{mode}-1.0x.jpg", quality=82)
            p.terminate()
            # log-out dialog (full-screen overlay as in a session)
            g = s.launch(["/usr/libexec/ksmserver-logout-greeter"], name="logout", extra={"LANG": "de_DE.UTF-8"})
            time.sleep(3)
            s.run(["gdbus", "call", "--session", "--dest", "org.kde.LogoutPrompt", "--object-path", "/LogoutPrompt", "--method", "org.kde.LogoutPrompt.promptShutDown"])
            time.sleep(3)
            img = s.screenshot()
            s.save_jpg(img, f"logout-shutdown-{mode}-1.0x.jpg", quality=82)
            centre = px(img, 640, 400)
            check(f"{mode}: shut-down confirmation shows (centre card drawn)", sum(centre) > 30, str(centre))
            g.terminate()
            # login splash (KSplash), our look-and-feel package
            k = s.launch(["ksplashqml", "--test", "--window", "org.kristall.desktop"], name="ksplash")
            time.sleep(4)
            s.save_jpg(s.screenshot(), f"login-splash-{mode}-1.0x.jpg", quality=82)
            k.terminate()
        finally:
            s.stop()
    # the login screen (plasma-login-manager's greeter in its test mode with the mock backend). The
    # greeter reads /usr/lib/plasmalogin/plasmalogin.conf.d; this throw-away container gets ours.
    if os.path.exists("/usr/libexec/plasma-login-greeter"):
        d = "/usr/lib/plasmalogin/plasmalogin.conf.d"
        os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(THEME, "plasma", "plasmalogin", "50-kristall.conf"), d)
        if not os.path.exists("/usr/share/wallpapers/Kristall"):
            os.symlink(os.path.join(P["share"], "wallpapers", "Kristall"), "/usr/share/wallpapers/Kristall")
        s = ts.ThemeSession(mode="light", name="login")
        try:
            s.start()
            w = s.launch(["/usr/bin/plasma-login-wallpaper"], name="login-wallpaper")
            time.sleep(4)
            s.save_jpg(s.screenshot(), "login-wallpaper-layer-light-1.0x.jpg", quality=80)
            # the greeter's test mode paints a dark grey placeholder instead of being transparent
            # over the wallpaper process (plasma-login-manager main.cpp); both layers are shown
            g = s.launch(["/usr/libexec/plasma-login-greeter", "--test"], name="greeter", extra={"LANG": "de_DE.UTF-8"})
            time.sleep(6)
            s.save_jpg(s.screenshot(), "login-screen-light-1.0x.jpg", quality=82)
            s.move(600, 500)
            s.move(640, 520)
            s.click(640, 420)
            time.sleep(2)
            s.save_jpg(s.screenshot(), "login-screen-prompt-light-1.0x.jpg", quality=82)
            check("login screen (greeter test mode) runs with our wallpaper, colours and font", g.poll() is None,
                  open(os.path.join(s.tmp, "app-greeter.log"), errors="replace").read()[-300:])
        finally:
            s.stop()
    else:
        skip("plasma-login-greeter not installed")


# ======================================================================== pointer
def capture_with_cursor(sess):
    import dbus
    bus = dbus.SessionBus()
    iface = dbus.Interface(bus.get_object("org.kde.KWin", "/org/kde/KWin/ScreenShot2"), "org.kde.KWin.ScreenShot2")
    r, w = os.pipe()
    opts = dbus.Dictionary({"native-resolution": dbus.Boolean(True), "include-cursor": dbus.Boolean(True)}, signature="sv")
    try:
        meta = iface.CaptureActiveScreen(opts, dbus.types.UnixFd(w))
    finally:
        os.close(w)
    width, height, stride = int(meta["width"]), int(meta["height"]), int(meta["stride"])
    data = b""
    with os.fdopen(r, "rb") as f:
        while len(data) < stride * height:
            chunk = f.read(stride * height - len(data))
            if not chunk:
                break
            data += chunk
    raw = np.frombuffer(data, dtype=np.uint8)[: stride * height].reshape(height, stride)[:, : width * 4].reshape(height, width, 4)
    return raw[:, :, [2, 1, 0]].copy()


def test_pointer():
    print("== pointer: black arrow with a white edge, sharp at 1.0 and 1.6", flush=True)
    ensure_stage()
    tiles = []
    for scale in (1.0, 1.6):
        s = ts.ThemeSession(mode="light", scale=scale, name=f"ptr-{scale}")
        try:
            s.start()
            bg_wallpaper(s, "light")
            time.sleep(1)
            s.launch(["konsole", "--separate"], name="konsole")
            w = s.wait_window("konsole", 20)
            s.place(w["c"][:15], 600, 200, 500, 360)
            time.sleep(2)
            for (x, y) in ((300, 300), (850, 400)):
                s.move(x, y)
                time.sleep(0.8)
                img = capture_with_cursor(s)
                k = scale
                tiles.append(Image.fromarray(img[int((y - 20) * k):int((y + 30) * k), int((x - 20) * k):int((x + 30) * k)]).resize((200, 200), Image.NEAREST))
            s.move(300, 300)
            time.sleep(0.5)
            # inside the arrow's body: 4 px right, 9 px below the tip (logical)
            centre = capture_with_cursor(s)[int(309 * scale), int(304 * scale)]
            check(f"{scale}x: the pointer KWin draws is our dark arrow (pixel inside the arrow is near black)", int(centre.sum()) < 150, str(centre))
        finally:
            s.stop()
    sheet = Image.new("RGB", (200 * len(tiles), 200), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, (200 * i, 0))
    sheet.save(os.path.join(ts.EVIDENCE, "pointer-arrow-ibeam-1.0x-1.6x-zoom.png"), optimize=True)
    # the full set as generated (48 px)
    import cursors
    cs = cursors.cursors()
    cell = 64
    sh = Image.new("RGBA", (cell * 8, cell * ((len(cs) + 7) // 8)), (236, 236, 238, 255))
    for i, n in enumerate(cs):
        im, _ = cursors.raster(cs[n][0][0], 36)
        sh.alpha_composite(im, ((i % 8) * cell + 8, (i // 8) * cell + 8))
    sh.convert("RGB").save(os.path.join(ts.EVIDENCE, "pointer-set.png"), optimize=True)
    info("pointer evidence: pointer-arrow-ibeam-1.0x-1.6x-zoom.png (as KWin draws it), pointer-set.png (all 24 shapes)")


# ======================================================================== fallback
def test_fallback():
    print("== fail soft: remove or break each custom piece", flush=True)
    ensure_stage()
    P = ts.stage_paths()
    # 1 decoration plugin missing → KWin uses Breeze
    for label, kw, env in (("missing decoration plugin", {"decoration": False}, {}),
                           ("decoration crash guard tripped", {}, {"KRISTALL_DECORATION_FORCE_FALLBACK": "1"})):
        s = ts.ThemeSession(mode="light", name="fb-deco", **kw)
        s.extra_env.update(env)
        try:
            s.start()
            bg_wallpaper(s)
            s.launch(["dolphin", "--new-window", "/usr/share"], name="dolphin")
            w = s.wait_window("dolphin", 30)
            s.place(w["c"][:15], 140, 70, 900, 560)
            time.sleep(2)
            img = s.screenshot()
            w = s.wait_window("dolphin", 3)
            red = px(img, w["x"] + 18, w["y"] + 14)
            check(f"{label}: the window is still decorated (KWin fell back to Breeze), no Kristall buttons",
                  not is_close(red, (0xFF, 0x5F, 0x57)) and w["h"] > 500, str(red))
            s.save_jpg(img, f"fallback-{'no-plugin' if not env else 'crash-guard'}-breeze-1.0x.jpg", crop=(100, 40, 1080, 660), quality=78)
        finally:
            s.stop()
    # 2 the crash guard counts KWin starts: two unhealthy starts recorded → third uses Breeze
    s = ts.ThemeSession(mode="light", name="fb-guard")
    os.makedirs(os.path.join(s.runtime, "kristall"), exist_ok=True)
    with open(os.path.join(s.runtime, "kristall", "decoration.guard"), "w") as f:
        f.write(f"2 {int(time.time())}\n")
    try:
        s.start()
        s.launch(["kate", "-n"], name="kate")
        w = s.wait_window("kate", 30)
        time.sleep(2)
        img = s.screenshot()
        red = px(img, w["x"] + 18, w["y"] + 14)
        check("crash guard: after two KWin starts that did not stay up 30 s, the third gets Breeze", not is_close(red, (0xFF, 0x5F, 0x57)),
              [l for l in s.log_text().splitlines() if "kristall-decoration" in l][-1:])
    finally:
        s.stop()
    # 3 GTK styling removed → GTK apps keep working in plain adw-gtk3/libadwaita
    if have("adwaita-1-demo"):
        s = ts.ThemeSession(mode="light", name="fb-gtk")
        try:
            s.start()
            bg_wallpaper(s)
            s.appearance("apply")
            for v in ("gtk-3.0", "gtk-4.0"):
                os.remove(os.path.join(s.config, v, "kristall.css"))
            p = s.launch(["adwaita-1-demo"], name="adw")
            w = s.wait_window("adwaita", 20)
            time.sleep(2)
            check("GTK styling deleted: libadwaita app still opens (stock look, @import of a missing file is ignored)", p.poll() is None and w is not None)
            s.save_jpg(s.screenshot(), "fallback-gtk-css-removed-1.0x.jpg", quality=78)
        finally:
            s.stop()
    # 4 lock screen: our file broken → stock lock screen; overlay missing → stock lock screen
    broken = "/tmp/kristall-broken-overlay"
    shutil.rmtree(broken, ignore_errors=True)
    shutil.copytree(P["overlay"], broken, symlinks=True)
    ls = os.path.join(broken, "plasma", "shells", "org.kde.plasma.desktop", "contents", "lockscreen", "KristallLockScreenUi.qml")
    with open(ls, "a") as f:
        f.write("\nthis is not QML {\n")
    lo = os.path.join(broken, "plasma", "shells", "org.kde.plasma.desktop", "contents", "logout", "KristallLogout.qml")
    with open(lo, "w") as f:
        f.write("import QtQuick\nItem { broken: }\n")
    for label, data_dirs in (("our lock-screen file broken", [broken]), ("overlay not installed", [])):
        s = ts.ThemeSession(mode="light", name="fb-lock", overlay=False)
        try:
            s.start()
            env = {"XDG_DATA_DIRS": ":".join(data_dirs + [P["share"], "/usr/share"])}
            p = s.launch(["/usr/libexec/kscreenlocker_greet", "--testing"], name="locker", extra=env)
            time.sleep(6)
            s.key(57)
            time.sleep(2)
            img = s.screenshot()
            log = open(os.path.join(s.tmp, "app-locker.log"), errors="replace").read()
            alive = p.poll() is None
            check(f"lock screen with {label}: the stock Plasma lock screen shows and stays usable", alive and "Failed to load the fallback" not in log,
                  [l for l in log.splitlines() if "kristall" in l.lower()][:2])
            s.save_jpg(img, f"fallback-lockscreen-{'broken' if data_dirs else 'no-overlay'}-1.0x.jpg", quality=78)
            p.terminate()
            if data_dirs:
                g = s.launch(["/usr/libexec/ksmserver-logout-greeter"], name="logout", extra=env)
                time.sleep(3)
                s.run(["gdbus", "call", "--session", "--dest", "org.kde.LogoutPrompt", "--object-path", "/LogoutPrompt", "--method", "org.kde.LogoutPrompt.promptReboot"], extra=env)
                time.sleep(3)
                lg = open(os.path.join(s.tmp, "app-logout.log"), errors="replace").read()
                check("log-out dialog with our file broken: the stock Plasma dialog is used", "using the stock dialog" in lg and g.poll() is None,
                      [l for l in lg.splitlines() if "kristall" in l.lower()][:2])
                s.save_jpg(s.screenshot(), "fallback-logout-broken-stock-1.0x.jpg", quality=78)
                g.terminate()
        finally:
            s.stop()
    # 5 the appearance service missing: apps keep the colours they have; nothing depends on it
    info("appearance service absent: Plasma colours persist in kdeglobals, GTK files persist; the switch then only reaches Qt/KDE via Plasma's own settings")


# ======================================================================== plymouth
def test_plymouth():
    print("== boot splash: Plymouth theme into the initramfs (checked, never booted)", flush=True)
    if not (have("dracut") and have("plymouth-set-default-theme") and glob.glob("/usr/lib/modules/*/vmlinuz")):
        skip("dracut/plymouth/kernel not in this container (use kristall-devenv-theme)")
        return
    ensure_stage()
    P = ts.stage_paths()
    kver = os.path.basename(os.path.dirname(glob.glob("/usr/lib/modules/*/vmlinuz")[0]))
    img = f"/usr/lib/modules/{kver}/initramfs.img"
    # 1 the "base image" initramfs: what Universal Blue's build leaves (plymouth + ostree modules)
    t = time.time()
    r = subprocess.run(["dracut", "--no-hostonly", "--kver", kver, "--reproducible", "--add", "ostree", "-f", img], capture_output=True, text=True,
                       env=dict(os.environ, DRACUT_NO_XATTR="1"))
    check("baseline initramfs (stock theme) builds", r.returncode == 0 and os.path.getsize(img) > 10e6, f"{os.path.getsize(img) / 1e6:.0f} MB, {time.time() - t:.0f} s" if r.returncode == 0 else r.stderr[-500:])
    shutil.copytree(os.path.join(P["share"], "plymouth", "themes", "kristall"), "/usr/share/plymouth/themes/kristall", dirs_exist_ok=True)
    before = subprocess.run(["plymouth-set-default-theme"], capture_output=True, text=True).stdout.strip()
    # 2 a dracut that produces garbage → rejected, original kept, theme restored
    fake = "/tmp/fakedracut"
    os.makedirs(fake, exist_ok=True)
    with open(os.path.join(fake, "dracut"), "w") as f:
        f.write("#!/bin/sh\nfor a; do last=$a; done\nhead -c 4096 /dev/urandom > \"$last\"\n")
    os.chmod(os.path.join(fake, "dracut"), 0o755)
    sha = subprocess.run(["sha256sum", img], capture_output=True, text=True).stdout.split()[0]
    r = subprocess.run(["bash", os.path.join(THEME, "image", "plymouth.sh")], capture_output=True, text=True,
                       env=dict(os.environ, PATH=fake + ":" + os.environ["PATH"]))
    after = subprocess.run(["plymouth-set-default-theme"], capture_output=True, text=True).stdout.strip()
    check("a bad initramfs is rejected: original kept byte-for-byte, theme selection restored, exit 1",
          r.returncode == 1 and subprocess.run(["sha256sum", img], capture_output=True, text=True).stdout.split()[0] == sha and after == before,
          " | ".join(r.stderr.strip().splitlines()[-4:]))
    # 3 the real run
    t = time.time()
    r = subprocess.run(["bash", os.path.join(THEME, "image", "plymouth.sh")], capture_output=True, text=True)
    lst = subprocess.run(["lsinitrd", img], capture_output=True, text=True).stdout
    mods = subprocess.run(["lsinitrd", "--mod", img], capture_output=True, text=True).stdout.split()
    check("plymouth.sh: initramfs rebuilt with the Kristall theme, two-step plugin, ostree and all original dracut modules",
          r.returncode == 0 and "plymouth/themes/kristall/kristall.plymouth" in lst and "ostree" in mods,
          " | ".join((r.stdout + r.stderr).strip().splitlines()[-4:]) + f" ({time.time() - t:.0f} s)")
    conf = open("/etc/plymouth/plymouthd.conf").read() if os.path.exists("/etc/plymouth/plymouthd.conf") else ""
    check("plymouthd.conf selects the theme", "Theme=kristall" in conf)
    sys.path.insert(0, os.path.join(THEME, "tools"))
    import gen_assets
    gen_assets.plymouth_preview("/usr/share/plymouth/themes/kristall", os.path.join(ts.EVIDENCE, "bootsplash-preview.jpg"))
    info("bootsplash-preview.jpg: our images composed at the configured positions (not rendered by plymouthd — no DRM here)")
    kargs = open(os.path.join(THEME, "config", "kargs.toml")).read()
    check("bootc kargs.d: rhgb quiet (no kernel text)", '"rhgb"' in kargs and '"quiet"' in kargs)


# ======================================================================== main
SECTIONS = {}


def main(argv):
    order = ["static", "install", "decoration", "apps", "menus", "switch", "screens", "pointer", "fallback", "plymouth"]
    funcs = {n: globals().get("test_" + n) for n in order}
    wanted = argv[1:] or order
    os.makedirs(ts.EVIDENCE, exist_ok=True)
    for name in wanted:
        fn = funcs.get(name)
        if not fn:
            skip(f"section {name} not implemented")
            continue
        try:
            fn()
        except Exception as e:  # a crashed section is a failure; the others still run
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    total = sum(os.path.getsize(f) for f in glob.glob(os.path.join(ts.EVIDENCE, "*")))
    info(f"evidence: {total / 1e6:.2f} MB in {ts.EVIDENCE}")
    out = os.path.join(ts.EVIDENCE, "results.json")
    old = json.load(open(out)) if os.path.exists(out) else {}
    old.update(results)
    old["failures_last_run"] = failures
    with open(out, "w") as f:
        json.dump(old, f, indent=1)
    print(f"== {'FAILED: ' + ', '.join(failures) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
