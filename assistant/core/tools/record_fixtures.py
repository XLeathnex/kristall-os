#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record real ``claude`` stream fixtures through the production Brain.

Each scenario makes one or two very short Haiku 5.5 requests (they count
against the owner's usage — keep the list short).  Output: one JSONL file per
scenario in tests/fixtures/, consumed by tests/fake_claude.py.

    python tools/record_fixtures.py <real-claude-path> [scenario ...]
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from kristall_assistant.brain.brain import Brain, Turn          # noqa: E402
from kristall_assistant.brain.memory import Memory              # noqa: E402
from kristall_assistant.brain.mcp_config import McpSetup        # noqa: E402
from kristall_assistant.config import DEFAULTS, Paths           # noqa: E402
from kristall_assistant.policy.policy import GrantStore, Policy, PolicyPaths  # noqa: E402

FIX = HERE.parent / "tests" / "fixtures"

SCENARIOS = {
    # name: (list of (prompt, spoken), permission answer, interrupt_after_deltas)
    "de_simple_followup": ([("Wie heißt die Hauptstadt von Australien?", True),
                            ("Und wie viele Leute wohnen da ungefähr?", True)], "allow_once", None),
    "en_simple": ([("What's seventeen times twenty-three?", True)], "allow_once", None),
    "de_delete_permission": ([("Lösch bitte die Datei alt.txt in deinem Arbeitsordner endgültig, nicht in den Papierkorb.", True)], "allow_once", None),
    "de_delete_denied": ([("Lösch bitte die Datei alt.txt in deinem Arbeitsordner.", True)], "deny", None),
    "de_websearch": ([("Wer hat den Nobelpreis für Literatur 2025 bekommen? Kurz bitte.", True)], "allow_once", None),
    "de_remember": ([("Merk dir bitte: Meine Schwester heißt Lena.", True)], "allow_once", None),
    "de_interrupt": ([("Erzähl mir ausführlich die Geschichte von Berlin, mindestens zehn Sätze.", False)], "allow_once", 8),
}


async def run(real_cli: str, name: str) -> None:
    prompts, answer, interrupt_after = SCENARIOS[name]
    tmp = Path(tempfile.mkdtemp(prefix="kristall-rec-"))
    os.environ["XDG_DATA_HOME"] = str(tmp / "data")
    os.environ["XDG_CONFIG_HOME"] = str(tmp / "config")
    paths = Paths.from_env()
    paths.workspace.mkdir(parents=True, exist_ok=True)
    (paths.workspace / "alt.txt").write_text("alter Inhalt\n")
    out = FIX / f"{name}.jsonl"
    if out.exists():
        out.unlink()
    os.environ["REC_REAL_CLI"] = real_cli
    os.environ["REC_FILE"] = str(out)
    wrapper = str(HERE / "rec_wrapper.py")
    policy = Policy(PolicyPaths(str(paths.workspace), [str(paths.grants_file)]), GrantStore(None))
    memory = Memory(paths.memory_file)
    asked = []

    async def ask_owner(req):
        asked.append(req)
        print("  PERMISSION:", req.decision.question["de"], "|", req.explanation, "->", answer)
        return answer

    brain = Brain(paths=paths, settings=lambda: dict(DEFAULTS), policy=policy, memory=memory,
                  mcp_setup=lambda: McpSetup(), ask_owner=ask_owner, cli_path=lambda: wrapper)
    brain.prepare_spare_later = lambda: None   # one process per fixture file
    for i, (p, spoken) in enumerate(prompts):
        deltas = 0
        turn: Turn

        def emit(ev):
            nonlocal deltas
            if ev["type"] == "reply_delta":
                deltas += 1
                print(ev["text"], end="", flush=True)
                if interrupt_after and deltas == interrupt_after:
                    asyncio.get_running_loop().create_task(brain.cancel())
            elif not ev["type"].startswith("_"):
                print("\n  EVENT", json.dumps(ev, ensure_ascii=False))
        turn = Turn(id=f"t{i}", text=p, spoken=spoken, emit=emit)
        await brain.run_turn(turn)
        print(f"\n  -> error={turn.error_code} cancelled={turn.cancelled} continued={turn.continued}")
    await brain.shutdown()
    print("memory:", memory.facts)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    real = sys.argv[1]
    names = sys.argv[2:] or list(SCENARIOS)
    for n in names:
        print(f"=== {n}")
        await run(real, n)


if __name__ == "__main__":
    asyncio.run(main())
