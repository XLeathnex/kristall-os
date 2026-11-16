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

    # 3. crashes later in the session ---------------------------------------------------------------
    # KWin running normally with the effect active is killed with SIGSEGV twice (KWin's wrapper
    # restarts it each time); the third KWin starts with glass disabled. A new boot (fresh runtime
    # directory) starts with glass on again.
    import json
    import signal as _signal
    s = harness.Session(800, 600)
    runs = []

    def start_kwin(n):
        env = s.env()
        env["LD_PRELOAD"] = harness.SHIM
        env["KWIN_RESTART_COUNT"] = str(n)
        log = open(os.path.join(s.tmp, f"kwin-later{n}.log"), "w")
        p = subprocess.Popen([harness.KWIN, "--virtual", "--width", "800", "--height", "600", "--no-lockscreen", "--socket", s.wayland],
                             env=env, stdout=log, stderr=subprocess.STDOUT)
        harness.wait_until(lambda: os.path.exists(s.glass_socket), 20)
        time.sleep(1.5)
        return p, log

    try:
        for n in range(2):
            p, log = start_kwin(n)
            r = ctl(s, "check")
            runs.append(r.stdout.strip())
            p.send_signal(_signal.SIGSEGV)
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            log.close()
            if os.path.exists(s.glass_socket):
                os.unlink(s.glass_socket)
        p, log = start_kwin(2)
        s.kwin, s.kwin_log = p, log
        state = ctl(s, "check").stdout.strip()
        st = ctl(s, "status")
        try:
            guard = json.loads(st.stdout).get("guard", {})
        except ValueError:
            guard = {}
        check("crash later in the session: two SIGSEGVs within 10 minutes → the third KWin runs with glass off",
              runs == ["active", "active"] and state == "disabled" and guard.get("disabled") is True and len(guard.get("crashes", [])) == 2,
              f"before the crashes: {runs}, now '{state}', status guard {json.dumps(guard)}")
        check("kristall-glass-ctl status shows the guard record", "crashes" in guard and "windowSeconds" in guard, json.dumps(guard))
        s.stop_proc(p)
        s.kwin = None
        # a clean stop is not a crash, but a disabled session stays disabled until the next boot
        p, log = start_kwin(3)
        s.kwin, s.kwin_log = p, log
        st4 = ctl(s, "check").stdout.strip()
        check("…and stays off for the rest of the session (even after a clean restart)", st4 == "disabled", st4)
        s.stop_proc(p)
        s.kwin = None
        # next boot: the runtime directory is new
        os.unlink(os.path.join(s.runtime, "kristall", "glass.guard"))
        p, log = start_kwin(0)
        s.kwin, s.kwin_log = p, log
        st5 = ctl(s, "check").stdout.strip()
        check("next boot (fresh runtime directory): glass is tried again", st5 == "active", st5)
        s.stop_proc(p)
        s.kwin = None
        # one crash alone does not disable anything
        p, log = start_kwin(0)
        p.send_signal(_signal.SIGSEGV)
        p.wait(10)
        log.close()
        if os.path.exists(s.glass_socket):
            os.unlink(s.glass_socket)
        p, log = start_kwin(1)
        s.kwin, s.kwin_log = p, log
        st6 = ctl(s, "check").stdout.strip()
        check("a single crash: glass stays on (one crash is remembered for 10 minutes)", st6 == "active", st6)
    finally:
        s.stop()

    if FAILURES:
        print(f"{len(FAILURES)} fail-safe check(s) failed: {FAILURES}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
