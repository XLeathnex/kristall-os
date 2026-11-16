# SPDX-License-Identifier: GPL-3.0-or-later
"""The risky-target gate (docs/contracts/hands.md §10).

Every hands tool that activates a UI element (ui_act press/open/toggle/select, a left click or a
drag, Return/Ctrl+Return/Ctrl+S/Space, type_text with a line break) asks this module first what the
element is.  If it looks like Send, Buy, Delete permanently, Install or an account change and the
call does not already declare a matching ``risk``, the call is refused with an error that tells
the model exactly how to retry; the retry carries ``risk``, the assistant daemon's policy asks the
owner (assistant-ipc.md §7.1), and only then does the action run.  Whether the owner is asked
before "Senden" is clicked therefore no longer rests on the model remembering to declare it.

The vocabulary is data (``data/risky-targets.json``).  Element lookups are bounded: one point
query (or the element already known from a ref), the enclosing dialog's title and labels, the
focused element and the default button, all within ``BUDGET`` seconds; an element that cannot be
identified in time, or at all (games, canvas apps, apps without accessibility), is ``unknown`` and
is not blocked — then only the model's own ``intent`` text is checked against the vocabulary.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass

from . import log
from .tooling import HandsError

BUDGET = 0.150          # seconds for all accessibility lookups of one gate check

# The assistant daemon's policy order (assistant/core/kristall_assistant/policy/policy.py ORDER:
# shell.ORDER with tool.use after shell.run).  A declared risk satisfies a required category when
# it is the same or stricter in this order.  tests/test_riskgate.py checks that the two agree.
ORDER = ["read", "reversible", "files.modify", "system.config", "processes.stop", "system.power",
         "apps.install", "files.delete", "shell.run", "tool.use", "send", "purchase", "elevated",
         "credentials", "deny"]
RANK = {c: i for i, c in enumerate(ORDER)}

# roles whose activation does something (buttons, menu items, links, check items)
ACTIVATING = {"push button", "button", "toggle button", "push button menu", "menu item", "check menu item",
              "radio menu item", "link", "check box", "switch"}
MENU_ITEMS = {"menu item", "check menu item", "radio menu item"}
# roles that say nothing about what is under the pointer
OPAQUE = {"", "unknown", "invalid", "filler", "panel", "canvas", "drawing area", "frame", "window", "application",
          "document web", "document frame", "embedded", "redundant object", "scroll pane", "viewport",
          "layered pane", "root pane", "glass pane", "internal frame", "section", "image", "desktop frame"}
DIALOGS = {"dialog", "alert", "file chooser"}
TEXTISH = {"label", "static", "heading", "paragraph", "text", "caption", "description term", "description value"}
ROLE_SHORT = {"push button": "button", "toggle button": "toggle button", "check box": "checkbox",
              "menu item": "menu item", "check menu item": "menu item", "radio menu item": "menu item",
              "push button menu": "menu button"}
KEY_NAMES = {"return": "Return", "kp_enter": "Enter", "ctrl+return": "Ctrl+Return", "ctrl+kp_enter": "Ctrl+Enter",
             "ctrl+s": "Ctrl+S", "space": "Space"}
GATED_CHORDS = set(KEY_NAMES)


def satisfies(declared: str | None, required: str) -> bool:
    return bool(declared) and declared in RANK and RANK[declared] >= RANK.get(required, len(ORDER))


# ---------------------------------------------------------------------------- vocabulary

def norm(s: str) -> str:
    """Lower-case, mnemonic-free, punctuation-free text with single spaces (ß becomes ss)."""
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = s.replace("’", "'").replace("&", "").replace("_", "")
    s = re.sub(r"[^\w']+", " ", s)
    return " ".join(s.split())


def _rx(phrase: str) -> re.Pattern:
    words = norm(phrase).split()
    return re.compile(r"(?<![\w'])" + r"\s+".join(re.escape(w) for w in words) + r"(?![\w'])")


@dataclass
class Term:
    phrase: str
    rx: re.Pattern
    weak: bool = False
    apps: list[str] | None = None
    not_apps: list[str] | None = None


@dataclass
class RiskClass:
    name: str
    category: str
    label: dict
    terms: list[Term]
    unless: list[re.Pattern]


@dataclass
class Match:
    cls: RiskClass
    term: str
    via: str = "name"          # name | dialog | intent

    @property
    def category(self) -> str:
        return self.cls.category


@dataclass
class Target:
    """What an action would activate, as far as accessibility can tell."""
    known: bool = False
    role: str = ""
    name: str = ""
    description: str = ""
    app: str = ""              # app ids/names, space separated (bridge appId, AT-SPI app name)
    window: str = ""           # window title
    dialog: str = ""           # title and labels of the enclosing dialog/alert, if any
    is_default: bool = False
    text_context: bool = False  # menu item of a text-editing menu, or focus in an editable field
    how: str = ""              # "", "default" (the key would press the default button), "focus"
    key: str = ""              # the key for "default"/"focus": Return, Ctrl+Return, Ctrl+S, Space
    reason: str = ""           # why it is unknown

    def describe(self) -> str:
        role = ROLE_SHORT.get(self.role, self.role or "element")
        s = f'{role} "{_clip(self.name) or "(no name)"}"'
        if self.how in ("default", "focus"):
            s = f"{self.key or 'the key'} would press the {'default' if self.how == 'default' else 'focused'} {s}"
        if self.dialog:
            s += f' in the dialog "{_clip(self.dialog, 90)}"'
        elif self.window:
            s += f' in "{_clip(self.window)}"'
        return s

    def note(self) -> str:
        if not self.known:
            return "target: unknown" + (f" ({self.reason})" if self.reason else "")
        role = ROLE_SHORT.get(self.role, self.role or "element")
        return f'target: {role} "{_clip(self.name)}"' + (" (default button)" if self.how == "default" else "")


def _clip(s: str, n: int = 60) -> str:
    s = " ".join(str(s or "").replace('"', "'").split())
    return s if len(s) <= n else s[:n - 1] + "…"


class Vocabulary:
    def __init__(self, data: dict):
        self.groups = {k: [str(x).lower() for x in v] for k, v in (data.get("app_groups") or {}).items()}
        self.harmless = {norm(x) for x in data.get("harmless") or []}
        self.affirmative = {norm(x) for x in data.get("affirmative") or []}
        self.negations = [_rx(x) for x in data.get("negation_prefixes") or []]
        self.text_menu = [_rx(x) for x in data.get("text_menu_markers") or []]
        self.item_menu = [_rx(x) for x in data.get("item_menu_markers") or []]
        self.classes: list[RiskClass] = []
        for c in data.get("classes") or []:
            if c.get("category") not in RANK:
                raise ValueError(f"unknown category {c.get('category')!r} in class {c.get('class')!r}")
            terms = []
            for t in c.get("terms") or []:
                if isinstance(t, str):
                    t = {"t": t}
                terms.append(Term(t["t"], _rx(t["t"]), bool(t.get("weak")), t.get("apps"), t.get("not_apps")))
            self.classes.append(RiskClass(c["class"], c["category"], dict(c.get("label") or {}), terms,
                                          [_rx(u) for u in c.get("unless") or []]))
        self.by_name = {c.name: c for c in self.classes}

    @classmethod
    def load(cls, path: str | None = None) -> "Vocabulary":
        for p in ([path] if path else []) + _data_paths():
            try:
                with open(p, encoding="utf-8") as f:
                    return cls(json.load(f))
            except FileNotFoundError:
                continue
            except (OSError, ValueError, KeyError, TypeError) as e:
                log.error("risky-targets vocabulary %s is unusable: %s", p, e)
                continue
        log.error("no usable risky-targets vocabulary; using the built-in minimum")
        return cls(FALLBACK)

    # ------------------------------------------------------------------ matching
    def in_apps(self, app: str, names: list[str]) -> bool:
        ids = [x for x in (app or "").lower().split() if x]
        if not ids:
            return False
        wanted: list[str] = []
        for n in names:
            wanted += self.groups.get(n, [n.lower()])
        for a in ids:
            a = a[:-8] if a.endswith(".desktop") else a
            for w in wanted:
                if a == w or a.endswith("." + w) or a.split(".")[-1] == w:
                    return True
        return False

    def match_text(self, text: str, app: str = "", text_context: bool = False) -> Match | None:
        """The strictest class whose vocabulary occurs in ``text`` (already normalised or not)."""
        t = norm(text)
        if not t:
            return None
        best: tuple[int, int, Match] | None = None
        for c in self.classes:
            suppressed = text_context or any(u.search(t) for u in c.unless)
            for term in c.terms:
                if term.apps is not None and not self.in_apps(app, term.apps):
                    continue
                if term.not_apps is not None and self.in_apps(app, term.not_apps):
                    continue
                if term.weak and suppressed:
                    continue
                if term.rx.search(t):
                    key = (RANK[c.category], 0 if term.weak else 1)
                    if best is None or key > best[:2]:
                        best = (key[0], key[1], Match(c, term.phrase))
        return best[2] if best else None

    def classify(self, tg: Target) -> Match | None:
        """The risk of activating ``tg``, or None.  Only activating roles are judged."""
        if not tg.known or tg.role not in ACTIVATING:
            return None
        name = norm(tg.name)
        if name in self.harmless or any(n.match(name) for n in self.negations):
            return None
        m = self.match_text(tg.name, tg.app, tg.text_context)
        if m is None and tg.description and norm(tg.description) not in self.harmless:
            m = self.match_text(tg.description, tg.app, tg.text_context)
        if m is not None:
            return m
        # a generic confirmation in a dialog whose own text is risky ("… endgültig löschen?" [OK])
        if tg.dialog and (name in self.affirmative or (not name and tg.is_default)):
            m = self.match_text(tg.dialog, tg.app, False)
            if m is not None:
                m.via = "dialog"
                return m
        return None

    def is_text_menu(self, sibling_names: list[str]) -> bool:
        joined = " | ".join(norm(n) for n in sibling_names if n)
        hits = sum(1 for r in self.text_menu if r.search(joined))
        return hits >= 2 and not any(r.search(joined) for r in self.item_menu)


FALLBACK = {
    "classes": [
        {"class": "send", "category": "send", "label": {"de": "sendet etwas", "en": "sends something"},
         "terms": ["senden", "absenden", "send", "submit", "post", "publish", "upload"]},
        {"class": "purchase", "category": "purchase", "label": {"de": "kostet Geld", "en": "costs money"},
         "terms": ["kaufen", "bestellen", "bezahlen", "buy", "order", "pay", "checkout"]},
        {"class": "delete", "category": "files.delete", "label": {"de": "löscht endgültig", "en": "deletes permanently"},
         "terms": ["endgültig löschen", "papierkorb leeren", "delete permanently", "empty trash",
                   {"t": "löschen", "weak": True}, {"t": "delete", "weak": True}],
         "unless": ["in den papierkorb", "move to trash"]},
        {"class": "install", "category": "apps.install", "label": {"de": "installiert Software", "en": "installs software"},
         "terms": ["installieren", "deinstallieren", "install", "uninstall"]},
    ],
    "harmless": ["abbrechen", "schließen", "cancel", "close"], "affirmative": ["ok", "ja", "yes"],
}


def _data_paths() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    out = []
    if os.environ.get("KRISTALL_HANDS_RISKY_TARGETS"):
        out.append(os.environ["KRISTALL_HANDS_RISKY_TARGETS"])
    out.append(os.path.join(os.path.dirname(here), "data", "risky-targets.json"))   # source tree and /usr/lib/kristall/hands
    return out


# ---------------------------------------------------------------------------- resolution

class _OutOfTime(Exception):
    pass


class _Budget:
    """Bounds the accessibility lookups of one check: each D-Bus call may take at most the time
    that is left (libatspi's method timeout), and every step checks the deadline."""

    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds
        self.atspi = None

    def __enter__(self):
        try:
            from .a11y import _atspi
            self.atspi = _atspi()
            self.atspi.set_timeout(max(20, int(self.left() * 1000)), 10000)
        except Exception:
            self.atspi = None
        return self

    def __exit__(self, *exc):
        if self.atspi is not None:
            try:
                self.atspi.set_timeout(1500, 10000)      # A11y.ensure's setting
            except Exception:
                pass
        return False

    def left(self) -> float:
        return self.end - time.monotonic()

    def check(self) -> None:
        if time.monotonic() > self.end:
            raise _OutOfTime()


class Gate:
    def __init__(self, hands, a11y, vocab: Vocabulary | None = None, budget: float = BUDGET):
        self.h = hands
        self.a = a11y
        self._vocab = vocab
        self.budget = budget
        self.last: dict = {}          # the last check (for tests and the log)

    @property
    def vocab(self) -> Vocabulary:
        if self._vocab is None:                 # loaded on first use, not for `dropin`/`--version`
            self._vocab = Vocabulary.load()
        return self._vocab

    # ------------------------------------------------------------------ public
    def check_element(self, tool: str, acc, win: dict | None, risk: str | None, intent: str | None) -> str:
        """ui_act and click/drag by ref: the element is known."""
        t0 = time.monotonic()
        tg = self._guarded(lambda b: self._info(b, acc, win))
        return self._decide(tool, tg, risk, intent, t0)

    def check_point(self, tool: str, gx: float, gy: float, risk: str | None, intent: str | None) -> str:
        """click/drag by coordinates: the element under the global point."""
        t0 = time.monotonic()
        tg = self._guarded(lambda b: self._at_point(b, gx, gy))
        return self._decide(tool, tg, risk, intent, t0)

    def check_keys(self, tool: str, win: dict, chord: str, risk: str | None, intent: str | None) -> str | None:
        """Keys that activate: the focused button, or the default button for Return and friends."""
        if chord not in GATED_CHORDS:
            return None
        t0 = time.monotonic()
        tg = self._guarded(lambda b: self._for_keys(b, win, chord))
        if tg is None:
            return None
        return self._decide(tool, tg, risk, intent, t0)

    # ------------------------------------------------------------------ decision
    def _decide(self, tool: str, tg: Target, risk: str | None, intent: str | None, t0: float) -> str:
        m = self.vocab.classify(tg)
        if m is None and not tg.known and intent:
            # the element can't be read: the model's own description of the step is the evidence
            m = self.vocab.match_text(intent, tg.app, False)
            if m is not None:
                m.via = "intent"
        ms = (time.monotonic() - t0) * 1000
        self.last = {"tool": tool, "target": tg, "match": m, "risk": risk, "ms": round(ms, 1)}
        if m is None:
            log.debug("riskgate %s: %s (%.0f ms)", tool, tg.note(), ms)
            return tg.note()
        if satisfies(risk, m.category):
            log.info("riskgate %s: %s looks like %s; risk %s declared (%.0f ms)", tool, tg.note(), m.cls.name, risk, ms)
            return tg.note() + f" ({m.cls.name}; risk {risk} declared)"
        log.info("riskgate %s: refused %s as %s (term %r via %s, risk %s, %.0f ms)", tool, tg.note(), m.cls.name,
                 m.term, m.via, risk, ms)
        self._announce(tg, m, intent)
        raise HandsError(self.refusal(tool, tg, m, risk, intent))

    @staticmethod
    def refusal(tool: str, tg: Target, m: Match, risk: str | None, intent: str | None) -> str:
        if m.via == "intent":
            what = f'your intent "{_clip(intent)}"; the element there can\'t be read'
        else:
            what = tg.describe()
        weaker = (f' The declared risk:"{risk}" is not enough for this.' if risk else "")
        return (f'This looks like a "{m.cls.name}" action ({what}).{weaker} If the owner asked for this, call {tool} '
                f'again with the same arguments plus risk:"{m.category}"; the owner will be asked to confirm. '
                f"If they did not ask for it, don't do it.")

    def _announce(self, tg: Target, m: Match, intent: str | None) -> None:
        """A short owner-facing line in the activity area (assistant-ipc §4 tool_activity)."""
        what = _clip(tg.name if tg.known and tg.name else (intent or ""), 40)
        de = m.cls.label.get("de") or m.cls.name
        en = m.cls.label.get("en") or m.cls.name
        text = ({"de": f"„{what}“ {de} – braucht deine Zustimmung", "en": f"“{what}” {en} – needs your OK"} if what else
                {"de": f"Das {de} – braucht deine Zustimmung", "en": f"This {en} – needs your OK"})
        try:
            self.h.link.activity(text, "running", "riskgate-" + uuid.uuid4().hex[:6])
        except Exception:
            pass

    # ------------------------------------------------------------------ lookups
    def _guarded(self, fn) -> Target | None:
        try:
            if self.a.mode() == "off":
                return Target(reason="accessibility is off")
            self.a.ensure()
        except HandsError:
            return Target(reason="accessibility not available")
        except Exception as e:
            return Target(reason=f"accessibility not available ({type(e).__name__})")
        try:
            with _Budget(self.budget) as b:
                return fn(b)
        except _OutOfTime:
            return Target(reason=f"not identified within {int(self.budget * 1000)} ms")
        except HandsError as e:
            return Target(reason=e.message[:80])
        except Exception as e:                  # the gate never breaks an action by itself
            log.debug("riskgate lookup failed: %s", e)
            return Target(reason=f"lookup failed ({type(e).__name__})")

    def _info(self, b: _Budget, acc, win: dict | None, how: str = "", key: str = "") -> Target:
        a = self.a
        role = a.role_name(acc)
        b.check()
        if not role:
            return Target(reason="the element is gone")
        name = (a.safe(acc.get_name, "") or "").strip()
        desc = (a.safe(acc.get_description, "") or "").strip()
        st = a.states(acc)
        b.check()
        app = a.safe(acc.get_application)
        app_ids = " ".join(x for x in ((win or {}).get("appId") or "", (a.safe(app.get_name, "") or "") if app is not None else "") if x)
        tg = Target(known=True, role=role, name=name[:200], description=desc[:200], app=app_ids,
                    window=str((win or {}).get("title") or ""), is_default="is-default" in st or "default" in st, how=how,
                    key=key)
        if role not in ACTIVATING:
            if role in OPAQUE and not name:
                return Target(app=app_ids, window=tg.window, reason=f"only a {role or 'surface'} without a name")
            return tg
        top = a.top_of(acc)
        b.check()
        if top is not None:
            trole = a.role_name(top)
            if not tg.window:
                tg.window = a.safe(top.get_name, "") or ""
            if trole in DIALOGS or (trole != "frame" and "modal" in a.states(top)):
                tg.dialog = self._dialog_text(b, top)
        if role in MENU_ITEMS:
            tg.text_context = self._text_menu(b, acc, win)
        return tg

    def _dialog_text(self, b: _Budget, top) -> str:
        a = self.a
        parts = [a.safe(top.get_name, "") or "", a.safe(top.get_description, "") or ""]
        seen = [0]

        def walk(acc, depth):
            if seen[0] > 80 or depth > 8 or sum(len(p) for p in parts) > 600:
                return
            for i in range(min(a.safe(acc.get_child_count, 0) or 0, 40)):
                b.check()
                c = a.safe(lambda: acc.get_child_at_index(i))
                if c is None:
                    continue
                seen[0] += 1
                r = a.role_name(c)
                if r in TEXTISH:
                    s = (a.safe(c.get_name, "") or "").strip()
                    if not s and r != "text" and "Text" in a.ifaces(c):
                        s = a.text_of(c, 200)
                    if s and s not in parts:
                        parts.append(s[:200])
                elif r not in ACTIVATING:
                    walk(c, depth + 1)
        try:
            walk(top, 0)
        except _OutOfTime:
            pass              # what was read so far still counts
        return " · ".join(p for p in parts if p)[:600]

    def _text_menu(self, b: _Budget, acc, win: dict | None) -> bool:
        """A menu item of a text-editing menu (Cut/Copy/Paste/Select all), or the window's focus is in
        an editable text field: "Löschen" there deletes text, not files."""
        a = self.a
        parent = a.safe(acc.get_parent)
        names = []
        if parent is not None:
            for i in range(min(a.safe(parent.get_child_count, 0) or 0, 40)):
                b.check()
                c = a.safe(lambda: parent.get_child_at_index(i))
                if c is not None:
                    names.append(a.safe(c.get_name, "") or "")
        if self.vocab.is_text_menu(names):
            return True
        if win is not None and b.left() > 0.04:
            try:
                frame, _ = a.frame_for(win, None)
                f = a._focused_in(frame, cap=200)
                if f is not None:
                    st = a.states(f)
                    return a.role_name(f) in ("text", "entry", "document text", "terminal") and "editable" in st
            except HandsError:
                return False
        return False

    def _window_at(self, gx: float, gy: float) -> dict | None:
        wins = self.h.windows(normal_only=False)
        for w in reversed(wins):                   # bottom to top
            if w.get("minimized"):
                continue
            if str(w.get("namespace", "")).startswith("kristall-assistant"):
                continue                          # transparent to agent input (bridge.md)
            if w.get("x", 0) <= gx <= w.get("x", 0) + w.get("w", 0) and w.get("y", 0) <= gy <= w.get("y", 0) + w.get("h", 0):
                return w
        return None

    def _tops(self, b: _Budget, win: dict) -> list:
        a = self.a
        pid = win.get("pid")
        apps = [x for x in a.apps() if a.safe(x.get_process_id) == pid]
        b.check()
        if not apps:
            aid = str(win.get("appId", "")).lower()
            apps = [x for x in a.apps() if (a.safe(x.get_name, "") or "").lower() in (aid, aid.split(".")[-1])]
        popup = win.get("type") in ("popup", "menu") or win.get("normal") is False
        title = str(win.get("title", ""))
        c = win.get("content") if isinstance(win.get("content"), dict) else {}
        cw, ch = float(c.get("w") or win.get("w") or 0), float(c.get("h") or win.get("h") or 0)
        scored = []
        for app in apps:
            for f in a.frames(app):
                b.check()
                st = a.states(f)
                if "showing" not in st and "visible" not in st:
                    continue
                role = a.role_name(f)
                name = a.safe(f.get_name, "") or ""
                if popup:
                    score = (2 if role != "frame" else 0) + (1 if "showing" in st else 0)
                else:
                    score = (3 if name == title else 2 if name and title and (name in title or title in name) else 0) + \
                            (1 if "active" in st else 0) + (1 if role != "frame" and win.get("type") == "dialog" else 0)
                r = a.extents(f)
                if r is not None and cw and abs(r[2] - cw) <= 4 and abs(r[3] - ch) <= 4:
                    score += 2                     # same size as the window's client area
                scored.append((score, len(scored), f))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [f for _, _, f in scored]

    def _hit(self, b: _Budget, top, wx: float, wy: float):
        """The deepest element at a window-relative point: the toolkit's own hit test
        (Component.GetAccessibleAtPoint) level by level; where a level does not answer (Firefox's
        browser frame, some containers) or answers with an element whose bounds do not contain the
        point (Firefox at a fractional output scale), its showing children's bounds are compared."""
        from .a11y import _atspi
        Atspi = _atspi()
        cur, depth = top, 0
        while depth < 40:
            b.check()
            try:
                child = Atspi.Component.get_accessible_at_point(cur, int(round(wx)), int(round(wy)), Atspi.CoordType.WINDOW)
            except Exception:
                child = None
            if child is not None and child != cur and not self._contains(child, wx, wy):
                child = None
            if child is None or child == cur:
                child = self._child_containing(b, cur, wx, wy)
                if child is None:
                    break
            cur, depth = child, depth + 1
        return None if cur is top else cur

    def _contains(self, acc, wx: float, wy: float, slack: float = 2) -> bool:
        r = self.a.extents(acc)
        if r is None or r[2] <= 0 or r[3] <= 0:
            return True                      # no bounds to judge by: trust the toolkit
        return r[0] - slack <= wx <= r[0] + r[2] + slack and r[1] - slack <= wy <= r[1] + r[3] + slack

    def _child_containing(self, b: _Budget, acc, wx: float, wy: float):
        a = self.a
        found = None
        for i in range(min(a.safe(acc.get_child_count, 0) or 0, 200)):
            b.check()
            c = a.safe(lambda: acc.get_child_at_index(i))
            if c is None:
                continue
            r = a.extents(c)
            if r is None or r[2] <= 0 or r[3] <= 0 or not (r[0] <= wx < r[0] + r[2] and r[1] <= wy < r[1] + r[3]):
                continue
            st = a.states(c)
            if "showing" not in st and "visible" not in st:
                continue
            found = c                       # the last one: later siblings are drawn on top
        return found

    def _at_point(self, b: _Budget, gx: float, gy: float) -> Target:
        win = self._window_at(gx, gy)
        if win is None:
            return Target(reason="no window at that point")
        if str(win.get("namespace", "")).startswith("kristall-") or win.get("type") in ("dock", "desktop", "layer"):
            return Target(window=str(win.get("namespace") or win.get("type")), reason="a shell surface")
        c = win.get("content") if isinstance(win.get("content"), dict) and "x" in win.get("content", {}) else None
        ox, oy = (float(c["x"]), float(c["y"])) if c else (float(win.get("x", 0)), float(win.get("y", 0)))
        wx, wy = gx - ox, gy - oy
        b.check()
        hit = None
        for top in self._tops(b, win)[:4]:
            h = self._hit(b, top, wx, wy)
            if h is None:
                continue
            if not self._contains(h, wx, wy):
                continue                           # another top-level's element: wrong candidate
            hit = h
            break
        if hit is None:
            return Target(app=str(win.get("appId") or ""), window=str(win.get("title") or ""),
                          reason="the app does not expose its controls there")
        # the actionable element around the hit (a button's label, a link's text leaf)
        cur, hops = hit, 0
        while cur is not None and hops < 4:
            if self.a.role_name(cur) in ACTIVATING:
                hit = cur
                break
            cur = self.a.safe(cur.get_parent)
            hops += 1
            b.check()
        return self._info(b, hit, win)

    def _for_keys(self, b: _Budget, win: dict, chord: str) -> Target | None:
        a = self.a
        key = KEY_NAMES.get(chord, chord)
        frame, _ = a.frame_for(win, None)
        b.check()
        f = a._focused_in(frame, cap=300)
        b.check()
        if f is not None:
            role = a.role_name(f)
            if role in ACTIVATING:
                return self._info(b, f, win, how="focus", key=key)
            if chord == "space":
                return None                         # Space types or toggles: only a focused button counts
            st = a.states(f)
            if chord in ("return", "kp_enter") and "multi-line" in st:
                return None                         # Return makes a new line in a multi-line text
        elif chord == "space":
            return Target(app=str(win.get("appId") or ""), window=str(win.get("title") or ""),
                          reason="the window does not report its focus")
        d = self._default_in(b, frame)
        if d is not None:
            return self._info(b, d, win, how="default", key=key)
        if f is None:
            return Target(app=str(win.get("appId") or ""), window=str(win.get("title") or ""),
                          reason="the window does not report its focus")
        return None

    def _default_in(self, b: _Budget, frame):
        a = self.a
        from .a11y import _atspi
        Atspi = _atspi()
        if "Collection" in a.ifaces(frame):
            try:
                ss = Atspi.StateSet.new([Atspi.StateType.IS_DEFAULT, Atspi.StateType.SHOWING])
                rule = Atspi.MatchRule.new(ss, Atspi.CollectionMatchType.ALL, [], Atspi.CollectionMatchType.NONE,
                                           [], Atspi.CollectionMatchType.NONE, [], Atspi.CollectionMatchType.NONE, False)
                res = Atspi.Collection.get_matches(frame, rule, Atspi.CollectionSortOrder.CANONICAL, 3, True)
                for r in res or []:
                    if a.role_name(r) in ACTIVATING:
                        return r
                return None
            except Exception:
                pass
        seen = [0]

        def dfs(acc, depth):
            b.check()
            seen[0] += 1
            if seen[0] > 300 or depth > 14:
                return None
            for i in range(min(a.safe(acc.get_child_count, 0) or 0, 60)):
                c = a.safe(lambda: acc.get_child_at_index(i))
                if c is None:
                    continue
                st = a.states(c)
                if "showing" not in st:
                    continue
                if a.role_name(c) in ACTIVATING:
                    if "is-default" in st or "default" in st:
                        return c
                    continue
                r = dfs(c, depth + 1)
                if r is not None:
                    return r
            return None
        return dfs(frame, 0)
