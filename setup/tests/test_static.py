#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Static checks for the setup component (no compositor needed): shellcheck, JSON, strings
parity and coverage, the module's qmldir, the unit's live-session conditions, the start script's
behaviour in a live session and after setup, the helper's display-size arithmetic, settings
defaults through kristall-settings check-defaults."""
import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.dirname(HERE)
REPO = os.path.dirname(SETUP)
MOD = os.path.join(REPO, "shell", "modules", "setup")
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(name)


scripts = [os.path.join(SETUP, "image", "install.sh"), os.path.join(MOD, "image", "install.sh"), os.path.join(SETUP, "bin", "kristall-setup-start"),
           os.path.join(HERE, "run.sh"), os.path.join(HERE, "build.sh")]
if shutil.which("shellcheck"):
    r = subprocess.run(["shellcheck"] + scripts, capture_output=True, text=True)
    check("shellcheck: install scripts, start script, test scripts", r.returncode == 0, r.stdout[-800:])
else:
    print("INFO shellcheck not installed here (it is in the dev container)")

for path in [os.path.join(SETUP, "data", "50-setup.json"), os.path.join(MOD, "strings.json")] + glob.glob(os.path.join(SETUP, "settings", "kcms", "*", "*.json")):
    try:
        json.load(open(path))
        ok = True
    except ValueError as e:
        ok = False
    check(f"valid JSON: {os.path.relpath(path, REPO)}", ok)

# install.sh: System Settings' main entry opens Kristall's first page (the block run on a copy)
src = open(os.path.join(SETUP, "image", "install.sh")).read()
block = src[src.index("# System Settings opens on Kristall"):src.index("# the Setup Assistant's shell module")]
with tempfile.TemporaryDirectory() as pre:
    os.makedirs(os.path.join(pre, "share", "applications"))
    desk = os.path.join(pre, "share", "applications", "systemsettings.desktop")
    open(desk, "w").write("[Desktop Entry]\nExec=systemsettings\nName=System Settings\n\n[Desktop Action Users]\nExec=systemsettings kcm_users\n")
    for _ in range(2):
        subprocess.run(["bash", "-c", "set -euo pipefail\n" + block], env=dict(os.environ, PREFIX=pre), check=True)
    text = open(desk).read()
check("install: System Settings opens on Kristall's About page (Exec), actions untouched, idempotent",
      text.count("Exec=systemsettings kcm_kristall_about") == 1 and "Exec=systemsettings kcm_users" in text and "\nExec=systemsettings\n" not in text, text)

d = json.load(open(os.path.join(SETUP, "data", "50-setup.json")))
check("defaults drop-in holds only our top-level keys (keyboard, setup)", sorted(d) == ["keyboard", "setup"], str(sorted(d)))
check("defaults: Mac shortcuts on, setup not done", d["keyboard"]["macShortcuts"] is True and d["keyboard"]["commandKey"] == "ctrl" and d["setup"]["done"] is False)

strings = json.load(open(os.path.join(MOD, "strings.json")))
de, en = set(strings["de"]), set(strings["en"])
check("strings: German and English have the same keys", de == en, f"only de: {sorted(de - en)[:5]} only en: {sorted(en - de)[:5]}")
used = set()
for f in glob.glob(os.path.join(MOD, "*.qml")):
    used |= set(re.findall(r'Strings\.t\("(setup\.[A-Za-z0-9_.]*[A-Za-z0-9_])"\s*[,)]', open(f).read()))
missing = sorted(k for k in used if k not in en)
check("strings: every literal key used in the module exists", not missing, str(missing[:8]))
check("strings: keys start with the module name", all(k.startswith("setup.") for k in en))

qml = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(MOD, "*.qml")) if not f.endswith("Module.qml"))
listed = sorted(l.split()[-1][:-4] for l in open(os.path.join(MOD, "qmldir")) if l.strip() and not l.startswith("#"))
check("qmldir lists every type of the module", qml == listed, f"{set(qml) ^ set(listed)}")

unit = open(os.path.join(SETUP, "systemd", "kristall-setup.service")).read()
check("unit: never in the live session (kernel command line and /etc/kristall/live)",
      "ConditionKernelCommandLine=!rd.live.image" in unit and "ConditionPathExists=!/etc/kristall/live" in unit)
check("unit: preset enables it", "enable kristall-setup.service" in open(os.path.join(SETUP, "systemd", "50-kristall-setup.preset")).read())

for page in glob.glob(os.path.join(SETUP, "settings", "kcms", "*", "main.qml")):
    t = open(page).read()
    check(f"page {page.split('/')[-2]}: settings read through bindings that follow changes (no bare Settings.value)", "Settings.value(" not in t)

# the start script: live session, finished setup, normal start
tmp = tempfile.mkdtemp(prefix="kristall-setup-static-")
try:
    bin_ = os.path.join(tmp, "bin")
    os.makedirs(bin_)
    log = os.path.join(tmp, "calls")
    with open(os.path.join(bin_, "kristall-shellctl"), "w") as f:
        f.write(f"#!/bin/sh\necho \"$*\" >> {log}\n")
    with open(os.path.join(bin_, "kristall-settings"), "w") as f:
        f.write("#!/bin/sh\necho ${FAKE_DONE:-false}\n")
    with open(os.path.join(bin_, "logger"), "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    for n in os.listdir(bin_):
        os.chmod(os.path.join(bin_, n), 0o755)
    cmd = os.path.join(tmp, "cmdline")
    open(cmd, "w").write("quiet rw\n")

    def run(**env):
        if os.path.exists(log):
            os.remove(log)
        e = dict(os.environ, PATH=bin_ + ":" + os.environ["PATH"], KRISTALL_SETUP_CMDLINE=cmd, KRISTALL_SETUP_LIVE_MARKER=os.path.join(tmp, "live"), KRISTALL_SETUP_WAIT="2")
        e.update(env)
        r = subprocess.run(["bash", os.path.join(SETUP, "bin", "kristall-setup-start")], env=e, capture_output=True, text=True, timeout=20)
        return r.returncode, (open(log).read() if os.path.exists(log) else "")
    rc, calls = run()
    check("start script: first login → kristall-shellctl setup start", rc == 0 and calls.strip() == "setup start", calls)
    rc, calls = run(FAKE_DONE="true")
    check("start script: setup.done → nothing", rc == 0 and calls == "", calls)
    open(os.path.join(tmp, "live"), "w").close()
    rc, calls = run()
    check("start script: /etc/kristall/live → nothing", rc == 0 and calls == "", calls)
    os.remove(os.path.join(tmp, "live"))
    open(cmd, "w").write("BOOT_IMAGE=x rd.live.image quiet\n")
    rc, calls = run()
    check("start script: rd.live.image → nothing", rc == 0 and calls == "", calls)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# the helper's display sizes
loader = importlib.machinery.SourceFileLoader("ksh", os.path.join(SETUP, "bin", "kristall-setup-helper"))
spec = importlib.util.spec_from_loader("ksh", loader)
ksh = importlib.util.module_from_spec(spec)
loader.exec_module(ksh)
rec, ch = ksh.display_choices(2880, 345, 1.5, 1800)        # 16" 16:10 panel
scales = [c["scale"] for c in ch]
check(f"display sizes for a 2880×1800 / 345 mm panel are theme.md §7's: default 1.6, sizes 2.0 1.75 1.6 1.5 (got {rec}, {scales})",
      rec == 1.6 and scales == [2.0, 1.75, 1.6, 1.5])
rec, ch = ksh.display_choices(2880, 310, 1.5, 1800)        # 14" class panel: denser → larger default
check(f"a denser panel gets a larger default ({rec}, {[c['scale'] for c in ch]})", rec > 1.6)
rec, ch = ksh.display_choices(1280, 0, 1.0)
check(f"no physical size: around the current scale ({[c['scale'] for c in ch]})", rec == 1.0 and all(c["scale"] >= 1.0 for c in ch))

# settings defaults with the real tool
tool = os.path.join(REPO, "image", "rootfs", "usr", "bin", "kristall-settings")
if os.path.exists(tool):
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(SETUP, "data", "50-setup.json"), os.path.join(tmp, "50-setup.json"))
    # every component's drop-in under its installed name: the ownership check sees them all
    for src, name in (("shell/image/settings.json", "50-shell.json"), ("shell/modules/dock/image/settings.json", "50-dock.json"),
                      ("shell/modules/panels/image/settings.json", "50-panels.json"), ("assistant/core/data/settings-assistant.json", "50-assistant-core.json"),
                      ("assistant/hands/data/settings-hands.json", "50-assistant-hands.json"), ("shell/modules/assistant/image/settings.json", "60-assistant-ui.json"),
                      ("power/config/50-power.json", "50-power.json")):
        if os.path.exists(os.path.join(REPO, src)):
            shutil.copy(os.path.join(REPO, src), os.path.join(tmp, name))
    r = subprocess.run([sys.executable, tool, "check-defaults"], env=dict(os.environ, KRISTALL_SETTINGS_DROPIN_DIRS=tmp,
                       KRISTALL_SETTINGS_DEFAULTS=os.path.join(tmp, "none.json")), capture_output=True, text=True)
    check("kristall-settings check-defaults (with ownership) accepts 50-setup.json among all drop-ins", r.returncode == 0 and "ERROR" not in r.stdout and "WARN" not in r.stdout, r.stdout + r.stderr)
    shutil.rmtree(tmp, ignore_errors=True)

for f in [os.path.join(SETUP, "bin", "kristall-setup-helper")] + glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "support", "*.py")):
    r = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True)
    check(f"python compiles: {os.path.relpath(f, REPO)}", r.returncode == 0, r.stderr)

print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
sys.exit(1 if failures else 0)
