# SPDX-License-Identifier: GPL-3.0-or-later
"""File locations. Everything that touches the machine goes through `sys()`/`host()` so the test
suite can point the whole component at a fixture tree (KRISTALL_POWER_ROOT)."""
import os

ROOT = os.environ.get("KRISTALL_POWER_ROOT", "").rstrip("/")


def host(path: str) -> str:
    """Map an absolute host path (/sys/..., /proc/..., /run/..., /var/..., /etc/...)."""
    return ROOT + path if ROOT else path


SYS = host("/sys")
PROC = host("/proc")
RUN_DIR = host("/run/kristall-power")              # root-written runtime state, world-readable
STATE_DIR = host("/var/lib/kristall/power")        # root-written persistent state, world-readable
TUNED_DIR = host("/etc/tuned")


def user_runtime_dir() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(base, "kristall")


def user_state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "kristall", "power")


def session_state_file() -> str:
    """Written by the session daemon on every change (watch with inotify)."""
    return os.path.join(user_runtime_dir(), "power.json")


def glass_socket() -> str:
    return os.environ.get("KRISTALL_GLASS_SOCKET") or os.path.join(user_runtime_dir(), "glass.sock")
