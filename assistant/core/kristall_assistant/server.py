# SPDX-License-Identifier: GPL-3.0-or-later
"""Unix-socket server: newline-delimited JSON, many clients, same user only.

Transport only — message meaning lives in daemon.py.  See
docs/contracts/assistant-ipc.md for the protocol.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import struct
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("kristall.server")

MAX_LINE = 1 << 20          # 1 MiB
MAX_QUEUE = 2000            # events buffered per slow client before it is dropped


class Client:
    _next = 1

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.id = Client._next
        Client._next += 1
        self.reader = reader
        self.writer = writer
        self.name = "?"
        self.role = "ui"
        self.levels = False
        self.closed = False
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.pid: int | None = None
        self.exe: str | None = None

    def send(self, msg: dict[str, Any]) -> None:
        if self.closed:
            return
        if self.queue.qsize() > MAX_QUEUE:
            log.warning("client %s too slow; disconnecting", self.id)
            self.close()
            return
        self.queue.put_nowait((json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode())

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.queue.put_nowait(None)


class Server:
    def __init__(self, path: Path, on_message: Callable[[Client, dict], Awaitable[None]],
                 on_connect: Callable[[Client], None], on_disconnect: Callable[[Client], None] = lambda c: None):
        self.path = path
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.clients: set[Client] = set()
        self._server: asyncio.base_events.Server | None = None
        self.seq = 0

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        if self.path.exists() or self.path.is_symlink():
            # Stale socket from a crash, or a live daemon?  Never steal a live one.
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.settimeout(0.5)
                s.connect(str(self.path))
                s.close()
                raise RuntimeError(f"another assistant daemon is serving {self.path}")
            except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError) as e:
                if isinstance(e, RuntimeError):
                    raise
                self.path.unlink(missing_ok=True)
        old = os.umask(0o177)
        try:
            self._server = await asyncio.start_unix_server(self._handle, path=str(self.path), limit=MAX_LINE + 2)
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        log.info("listening on %s", self.path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
        for c in list(self.clients):
            c.close()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def stamp(self, msg: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        msg["seq"] = self.seq
        msg["ts"] = int(time.time() * 1000)
        return msg

    def broadcast(self, msg: dict[str, Any], *, levels: bool = False) -> None:
        self.stamp(msg)
        for c in list(self.clients):
            if levels and not c.levels:
                continue
            c.send(msg)

    def send(self, client: Client, msg: dict[str, Any]) -> None:
        client.send(self.stamp(msg))

    async def _writer(self, c: Client) -> None:
        try:
            while True:
                data = await c.queue.get()
                if data is None:
                    break
                c.writer.write(data)
                if c.writer.transport.get_write_buffer_size() > 256 * 1024:
                    await c.writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            c.closed = True
            try:
                c.writer.close()
            except Exception:   # noqa: BLE001
                pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        c = Client(reader, writer)
        sock = writer.get_extra_info("socket")
        try:
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, _gid = struct.unpack("3i", creds)
            if uid != os.getuid():
                log.warning("rejecting client of uid %s", uid)
                writer.close()
                return
            c.pid = pid
            try:
                c.exe = os.readlink(f"/proc/{pid}/exe")
            except OSError:
                c.exe = None
        except OSError:
            pass
        self.clients.add(c)
        wtask = asyncio.ensure_future(self._writer(c))
        try:
            self.on_connect(c)
            while not c.closed:
                try:
                    line = await reader.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    self.send(c, {"type": "error", "code": "bad_request",
                                  "message": {"de": "Nachricht zu lang.", "en": "Message too long."},
                                  "retryable": False, "action": None, "turn_id": None})
                    break
                except (ConnectionError, OSError):
                    break
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
                        raise ValueError("not an object with a type")
                except ValueError as e:
                    self.send(c, {"type": "ack", "id": None, "ok": False, "code": "bad_json",
                                  "detail": str(e)[:200]})
                    continue
                try:
                    await self.on_message(c, msg)
                except Exception:   # noqa: BLE001 - a bad message must never kill the daemon
                    log.exception("error handling %s", msg.get("type"))
                    if "id" in msg:
                        self.send(c, {"type": "ack", "id": msg.get("id"), "ok": False, "code": "internal"})
        finally:
            self.clients.discard(c)
            c.close()
            try:
                self.on_disconnect(c)
            except Exception:   # noqa: BLE001
                log.exception("disconnect handler")
            await wtask
