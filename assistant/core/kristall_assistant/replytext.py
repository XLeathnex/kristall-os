# SPDX-License-Identifier: GPL-3.0-or-later
"""Reply markup: what a reply may contain (docs/contracts/assistant-ipc.md §5.1), normalised while
it streams.

The assistant interface renders typed replies with a small Markdown subset
(shell/core/Markdown.js). The model writes CommonMark/GFM freely, so everything outside
that subset is rewritten here into something inside it, and the interface always shows what the
model meant. Spoken replies are made plain (no markup at all): they are read aloud and shown as
spoken text.

Streaming: `feed()` returns the normalised text that is final already, `flush()` the rest. Text is
held back only where a rewrite may still happen: the first few characters of a line (until its
head — list marker, heading, quote, table bar, fence — is known), whole table and fence lines, and
the part of a line from the first character that can start an inline rewrite (`<`, `&`, `\\`, `!`,
`[`, `` ` `` — in plain mode also `*`, `_`, `~`). Ordinary prose streams through at once.
The concatenation of everything returned equals `normalise(whole text)`.
"""
from __future__ import annotations

import html
import re

SAFE_URL = re.compile(r"^(https?://|mailto:)", re.I)
HEAD_HOLD = 8                    # characters of a line (after indentation) before its head is known
RISKY_TYPED = set("<&\\![`")
RISKY_PLAIN = RISKY_TYPED | set("*_~")

_LIST = re.compile(r"^(\s*)([-*+•])\s+(?:(\[[ xX]\])\s+)?")
_ORDERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+")
_QUOTE = re.compile(r"^\s*>\s?")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_SETEXT = re.compile(r"^\s{0,3}={3,}\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_CODE_SPAN = re.compile(r"`[^`]+`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>", re.I)
_BR = re.compile(r"[ \t]*<br\s*/?>[ \t]*", re.I)
_TAG = re.compile(r"</?([A-Za-z][A-Za-z0-9-]*)(?:\s[^<>]*)?/?>")
_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});")
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_TAG_MARK = {"b": "**", "strong": "**", "i": "*", "em": "*", "code": "`", "s": "~~", "del": "~~", "strike": "~~"}


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


