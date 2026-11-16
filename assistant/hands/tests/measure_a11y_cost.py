# SPDX-License-Identifier: GPL-3.0-or-later
"""Measures what AT-SPI costs Qt apps (dev container, under dbus-run-session):
memory and CPU of Dolphin listing a large folder and of Kate idling, with accessibility off, on
(no assistant listening), and after a snapshot; plus the accessibility bus processes."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from support.session import Session  # noqa: E402


def cpu_rss(pid):
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    ticks = int(parts[11]) + int(parts[12])
    with open(f"/proc/{pid}/status") as f:
        rss = next(int(l.split()[1]) for l in f if l.startswith("VmRSS"))
    return ticks / os.sysconf("SC_CLK_TCK"), rss / 1024


def set_a11y(on):
    subprocess.run(["gdbus", "call", "--session", "-d", "org.a11y.Bus", "-o", "/org/a11y/bus", "-m",
                    "org.freedesktop.DBus.Properties.Set", "org.a11y.Status", "IsEnabled", f"<{'true' if on else 'false'}>"],
                   capture_output=True)


def registered():
    out = subprocess.run([sys.executable, "-c", "import gi; gi.require_version('Atspi','2.0'); from gi.repository import Atspi; "
                          "d=Atspi.get_desktop(0); print([d.get_child_at_index(i).get_name() for i in range(d.get_child_count())])"],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip()


def run(mode, folder="/usr/share/icons/breeze/actions/16"):
    with Session(name=f"cost{mode}") as s:
        os.environ.update({"XDG_RUNTIME_DIR": s.run, "WAYLAND_DISPLAY": s.wayland})
        set_a11y(mode != "off")
        time.sleep(0.5)
        p = s.app(["dolphin", "--new-window", folder], name="dolphin")
        k = s.app(["kate", "-n"], name="kate")
        time.sleep(8)
        c0, r0 = cpu_rss(p.pid)
        kc0, kr0 = cpu_rss(k.pid)
        time.sleep(10)
        c1, r1 = cpu_rss(p.pid)
        kc1, kr1 = cpu_rss(k.pid)
        res = {"dolphin_startup_cpu_s": round(c0, 2), "dolphin_rss_mb": round(r0, 1),
               "dolphin_idle_cpu_10s": round(c1 - c0, 3), "kate_startup_cpu_s": round(kc0, 2),
               "kate_rss_mb": round(kr0, 1), "kate_idle_cpu_10s": round(kc1 - kc0, 3)}
        if mode == "snapshot":
            t0 = time.monotonic()
            subprocess.run([sys.executable, "-c",
                            "import sys; sys.path.insert(0,'/work/assistant/hands'); "
                            "from kristall_hands.core import Hands; from kristall_hands.a11y import A11y; "
                            "from kristall_hands.bridge import Bridge; from kristall_hands.link import Link; "
                            "from kristall_hands.tooling import Context; "
                            "h=Hands(bridge=Bridge(path='/x'), link=Link(path='/x')); h.check_lock=False; a=A11y(h); "
                            "[a.snapshot(Context(), w) for w in ('dolphin','kate')]"], capture_output=True, timeout=60)
            res["two_snapshots_s"] = round(time.monotonic() - t0, 2)
            c2, r2 = cpu_rss(p.pid)
            res["dolphin_rss_after_snapshot_mb"] = round(r2, 1)
            res["dolphin_cpu_for_snapshot_s"] = round(c2 - c1, 3)
            set_a11y(False)
            time.sleep(2)
            res["registered_after_switch_off"] = registered()
        bus = subprocess.run(["sh", "-c", "for p in $(pgrep -f 'at-spi'); do grep VmRSS /proc/$p/status; done"],
                             capture_output=True, text=True).stdout.split()
        res["atspi_processes_rss_mb"] = round(sum(int(x) for x in bus if x.isdigit()) / 1024, 1)
        return res


if __name__ == "__main__":
    for mode in ("off", "on", "snapshot"):
        print(mode, run(mode), flush=True)
