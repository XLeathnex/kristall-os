# SPDX-License-Identifier: GPL-3.0-or-later
"""Reply markup (assistant-ipc §5.1): the daemon lets through exactly the Markdown subset the
interface renders (shell/modules/assistant/Markdown.js) and normalises everything else, while
streaming; spoken replies are plain."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from conftest import HERE, ROOT, SockClient, run, start_daemon
from kristall_assistant.replytext import ReplyText, normalise

LETTER = (
    "Hier ist die Übersicht:\n\n"
    "| Stadt | Temperatur |\n|---|---:|\n| Berlin | 12 °C |\n| München | **9 °C** |\n\n"
    "Titel\n=====\nText mit <b>fett</b>,<br>Umbruch &amp; mehr &lt;3. Siehe <https://example.org>, "
    "![Karte](https://x.org/a.png) und [Datei](file:///home/a.txt).\n"
    "- [ ] Milch\n- [x] Eier\n        - tief verschachtelt\n1. Schritt *eins*\n2) Schritt `zwei <b>`\n"
    "> Zitat \\*kein kursiv\\*\n\n```python\nprint('<b>')\n```\n---\n### Ende"
)

# what Markdown.js handles (the contract's list); anything else must not reach a typed reply
ALLOWED_LINE = re.compile(
    r"^(|#{1,6} .*|(  )?[-*+•] .*|(  )?\d{1,3}[.)] .*|> .*|---|(```|~~~).*|[^|=<].*)$")


def test_typed_reply_is_inside_the_interface_subset():
    out = normalise(LETTER)
    assert "| Stadt" not in out and "|---" not in out
    assert "- Stadt: Berlin; Temperatur: 12 °C" in out
    assert "- Stadt: München; Temperatur: **9 °C**" in out
    prose = re.sub(r"`[^`]+`", "", out.split("```")[0])     # code is verbatim by design
    assert "<b>" not in prose and "</b>" not in prose and "&amp;" not in out and "&lt;" not in out
    assert "Text mit **fett**,\nUmbruch & mehr <3." in out
    assert "[https://example.org](https://example.org)" in out
    assert "[Karte](https://x.org/a.png)" in out and "![" not in out
    assert "Datei (file:///home/a.txt)" in out
    assert "- ☐ Milch" in out and "- ☑ Eier" in out
    assert "\n  - tief verschachtelt\n" in out
    assert "`zwei <b>`" in out                      # code spans are left alone
    assert "> Zitat ∗kein kursiv∗" in out           # an escaped * never becomes emphasis
    assert "```python\nprint('<b>')\n```" in out    # fenced code is left alone
    assert "Titel\n---\n" in out                    # setext underline: a rule (no lookahead)
    in_fence = False
    for line in out.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            assert ALLOWED_LINE.match(line), line


def test_spoken_reply_is_plain():
    out = normalise(LETTER, plain=True)
    prose = out.replace("Schritt zwei <b>", "").replace("print('<b>')", "")   # code text is kept
    for marker in ("**", "`", "](", "<b>", "&amp;", "# ", "> ", "- [", "|"):
        assert marker not in prose, marker
    assert "Stadt: München; Temperatur: 9 °C" in out
    assert "Text mit fett,\nUmbruch & mehr <3." in out
    assert "Milch" in out and "Schritt eins" in out
    assert "print('<b>')" in out          # code is kept as text


@pytest.mark.parametrize("plain", [False, True])
def test_streaming_equals_whole_and_prose_is_not_delayed(plain):
    whole = normalise(LETTER, plain)
    rnd = random.Random(7)
    for _ in range(300):
        r, out, i = ReplyText(plain), "", 0
        while i < len(LETTER):
            n = rnd.randint(1, 9)
            out += r.feed(LETTER[i:i + n])
            i += n
        out += r.flush()
        assert out == whole
    r = ReplyText(plain)
    assert r.feed("Ein ganz normaler Satz, der sofort") == "Ein ganz normaler Satz, der sofort"


def test_markdown_js_supports_what_the_contract_says():
    """The contract's list is checked against the renderer's own header comment."""
    js = (ROOT.parent.parent / "shell/modules/assistant/Markdown.js").read_text()
    doc = (ROOT.parent.parent / "docs/contracts/assistant-ipc.md").read_text()
    for word in ("headings", "bullet and numbered lists", "block quotes", "fenced", "horizontal rules",
                 "**bold**", "*italic*", "`code`", "~~strike~~", "[text](url)", "http/https/mailto"):
        assert word in js, word
    sect = doc.split("### 5.1", 1)[1].split("\n## ", 1)[0]
    for word in ("**bold**", "*italic*", "`code`", "~~strike~~", "[text](url)", "http", "mailto", "Tables",
                 "plain"):
        assert word in sect, word


def _fixture_with(tmp_path: Path, parts: list[str]) -> str:
    """en_simple with its two text deltas replaced by `parts` (and the final message by their sum)."""
    old = ["17 times 23 is ", "391."]
    repl = dict(zip(old, parts))
    repl["17 times 23 is 391."] = "".join(parts)

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            return repl.get(o, o)
        return o
    lines = (HERE / "fixtures/en_simple.jsonl").read_text().splitlines()
    out = tmp_path / "markdown.jsonl"
    out.write_text("\n".join(json.dumps(walk(json.loads(l)), ensure_ascii=False) for l in lines) + "\n")
    return str(out)


def test_daemon_normalises_typed_replies(env, monkeypatch, tmp_path):
    cut = LETTER.index("Titel")
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", _fixture_with(tmp_path, [LETTER[:cut + 3], LETTER[cut + 3:]]))

    async def go():
        a = await start_daemon(env)
        await a.refresh_account()
        ui = await SockClient.connect(env.socket)
        ack = await ui.request({"type": "invoke", "mode": "text", "text": "What is 17 times 23?"})
        await ui.wait_for(lambda e: e["type"] == "turn_finished" and e["turn_id"] == ack["turn_id"])
        await ui.close()
        await a.stop()
        return ui.events, ack["turn_id"]
    ev, tid = run(go())
    deltas = [e["text"] for e in ev if e["type"] == "reply_delta" and e["turn_id"] == tid]
    done = next(e for e in ev if e["type"] == "reply_done" and e["turn_id"] == tid)
    assert "".join(deltas) == done["text"] == normalise(LETTER)
    assert len(deltas) >= 2
