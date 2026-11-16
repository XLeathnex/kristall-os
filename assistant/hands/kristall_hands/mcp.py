# SPDX-License-Identifier: GPL-3.0-or-later
"""A small MCP server over stdio (JSON-RPC 2.0, one JSON object per line).

Implements what Claude Code uses: ``initialize``, ``notifications/initialized``,
``ping``, ``tools/list``, ``tools/call``, ``notifications/cancelled`` and
``logging/setLevel``.  Tool calls run one at a time on a worker thread (the
desktop is one shared resource, and AT-SPI is not thread-safe); the reader
thread stays free to answer ``ping`` and to deliver cancellations, which the
running tool notices at its next checkpoint.  A cancelled request gets no
response, as the specification asks.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import traceback
from typing import Any, Callable

from .tooling import Cancelled, Context, HandsError, Registry, Result
from . import log

PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class Server:
    def __init__(self, registry: Registry, *, name: str, version: str, instructions: str,
                 stdin=None, stdout=None, on_cancel: Callable[[], None] | None = None,
                 on_exit: Callable[[], None] | None = None):
        self.registry = registry
        self.name, self.version, self.instructions = name, version, instructions
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self._wlock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue()
        self._active: dict[Any, Context] = {}
        self._alock = threading.Lock()
        self.on_cancel = on_cancel
        self.on_exit = on_exit
        self.initialized = False
        self.client_info: dict = {}

    # ------------------------------------------------------------------ io
    def send(self, obj: dict) -> None:
        data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._wlock:
            try:
                self.stdout.write(data)
                self.stdout.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

    def _reply(self, rid, result=None, error=None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result if result is not None else {}
        self.send(msg)

    @staticmethod
    def _err(code: int, message: str, data: Any = None) -> dict:
        e = {"code": code, "message": message}
        if data is not None:
            e["data"] = data
        return e

    # ------------------------------------------------------------------ main loop
    def serve(self) -> None:
        worker = threading.Thread(target=self._worker, name="hands-worker", daemon=True)
        worker.start()
        try:
            for raw in self.stdin:
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    self._reply(None, error=self._err(PARSE_ERROR, "Parse error"))
                    continue
                if isinstance(msg, list):          # batches were removed from MCP; answer each
                    for m in msg:
                        self._handle(m)
                else:
                    self._handle(msg)
        finally:
            self._jobs.put(None)
            with self._alock:
                for ctx in self._active.values():
                    ctx.cancel("stdin closed")
            if self.on_exit:
                try:
                    self.on_exit()
                except Exception:   # pragma: no cover - best effort
                    log.exception("on_exit failed")

    def _handle(self, msg: Any) -> None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            self._reply(msg.get("id") if isinstance(msg, dict) else None,
                        error=self._err(INVALID_REQUEST, "Invalid Request"))
            return
        method = msg.get("method")
        rid = msg.get("id")
        is_request = "id" in msg
        if not isinstance(method, str):
            if is_request and ("result" in msg or "error" in msg):
                return  # a response to something we never send; ignore
            self._reply(rid, error=self._err(INVALID_REQUEST, "Invalid Request"))
            return
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            if is_request:
                self._reply(rid, error=self._err(INVALID_PARAMS, "params must be an object"))
            return

        if not is_request:
            self._notification(method, params)
            return
        if method == "initialize":
            self._initialize(rid, params)
        elif method == "ping":
            self._reply(rid, {})
        elif method == "tools/list":
            self._reply(rid, {"tools": self.registry.describe()})
        elif method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or name not in self.registry.tools:
                self._reply(rid, error=self._err(INVALID_PARAMS, f"Unknown tool: {name}"))
                return
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                self._reply(rid, error=self._err(INVALID_PARAMS, "arguments must be an object"))
                return
            ctx = Context(rid, name)
            with self._alock:
                self._active[rid] = ctx
            self._jobs.put((rid, name, args, ctx))
        elif method == "logging/setLevel":
            self._reply(rid, {})
        elif method in ("resources/list", "prompts/list"):
            # Not offered (no capability advertised), but answer politely.
            self._reply(rid, {"resources": []} if method == "resources/list" else {"prompts": []})
        else:
            self._reply(rid, error=self._err(METHOD_NOT_FOUND, f"Method not found: {method}"))

    def _notification(self, method: str, params: dict) -> None:
        if method == "notifications/initialized":
            self.initialized = True
        elif method == "notifications/cancelled":
            rid = params.get("requestId")
            with self._alock:
                ctx = self._active.get(rid)
            if ctx:
                log.info("request %s cancelled by client: %s", rid, params.get("reason", ""))
                ctx.cancel(str(params.get("reason") or "cancelled"))
                if self.on_cancel:
                    try:
                        self.on_cancel()
                    except Exception:
                        log.exception("on_cancel failed")
        # other notifications are ignored

    def _initialize(self, rid, params: dict) -> None:
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        self.client_info = params.get("clientInfo") or {}
        self._reply(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}, "logging": {}},
            "serverInfo": {"name": self.name, "version": self.version},
            "instructions": self.instructions,
        })

    # ------------------------------------------------------------------ worker
    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            rid, name, args, ctx = job
            try:
                if ctx.cancelled:
                    continue
                result = self._call(name, args, ctx)
                if not ctx.cancelled:
                    self._reply(rid, result)
            finally:
                with self._alock:
                    self._active.pop(rid, None)

    def _call(self, name: str, args: dict, ctx: Context) -> dict:
        tool = self.registry.tools[name]
        # intent/risk are read by the assistant daemon on any tool; accept them everywhere
        props = tool.schema.get("properties", {})
        args = {k: v for k, v in args.items() if k in props or k not in ("intent", "risk")}
        try:
            problem = tool.validate(args)
            if problem:
                return Result.error(problem).to_mcp()
            res = tool.fn(ctx, **args)
            if not isinstance(res, Result):
                res = Result.text(str(res))
            return res.to_mcp()
        except Cancelled:
            return Result.error("Stopped: the request was cancelled.").to_mcp()
        except HandsError as e:
            log.info("tool %s: %s", name, e.message)
            return Result.error(e.message).to_mcp()
        except Exception as e:   # a bug: say so plainly, log the details
            log.error("tool %s crashed: %s\n%s", name, e, traceback.format_exc())
            return Result.error(f"This did not work because of an internal error in the screen-control "
                                f"service ({type(e).__name__}). Try another way.").to_mcp()
