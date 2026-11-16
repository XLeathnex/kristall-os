# SPDX-License-Identifier: GPL-3.0-or-later
"""Tier 2: operating apps through their accessibility tree (AT-SPI), without the pointer.

A snapshot is a compact, indented text outline of a window's *useful* elements: interactive
controls and named content, each with a short reference (``e12``), role, name, value, state and
bounds (logical pixels relative to the window's content area).  Layout-only containers are
dropped and their children hoisted, invisible subtrees are skipped, long lists are cut with a
count, and a budget caps the size; ``find`` searches the whole tree by text instead.

Accessibility (``org.a11y.Status.IsEnabled``) is on from the start of the session while the
assistant is enabled (mode ``always``, the default: apps such as Firefox and Chromium only look at
it when they start); in mode ``on_demand`` it is switched on when first needed and off again when
this server exits.  See docs/contracts/hands.md §5 for per-toolkit details and the measured cost.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from . import dbus, log
from .safety import PROTECTED_MSG, is_protected_app, mask_secrets
from .tooling import Context, HandsError

UNAVAILABLE = ("App controls can't be read on this system right now (the accessibility service is not "
               "available). Use screenshot and click instead.")

ROLE_SHORT = {
    "push button": "button", "toggle button": "toggle", "check box": "checkbox", "radio button": "radio",
    "combo box": "combobox", "page tab": "tab", "page tab list": "tabs", "menu item": "menuitem",
    "check menu item": "menuitem-check", "radio menu item": "menuitem-radio", "menu bar": "menubar",
    "tool bar": "toolbar", "status bar": "statusbar", "list item": "item", "tree item": "treeitem",
    "table cell": "cell", "column header": "colheader", "row header": "rowheader", "spin button": "spinbox",
    "password text": "password", "entry": "textbox", "text": "text", "document web": "document",
    "document frame": "document", "document text": "document", "tree table": "treetable",
    "scroll bar": "scrollbar", "split pane": "splitpane", "progress bar": "progress", "push button menu": "menubutton",
    "editbar": "toolbar", "description list": "list", "table row": "row", "tool tip": "tooltip",
}
STRUCTURAL = {"panel", "filler", "section", "unknown", "layered pane", "scroll pane", "viewport", "split pane",
              "internal frame", "redundant object", "form", "glass pane", "root pane", "option pane",
              "invalid", "extended", "block quote", "paragraph", "article", "landmark", "grouping", "group",
              "table row", "description list", "static", "image map", "autocomplete", "embedded"}
INTERACTIVE = {"push button", "toggle button", "check box", "radio button", "combo box", "page tab", "menu item",
               "check menu item", "radio menu item", "menu", "entry", "text", "password text", "spin button",
               "slider", "link", "list item", "tree item", "table cell", "icon", "dial", "editbar", "column header",
               "push button menu", "terminal", "document web", "document frame", "document text", "row header",
               "switch", "tab", "date editor", "font chooser", "color chooser", "file chooser", "toggle"}
CONTAINERS = {"list", "list box", "tree", "tree table", "table", "page tab list", "menu bar", "tool bar",
              "menu", "combo box", "dialog", "alert", "frame", "window", "status bar", "heading", "label",
              "document web", "document frame", "notification", "tool tip"}
SKIP = {"scroll bar", "separator", "tool tip"}
TEXTISH = {"entry", "text", "password text", "terminal", "document text", "spin button", "editbar", "combo box"}
LISTISH = {"list", "list box", "tree", "tree table", "table", "menu"}

PRESS_ACTIONS = ["press", "click", "activate", "invoke", "jump", "open", "select", "toggle", "default",
                 "SetFocus", "showMenu"]


def _atspi():
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="gi")
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    return Atspi


class Node:
    __slots__ = ("acc", "role", "name", "pid", "win_id")

    def __init__(self, acc, role="", name="", pid=0, win_id=None):
        self.acc, self.role, self.name, self.pid, self.win_id = acc, role, name, pid, win_id


class A11y:
    def __init__(self, hands):
        self.h = hands
        self._ready = False
        self._enabled_by_us = False
        self._refs: "OrderedDict[str, Node]" = OrderedDict()
        self._next = 1
        self._lock = threading.Lock()
        self.stats = {}
        self.text_limit = 160

    # ------------------------------------------------------------------ session switch
    def mode(self) -> str:
        m = self.h.cfg().get("accessibility", "always")
        return m if m in ("on_demand", "always", "off") else "always"

    def prepare(self) -> None:
        """Make sure apps expose their trees (called before tier-2 work and before launching apps)."""
        if self.mode() == "off":
            return
        bus = dbus.session()
        try:
            on = bus.get("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled")
            if not on:
                bus.set("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled", "b", True)
                self._enabled_by_us = True
                log.info("accessibility switched on for the session")
                time.sleep(0.4)   # Qt apps register asynchronously
        except dbus.DBusError as e:
            log.info("cannot switch accessibility on: %s", e)

    def restore(self) -> None:
        if self._enabled_by_us and self.mode() == "on_demand":
            try:
                dbus.session().set("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled", "b", False)
                log.info("accessibility switched off again")
            except dbus.DBusError:
                pass
            self._enabled_by_us = False

    def ensure(self):
        if self.mode() == "off":
            raise HandsError("Reading app controls is switched off in the settings. Use screenshot and click instead.")
        try:
            Atspi = _atspi()
        except (ImportError, ValueError):
            raise HandsError(UNAVAILABLE)
        if not self._ready:
            # libatspi aborts the whole process when it cannot reach the accessibility bus, so make
            # sure the bus exists (or can be activated) before initialising it.
            bus = dbus.session()
            if not (bus.has_owner("org.a11y.Bus") or bus.activatable("org.a11y.Bus")):
                raise HandsError(UNAVAILABLE)
            try:
                bus.call("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress", timeout_ms=3000)
            except dbus.DBusError:
                raise HandsError(UNAVAILABLE)
            try:
                Atspi.init()
                Atspi.set_timeout(1500, 10000)
            except Exception as e:
                log.warning("atspi init failed: %s", e)
                raise HandsError(UNAVAILABLE)
            self._ready = True
        self.prepare()
        return Atspi

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def role_name(acc) -> str:
        try:
            return acc.get_role_name() or ""
        except Exception:
            return ""

    @staticmethod
    def safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    # Interface methods are called explicitly as Atspi.<Interface>.<method>(acc, ...): through the
    # PyGObject wrappers `acc.get_text_iface().get_text(...)` resolves to the deprecated
    # Accessible.get_text() and fails.
    def ifaces(self, acc) -> set[str]:
        return set(self.safe(acc.get_interfaces, []) or [])

    def char_count(self, acc) -> int:
        return int(self.safe(lambda: _atspi().Text.get_character_count(acc), 0) or 0)

    def text_of(self, acc, limit: int | None = None) -> str:
        n = self.char_count(acc)
        if n <= 0:
            return ""
        end = n if limit is None else min(n, limit)
        return self.safe(lambda: _atspi().Text.get_text(acc, 0, end), "") or ""

    def text_tail(self, acc, count: int = 120) -> tuple[str, int]:
        n = self.char_count(acc)
        if n <= 0:
            return "", 0
        start = max(0, n - count)
        return (self.safe(lambda: _atspi().Text.get_text(acc, start, n), "") or ""), n

    def set_text(self, acc, text: str) -> bool:
        return bool(self.safe(lambda: _atspi().EditableText.set_text_contents(acc, text), False))

    def insert_text(self, acc, pos: int, text: str) -> bool:
        return bool(self.safe(lambda: _atspi().EditableText.insert_text(acc, pos, text, len(text)), False))

    def value(self, acc):
        if "Value" not in self.ifaces(acc):
            return None
        V = _atspi().Value
        cur = self.safe(lambda: V.get_current_value(acc))
        if cur is None:
            return None
        return cur, self.safe(lambda: V.get_minimum_value(acc)), self.safe(lambda: V.get_maximum_value(acc))

    def set_value(self, acc, v: float) -> bool:
        return bool(self.safe(lambda: _atspi().Value.set_current_value(acc, v), False))

    def grab_focus(self, acc) -> bool:
        return bool(self.safe(lambda: _atspi().Component.grab_focus(acc), False))

    def scroll_to(self, acc) -> bool:
        Atspi = _atspi()
        return bool(self.safe(lambda: Atspi.Component.scroll_to(acc, Atspi.ScrollType.ANYWHERE), False))

    def top_of(self, acc):
        cur, hops = acc, 0
        while cur is not None and hops < 60:
            if self.role_name(cur) in ("frame", "dialog", "window", "alert", "file chooser"):
                return cur
            cur = self.safe(cur.get_parent)
            hops += 1
        return None

    def states(self, acc) -> set[str]:
        Atspi = _atspi()
        ss = self.safe(acc.get_state_set)
        if ss is None:
            return set()
        out = set()
        for st in self.safe(ss.get_states, []) or []:
            out.add(Atspi.StateType(st).value_nick if hasattr(Atspi.StateType(st), "value_nick") else str(st))
        return out

    def new_ref(self, node: Node) -> str:
        with self._lock:
            ref = f"e{self._next}"
            self._next += 1
            self._refs[ref] = node
            while len(self._refs) > 5000:
                self._refs.popitem(last=False)
            return ref

    def node(self, ref: str) -> Node:
        n = self._refs.get(ref.strip())
        if n is None:
            raise HandsError(f"I don't know the element “{ref[:20]}”. Take a fresh ui_tree of the window first.")
        return n

    # ------------------------------------------------------------------ apps and windows
    def apps(self) -> list:
        Atspi = self.ensure()
        desk = Atspi.get_desktop(0)
        out = []
        for i in range(self.safe(desk.get_child_count, 0) or 0):
            app = self.safe(lambda: desk.get_child_at_index(i))
            if app is not None:
                out.append(app)
        return out

    def frames(self, app) -> list:
        out = []
        for i in range(self.safe(app.get_child_count, 0) or 0):
            f = self.safe(lambda: app.get_child_at_index(i))
            if f is None:
                continue
            out.append(f)
        return out

    def frame_for(self, win: dict | None, spec: str | None = None):
        """The top-level accessible of a bridge window (by pid + title), or — without the
        bridge — by app/window name or the active frame."""
        apps = self.apps()
        if win is not None:
            pid = win.get("pid")
            title = str(win.get("title", ""))
            cands = [a for a in apps if self.safe(a.get_process_id) == pid]
            if not cands:
                aid = str(win.get("appId", "")).lower().split(".")[-1]
                cands = [a for a in apps if (self.safe(a.get_name, "") or "").lower() in (aid, str(win.get("appId", "")).lower())]
            best = None
            for app in cands:
                for f in self.frames(app):
                    name = self.safe(f.get_name, "") or ""
                    st = self.states(f)
                    score = (3 if name == title else 2 if name and (name in title or title in name) else 0) + \
                            (1 if "active" in st else 0) + (1 if "showing" in st else 0)
                    if best is None or score > best[0]:
                        best = (score, f, app)
            if best is None:
                raise HandsError("This window does not expose its controls (the app was probably started before "
                                 "accessibility was switched on, or its toolkit has no support). Use screenshot and "
                                 "click instead, or restart the app if the owner agrees.")
            return best[1], best[2]
        # no bridge: AT-SPI only
        from .apps import fold
        q = fold(spec) if spec else ""
        best = None
        for app in apps:
            an = (self.safe(app.get_name, "") or "")
            if an in ("kwin", "kwin_wayland", "plasmashell", "quickshell") and not q:
                continue
            for f in self.frames(app):
                name = self.safe(f.get_name, "") or ""
                st = self.states(f)
                if q:
                    score = 3 if q == fold(an) else 2 if q in fold(name) or q in fold(an) else 0
                    if not score:
                        continue
                else:
                    score = 0
                score += (2 if "active" in st else 0) + (1 if "showing" in st else 0)
                if best is None or score > best[0]:
                    best = (score, f, app)
        if best is None:
            raise HandsError("I can't find that window's controls.")
        return best[1], best[2]

    def target(self, window: str | None):
        """Resolve a window spec to (bridge window or None, frame, app)."""
        win = None
        if self.h.bridge.ensure():
            win = self.h.resolve_window(window)
            if is_protected_app(str(win.get("appId", "")), self.h.protected):
                raise HandsError(PROTECTED_MSG)
        frame, app = self.frame_for(win, window)
        an = self.safe(app.get_name, "") or ""
        if is_protected_app(an, self.h.protected):
            raise HandsError(PROTECTED_MSG)
        return win, frame, app

    # ------------------------------------------------------------------ geometry
    def extents(self, acc):
        Atspi = _atspi()
        r = self.safe(lambda: Atspi.Component.get_extents(acc, Atspi.CoordType.WINDOW))
        if r is None:
            return None
        return (r.x, r.y, r.width, r.height)

    def to_global(self, win: dict | None, frame, rect) -> tuple[float, float] | None:
        """Centre of an element in global compositor coordinates (approximate on Wayland: the
        element's window-relative position plus the window's frame position and decoration)."""
        if win is None or rect is None:
            return None
        x, y, w, h = rect
        c = win.get("content")
        if isinstance(c, dict) and "x" in c:
            # the bridge reports the client area inside the frame: exact
            return float(c["x"]) + x + w / 2, float(c["y"]) + y + h / 2
        fx, fy, fw, fh = float(win.get("x", 0)), float(win.get("y", 0)), float(win.get("w", 0)), float(win.get("h", 0))
        fr = self.extents(frame)
        dx = dy = 0.0
        if fr and fr[2] > 0 and fr[3] > 0 and fr[2] <= fw and fr[3] <= fh:
            dx = (fw - fr[2]) / 2
            dy = max(0.0, fh - fr[3] - dx)
        return fx + dx + x + w / 2, fy + dy + y + h / 2

    # ------------------------------------------------------------------ snapshot
    def describe(self, acc, role: str, *, bounds: bool, with_value: bool = True) -> tuple[str, str, set]:
        """(label line without ref, name, states)"""
        name = (self.safe(acc.get_name, "") or "").strip()
        st = self.states(acc)
        short = ROLE_SHORT.get(role, role)
        parts = [short]
        if name:
            parts.append('"' + mask_secrets(name[:100]).replace("\n", " ") + '"')
        if with_value:
            val = self.value_text(acc, role)
            if val is not None:
                parts.append(val)
        flags = []
        if "focused" in st:
            flags.append("focused")
        if role in ("check box", "toggle button", "check menu item", "radio button", "radio menu item", "switch"):
            flags.append("checked" if ("checked" in st or "pressed" in st) else "unchecked")
        if "selected" in st and role not in ("frame", "window"):
            flags.append("selected")
        if "expandable" in st:
            flags.append("expanded" if "expanded" in st else "collapsed")
        if "enabled" not in st and "sensitive" not in st and role not in STRUCTURAL and role not in ("label", "heading"):
            flags.append("disabled")
        if role in TEXTISH and role != "combo box" and "editable" not in st and "focusable" in st:
            flags.append("readonly")
        if "modal" in st:
            flags.append("modal")
        if flags:
            parts.append("{" + ",".join(flags) + "}")
        if bounds:
            r = self.extents(acc)
            if r and r[2] > 0 and r[3] > 0:
                parts.append(f"@{r[0]},{r[1]} {r[2]}x{r[3]}")
        return " ".join(parts), name, st

    def value_text(self, acc, role: str) -> str | None:
        if role == "password text":
            return "=•••(hidden)"
        if role in ("slider", "spin button", "progress bar", "dial", "scroll bar", "level bar"):
            v = self.value(acc)
            if v is not None:
                cur, lo, hi = v
                rng = f" ({lo:g}–{hi:g})" if lo is not None and hi is not None else ""
                return f"={cur:g}{rng}"
        if role in TEXTISH or role in ("document web", "document frame", "label", "heading", "table cell", "list item"):
            if "Text" in self.ifaces(acc):
                n = self.char_count(acc)
                if n == 0:
                    return '=""' if role in TEXTISH else None
                lim = self.text_limit
                s = self.text_of(acc, lim)
                name = (self.safe(acc.get_name, "") or "").strip()
                if role not in TEXTISH and s.strip() == name:
                    return None
                s = mask_secrets(s).replace("\n", "⏎")
                more = f"…({n} chars)" if n > lim else ""
                return f'="{s}"{more}'
        return None

    def snapshot(self, ctx: Context, window: str | None = None, *, root: str | None = None, find: str | None = None,
                 max_items: int | None = None, max_depth: int | None = None, bounds: bool = True,
                 region: list | None = None) -> tuple[str, dict]:
        cfg = self.h.cfg().get("snapshot", {})
        max_items = int(max_items or cfg.get("max_items", 120))
        max_depth = int(max_depth or cfg.get("max_depth", 30))
        t0 = time.monotonic()
        if root:
            n = self.node(root)
            start, win_id, app_pid = n.acc, n.win_id, n.pid
            win = self.h.window_by_id(win_id) if (win_id and self.h.bridge.ensure()) else None
            frame = start
        else:
            win, frame, app = self.target(window)
            start = frame
            win_id = win.get("id") if win else None
            app_pid = self.safe(app.get_process_id, 0)
        title = self.safe(frame.get_name, "") or ""
        lines: list[str] = []
        visited = [0]
        count = [0]
        truncated = [False]
        fq = find.lower().strip() if find else None
        list_cap = 25
        visit_cap = 4000 if fq else max(800, max_items * 15)
        matches: list[str] = []

        def inter(a, b):
            if a is None:
                return b
            if b is None:
                return a
            x0, y0 = max(a[0], b[0]), max(a[1], b[1])
            x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
            return (x0, y0, x1 - x0, y1 - y0)

        def visible_in(r, clip) -> bool:
            if r is None or clip is None:
                return True
            i = inter(r, clip)
            return i[2] > 0 and i[3] > 0

        region_rect = tuple(region) if region else None
        # asking for one text element (root=) shows its text in full, up to 4000 characters
        self.text_limit = 4000 if root and self.role_name(start) in TEXTISH | {"document web", "document frame", "label"} else 160
        menu_root = bool(root) and self.role_name(start) in ("menu bar", "menu", "menu item")
        if menu_root:
            list_cap = 60

        def walk(acc, depth: int, indent: int, path: list[str], clip, menu_ok: bool = False):
            """Returns True if the element is on screen (used to count list items).  menu_ok: inside a
            closed menu, whose items are hidden but can still be triggered."""
            if ctx.cancelled or truncated[0]:
                return False
            visited[0] += 1
            if visited[0] > visit_cap:
                truncated[0] = True
                return False
            role = self.role_name(acc)
            if role in SKIP:
                return False
            st = self.states(acc)
            if depth > 0 and not menu_ok and ("showing" not in st and "visible" not in st):
                return False
            r = self.extents(acc)
            offscreen = False
            if depth > 0 and r is not None and not menu_ok:
                if (r[2] <= 0 or r[3] <= 0) and role not in ("menu", "menu bar"):
                    return False
                if not visible_in(r, clip):      # scrolled out of its container
                    if fq is None:
                        return False
                    offscreen = True
            name = (self.safe(acc.get_name, "") or "").strip()
            structural = role in STRUCTURAL and not (name and role in ("grouping", "group", "form", "landmark", "panel"))
            printable = depth == 0 or (not structural and (name or role in INTERACTIVE or role in CONTAINERS or role in TEXTISH))
            if role in ("label", "heading", "static") and not name:
                printable = bool(self.value_text(acc, role))
            if printable and region_rect and not visible_in(r, region_rect):
                printable = False
            next_indent = indent
            if printable:
                line, nm, _ = self.describe(acc, role, bounds=bounds)
                if fq is not None:
                    hay = (nm + " " + (self.value_text(acc, role) or "") + " " + (self.safe(acc.get_description, "") or "")).lower()
                    if fq in hay:
                        ref = self.new_ref(Node(acc, role, nm, app_pid, win_id))
                        crumbs = " › ".join(p for p in path[-3:] if p)
                        matches.append(f"{ref} {line}" + (" (scrolled out of view: scroll_to first)" if offscreen else "")
                                       + (f"   (in {crumbs})" if crumbs else ""))
                        if len(matches) >= 40:
                            truncated[0] = True
                            return True
                else:
                    if count[0] >= max_items:
                        truncated[0] = True
                        return True
                    ref = self.new_ref(Node(acc, role, nm, app_pid, win_id))
                    lines.append("  " * indent + f"{ref} {line}")
                    count[0] += 1
                next_indent = indent + 1
            if depth >= max_depth:
                return True
            if role in ("text", "entry", "terminal", "password text", "label", "push button", "check box",
                        "radio button", "toggle button", "spin button", "slider", "progress bar"):
                return True   # leaf-like: their children are internal
            n = self.safe(acc.get_child_count, 0) or 0
            sub_path = path + ([ROLE_SHORT.get(role, role) + (f' "{name[:30]}"' if name else "")] if printable else [])
            sub_clip = inter(clip, r) if (r is not None and r[2] > 0 and r[3] > 0 and not offscreen) else clip
            child_menu_ok = menu_ok or (role in ("menu bar", "menu", "menu item") and (fq is not None or menu_root))
            if child_menu_ok and role == "separator":
                return True
            if role in LISTISH and fq is None:
                shown = 0
                seen_visible = False
                for i in range(min(n, 400)):
                    c = self.safe(lambda: acc.get_child_at_index(i))
                    if c is None:
                        continue
                    if shown >= list_cap:
                        pass
                        break
                    on = walk(c, depth + 1, next_indent, sub_path, sub_clip, child_menu_ok)
                    if truncated[0]:
                        return True
                    if on:
                        shown += 1
                        seen_visible = True
                    elif seen_visible and i > shown + 40:
                        break                       # past the visible part of a long list
                more = n - shown
                if more > 0 and printable:
                    lines.append("  " * next_indent + f"… {more} more items not shown (scroll, or use find)")
                return True
            for i in range(n):
                c = self.safe(lambda: acc.get_child_at_index(i))
                if c is None:
                    continue
                walk(c, depth + 1, next_indent, sub_path, sub_clip, child_menu_ok)
                if truncated[0]:
                    return True
            return True

        walk(start, 0, 0, [], None)
        if not root:
            # Menus, popups and dialogs of the same app are separate top-level accessibles.
            for f in self.frames(app):
                if truncated[0] or f is frame or self.safe(lambda: f == frame, False) or self.role_name(f) == "frame":
                    continue
                st = self.states(f)
                if "showing" not in st and "visible" not in st:
                    continue
                r = self.extents(f)
                if r is not None and (r[2] <= 0 or r[3] <= 0):
                    continue
                if fq is None:
                    lines.append(f"also open ({ROLE_SHORT.get(self.role_name(f), self.role_name(f))}, own window):")
                walk(f, 0, 1, [], None)
        dt = time.monotonic() - t0
        if win is not None:
            head = f"window {self.h.alias(str(win.get('id')))} \"{str(win.get('title', ''))[:100]}\" app={win.get('appId', '')}"
        else:
            head = f"window \"{title[:100]}\""
        if fq is not None:
            body = "\n".join(matches) if matches else f"no visible element contains “{find}”"
            if truncated[0]:
                body += "\n… search stopped early (very large tree); narrow the search"
        else:
            body = "\n".join(lines)
            if truncated[0]:
                body += (f"\n… cut at {max_items} elements. Narrow it: find=\"text\", root=<ref of a part>, "
                         f"region=[x,y,w,h], or a larger max_items")
        self.text_limit = 160
        text = head + "\n" + body
        self.stats = {"visited": visited[0], "printed": count[0], "matches": len(matches), "seconds": round(dt, 3),
                      "chars": len(text)}
        log.debug("snapshot %s", self.stats)
        return text, self.stats

    # ------------------------------------------------------------------ focus and checks
    def focused_in(self, frame, cap: int = 800):
        """The deepest focused element inside a frame.  Toolkits report focus on containers too
        (Qt marks Kate's whole view area focused, with the text area several levels below)."""
        f = self._focused_in(frame, cap)
        if f is None:
            return None
        best, best_depth = f, 0
        seen = [0]

        def dfs(acc, depth):
            nonlocal best, best_depth
            seen[0] += 1
            if seen[0] > 400 or depth > 12:
                return
            for i in range(min(self.safe(acc.get_child_count, 0) or 0, 80)):
                c = self.safe(lambda: acc.get_child_at_index(i))
                if c is None:
                    continue
                st = self.states(c)
                if "showing" not in st and "visible" not in st:
                    continue
                if "focused" in st and depth + 1 > best_depth:
                    best, best_depth = c, depth + 1
                dfs(c, depth + 1)
        dfs(f, 0)
        return best

    def _focused_in(self, frame, cap: int = 800):
        """The focused element inside a frame (bounded search through showing elements)."""
        Atspi = _atspi()
        if "Collection" in self.ifaces(frame):
            try:
                ss = Atspi.StateSet.new([Atspi.StateType.FOCUSED])
                rule = Atspi.MatchRule.new(ss, Atspi.CollectionMatchType.ALL, [], Atspi.CollectionMatchType.NONE,
                                           [], Atspi.CollectionMatchType.NONE, [], Atspi.CollectionMatchType.NONE, False)
                res = Atspi.Collection.get_matches(frame, rule, Atspi.CollectionSortOrder.CANONICAL, 1, True)
                if res:
                    return res[0]
            except Exception:
                pass
        seen = [0]

        def dfs(acc):
            seen[0] += 1
            if seen[0] > cap:
                return None
            st = self.states(acc)
            if "focused" in st and acc is not frame:
                return acc
            if acc is not frame and "showing" not in st:
                return None
            for i in range(self.safe(acc.get_child_count, 0) or 0):
                c = self.safe(lambda: acc.get_child_at_index(i))
                if c is not None:
                    r = dfs(c)
                    if r is not None:
                        return r
            return None
        return dfs(frame)

    EDITABLE_ROLES = {"text", "entry", "terminal", "document text", "spin button", "editbar", "password text",
                      "date editor", "combo box"}

    def keyboard_focus(self, win: dict | None):
        """(focused element or None, role, editable) for a window; (None, "", None) when unknown."""
        try:
            self.ensure()
            frame, _ = self.frame_for(win, None)
        except HandsError:
            return None, "", None
        f = self.focused_in(frame)
        if f is None:
            return None, "", None
        role = self.role_name(f)
        st = self.states(f)
        editable = role in self.EDITABLE_ROLES or "editable" in st
        return f, role, editable

    def password_focused(self, win: dict | None) -> bool:
        """True when keyboard input to this window would land in a password field."""
        try:
            self.ensure()
            frame, _ = self.frame_for(win, None)
        except HandsError:
            return False
        f = self.focused_in(frame)
        return f is not None and self.role_name(f) == "password text"

    # ------------------------------------------------------------------ actions
    def action_names(self, acc) -> list[str]:
        if "Action" not in self.ifaces(acc):
            return []
        A = _atspi().Action
        n = self.safe(lambda: A.get_n_actions(acc), 0) or 0
        return [self.safe(lambda: A.get_action_name(acc, i), "") or "" for i in range(n)]

    def do_named(self, acc, names: list[str]) -> str | None:
        have = self.action_names(acc)
        if not have:
            return None
        A = _atspi().Action
        low = [a.lower() for a in have]
        for want in names:
            w = want.lower()
            for i, a in enumerate(low):
                if a == w or (len(w) > 3 and w in a):
                    if self.safe(lambda: A.do_action(acc, i), False):
                        return have[i]
        return None

    def select_in_parent(self, acc) -> bool:
        idx = self.safe(acc.get_index_in_parent, -1)
        parent = self.safe(acc.get_parent)
        hops = 0
        while parent is not None and hops < 3:
            if "Selection" in self.ifaces(parent) and idx is not None and idx >= 0:
                return bool(self.safe(lambda: _atspi().Selection.select_child(parent, idx), False))
            idx = self.safe(parent.get_index_in_parent, -1)
            parent = self.safe(parent.get_parent)
            hops += 1
        return False

    def find_option(self, acc, value: str, cap: int = 400):
        want = value.strip().lower()
        seen = [0]
        best = [None]

        def dfs(a):
            seen[0] += 1
            if seen[0] > cap or best[0] is not None:
                return
            for i in range(self.safe(a.get_child_count, 0) or 0):
                c = self.safe(lambda: a.get_child_at_index(i))
                if c is None:
                    continue
                n = (self.safe(c.get_name, "") or "").strip().lower()
                if n == want or (want and n.startswith(want)):
                    best[0] = c
                    return
                dfs(c)
        dfs(acc)
        return best[0]
