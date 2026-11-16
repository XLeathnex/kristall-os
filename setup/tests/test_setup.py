#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Setup Assistant tests — the whole shell in a headless KWin with the glass effect, the real
bridge and our keyboard plugin; the owner's real pointer and keys (fake input). Sections:
  walk-de walk-en   the whole Setup Assistant by pointer and keyboard, every choice checked in the settings
  offline           offline start: the Wi-Fi step, our password sheet (wrong, then right), online
  signin-fail       installer fails → plain message, Try Again works; offline sign-in
  signin-abandon    sign-in abandoned in the browser: cancel, skip, resumes later; code pasted
  resume            killed (shell crash / restart) at every step → resumes at that step
  skip              "Set up later" on the welcome; request claude-signin opens the sign-in alone
  live              never starts in the installer's live session
  looks             screenshots: every step, light and dark, German; 1.6×, fallback, reduce motion
"""
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import setupsession as S  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.join(S.REPO, "kwin", "glass", "tests", "support"))
import pattern  # noqa: E402

EVIDENCE = os.path.join(HERE, "evidence")
failures, results = [], {}
check, info = S.A.check_factory(failures, results)
wait_until = S.wait_until
ORDER = ["welcome", "network", "appearance", "glass", "display", "keyboard", "trackpad", "assistant", "voice", "microphone",
         "privacy", "energy", "done"]


def save(img, name, crop=None, quality=80):
    im = Image.fromarray(img)
    if crop:
        im = im.crop(crop)
    os.makedirs(EVIDENCE, exist_ok=True)
    im.convert("RGB").save(os.path.join(EVIDENCE, name), quality=quality, optimize=True)


def calm_wallpaper(w, h, dark=False):
    """a quiet wallpaper like the owner will have (the busy test pattern is used for legibility)"""
    import numpy as np
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    t = (y / h)[..., None]
    a = np.array([30, 60, 120] if dark else [120, 170, 235], np.float32)
    b = np.array([70, 30, 90] if dark else [240, 190, 210], np.float32)
    img = a * (1 - t) + b * t
    for cx, cy, r, col in ((0.25, 0.3, 0.45, [90, 140, 255]), (0.8, 0.7, 0.5, [255, 140, 120])):
        d = np.sqrt(((x / w - cx) * w / h) ** 2 + (y / h - cy) ** 2) / r
        k = np.clip(1 - d, 0, 1)[..., None] ** 2 * (0.35 if dark else 0.5)
        img = img * (1 - k) + np.array(col, np.float32) * k
    return np.clip(img, 0, 255).astype(np.uint8)


def boot(s, wallpaper="calm"):
    s.start()
    if wallpaper:
        bg = os.path.join(s.tmp, "bg.png")
        if wallpaper == "busy":
            Image.fromarray(pattern.busy(s.width, s.height)).save(bg)
        else:
            Image.fromarray(calm_wallpaper(s.width, s.height, wallpaper == "calm-dark")).save(bg)
        s.background(bg)
    s.start_shell()
    wait_until(lambda: "module setup loaded" in s.shell_log() or "setup" in s.shell_log(), 15)
    st = s.wait_st(lambda st: st.get("liveChecked"), 15)
    if not st:
        raise RuntimeError("setup module did not come up:\n" + s.shell_log()[-3000:])
    return st


def shell_problems(s):
    bad = []
    for l in s.shell_log().splitlines():
        if ("modules/setup" in l or "setup:" in l.lower()) and ("WARN" in l or "ERROR" in l or "TypeError" in l or "ReferenceError" in l):
            bad.append(l)
    return bad


def test_smoke():
    print("== smoke: the module loads, start request opens the welcome", flush=True)
    s = S.SetupSession(name="setup-smoke", force_steps="trackpad", daemon=True,
                       apps_state={"schema": 1, "state": "installing", "total": 10, "done": 4})
    try:
        boot(s)
        r = s.request("start")
        check("kristall-shellctl setup start delivered", r.returncode == 0, r.stdout + r.stderr)
        st = s.wait_st(lambda st: st["open"] and st["step"] == "welcome", 8)
        check("the Setup Assistant opens at the welcome", bool(st and st["open"]), json.dumps(st)[:300])
        time.sleep(1.6)
        save(s.screenshot(), "smoke-welcome.jpg")
        for step in ORDER[1:]:
            s.ipc("setuptest", "go", step)
            time.sleep(1.0)
            save(s.screenshot(), f"smoke-{step}.jpg")
        bad = shell_problems(s)
        check("no QML warnings from the setup module", not bad, "\n".join(bad[:12]))
    finally:
        s.stop()


def segment_click(s, name, index, count):
    r = s.rect(name)
    if not r:
        raise RuntimeError(f"no {name} on screen; state {json.dumps(s.st())[:300]}")
    s.click(r["x"] + r["w"] * (index + 0.5) / count, r["y"] + r["h"] / 2)
    time.sleep(0.3)


def primary(s):
    s.click_named("setup.primary")
    time.sleep(0.5)


def at(s, step, timeout=6):
    st = s.wait_st(lambda st: st["step"] == step, timeout)
    return st and st["step"] == step


def shot(s, name, small=True):
    img = s.screenshot()
    im = Image.fromarray(img)
    if small and im.width > 1100:
        im = im.resize((im.width * 1024 // im.width, im.height * 1024 // im.width), Image.LANCZOS)
    os.makedirs(EVIDENCE, exist_ok=True)
    im.convert("RGB").save(os.path.join(EVIDENCE, name), quality=74, optimize=True)


def walk(lang):
    de = lang == "de"
    print(f"== the whole Setup Assistant by pointer and keyboard ({'German' if de else 'English'})", flush=True)
    s = S.SetupSession(name=f"setup-walk-{lang}", lang="de_DE" if de else "en_US", daemon=True, account="success",
                       apps_state={"schema": 1, "state": "installing", "total": 10, "done": 4,
                                   "current": {"id": "blender", "name": {"en": "Blender", "de": "Blender"}}})
    try:
        boot(s)
        r = s.request("start")
        check(f"[{lang}] start request (kristall-shellctl setup start) delivered", r.returncode == 0, r.stderr)
        check(f"[{lang}] opens at the welcome", at(s, "welcome"))
        check(f"[{lang}] setting setup.running = true", s.wait_st(lambda st: True) and wait_until(lambda: s.setting("setup.running") is True, 4))
        time.sleep(1.3)
        s.click_named("setup.welcome.start")
        check(f"[{lang}] online: the Wi-Fi step is left out, Continue leads to the looks", at(s, "appearance"))
        # appearance: pointer for the theme and accent, keyboard (→) for automatic
        s.click_named("setup.theme.dark")
        check(f"[{lang}] click Dark → appearance.theme = dark (live)", wait_until(lambda: s.setting("appearance.theme") == "dark", 4))
        s.click_named("setup.accent.purple")
        check(f"[{lang}] click purple → appearance.accent = purple", wait_until(lambda: s.setting("appearance.accent") == "purple", 4))
        s.tap("right")
        check(f"[{lang}] → key → Automatic", wait_until(lambda: s.setting("appearance.theme") == "auto", 4))
        if not de:
            s.click_named("setup.theme.light")
            wait_until(lambda: s.setting("appearance.theme") == "light", 4)
            s.click_named("setup.accent.blue")
        primary(s)
        check(f"[{lang}] Continue → glass", at(s, "glass"))
        r = s.rect("setup.glass.slider")
        s.click(r["x"] + 14 + (r["w"] - 28) * 0.8, r["y"] + r["h"] / 2)
        ok = wait_until(lambda: abs(float(s.setting("appearance.glass", 0)) - 0.8) < 0.06, 4)
        check(f"[{lang}] click on the slider at 80 % → appearance.glass ≈ 0.8", bool(ok), str(s.setting("appearance.glass")))
        s.tap("left")
        ok = wait_until(lambda: abs(float(s.setting("appearance.glass", 0)) - 0.7) < 0.06, 4)
        check(f"[{lang}] ← key → 0.7", bool(ok), str(s.setting("appearance.glass")))
        s.tap("enter")
        check(f"[{lang}] Return = Continue → display size", at(s, "display"))
        st = s.st()
        outs = st["displays"]
        check(f"[{lang}] display sizes offered for the output (no percentages)", bool(outs) and len(outs[0]["choices"]) >= 2, json.dumps(outs)[:200])
        if outs and len(outs[0]["choices"]) >= 2:
            before = outs[0]["scale"]
            s.click_named("setup.display.0")
            ok = s.wait_st(lambda st: st["displays"] and abs(st["displays"][0]["scale"] - outs[0]["choices"][0]["scale"]) < 0.01, 10)
            check(f"[{lang}] 'Larger text' sets the output scale ({before} → {outs[0]['choices'][0]['scale']}) live",
                  bool(ok) and abs(ok["displays"][0]["scale"] - outs[0]["choices"][0]["scale"]) < 0.01, json.dumps(ok["displays"] if ok else None)[:200])
            time.sleep(1.0)
            shot(s, f"walk-{lang}-display-larger.jpg")
            rec = [i for i, c in enumerate(outs[0]["choices"]) if abs(c["scale"] - outs[0]["recommended"]) < 0.01]
            s.click_named(f"setup.display.{rec[0] if rec else len(outs[0]['choices']) - 1}")
            s.wait_st(lambda st: st["displays"] and abs(st["displays"][0]["scale"] - before) < 0.01, 10)
            time.sleep(1.0)
        primary(s)
        check(f"[{lang}] Continue → keyboard", at(s, "keyboard"))
        if de:
            # try it: physical Alt (Command) + C arrives as Control+C
            s.tap("leftalt", "c")
            ok = wait_until(lambda: "Befehl-C" in s.ipc("setuptest", "text", "setup.keyboard.try"), 3)
            check("[de] try it: the owner presses Alt+C → 'Das war Befehl-C' (the plugin is translating)", bool(ok), s.ipc("setuptest", "text", "setup.keyboard.try"))
            shot(s, "walk-de-keyboard-tried.jpg")
        else:
            segment_click(s, "setup.keyboard.choice", 1, 2)
            check("[en] 'Keep PC Shortcuts' → keyboard.macShortcuts = false, commandKey = ''",
                  wait_until(lambda: s.setting("keyboard.macShortcuts") is False and s.setting("keyboard.commandKey") == "", 4))
            ok = wait_until(lambda: (lambda k: k and k.get("reason") == "off")(s.st().get("keyboard")), 4)
            check("[en] the keyboard plugin follows live (status off)", bool(ok), json.dumps(s.st().get("keyboard")))
            s.tap("leftctrl", "c")
            ok = wait_until(lambda: "Ctrl-C" in s.ipc("setuptest", "text", "setup.keyboard.try"), 3)
            check("[en] try it with PC keys: Ctrl+C → 'That's Ctrl-C — the PC way'", bool(ok), s.ipc("setuptest", "text", "setup.keyboard.try"))
        primary(s)
        if de:
            check("[de] Continue → keyboard.macShortcuts = true, commandKey = ctrl", wait_until(lambda: s.setting("keyboard.macShortcuts") is True and s.setting("keyboard.commandKey") == "ctrl", 4))
        check(f"[{lang}] no touchpad here: the trackpad step is left out → assistant", at(s, "assistant"))
        st = s.wait_st(lambda st: st["account"]["phase"] in ("idle", "ready") and st["account"]["status"] != "", 6)
        time.sleep(0.4)
        check(f"[{lang}] account checked: Claude not installed yet", st["account"]["status"] == "cli_missing", json.dumps(st["account"]))
        if de:
            primary(s)    # "Mit Claude anmelden"
            st = s.wait_st(lambda st: st["account"]["phase"] in ("working", "browser"), 4)
            shot(s, "walk-de-signin-installing.jpg")
            st = s.wait_st(lambda st: st["account"]["phase"] == "browser", 8)
            check("[de] installed with the official installer, then 'Weiter im Browser' with the sign-in page",
                  st["account"]["phase"] == "browser" and st["account"]["url"].startswith("https://claude.ai/"), json.dumps(st["account"]))
            shot(s, "walk-de-signin-browser.jpg")
            st = s.wait_st(lambda st: st["account"]["phase"] == "ready", 10)
            check("[de] signed in → 'Du bist angemeldet'", st["account"]["phase"] == "ready", json.dumps(st["account"]))
            shot(s, "walk-de-signin-ready.jpg")
            calls = open(os.path.join(s.acct_dir, "calls.log")).read().split("\n")
            check("[de] account commands called: status, install, login --open", calls[:3] == ["status", "install", "login --open"], str(calls))
            primary(s)
        else:
            s.click_named("setup.secondary")      # Not Now
        check(f"[{lang}] → name and voice", at(s, "voice"))
        s.click_named("setup.voice.name")
        if de:
            s.tap("leftalt", "a")                # ⌘A selects all (Mac shortcuts on)
        else:
            s.tap("leftctrl", "a")
        s.type_text("Luna")
        s.tap("enter")
        check(f"[{lang}] typed name → assistant.name = Luna", wait_until(lambda: s.setting("assistant.name") == "Luna", 4), str(s.setting("assistant.name")))
        segment_click(s, "setup.voice.speak", 0, 3)
        check(f"[{lang}] 'read answers aloud: always' → assistant.speak_replies = always", wait_until(lambda: s.setting("assistant.speak_replies") == "always", 4))
        if not de:
            segment_click(s, "setup.voice.language", 1, 2)
            check("[en] language English → assistant.language = en", wait_until(lambda: s.setting("assistant.language") == "en", 4))
        primary(s)
        check(f"[{lang}] → microphone check", at(s, "microphone"))
        st = s.wait_st(lambda st: st["mic"] and st["mic"]["ready"], 8)
        check(f"[{lang}] the microphone check is connected to the assistant (demo daemon)", bool(st and st["mic"] and st["mic"]["ready"]), json.dumps(st.get("mic") if st else None))
        s.click_named("setup.mic.listen")
        st = s.wait_st(lambda st: st["mic"] and st["mic"]["phase"] == "heard", 20)
        check(f"[{lang}] the owner's words appear, transcribed (demo transcript)", st and st["mic"]["phase"] == "heard" and st["mic"]["transcript"] != "",
              json.dumps(st.get("mic") if st else None))
        time.sleep(0.6)
        shot(s, f"walk-{lang}-microphone-heard.jpg")
        primary(s)
        check(f"[{lang}] → privacy", at(s, "privacy"))
        s.tap("enter")
        check(f"[{lang}] Return → energy", at(s, "energy"))
        if de:
            s.click_named("setup.energy.limit")
            check("[de] 'Batterie schonen' → power.chargeLimit = 80", wait_until(lambda: s.setting("power.chargeLimit") == 80, 4))
        primary(s)
        check(f"[{lang}] Continue keeps automatic energy on (power.automatic = true)", s.setting("power.automatic") is True)
        check(f"[{lang}] → the closing screen", at(s, "done"))
        txt = s.ipc("setuptest", "text", "setup.finish.apps")
        check(f"[{lang}] apps progress from the apps contract: '{txt}'", ("4 von 10" if de else "4 of 10") in txt, txt)
        s.set_apps({"schema": 1, "state": "done", "total": 10, "done": 10})
        ok = wait_until(lambda: ("bereit" if de else "ready") in s.ipc("setuptest", "text", "setup.finish.apps"), 5)
        check(f"[{lang}] follows the status file live (inotify): apps ready", bool(ok), s.ipc("setuptest", "text", "setup.finish.apps"))
        primary(s)
        st = s.wait_st(lambda st: not st["open"], 5)
        check(f"[{lang}] 'Start using Kristall' closes it", not st["open"])
        check(f"[{lang}] setup.done = true, setup.running = false", wait_until(lambda: s.setting("setup.done") is True and s.setting("setup.running") is False, 4))
        bad = shell_problems(s)
        check(f"[{lang}] no QML warnings from the setup module", not bad, "\n".join(bad[:8]))
    finally:
        s.stop()


def test_walk_de():
    walk("de")


def test_walk_en():
    walk("en")


def test_offline():
    print("== offline: the Wi-Fi step, our password sheet (wrong, then right), online", flush=True)
    s = S.SetupSession(name="setup-offline", offline=True)
    try:
        boot(s)
        s.request("start")
        at(s, "welcome")
        time.sleep(1.2)
        s.tap("enter")
        check("offline: Return on the welcome → the Wi-Fi step comes first", at(s, "network"))
        ok = s.rect("setup.wifi:Zuhause", 10)
        check("the networks around are listed", bool(ok))
        time.sleep(0.5)
        shot(s, "offline-de-network-list.jpg")
        s.click_named("setup.wifi:Zuhause")
        r = s.rect("setup.wifi.password")
        check("a new protected network asks for its password in our own sheet", bool(r))
        s.click_named("setup.wifi.password")
        s.type_text("falsch123")
        s.tap("enter")
        time.sleep(2.0)
        shot(s, "offline-de-password-wrong.jpg")
        check("a wrong password is said plainly, the sheet stays", s.rect("setup.wifi.password") is not None and not s.st()["steps"] == [])
        s.tap("leftalt", "a")
        s.type_text("richtig123")
        s.tap("enter")
        ok = wait_until(lambda: s.rect("setup.wifi.password", 0.3) is None, 10)
        check("the right password joins; the sheet closes", bool(ok))
        st = s.wait_st(lambda st: st["primary"] in ("Weiter", "Continue"), 8)
        check("online now: the button says Continue", st["primary"] == "Weiter", st["primary"])
        shot(s, "offline-de-online.jpg")
        primary(s)
        check("→ appearance (the Wi-Fi step stays in the list for Back)", at(s, "appearance") and "network" in s.st()["steps"])
    finally:
        s.stop()


def set_scenario(s, name):
    with open(os.path.join(s.acct_dir, "scenario"), "w") as f:
        f.write(name)


def test_signin_fail():
    print("== sign-in: the installer fails, then works; offline", flush=True)
    s = S.SetupSession(name="setup-signin-fail", account="install-fail")
    try:
        boot(s)
        s.request("start", "assistant")
        check("start at a named step (start -- assistant)", at(s, "assistant"))
        s.wait_st(lambda st: st["account"]["phase"] == "idle" and st["account"]["status"] != "", 6)
        primary(s)
        st = s.wait_st(lambda st: st["account"]["phase"] == "failed", 10)
        check("installer fails → failed with a plain message, no jargon", st["account"]["phase"] == "failed", json.dumps(st["account"]))
        check("the button offers 'Erneut versuchen'", st["primary"] == "Erneut versuchen", st["primary"])
        shot(s, "signin-de-install-failed.jpg")
        set_scenario(s, "success")
        primary(s)
        st = s.wait_st(lambda st: st["account"]["phase"] == "ready", 15)
        check("Try Again → installed and signed in", st["account"]["phase"] == "ready", json.dumps(st["account"]))
        s.ipc("setuptest", "go", "voice")
        # offline sign-in from the start
        with open(os.path.join(s.acct_dir, "state.json"), "w") as f:
            f.write('{"status": "cli_missing"}')
        set_scenario(s, "offline")
        s.ipc("setuptest", "go", "assistant")
        s.wait_st(lambda st: st["account"]["phase"] in ("idle", "ready") and st["account"]["status"] != "", 6)
        time.sleep(0.4)
        primary(s)
        st = s.wait_st(lambda st: st["account"]["phase"] == "failed", 10)
        check("offline → 'needs the internet' message", st["account"]["phase"] == "failed" and st["account"]["error"]["code"] == "offline", json.dumps(st["account"]))
        shot(s, "signin-de-offline.jpg")
        s.click_named("setup.secondary")
        check("'Jetzt nicht' always moves on", at(s, "voice"))
    finally:
        s.stop()


def test_signin_abandon():
    print("== sign-in abandoned in the browser; cancel, skip, later from the assistant; a pasted code", flush=True)
    s = S.SetupSession(name="setup-signin-abandon", account="abandon", account_start="signed_out", settings={"setup": {"done": True}})
    try:
        boot(s)
        r = s.request("claude-signin", "sign_in")
        check("request claude-signin opens the sign-in on its own", s.wait_st(lambda st: st["open"] and st["mode"] == "signin")["mode"] == "signin")
        s.wait_st(lambda st: st["account"]["phase"] == "idle" and st["account"]["status"] != "", 6)
        time.sleep(0.5)
        shot(s, "signin-de-alone.jpg")
        primary(s)
        st = s.wait_st(lambda st: st["account"]["phase"] == "browser", 6)
        check("waiting for the browser", st["account"]["phase"] == "browser")
        check("Cancel is offered while waiting", st["secondary"] == "Abbrechen", st["secondary"])
        s.click_named("setup.secondary")
        st = s.wait_st(lambda st: st["account"]["phase"] == "cancelled", 6)
        check("abandoned: cancel stops the sign-in, says so plainly", st["account"]["phase"] == "cancelled", json.dumps(st["account"]))
        shot(s, "signin-de-cancelled.jpg")
        s.tap("esc")
        st = s.wait_st(lambda st: not st["open"], 5)
        check("Escape closes the sign-in sheet; nothing else changes (setup.done stays true)", not st["open"] and s.setting("setup.done") is True)
        set_scenario(s, "need-code")
        s.request("claude-signin")
        s.wait_st(lambda st: st["open"] and st["account"]["phase"] in ("idle", "cancelled") and st["account"]["status"] != "", 6)
        time.sleep(0.4)
        primary(s)
        st = s.wait_st(lambda st: st["account"]["needCode"], 6)
        check("the browser shows a code → a field to paste it", st["account"]["needCode"])
        s.click_named("setup.assistant.code")
        for ch in "KRISTALL-1234":
            if ch == "-":
                s.tap("slash")   # '-' on the German layout is the key right of '.'
            elif ch.isdigit():
                s.tap(ch)
            else:
                s.tap("leftshift", ch.lower())
        s.tap("enter")
        st = s.wait_st(lambda st: st["account"]["phase"] in ("ready", "failed"), 8)
        info("fake account calls: " + open(os.path.join(s.acct_dir, "calls.log")).read().replace("\n", " | "))
        check("the pasted code completes the sign-in", st["account"]["phase"] == "ready", json.dumps(st["account"]))
        primary(s)
        check("Done closes it", not s.wait_st(lambda st: not st["open"], 5)["open"])
    finally:
        s.stop()


def test_resume():
    print("== resume: the shell is killed at every step and comes back at that step", flush=True)
    s = S.SetupSession(name="setup-resume", force_steps="trackpad,network")
    try:
        boot(s)
        s.request("start")
        at(s, "welcome")
        for step in ORDER[1:]:
            s.ipc("setuptest", "go", step)
            wait_until(lambda: s.setting("setup.step") == step, 4)
            s.shell.send_signal(signal.SIGKILL)
            s.shell.wait(5)
            s.procs.remove(s.shell)
            s.start_shell()
            st = s.wait_st(lambda st: st["open"] and st["step"] == step, 15)
            check(f"killed at '{step}' → resumes at '{step}'", bool(st) and st["open"] and st["step"] == step, json.dumps(st)[:160] if st else "no state")
        primary(s)
        wait_until(lambda: s.setting("setup.done") is True, 5)
        s.shell.send_signal(signal.SIGKILL)
        s.shell.wait(5)
        s.procs.remove(s.shell)
        s.start_shell()
        st = s.wait_st(lambda st: st["liveChecked"], 15)
        time.sleep(1.5)
        check("after finishing, a restart does not bring it back", not s.st()["open"])
    finally:
        s.stop()


def test_skip():
    print("== skipped entirely; opened again later", flush=True)
    s = S.SetupSession(name="setup-skip")
    try:
        boot(s)
        s.request("start")
        at(s, "welcome")
        time.sleep(1.3)
        s.click_named("setup.welcome.later")
        st = s.wait_st(lambda st: not st["open"], 5)
        check("'Später einrichten' closes it at once", not st["open"])
        check("setup.done = true, setup.skipped = true; defaults stay (Mac keys on)",
              wait_until(lambda: s.setting("setup.done") is True and s.setting("setup.skipped") is True, 4) and s.setting("keyboard.macShortcuts") is True)
        s.request("start")
        check("opened again later (as from Settings) → the welcome", at(s, "welcome"))
    finally:
        s.stop()


def test_live():
    print("== the installer's live session: never starts", flush=True)
    s = S.SetupSession(name="setup-live")
    try:
        open(s.live_marker, "w").close()
        boot(s)
        s.request("start")
        time.sleep(2.0)
        st = s.st()
        check("live marker /etc/kristall/live present → start is refused", st["live"] and not st["open"], json.dumps(st)[:200])
    finally:
        s.stop()
    s = S.SetupSession(name="setup-live2", settings={"setup": {"running": True, "step": "glass"}})
    try:
        with open(s.cmdline, "w") as f:
            f.write("BOOT_IMAGE=/images/pxeboot/vmlinuz rd.live.image quiet\n")
        boot(s)
        time.sleep(2.0)
        st = s.st()
        check("kernel command line rd.live.image → no resume either", st["live"] and not st["open"], json.dumps(st)[:200])
    finally:
        s.stop()


def looks_run(name, theme="light", lang="de_DE", scale=1.0, glass=True, reduce_motion=False, steps=None, prefix="setup", width=1280, height=800):
    settings = {"appearance": {"theme": theme, "glass": 0.3}}
    if reduce_motion:
        settings["accessibility"] = {"reduceMotion": True}
    s = S.SetupSession(name=name, lang=lang, settings=settings, daemon=True, force_steps="trackpad,network", glass=glass,
                       width=width, height=height, scale=scale,
                       apps_state={"schema": 1, "state": "installing", "total": 10, "done": 4})
    try:
        boot(s, "calm-dark" if theme == "dark" else "calm")
        s.request("start")
        at(s, "welcome")
        time.sleep(1.8)
        tag = f"{theme}-{lang[:2]}" + ("" if scale == 1.0 else f"-{scale}x") + ("" if glass else "-fallback") + ("-reducemotion" if reduce_motion else "")
        for step in steps or ORDER:
            if step != "welcome":
                s.ipc("setuptest", "go", step)
                at(s, step)
                time.sleep(1.0)
            if step == "microphone":
                s.wait_st(lambda st: st["mic"] and st["mic"]["ready"], 8)
                s.click_named("setup.mic.listen")
                s.wait_st(lambda st: st["mic"] and st["mic"]["phase"] == "heard", 20)
                time.sleep(0.6)
            if step == "assistant":
                s.wait_st(lambda st: st["account"]["phase"] == "idle" and st["account"]["status"] != "", 6)
                time.sleep(0.5)
            shot(s, f"{prefix}-{step}-{tag}.jpg")
        bad = shell_problems(s)
        check(f"looks {tag}: every step drawn without QML warnings", not bad, "\n".join(bad[:6]))
    finally:
        s.stop()


def test_looks():
    print("== screenshots: every step, light and dark, German; English; 1.6×; no glass; reduce motion", flush=True)
    for f in os.listdir(EVIDENCE) if os.path.isdir(EVIDENCE) else []:
        if f.startswith("smoke-"):
            os.remove(os.path.join(EVIDENCE, f))
    only = os.environ.get("KRISTALL_LOOKS_ONLY", "")
    if not only or "main" in only:
        looks_run("setup-looks-light", "light")
        looks_run("setup-looks-dark", "dark")
        looks_run("setup-looks-en", "light", lang="en_US", steps=["welcome", "keyboard", "assistant", "privacy", "done"])
        looks_run("setup-looks-16", "light", scale=1.6, width=2880, height=1800, steps=["welcome", "appearance", "keyboard", "done"])
    looks_run("setup-looks-fallback", "light", glass=False, steps=["appearance", "energy"])
    looks_run("setup-looks-rm", "dark", reduce_motion=True, steps=["welcome", "glass"])
    # legibility over the busiest wallpaper (the shell's test pattern)
    s = S.SetupSession(name="setup-looks-busy")
    try:
        boot(s, "busy")
        s.request("start", "privacy")
        at(s, "privacy")
        time.sleep(1.2)
        shot(s, "setup-privacy-light-de-busy-wallpaper.jpg")
    finally:
        s.stop()


SECTIONS = {"looks": test_looks, "smoke": test_smoke, "walk-de": test_walk_de, "walk-en": test_walk_en, "offline": test_offline,
            "signin-fail": test_signin_fail, "signin-abandon": test_signin_abandon, "resume": test_resume,
            "skip": test_skip, "live": test_live}

if __name__ == "__main__":
    want = sys.argv[1:] or [k for k in SECTIONS if k != "smoke"]
    for name in want:
        try:
            SECTIONS[name]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
