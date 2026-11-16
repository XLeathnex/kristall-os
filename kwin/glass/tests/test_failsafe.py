#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Fail-soft checks: (1) a plugin that cannot load leaves KWin compositing without glass,
# (2) an effect that crashes KWin at start-up is disabled by the crash guard after two
# attempts instead of looping, (3) clients see "absent"/"disabled" and can fall back.
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import harness  # noqa: E402

FAILURES = []
CTL = os.path.join(os.path.dirname(HERE), "tools", "kristall-glass-ctl")


def check(name, ok, detail):
    print(("PASS " if ok else "FAIL ") + name + ": " + detail, flush=True)
    if not ok:
        FAILURES.append(name)


def support_info(s):
    r = subprocess.run(["dbus-send", "--session", "--print-reply", "--dest=org.kde.KWin", "/KWin", "org.kde.KWin.supportInformation"],
                       capture_output=True, text=True, timeout=20, env=s.env())
    return r.stdout


def ctl(s, *args):
    return subprocess.run([sys.executable, CTL, *args], capture_output=True, text=True, timeout=20, env=s.env())


def main():
    broken = os.environ.get("KRISTALL_GLASS_BROKEN_PLUGINS")
    # 1. unloadable plugin (unresolved symbol) ---------------------------------------------------
    if broken:
        s = harness.Session(800, 600, env={"QT_PLUGIN_PATH": broken})
        s.start(wait_glass=False)
        try:
            time.sleep(3)
            info = support_info(s)
            loaded = "kristall_glass" in info.split("Loaded Effects:")[1].split("Currently Active Effects:")[0] if "Loaded Effects:" in info else None
            r = ctl(s, "check")
            check("unloadable plugin: KWin keeps compositing, glass is simply absent",
                  s.kwin.poll() is None and "Compositing is active" in info and loaded is False and r.returncode == 1 and "absent" in r.stdout,
                  f"KWin running={s.kwin.poll() is None}, compositing={'Compositing is active' in info}, effect loaded={loaded}, ctl check -> {r.stdout.strip()} (exit {r.returncode})")
            failed_line = [l for l in s.log_text().splitlines() if "kristall_glass" in l][:2]
            print("   KWin log:", failed_line)
        finally:
            s.stop()
    else:
        check("unloadable plugin", False, "KRISTALL_GLASS_BROKEN_PLUGINS not set (tests/run.sh builds it)")

    # 2. crash loop guard ------------------------------------------------------------------------------
    # KWin's wrapper restarts KWin after every crash; emulate that with one runtime dir.
    s = harness.Session(800, 600, env={"KRISTALL_GLASS_TEST_CRASH": "1"})
    outcomes = []
    try:
        for attempt in range(4):
            env = s.env()
            env["LD_PRELOAD"] = harness.SHIM
            env["KWIN_RESTART_COUNT"] = str(attempt)
            log = open(os.path.join(s.tmp, f"kwin{attempt}.log"), "w")
            p = subprocess.Popen([harness.KWIN, "--virtual", "--width", "800", "--height", "600", "--no-lockscreen", "--socket", s.wayland],
                                 env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                p.wait(12)
                outcomes.append(f"exit {p.returncode}")
            except subprocess.TimeoutExpired:
                outcomes.append("running")
                s.kwin = p
                s.kwin_log = log
                break
        guard = os.path.join(s.runtime, "kristall", "glass.guard")
        state = None
        if s.kwin and s.kwin.poll() is None:
            time.sleep(1)
            r = ctl(s, "check")
            state = r.stdout.strip()
        check("crash at start-up: after two crashes the guard keeps glass off and KWin runs",
              outcomes[:2] == [o for o in outcomes[:2] if o.startswith("exit")] and outcomes[-1] == "running" and len(outcomes) == 3 and state == "disabled",
              f"attempts: {outcomes}, guard file {'present' if os.path.exists(guard) else 'absent'}, client sees state '{state}'")
    finally:
        s.stop()

    if FAILURES:
        print(f"{len(FAILURES)} fail-safe check(s) failed: {FAILURES}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
