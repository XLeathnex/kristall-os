# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared settings (docs/contracts/settings.md) through `kristall-settings`, cached by file mtime."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from typing import Any

from . import log

DEFAULTS: dict[str, Any] = {
    "cursor": {
        "enabled": True,
        "speed": 1.0,
        "linger_seconds": 6
    },
    "accessibility": "always",
    "screenshot": {
        "max_width": 1280,
        "max_height": 800
    },
    "snapshot": {
        "max_items": 120,
        "max_depth": 30
    },
    "protected_apps": [
        "org.kde.polkit-kde-authentication-agent-1",
        "polkit-kde-authentication-agent-1",
        "org.kde.kwalletd6",
        "kwalletd6",
        "org.kde.kwalletmanager",
        "org.kde.ksshaskpass",
        "ksshaskpass",
        "pinentry",
        "pinentry-qt",
        "org.gnupg.pinentry-qt",
        "org.keepassxc.KeePassXC",
        "com.bitwarden.desktop",
        "com.1password.1Password",
        "1password",
        "kscreenlocker_greet",
        "org.kde.kscreenlocker_greet"
    ]
}


def tool_path() -> str | None:
    p = os.environ.get("KRISTALL_SETTINGS_BIN") or shutil.which("kristall-settings")
    return p if p and os.access(p, os.X_OK) else None


class Settings:
    def __init__(self):
        self._cache: dict | None = None
        self._stamp: tuple = ()
        self._paths: list[str] | None = None
        self._lock = threading.Lock()

    def _files(self) -> list[str]:
        if self._paths is None:
            exe = tool_path()
            paths: list[str] = []
            if exe:
                try:
                    out = subprocess.run([exe, "paths"], capture_output=True, text=True, timeout=5)
                    d = json.loads(out.stdout or "{}")
                    paths = list(d.get("defaults") or []) + [d.get("user")]
                except (OSError, ValueError, subprocess.SubprocessError):
                    paths = []
            paths = [p for p in paths if p]
            # watch the drop-in directories too (a new file changes the result)
            dirs = {os.path.dirname(p) for p in paths}
            self._paths = paths + sorted(dirs)
        return self._paths

    def _stamp_now(self) -> tuple:
        st = []
        for p in self._files():
            try:
                s = os.stat(p)
                st.append((p, s.st_mtime_ns, s.st_size))
            except OSError:
                st.append((p, 0, 0))
        return tuple(st)

    def all(self) -> dict:
        with self._lock:
            stamp = self._stamp_now()
            if self._cache is not None and stamp == self._stamp and stamp:
                return self._cache
            data: dict = {}
            exe = tool_path()
            if exe:
                try:
                    out = subprocess.run([exe, "get"], capture_output=True, text=True, timeout=5)
                    if out.returncode == 0:
                        data = json.loads(out.stdout or "{}")
                except (OSError, ValueError, subprocess.SubprocessError) as e:
                    log.warning("cannot read settings: %s", e)
            self._cache, self._stamp = data, stamp
            return data

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.all()
        for seg in path.split("."):
            if isinstance(cur, dict) and seg in cur:
                cur = cur[seg]
            else:
                return default
        return cur

    def hands(self) -> dict:
        h = self.get("assistant.hands", {}) or {}
        merged = json.loads(json.dumps(DEFAULTS))
        for k, v in h.items() if isinstance(h, dict) else []:
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        return merged

    def language(self) -> str:
        lang = self.get("assistant.language", "de")
        return lang if lang in ("de", "en") else "de"

    def set(self, path: str, value: Any) -> None:
        exe = tool_path()
        if not exe:
            raise OSError("kristall-settings is not installed")
        r = subprocess.run([exe, "set", path, json.dumps(value)], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise OSError(r.stderr.strip() or f"kristall-settings exited {r.returncode}")
        with self._lock:
            self._cache = None
