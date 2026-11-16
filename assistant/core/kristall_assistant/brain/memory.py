# SPDX-License-Identifier: GPL-3.0-or-later
"""The assistant's own persistent memory.

A small JSON file of facts the owner asked it to keep (name, preferences,
"merk dir …").  It is independent of Claude Code's auto-memory (which we turn
off for the assistant) and survives restarts.  The model edits it through two
in-process MCP tools; the daemon injects it into the system prompt of each new
conversation.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger("kristall.memory")

MAX_FACTS = 200
MAX_LEN = 500


class Memory:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.facts: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.facts = [f for f in d.get("facts", []) if isinstance(f, dict) and f.get("text")]
        except FileNotFoundError:
            self.facts = []
        except (OSError, ValueError) as e:
            log.warning("memory unreadable (%s); starting empty, keeping a copy", e)
            try:
                os.replace(self.path, self.path.with_suffix(".broken"))
            except OSError:
                pass
            self.facts = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".memory.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "facts": self.facts}, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def remember(self, text: str) -> dict[str, Any]:
        text = " ".join(str(text).split())[:MAX_LEN]
        if not text:
            raise ValueError("empty")
        with self._lock:
            for f in self.facts:
                if f["text"].casefold() == text.casefold():
                    return f
            fact = {"id": uuid.uuid4().hex[:8], "text": text, "at": int(time.time())}
            self.facts.append(fact)
            self.facts = self.facts[-MAX_FACTS:]
            self._save()
            return fact

    def forget(self, what: str) -> list[dict[str, Any]]:
        w = str(what).strip().casefold()
        with self._lock:
            gone = [f for f in self.facts if f["id"] == w or (w and w in f["text"].casefold())]
            if gone:
                self.facts = [f for f in self.facts if f not in gone]
                self._save()
            return gone

    def as_prompt(self) -> str:
        if not self.facts:
            return "(noch nichts)"
        return "\n".join(f"- [{f['id']}] {f['text']}" for f in self.facts)


def make_mcp_server(memory: Memory):
    """In-process MCP server ``kristall`` with the memory tools."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool("remember",
          "Save one short fact about the owner or their wishes in your persistent memory "
          "(e.g. their name, a preference, something they asked you to remember). Never store passwords.",
          {"type": "object", "properties": {"fact": {"type": "string", "description": "The fact, one sentence."}},
           "required": ["fact"]})
    async def remember(args: dict[str, Any]) -> dict[str, Any]:
        try:
            f = memory.remember(args.get("fact", ""))
        except ValueError:
            return {"content": [{"type": "text", "text": "Nothing to remember."}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Saved as [{f['id']}]."}]}

    @tool("forget",
          "Remove facts from your persistent memory, by id or by a word they contain.",
          {"type": "object", "properties": {"what": {"type": "string"}}, "required": ["what"]})
    async def forget(args: dict[str, Any]) -> dict[str, Any]:
        gone = memory.forget(args.get("what", ""))
        txt = f"Removed {len(gone)} fact(s)." if gone else "No matching fact."
        return {"content": [{"type": "text", "text": txt}]}

    return create_sdk_mcp_server("kristall", "1.0.0", [remember, forget])
