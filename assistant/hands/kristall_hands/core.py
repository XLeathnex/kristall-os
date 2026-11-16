# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared state of the tool server: bridge, assistant link, cursor, settings, apps, windows."""
from __future__ import annotations

import threading
import time

from . import log
from .apps import AppIndex, clean_query, fold
from .bridge import Bridge, BridgeError
from .config import Settings
from .cursor import Cursor
from .link import Link
from .safety import ensure_unlocked
from .tooling import Context, HandsError

NO_BRIDGE = ("Window control and pointing are not available right now (the compositor bridge is not "
             "running). Opening apps, settings and reading app controls still work.")
BRIDGE_DENIED = ("The compositor refused screen control to this program. This is an installation "
                 "problem; the owner can do this step by hand meanwhile.")
CANCELLED_BY_OWNER = ("The owner pressed Escape to stop you. Stop what you were doing and briefly tell "
                      "them where you stopped.")


class Hands:
    def __init__(self, *, bridge: Bridge | None = None, link: Link | None = None, settings: Settings | None = None,
                 apps: AppIndex | None = None):
        self.bridge = bridge or Bridge()
        self.link = link or Link()
        self.settings = settings or Settings()
        self.apps = apps or AppIndex()
        self.cursor = Cursor(self.link, lambda: self.cfg().get("cursor", {}))
        self.bridge.on_agent_state = self._agent_state
        self.link.on_turn_finished = self._turn_finished
        self.link.on_turn_started = self._turn_started
        self.owner_cancelled = False
        self._aliases: dict[str, str] = {}     # short alias -> bridge window id
        self._rev: dict[str, str] = {}
        self._lock = threading.Lock()
        self.a11y = None                        # set by server (A11y instance)
        self.check_lock = True
        self.last_action = 0.0

    # ------------------------------------------------------------------ settings
    def cfg(self) -> dict:
        try:
            return self.settings.hands()
        except Exception:     # settings must never break a tool
            log.exception("settings")
            from .config import DEFAULTS
            return DEFAULTS

    def lang(self) -> str:
        if self.link.language in ("de", "en"):
            return self.link.language
        try:
            return self.settings.language()
        except Exception:
            return "de"

    def say(self, de: str, en: str) -> str:
        return de if self.lang() == "de" else en

    @property
    def protected(self) -> list[str]:
        return list(self.cfg().get("protected_apps") or [])

    # ------------------------------------------------------------------ events
    def _agent_state(self, data: dict) -> None:
        if data.get("active"):
            return
        label = data.get("label")
        if label == "cancelled":
            log.info("owner pressed Escape: agent session cancelled")
            self.owner_cancelled = True
            self.cursor.hide()
        elif label == "locked":
            self.cursor.hide()

    def _turn_started(self, _tid) -> None:
        self.owner_cancelled = False

    def _turn_finished(self, _tid, outcome: str) -> None:
        self.finish_work()
        if outcome == "cancelled":
            self.owner_cancelled = False

    def finish_work(self) -> None:
        """The work is over: the cursor leaves and the agent session closes."""
        self.cursor.hide()
        if self.bridge.session:
            try:
                self.bridge.end()
            except Exception:
                pass

    # ------------------------------------------------------------------ guards
    def guard(self, ctx: Context | None = None, acting: bool = True) -> None:
        """Checks before reading the screen or acting on it."""
        if self.owner_cancelled and acting:
            raise HandsError(CANCELLED_BY_OWNER)
        if ctx:
            ctx.check()
        if self.check_lock:
            ensure_unlocked()

    def need_bridge(self, cap: str | None = None) -> Bridge:
        b = self.bridge
        if not b.ensure():
            raise HandsError(NO_BRIDGE)
        if cap and not b.has(cap):
            raise HandsError(f"This compositor does not offer '{cap}', so this action is not available. "
                             f"Try another way (for example the app's controls via ui_tree).")
        if cap in ("agentInput", "agentText", "screenshot") and b.privileged is False:
            if self.check_lock:
                ensure_unlocked()
            raise HandsError(BRIDGE_DENIED)
        return b

    def agent(self, ctx: Context | None, method: str, params: dict, label: str = "Kristall", timeout: float = 10.0) -> dict:
        """An agent.* call inside the session: begins one if needed, starts a new one when the old
        one ended (timeout, disconnect), waits once when the owner is busy."""
        b = self.bridge
        for attempt in range(3):
            if ctx:
                ctx.check()
            if self.owner_cancelled:
                raise HandsError(CANCELLED_BY_OWNER)
            sess = b.session or self.begin_session(label)
            try:
                return b.request(method, dict(params, session=sess), timeout=timeout)
            except BridgeError as e:
                if e.code == "denied" or (e.code in ("invalid", "not_found") and "session" in e.message.lower()):
                    b.session = None            # expired, ended by lock, or refused
                    if self.check_lock:
                        ensure_unlocked()
                    if attempt < 1:
                        continue
                    raise HandsError(BRIDGE_DENIED)
                if e.code == "busy" and attempt < 2:
                    if ctx:
                        ctx.sleep(1.0)
                    else:
                        time.sleep(1.0)
                    continue
                raise
        raise HandsError("Screen control did not respond. Try again in a moment.")

    def begin_session(self, label: str) -> str | None:
        """Bracket work with the bridge's agent session (Escape cancels it).  None when the
        bridge is not available (tier 2 still works without it)."""
        b = self.bridge
        if not b.ensure() or not b.has("agentInput"):
            return None
        try:
            return b.begin(label or "Kristall")
        except BridgeError as e:
            if e.code == "denied":
                if self.check_lock:
                    ensure_unlocked()
                raise HandsError(BRIDGE_DENIED)
            if e.code == "busy":
                # an orphaned session of ours from an earlier connection, or another tool: retry once
                time.sleep(0.3)
                try:
                    return b.begin(label or "Kristall")
                except BridgeError:
                    raise HandsError("Another program is controlling the screen right now. Try again in a moment.")
            raise HandsError(f"Screen control is not available right now ({e.code}).")

    def touch(self) -> None:
        self.last_action = time.monotonic()
        self.cursor.linger()

    # ------------------------------------------------------------------ windows
    def alias(self, wid: str) -> str:
        with self._lock:
            a = self._rev.get(wid)
            if a is None:
                a = f"w{len(self._aliases) + 1}"
                self._aliases[a] = wid
                self._rev[wid] = a
            return a

    def unalias(self, ref: str) -> str:
        return self._aliases.get(ref, ref)

    def windows(self, normal_only: bool = True) -> list[dict]:
        b = self.bridge
        if not b.ensure():
            raise HandsError(NO_BRIDGE)
        wins = b.windows()
        if normal_only:
            wins = [w for w in wins if w.get("normal", True)]
        return wins

    def window_by_id(self, wid: str) -> dict | None:
        for w in self.windows(normal_only=False):
            if w.get("id") == wid:
                return w
        return None

    def active_window(self) -> dict | None:
        for w in self.windows():
            if w.get("active"):
                return w
        return None

    def resolve_window(self, spec: str | None, *, default_active: bool = True) -> dict:
        wins = self.windows()
        if not spec:
            if default_active:
                for w in wins:
                    if w.get("active"):
                        return w
                visible = [w for w in wins if not w.get("minimized")]
                if visible:
                    return visible[-1]
            raise HandsError("There is no open window to work with.")
        wid = self.unalias(spec.strip())
        for w in wins:
            if w.get("id") == wid:
                return w
        q = clean_query(spec) or fold(spec)
        best, best_score = None, 0
        for w in wins:
            app = fold(str(w.get("appId", "")))
            title = fold(str(w.get("title", "")))
            names = [app, app.split(" ")[-1] if app else ""]
            entry = self.apps.apps().get(str(w.get("appId", "")) + ".desktop")
            if entry:
                names += [fold(n) for n in entry.names]
            score = 0
            if q and any(q == n for n in names if n):
                score = 100
            elif q and any(n and (q in n or n in q) for n in names if len(n) >= 3):
                score = 80
            elif q and q in title:
                score = 70
            elif q and all(t in title for t in q.split()):
                score = 60
            if w.get("active"):
                score += 1
            if score > best_score:
                best, best_score = w, score
        if best is None or best_score < 60:
            raise HandsError(f"I can't find an open window matching “{spec[:60]}”. Use list_windows to see what is open.")
        return best

    def describe_window(self, w: dict) -> str:
        flags = [f for f in ("active", "minimized", "maximized", "fullscreen") if w.get(f)]
        geo = f"{int(w.get('w', 0))}x{int(w.get('h', 0))} at {int(w.get('x', 0))},{int(w.get('y', 0))}"
        return (f"{self.alias(str(w.get('id')))} \"{str(w.get('title', ''))[:120]}\" app={w.get('appId', '')} {geo}"
                + (" [" + ",".join(flags) + "]" if flags else ""))
