# SPDX-License-Identifier: GPL-3.0-or-later
"""Workload measurement for automatic boosts. Only used while a heavy app is running on mains in
automatic mode (the session daemon samples every 10 s then, and not at all otherwise)."""
import os
import re
import time

from . import hw, paths, sysfs

CGROUP_ROOT = paths.host("/sys/fs/cgroup")


def app_of_unit(unit: str):
    """Application id from a systemd user unit named per the XDG convention
    `app[-<launcher>]-<AppID>[@<random>].service` / `app[-<launcher>]-<AppID>-<random>.scope`,
    e.g. app-flatpak-org.blender.Blender-12345.scope, app-org.kde.konsole@a1b2c3.service."""
    if not unit.startswith("app-") or not unit.endswith((".scope", ".service")):
        return None
    name = unit[4:].rsplit(".", 1)[0]
    name = name.split("@", 1)[0]
    if unit.endswith(".scope"):
        name = re.sub(r"-[0-9a-f]+$", "", name)
    if name.startswith("flatpak-"):
        name = name[len("flatpak-"):]
    return name or None


def matches(app: str, heavy_list):
    """True if `app` (possibly still carrying a launcher prefix) is one of the heavy apps."""
    a = (app or "").lower()
    for h in heavy_list or []:
        h = h.lower()
        if a == h or a.endswith("-" + h):
            return True
    return False


def cgroup_usage_usec(cgroup_path: str):
    st = sysfs.read(os.path.join(CGROUP_ROOT, cgroup_path.lstrip("/"), "cpu.stat"))
    if not st:
        return None
    m = re.search(r"^usage_usec (\d+)", st, re.M)
    return int(m.group(1)) if m else None


def gpu_idle_ms():
    total, n = 0, 0
    for p in hw.gpu_idle_residency_paths():
        v = sysfs.read_int(p)
        if v is not None:
            total += v
            n += 1
    return (total, n) if n else (None, 0)


class Sampler:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.prev = {}
        self.prev_gpu = None

    def sample(self, units: dict):
        """units: {unit_name: (app, cgroup_path)}. Returns ({app: cores}, gpu_busy or None)."""
        now = self.clock()
        cores = {}
        nxt = {}
        for unit, (app, cg) in units.items():
            u = cgroup_usage_usec(cg)
            if u is None:
                continue
            nxt[unit] = (now, u)
            if unit in self.prev:
                t0, u0 = self.prev[unit]
                if now > t0:
                    cores[app] = cores.get(app, 0.0) + max(u - u0, 0) / 1e6 / (now - t0)
        self.prev = nxt
        gpu_busy = None
        idle, n = gpu_idle_ms()
        if idle is not None:
            if self.prev_gpu and now > self.prev_gpu[0]:
                dt_ms = (now - self.prev_gpu[0]) * 1000 * n
                gpu_busy = min(max(1.0 - (idle - self.prev_gpu[1]) / dt_ms, 0.0), 1.0) if dt_ms else None
            self.prev_gpu = (now, idle)
        return cores, gpu_busy

    def reset(self):
        self.prev = {}
        self.prev_gpu = None


def system_cpu_busy(prev):
    """(busy fraction since prev, new prev) from /proc/stat; prev=None on first call."""
    txt = sysfs.read(os.path.join(paths.PROC, "stat"), "")
    m = re.match(r"cpu\s+(.+)", txt)
    if not m:
        return None, prev
    vals = [int(x) for x in m.group(1).split()]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals[:8])
    if not prev:
        return None, (idle, total)
    di, dt = idle - prev[0], total - prev[1]
    return (1.0 - di / dt if dt > 0 else None), (idle, total)