class ReplyText:
    def __init__(self, plain: bool = False):
        self.plain = plain
        self.risky = RISKY_PLAIN if plain else RISKY_TYPED
        self.buf = ""            # the current line, raw, without its newline
        self.emitted = ""        # normalised prefix of the current line already returned
        self.in_fence = False
        self.pending_row: list[str] | None = None   # a table line that may be a header
        self.header: list[str] | None = None        # inside a table: its header cells

    # ------------------------------------------------------------------ public
    def feed(self, text: str) -> str:
        out = []
        self.buf += text.replace("\r", "")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            out.append(self._finish(line, True))
        out.append(self._partial())
        return "".join(out)

    def flush(self) -> str:
        """End of the text (or of a segment): the current line is complete as it is."""
        line, self.buf = self.buf, ""
        out = self._finish(line, False)
        if self.pending_row is not None:
            out += self._row(self.pending_row, None)
            self.pending_row = None
        self.header = None
        return out

    # ------------------------------------------------------------------ lines
    def _finish(self, line: str, newline: bool) -> str:
        nl = "\n" if newline else ""
        full = self._line(line)
        if full is None:              # held (a possible table header)
            self.emitted = ""
            return ""
        prefix, self.emitted = self.emitted, ""
        if not full.startswith(prefix):   # cannot happen by construction; never lose text
            return full[len(prefix):] + nl
        return full[len(prefix):] + nl

    def _line(self, line: str) -> str | None:
        """The normalised line (with a pending table line in front, if any), or None if held."""
        before = ""
        stripped = line.strip()
        if self.in_fence:
            if _FENCE.match(line):
                self.in_fence = False
                return "" if self.plain else line
            return line
        is_row = stripped.startswith("|") and stripped.count("|") >= 2
        if self.pending_row is not None:
            row, self.pending_row = self.pending_row, None
            if _TABLE_SEP.match(line):
                self.header = row
                return None
            before = self._row(row, None) + "\n"
        if self.header is not None:
            if is_row:
                return before + self._row(_cells(line), self.header)
            self.header = None
        if is_row:
            if _TABLE_SEP.match(line):
                return before.rstrip("\n") if before else ""
            self.pending_row = _cells(line)
            if before:
                return before.rstrip("\n")
            return None
        return before + self._plain_line(line)

    def _row(self, cells: list[str], header: list[str] | None) -> str:
        parts = []
        for i, c in enumerate(cells):
            h = header[i] if header and i < len(header) and header[i] else ""
            parts.append(f"{h}: {c}" if h and c else (c or h))
        body = self._inline("; ".join(p for p in parts if p))
        return body if self.plain else "- " + body

    def _plain_line(self, line: str) -> str:
        if _FENCE.match(line):
            self.in_fence = True
            return "" if self.plain else line
        head, rest = self._head(line)
        if head is None:
            return rest
        return head + self._inline(rest)

    def _head(self, line: str) -> tuple[str | None, str]:
        """(normalised head, rest of the line) — head None means the whole line is `rest`, final."""
        if _SETEXT.match(line) or _RULE.match(line):
            return None, ("" if self.plain else "---")
        m = _HEADING.match(line)
        if m:
            return ("" if self.plain else m.group(1) + " "), line[m.end():]
        m = _QUOTE.match(line)
        if m:
            return ("" if self.plain else "> "), line[m.end():]
        m = _LIST.match(line)
        if m:
            box = {"[ ]": "☐ ", "[x]": "☑ ", "[X]": "☑ "}.get(m.group(3) or "", "")
            if self.plain:
                return box, line[m.end():]
            indent = "  " if len(m.group(1).expandtabs(4)) >= 2 else ""
            return indent + m.group(2) + " " + box, line[m.end():]
        m = _ORDERED.match(line)
        if m:
            if self.plain:
                return "", line[m.end():]
            indent = "  " if len(m.group(1).expandtabs(4)) >= 2 else ""
            return indent + line[len(m.group(1)):m.end()].rstrip() + " ", line[m.end():]
        return "", line

    # ------------------------------------------------------------------ inline
    def _inline(self, text: str) -> str:
        out, last = [], 0
        for m in _CODE_SPAN.finditer(text):
            out.append(self._inline_prose(text[last:m.start()]))
            out.append(m.group(0)[1:-1] if self.plain else m.group(0))
            last = m.end()
        out.append(self._inline_prose(text[last:]))
        return "".join(out)

    def _inline_prose(self, s: str) -> str:
        if not s:
            return s
        s = _ESCAPE.sub(lambda m: "\u0001%d\u0001" % ord(m.group(1)), s)   # protect escaped chars

        def image(m):
            alt, url = m.group(1), m.group(2)
            if self.plain or not SAFE_URL.match(url):
                return alt
            return f"[{alt or url}]({url})"
        s = _IMAGE.sub(image, s)

        def link(m):
            label, url = m.group(1), m.group(2)
            if self.plain:
                return label
            return m.group(0) if SAFE_URL.match(url) else f"{label} ({url})"
        s = _LINK.sub(link, s)
        s = _AUTOLINK.sub(lambda m: m.group(1) if self.plain else f"[{m.group(1)}]({m.group(1)})", s)
        s = _BR.sub("\n", s)
        s = _TAG.sub(lambda m: "" if self.plain else _TAG_MARK.get(m.group(1).lower(), ""), s)
        s = _ENTITY.sub(lambda m: html.unescape(m.group(0)), s)
        if self.plain:
            s = re.sub(r"\*\*([^*]+?)\*\*", r"\1", s)
            s = re.sub(r"__([^_]+?)__", r"\1", s)
            s = re.sub(r"(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)", r"\1\2", s)
            s = re.sub(r"(^|[^\w])_([^_\s][^_]*?)_(?!\w)", r"\1\2", s)
            s = re.sub(r"~~([^~]+?)~~", r"\1", s)
        # an escaped asterisk must not become emphasis in the interface: U+2217 looks the same
        return re.sub("\u0001(\\d+)\u0001",
                      lambda m: "\u2217" if m.group(1) == "42" and not self.plain else chr(int(m.group(1))), s)

    # ------------------------------------------------------------------ streaming
    def _partial(self) -> str:
        """Return what of the incomplete current line is final already."""
        line = self.buf
        if self.in_fence:
            if _FENCE.match(line) or not line.strip() or line.lstrip()[:1] in "`~":
                return ""
            target = line
        else:
            if self.pending_row is not None or self.header is not None:
                return ""
            body = line.lstrip()
            if len(body) < HEAD_HOLD or body[0] in "|=`~<" or _RULE.match(line):
                return ""
            head, rest = self._head(line)
            if head is None:
                return ""
            cut = next((i for i, ch in enumerate(rest) if ch in self.risky), len(rest))
            # trailing blanks are held too: a following <br> swallows them
            target = head + rest[:cut].rstrip(" \t")
        if not target.startswith(self.emitted):
            return ""
        out, self.emitted = target[len(self.emitted):], target
        return out


def normalise(text: str, plain: bool = False) -> str:
    r = ReplyText(plain)
    return r.feed(text) + r.flush()
