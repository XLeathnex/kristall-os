# SPDX-License-Identifier: GPL-3.0-or-later
"""Paths and settings.

Settings live in the shared settings under the ``assistant`` key, merged as
docs/contracts/settings.md specifies (defaults file, ``settings.d`` drop-ins,
``/etc/kristall/settings.d``, user file).  We only read; ``kristall-settings``
writes.  The directories are watched with inotify (no polling) so changes
apply live.
"""
from __future__ import annotations

import copy
import ctypes
import ctypes.util
import json
import logging
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("kristall.config")

PREFIX = os.environ.get("KRISTALL_PREFIX", "/usr")

# Built-in defaults: identical to data/settings-assistant.json, which install.sh
# contributes to the shared defaults file.  Kept here so the daemon works even
# when the defaults file is missing (fail soft).
DEFAULTS: dict[str, Any] = {
    "enabled": True,                  # the owner uses the assistant (gates session-wide accessibility, hands.md §5)
    "name": "Kristall",
    "language": "de",                 # "de" | "en": first language; replies follow the owner
    "owner_name": "",
    "voice": {"de": "de_DE-thorsten-medium", "en": "en_US-joe-medium"},
    "speaking_rate": 1.0,             # 0.7 … 1.4
    "input_mode": "voice",            # "voice" | "text": what the hotkey starts with
    "speak_replies": "voice_only",    # "always" | "voice_only" | "never"
    "recognizer": "parakeet",         # "parakeet" (de+en, automatic) | "canary-de" (German only)
    "barge_in": "auto",               # "auto" | "on" | "off" (needs an echo-cancelled microphone)
    "wake_word": False,               # reserved, not implemented
    "duck_other_audio": True,
    "model": "claude-haiku-5-5",
    "effort": "low",                  # "low" keeps the first word under a second
    "conversation_window_seconds": 180,
    "end_of_speech_ms": 800,
    "no_speech_timeout_seconds": 7,
    "max_utterance_seconds": 45,
    "models_unload_after_seconds": 300,
    "brain_unload_after_seconds": 600,
    "permission_timeout_seconds": 120,
}


