# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared test fixtures: isolated XDG dirs, the fake claude, an in-process
daemon with a socket client."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
FAKE = str(HERE / "fake_claude.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated user directories (never touches the real ~/.claude or settings)."""
    home = tmp_path / "home"
    home.mkdir()
    rt = tmp_path / "rt"
    rt.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(rt))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("KRISTALL_SETTINGS_DEFAULTS", str(tmp_path / "defaults.json"))
    (tmp_path / "settings.d").mkdir()
    monkeypatch.setenv("KRISTALL_SETTINGS_DROPIN_DIRS", str(tmp_path / "settings.d"))
    monkeypatch.setenv("KRISTALL_ASSISTANT_SHARE", str(tmp_path / "share"))
    monkeypatch.setenv("KRISTALL_CLAUDE_CLI", FAKE)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake.log"))
    monkeypatch.setenv("KRISTALL_DEMO_SPEED", "25")
    monkeypatch.delenv("FAKE_CLAUDE_FIXTURE", raising=False)
    monkeypatch.delenv("FAKE_CLAUDE_MODE", raising=False)
    models = os.environ.get("KRISTALL_TEST_MODELS")
    if models:
        monkeypatch.setenv("KRISTALL_ASSISTANT_MODELS", models)
    else:
        monkeypatch.setenv("KRISTALL_ASSISTANT_MODELS", str(tmp_path / "no-models"))
    from kristall_assistant.config import Paths
    return Paths.from_env()


def fake_log(paths) -> list[dict]:
    p = Path(os.environ["FAKE_CLAUDE_LOG"])
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines()]


class SockClient:
    """Asyncio client speaking the protocol, recording every event."""

    def __init__(self, reader, writer):
        self.r, self.w = reader, writer
        self.events: list[dict] = []
        self.n = 0
        self._new = asyncio.Event()
        self._task = asyncio.ensure_future(self._read())

    @classmethod
    async def connect(cls, path):
        r, w = await asyncio.open_unix_connection(str(path), limit=1 << 21)
        return cls(r, w)

    async def _read(self):
        while True:
            line = await self.r.readline()
            if not line:
                break
            self.events.append(json.loads(line))
            self._new.set()

    async def send(self, msg: dict, with_id: bool = True) -> int | None:
        if with_id:
            self.n += 1
            msg = dict(msg, id=self.n)
        self.w.write((json.dumps(msg) + "\n").encode())
        await self.w.drain()
        return msg.get("id")

    async def request(self, msg: dict, timeout: float = 10) -> dict:
        mid = await self.send(msg)
        return await self.wait_for(lambda e: e.get("type") == "ack" and e.get("id") == mid, timeout)

    async def wait_for(self, pred, timeout: float = 15, start: int = 0) -> dict:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        i = start
        while True:
            while i < len(self.events):
                if pred(self.events[i]):
                    return self.events[i]
                i += 1
            left = end - loop.time()
            if left <= 0:
                types = [e.get("type") for e in self.events[-30:]]
                raise AssertionError(f"timed out; last events: {types}")
            self._new.clear()
            try:
                await asyncio.wait_for(self._new.wait(), left)
            except asyncio.TimeoutError:
                pass

    def of(self, typ: str, turn_id: str | None = None) -> list[dict]:
        return [e for e in self.events if e.get("type") == typ and (turn_id is None or e.get("turn_id") == turn_id)]

    async def close(self):
        self.w.close()
        self._task.cancel()


async def start_daemon(paths, **kw):
    from kristall_assistant.daemon import Assistant
    a = Assistant(paths, **kw)
    await a.start()
    return a


def run(coro, timeout: float = 60):
    async def _with_timeout():
        return await asyncio.wait_for(coro, timeout)
    return asyncio.run(_with_timeout())
