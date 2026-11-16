# SPDX-License-Identifier: GPL-3.0-or-later
"""Choreography of the assistant's own cursor (drawn by the interface from ``agent_cursor``).

The cursor should read as a calm hand: it appears close to where the work starts, glides to each
target and only then does the action land (the interface animates the glide over
``duration_ms``; we wait for it), pulses as the click/keystroke happens, carries a short label
of the current step, and leaves when the work is over (end of the turn, the owner's Escape, a
cancelled call, or a few idle seconds).  One event per glide, one per pulse: no streams of
positions, so the daemon and the interface stay quiet.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable

from .tooling import Context


class Cursor:
    APPEAR_OFFSET = (-48.0, 36.0)

    def __init__(self, link, config: Callable[[], dict] | None = None):
        self.link = link
        self.config = config or (lambda: {})
        self.visible = False
        self.pos: tuple[float, float] | None = None
        self.label = ""
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ settings
    def _cfg(self) -> dict:
        c = self.config() or {}
        return c if isinstance(c, dict) else {}

    def enabled(self) -> bool:
        return bool(self._cfg().get("enabled", True))

    def glide_ms(self, dist: float) -> int:
        speed = float(self._cfg().get("speed", 1.0) or 1.0)
        speed = min(3.0, max(0.25, speed))
        ms = 220.0 + 0.40 * dist
        return int(min(800.0, max(260.0, ms)) / speed)

    # ------------------------------------------------------------------ moves
    def _send(self, **f) -> bool:
        return self.link.cursor(**f)

    def move_to(self, ctx: Context | None, x: float, y: float, label: str = "", output: str | None = None) -> None:
        """Glide to (x, y) and return when the cursor has arrived."""
        if not self.enabled():
            return
        self._cancel_timer()
        x, y = round(float(x), 1), round(float(y), 1)
        label = (label or self.label or "")[:60]
        self.label = label
        delivered = True
        if not self.visible or self.pos is None:
            sx, sy = round(x + self.APPEAR_OFFSET[0], 1), round(y + self.APPEAR_OFFSET[1], 1)
            delivered = self._send(x=sx, y=sy, visible=True, label=label, duration_ms=0)
            self.visible, self.pos = True, (sx, sy)
        dist = math.hypot(x - self.pos[0], y - self.pos[1])
        dur = self.glide_ms(dist) if dist > 1 else 0
        delivered = self._send(x=x, y=y, visible=True, label=label, output=output, duration_ms=dur) and delivered
        self.pos = (x, y)
        # Time the action to the arrival, but only if somebody can actually see the cursor.
        if delivered and dur:
            wait = dur / 1000.0 + 0.04
            if ctx is not None:
                ctx.sleep(wait)
            else:
                time.sleep(wait)

    def pulse(self, kind: str, label: str | None = None, output: str | None = None) -> None:
        if not self.enabled() or not self.visible:
            return
        f = {"visible": True, "pulse": kind}
        if self.pos:
            f["x"], f["y"] = self.pos
        if label:
            self.label = label[:60]
            f["label"] = self.label
        if output is not None:
            f["output"] = output[:80]
        self._send(**f)

    def set_label(self, label: str) -> None:
        if self.visible and label and label != self.label:
            self.label = label[:60]
            self._send(visible=True, label=self.label)

    def hide(self) -> None:
        self._cancel_timer()
        if self.visible:
            self.visible = False
            self._send(visible=False)

    def linger(self) -> None:
        """Hide after a quiet period unless another action comes first (one-shot timer)."""
        secs = float(self._cfg().get("linger_seconds", 6) or 6)
        with self._lock:
            self._cancel_timer_locked()
            t = threading.Timer(secs, self.hide)
            t.daemon = True
            self._timer = t
            t.start()

    def _cancel_timer(self) -> None:
        with self._lock:
            self._cancel_timer_locked()

    def _cancel_timer_locked(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
