# SPDX-License-Identifier: GPL-3.0-or-later
"""What accessibility-from-the-start costs (hands.md §5): Firefox (the RPM) idling on a static page
in a headless KWin session, accessibility off (old scheme before hands is used) versus on (the
generator's environment + IsEnabled at login), no assistant attached. Measures over WINDOW seconds
after a settle time: CPU time and wake-ups (context switches) of the Firefox processes, of the
AT-SPI bus/registry processes and of KWin. Dev container, under dbus-run-session:
    dbus-run-session -- python3 assistant/hands/tests/measure_session_a11y.py [rounds] [window]"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from support import firefox  # noqa: E402
from support.session import Session  # noqa: E402
from test_session_a11y import generator_env  # noqa: E402

TCK = os.sysconf("SC_CLK_TCK")


def procs(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]


def tree(root: int) -> list[int]:
    """root and all its descendants (Firefox's content, GPU, socket and utility processes)."""
    kids: dict[int, list[int]] = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open(f"/proc/{d}/stat") as f:
                    ppid = int(f.read().rsplit(")", 1)[1].split()[1])
                kids.setdefault(ppid, []).append(int(d))
            except (OSError, ValueError, IndexError):
                pass
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        out.append(p)
        todo.extend(kids.get(p, []))
    return out


def sample(pids: list[int]) -> tuple[float, int]:
    cpu, ctx = 0.0, 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                parts = f.read().rsplit(")", 1)[1].split()
            cpu += (int(parts[11]) + int(parts[12])) / TCK
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
                        ctx += int(line.split()[1])
            for tid in os.listdir(f"/proc/{pid}/task"):
                if int(tid) == pid:
                    continue
                with open(f"/proc/{pid}/task/{tid}/status") as f:
                    for line in f:
                        if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
                            ctx += int(line.split()[1])
        except (OSError, ValueError, IndexError):
            pass
    return cpu, ctx


def measure(on: bool, window: float, settle: float = 25.0) -> dict:
    tmp = tempfile.mkdtemp(prefix="kristall-ffcost-")
    with Session(name="ffcost" + ("1" if on else "0")) as s:
        os.environ.update({"XDG_RUNTIME_DIR": s.run, "WAYLAND_DISPLAY": s.wayland})
        dbusenv = generator_env(tmp) if on else {}
        subprocess.run(["gdbus", "call", "--session", "-d", "org.a11y.Bus", "-o", "/org/a11y/bus", "-m",
                        "org.freedesktop.DBus.Properties.Set", "org.a11y.Status", "IsEnabled",
                        f"<{'true' if on else 'false'}>"], capture_output=True)
        ff = firefox.start(s, tmp, dbusenv, name="ffcost")
        time.sleep(settle)
        groups = {"firefox": tree(ff.pid), "atspi": procs("at-spi"), "kwin": [s.kwin.pid]}
        before = {k: sample(v) for k, v in groups.items()}
        time.sleep(window)
        after = {k: sample(v) for k, v in groups.items()}
        res = {"a11y": "on" if on else "off", "window_s": window, "firefox_processes": len(groups["firefox"])}
        for k in groups:
            res[f"{k}_cpu_ms_per_s"] = round((after[k][0] - before[k][0]) * 1000 / window, 2)
            res[f"{k}_wakeups_per_s"] = round((after[k][1] - before[k][1]) / window, 1)
        with open(f"/proc/{ff.pid}/status") as f:
            res["firefox_main_rss_mb"] = round(next(int(l.split()[1]) for l in f if l.startswith("VmRSS")) / 1024, 1)
        return res


if __name__ == "__main__":
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    window = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    for _ in range(rounds):
        for on in (False, True):
            print(json.dumps(measure(on, window)), flush=True)