def _xdg(var: str, fallback: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v else Path.home() / fallback


@dataclass(frozen=True)
class Paths:
    runtime_dir: Path
    socket: Path
    config_dir: Path        # ~/.config/kristall
    settings_file: Path
    state_dir: Path         # ~/.local/share/kristall/assistant
    workspace: Path         # Claude's working directory (private)
    memory_file: Path
    grants_file: Path
    cache_dir: Path
    defaults_file: Path
    settings_dropin_dirs: tuple
    share_dir: Path         # /usr/share/kristall/assistant
    models_dir: Path
    system_mcp_dir: Path
    user_mcp_dir: Path

    @classmethod
    def from_env(cls) -> "Paths":
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
        cfg = _xdg("XDG_CONFIG_HOME", ".config") / "kristall"
        data = _xdg("XDG_DATA_HOME", ".local/share") / "kristall" / "assistant"
        cache = _xdg("XDG_CACHE_HOME", ".cache") / "kristall" / "assistant"
        share = Path(os.environ.get("KRISTALL_ASSISTANT_SHARE", f"{PREFIX}/share/kristall/assistant"))
        return cls(
            runtime_dir=runtime / "kristall",
            socket=Path(os.environ.get("KRISTALL_ASSISTANT_SOCKET", str(runtime / "kristall" / "assistant.sock"))),
            config_dir=cfg,
            settings_file=Path(os.environ.get("KRISTALL_SETTINGS_FILE", str(cfg / "settings.json"))),
            state_dir=data,
            workspace=data / "workspace",
            memory_file=data / "memory.json",
            grants_file=cfg / "assistant" / "permissions.json",
            cache_dir=cache,
            defaults_file=Path(os.environ.get("KRISTALL_SETTINGS_DEFAULTS", f"{PREFIX}/share/kristall/defaults/settings.json")),
            settings_dropin_dirs=tuple(Path(p) for p in os.environ.get(
                "KRISTALL_SETTINGS_DROPIN_DIRS",
                f"{PREFIX}/share/kristall/defaults/settings.d:/etc/kristall/settings.d").split(":") if p),
            share_dir=share,
            models_dir=Path(os.environ.get("KRISTALL_ASSISTANT_MODELS", str(share / "models"))),
            system_mcp_dir=share / "mcp.d",
            user_mcp_dir=cfg / "assistant" / "mcp.d",
        )


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_json(p: Path) -> dict:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("cannot read %s: %s", p, e)
        return {}


def settings_layers(paths: Paths) -> list[Path]:
    """The shared-settings files in merge order (docs/contracts/settings.md)."""
    layers = [paths.defaults_file]
    for d in paths.settings_dropin_dirs:
        try:
            layers += sorted(p for p in d.glob("*.json") if p.is_file())
        except OSError:
            pass
    layers.append(paths.settings_file)
    return layers


def load_settings(paths: Paths) -> dict[str, Any]:
    """Return the effective ``assistant`` settings: our built-in defaults, then every
    shared-settings layer (defaults file, settings.d drop-ins, /etc drop-ins, user file)."""
    eff = copy.deepcopy(DEFAULTS)
    for layer in settings_layers(paths):
        a = _read_json(layer).get("assistant")
        if isinstance(a, dict):
            eff = deep_merge(eff, a)
    # Clamp values a hand-edited file could break.
    try:
        eff["speaking_rate"] = min(1.6, max(0.6, float(eff.get("speaking_rate", 1.0))))
    except (TypeError, ValueError):
        eff["speaking_rate"] = 1.0
    if eff.get("language") not in ("de", "en"):
        eff["language"] = "de"
    return eff


def system_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v:
            return "de" if v.lower().startswith("de") else "en"
    return "de"


# --- inotify watcher (no polling; rule 3 "idle means idle") -----------------

_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_NONBLOCK = 0o4000
_IN_CLOEXEC = 0o2000000


class DirWatcher:
    """Calls ``callback(name)`` when a file in one of ``dirs`` is written/renamed in.

    Integrates with asyncio through ``loop.add_reader``.  Directories that do
    not exist yet are created (they are ours, under ~/.config/kristall).
    """

    def __init__(self, dirs: list[Path], callback: Callable[[Path], None]):
        self._cb = callback
        self._fd = -1
        self._wd: dict[int, Path] = {}
        libc_name = ctypes.util.find_library("c") or "libc.so.6"
        try:
            self._libc = ctypes.CDLL(libc_name, use_errno=True)
            fd = self._libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC)
        except (OSError, AttributeError):
            fd = -1
        if fd < 0:
            log.warning("inotify unavailable; settings changes apply on restart")
            return
        self._fd = fd
        for d in dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            wd = self._libc.inotify_add_watch(
                fd, str(d).encode(), _IN_CLOSE_WRITE | _IN_MOVED_TO | _IN_CREATE | _IN_DELETE)
            if wd >= 0:
                self._wd[wd] = d

    def attach(self, loop) -> None:
        if self._fd >= 0:
            loop.add_reader(self._fd, self._on_readable)

    def close(self, loop=None) -> None:
        if self._fd >= 0:
            if loop is not None:
                try:
                    loop.remove_reader(self._fd)
                except Exception:
                    pass
            os.close(self._fd)
            self._fd = -1

    def _on_readable(self) -> None:
        try:
            buf = os.read(self._fd, 65536)
        except BlockingIOError:
            return
        i = 0
        while i + 16 <= len(buf):
            wd, _mask, _cookie, ln = struct.unpack_from("iIII", buf, i)
            name = buf[i + 16:i + 16 + ln].rstrip(b"\0").decode(errors="replace")
            i += 16 + ln
            d = self._wd.get(wd)
            if d is not None and name:
                try:
                    self._cb(d / name)
                except Exception:  # never let a callback kill the loop
                    log.exception("watch callback failed")
