# SPDX-License-Identifier: GPL-3.0-or-later
"""Discovery of additional tool servers from drop-in files.

Files: ``/usr/share/kristall/assistant/mcp.d/*.json`` (shipped by components
such as ``hands``) and ``~/.config/kristall/assistant/mcp.d/*.json`` (user).
Read in that order, each directory sorted by file name; a later definition of
the same server name replaces an earlier one, and ``null`` removes it.

File format (see docs/contracts/assistant-ipc.md §8)::

    {
      "mcpServers": { "<name>": { "type": "stdio", "command": "...", "args": [], "env": {} } },
      "kristall":   { "<name>": { "label": {"de": "...", "en": "..."},
                                  "publishes_events": true,
                                  "tools": { "<tool>": {"risk": "read", "label": {...}},
                                             "*": {"risk": "ask"} } } }
    }
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..policy.policy import CATEGORIES, ToolDecl

log = logging.getLogger("kristall.mcp")

RESERVED = {"kristall"}
NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
ALLOWED_TYPES = {"stdio", "http", "sse"}


@dataclass
class McpSetup:
    servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    decls: dict[str, dict[str, ToolDecl]] = field(default_factory=dict)
    labels: dict[str, dict[str, str]] = field(default_factory=dict)
    event_publishers: set[str] = field(default_factory=set)
    files: list[str] = field(default_factory=list)


def _valid_server(name: str, cfg: Any) -> bool:
    if not NAME_RE.match(name) or name in RESERVED:
        log.warning("mcp.d: ignoring server with invalid/reserved name %r", name)
        return False
    if not isinstance(cfg, dict):
        return False
    typ = cfg.get("type", "stdio")
    if typ not in ALLOWED_TYPES:
        log.warning("mcp.d: server %s has unsupported type %r", name, typ)
        return False
    if typ == "stdio" and not isinstance(cfg.get("command"), str):
        log.warning("mcp.d: stdio server %s lacks a command", name)
        return False
    if typ in ("http", "sse") and not isinstance(cfg.get("url"), str):
        return False
    return True


def load(dirs: list[Path]) -> McpSetup:
    setup = McpSetup()
    for d in dirs:
        try:
            files = sorted(p for p in d.glob("*.json") if p.is_file())
        except OSError:
            continue
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                log.warning("mcp.d: cannot read %s: %s", f, e)
                continue
            if not isinstance(data, dict):
                continue
            setup.files.append(str(f))
            for name, cfg in (data.get("mcpServers") or {}).items():
                if cfg is None:
                    setup.servers.pop(name, None)
                    setup.decls.pop(name, None)
                    setup.event_publishers.discard(name)
                    continue
                if _valid_server(name, cfg):
                    clean = {k: v for k, v in cfg.items() if k in ("type", "command", "args", "env", "url", "headers")}
                    clean.setdefault("type", "stdio")
                    setup.servers[name] = clean
            for name, meta in (data.get("kristall") or {}).items():
                if not isinstance(meta, dict):
                    continue
                tools: dict[str, ToolDecl] = {}
                for tname, td in (meta.get("tools") or {}).items():
                    if not isinstance(td, dict):
                        continue
                    risk = td.get("risk", "ask")
                    if risk == "ask":
                        risk = "tool.use"
                    if risk not in CATEGORIES:
                        log.warning("mcp.d: %s.%s has unknown risk %r; asking", name, tname, risk)
                        risk = "tool.use"
                    lbl = td.get("label") if isinstance(td.get("label"), dict) else {}
                    tools[tname] = ToolDecl(risk=risk, label={k: str(v) for k, v in lbl.items()})
                setup.decls[name] = tools
                if isinstance(meta.get("label"), dict):
                    setup.labels[name] = {k: str(v) for k, v in meta["label"].items()}
                if meta.get("publishes_events"):
                    setup.event_publishers.add(name)
    # Declarations for servers that are not configured are dropped.
    setup.decls = {k: v for k, v in setup.decls.items() if k in setup.servers}
    return setup
