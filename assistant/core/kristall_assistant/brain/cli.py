# SPDX-License-Identifier: GPL-3.0-or-later
"""Locating the owner's ``claude`` CLI and asking it about its state.

We never read Claude's credential files ourselves: sign-in state comes only
from ``claude auth status``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

log = logging.getLogger("kristall.cli")

# Oldest CLI we drive.  2.1.302 made `default` the starting permission mode for
# non-interactive runs, which our permission design relies on; Haiku 5.5 also
# needs a recent CLI.  Raise when we start using newer protocol features.
MIN_VERSION = (2, 1, 302)
MIN_VERSION_STR = ".".join(map(str, MIN_VERSION))


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for every ``claude`` child we start.

    Keeps the owner's login working (HOME, XDG, proxy settings) while switching
    off what would mix the assistant with their own coding setup.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "KRISTALL_FAKE_"))}
    env.update({
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",      # our own memory instead
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",       # never load the owner's CLAUDE.md files
        "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",   # also skips a title-generation request
        "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
        "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
        "DISABLE_AUTOUPDATER": "1",                  # updates go through kristall-assistant-account
        "CLAUDE_AGENT_SDK_CLIENT_APP": "kristall-assistant",
    })
    if extra:
        env.update(extra)
    return env


def find_cli(override: str | None = None) -> str | None:
    cands: list[str] = []
    for c in (override, os.environ.get("KRISTALL_CLAUDE_CLI")):
        if c:
            cands.append(os.path.expanduser(c))
    cands.append(str(Path.home() / ".local" / "bin" / "claude"))
    w = shutil.which("claude")
    if w:
        cands.append(w)
    cands += [str(Path.home() / ".claude" / "local" / "claude"), "/usr/bin/claude"]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def parse_version(s: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else None


@dataclass
class CliStatus:
    status: str                  # "ready" | "cli_missing" | "cli_outdated" | "signed_out" | "unknown"
    cli_path: str | None = None
    cli_version: str | None = None
    min_version: str = MIN_VERSION_STR
    logged_in: bool | None = None
    auth_method: str | None = None
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


async def _run(argv: list[str], timeout: float = 20.0, env: dict | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env or child_env(), cwd=str(Path.home()))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", "timeout"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def check(override: str | None = None) -> CliStatus:
    path = find_cli(override)
    if not path:
        return CliStatus("cli_missing")
    rc, out, err = await _run([path, "--version"], 20)
    ver = parse_version(out)
    if rc != 0 or not ver:
        return CliStatus("cli_missing", path, None, detail=(err or out)[:200])
    vstr = ".".join(map(str, ver))
    if ver < MIN_VERSION:
        return CliStatus("cli_outdated", path, vstr)
    rc, out, err = await _run([path, "auth", "status", "--json"], 20)
    try:
        d = json.loads(out)
    except ValueError:
        return CliStatus("unknown", path, vstr, detail=(err or out)[:200])
    li = bool(d.get("loggedIn"))
    return CliStatus("ready" if li else "signed_out", path, vstr, li, d.get("authMethod"))
