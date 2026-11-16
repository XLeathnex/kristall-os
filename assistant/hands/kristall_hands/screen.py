# SPDX-License-Identifier: GPL-3.0-or-later
"""Tier 2 tools (ui_tree, ui_act) and tier 3 tools (screenshot, zoom, click, drag, scroll,
type_text, press_keys, save_screenshot).  Pointing and typing go through the bridge's agent
input, so the owner's pointer never moves; the assistant's own cursor is choreographed around
every action."""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import time

from . import log
from .a11y import A11y, PRESS_ACTIONS
from .bridge import BridgeError
from .core import Hands
from .riskgate import Gate
from .safety import AUTH_MSG, PROTECTED_MSG, check_window, is_auth_window, is_protected_app, mask_secrets
from .tooling import INTENT_PROPERTY, RISK_PROPERTY, Context, HandsError, Registry, Result, untrusted

KEY_ALIASES = {
    "enter": "return", "eingabe": "return", "esc": "escape", "strg": "ctrl", "control": "ctrl", "ctl": "ctrl",
    "cmd": "meta", "command": "meta", "super": "meta", "win": "meta", "windows": "meta", "option": "alt",
    "opt": "alt", "altgr": "iso_level3_shift", "del": "delete", "entf": "delete", "bksp": "backspace",
    "pgup": "page_up", "pageup": "page_up", "bild_auf": "page_up", "pgdn": "page_down", "pagedown": "page_down",
    "bild_ab": "page_down", "pos1": "home", "ende": "end", "einfg": "insert", "ins": "insert",
    "leertaste": "space", "spacebar": "space", "arrowup": "up", "arrowdown": "down", "arrowleft": "left",
    "arrowright": "right", "↑": "up", "↓": "down", "←": "left", "→": "right", "umschalt": "shift",
    "hoch": "up", "runter": "down", "links": "left", "rechts": "right", "tabulator": "tab", "rücktaste": "backspace",
}
MODS = {"ctrl", "shift", "alt", "meta"}


def normalize_keys(keys: str) -> str:
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", keys.strip()) if p.strip()]
    if not parts:
        raise HandsError("No keys given.")
    out = []
    for p in parts:
        p = KEY_ALIASES.get(p, p).replace(" ", "_")
        out.append(p)
    mods = [p for p in out[:-1] if p in MODS]
    if len(mods) != len(out) - 1:
        raise HandsError(f"“{keys}” is not a key chord I understand. Use e.g. ctrl+s, alt+f4, shift+tab, return.")
    return "+".join(out)


def pictures_dir() -> str:
    try:
        cfg = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "user-dirs.dirs")
        with open(cfg, encoding="utf-8") as f:
            for line in f:
                if line.startswith("XDG_PICTURES_DIR="):
                    v = line.split("=", 1)[1].strip().strip('"').replace("$HOME", os.path.expanduser("~"))
                    if v:
                        return v
    except OSError:
        pass
    for cand in ("~/Bilder", "~/Pictures"):
        p = os.path.expanduser(cand)
        if os.path.isdir(p):
            return p
    return os.path.expanduser("~/Bilder")


def send_text(h, ctx, text: str, window_id: str | None, label: str = "Kristall") -> dict:
    """Types text through the bridge in one call: the bridge types line breaks and tabs as
    Return/Tab itself, in order.  (Splitting the text into agent.text and agent.key calls
    reordered input in Qt apps, whose text-input commits and key events take different paths.)"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    params = {"text": text, "windowId": window_id}
    switches = text.count("\n") + text.count("\t")
    if switches and not h.bridge.has("orderedText"):
        # Bridges before `orderedText` (bridge.md, agent.text "Order") let Qt/GTK apply
        # text-input commits before queued Return/Tab key events, so line breaks landed at the
        # end. With such a bridge every character stays on the key-event paths, which keeps the
        # order. Current bridges keep the order on every path, so the text-input path (one
        # commit per line, best for input methods and speed) is used again.
        params["paths"] = ["keymap", "temporaryKeymap", "clipboard"]
    # each switch between text-input and a key path costs the bridge a client round trip
    timeout = 10.0 + len(text) / 1000 + 2 * switches * 0.06
    try:
        return h.agent(ctx, "agent.text", params, label, timeout=timeout)
    except BridgeError as e:
        if e.code in ("unsupported", "invalid") and "paths" in params:
            params.pop("paths")
            return h.agent(ctx, "agent.text", params, label, timeout=timeout)
        raise


def preview(text: str) -> str:
    return text.replace("\r\n", "⏎").replace("\n", "⏎").replace("\t", "⇥")[:80]


class Screen:
    def __init__(self, h: Hands, a11y: A11y):
        self.h = h
        self.a = a11y
        self.shots: dict[str, dict] = {}
        self.last_shot: str | None = None
        self._n = 0
        self.gate: Gate | None = None

    # ------------------------------------------------------------------ capture
    def capture(self, target, max_w: int = 0, max_h: int = 0) -> tuple[bytes, dict]:
        b = self.h.need_bridge("screenshot")
        try:
            r = b.request("screenshot", {"target": target, "maxWidth": max_w, "maxHeight": max_h,
                                         "includeCursor": False, "excludeShell": True}, timeout=10.0)
        except BridgeError as e:
            if e.code == "denied":
                self.h.guard(None, acting=False)
                raise HandsError("The compositor refused to take a screenshot for this program.")
            if e.code == "not_found":
                raise HandsError("That window has just closed.")
            raise HandsError(f"The screenshot did not work ({e.code}).")
        path = r.get("path", "")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            raise HandsError("The screenshot file could not be read.")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        return data, r

    def store(self, meta: dict, kind: str, label: str, window_id: str | None = None) -> str:
        self._n += 1
        sid = f"{'z' if kind == 'zoom' else 's'}{self._n}"
        self.shots[sid] = {"ox": float(meta.get("originX", 0)), "oy": float(meta.get("originY", 0)),
                           "sx": float(meta.get("scaleX", 1) or 1), "sy": float(meta.get("scaleY", 1) or 1),
                           "w": int(meta.get("width", 0)), "h": int(meta.get("height", 0)), "kind": kind,
                           "label": label, "t": time.monotonic(), "window": window_id}
        if kind != "zoom":
            self.last_shot = sid
        while len(self.shots) > 50:
            self.shots.pop(next(iter(self.shots)))
        return sid

    def to_global(self, x: float, y: float, image: str | None) -> tuple[float, float, str]:
        sid = image or self.last_shot
        if not sid or sid not in self.shots:
            raise HandsError("Take a screenshot first: coordinates are pixels in a screenshot image.")
        s = self.shots[sid]
        if not (0 <= x <= s["w"] and 0 <= y <= s["h"]):
            raise HandsError(f"({x:g}, {y:g}) is outside image {sid} ({s['w']}x{s['h']} px).")
        return s["ox"] + x / s["sx"], s["oy"] + y / s["sy"], sid

    def from_global(self, gx: float, gy: float, sid: str | None = None) -> tuple[int, int] | None:
        sid = sid or self.last_shot
        if not sid or sid not in self.shots:
            return None
        s = self.shots[sid]
        return round((gx - s["ox"]) * s["sx"]), round((gy - s["oy"]) * s["sy"])

    # ------------------------------------------------------------------ helpers
    def window_at(self, gx: float, gy: float, wins: list[dict]) -> dict | None:
        hits = [w for w in wins if not w.get("minimized") and
                w.get("x", 0) <= gx <= w.get("x", 0) + w.get("w", 0) and w.get("y", 0) <= gy <= w.get("y", 0) + w.get("h", 0)]
        if not hits:
            return None
        return hits[-1]          # the window list is in stacking order, bottom to top

    def changes(self, ctx: Context, before: list[dict] | None, target_id: str | None, settle: float = 0.35) -> str:
        """Cheap description of what changed after an action."""
        ctx.sleep(settle)
        out = []
        try:
            after = self.h.windows() if self.h.bridge.connected() else None
        except HandsError:
            after = None
        if before is not None and after is not None:
            b = {w["id"]: w for w in before}
            a = {w["id"]: w for w in after}
            for wid, w in a.items():
                if wid not in b:
                    out.append("new window: " + self.h.describe_window(w))
            for wid, w in b.items():
                if wid not in a:
                    out.append(f"window closed: {self.h.alias(wid)} \"{str(w.get('title', ''))[:60]}\"")
            for wid, w in a.items():
                if wid in b and w.get("title") != b[wid].get("title"):
                    out.append(f"title of {self.h.alias(wid)} is now \"{str(w.get('title', ''))[:80]}\"")
            act_b = next((w["id"] for w in before if w.get("active")), None)
            act_a = next((w for w in after if w.get("active")), None)
            if act_a and act_a["id"] != act_b:
                out.append("active window: " + self.h.describe_window(act_a))
        focus = self.focus_line(after, target_id)
        if focus:
            out.append(focus)
        return "\n".join(out) if out else "no visible window change"

    def focus_line(self, wins: list[dict] | None, target_id: str | None) -> str | None:
        if self.a.mode() == "off":
            return None
        try:
            win = None
            if wins is not None:
                win = next((w for w in wins if w.get("id") == target_id), None) or next((w for w in wins if w.get("active")), None)
            self.a.ensure()
            frame, _ = self.a.frame_for(win, None)
            f = self.a.focused_in(frame, cap=500)
            if f is None:
                return None
            role = self.a.role_name(f)
            line, _, _ = self.a.describe(f, role, bounds=False, with_value=role not in ("text", "entry", "terminal", "document text"))
            if role in ("text", "entry", "terminal", "document text") and "Text" in self.a.ifaces(f):
                tail, n = self.a.text_tail(f, 120)
                tail = mask_secrets(tail).replace("\n", "⏎")
                line += f' ={"…" if n > len(tail) else ""}"{tail}" ({n} chars)'
            return "focus: " + line
        except HandsError:
            return None
        except Exception as e:   # never fail an action because of feedback
            log.debug("focus feedback failed: %s", e)
            return None

    def label(self, intent: str | None, de: str, en: str) -> str:
        return (intent or self.h.say(de, en))[:60]

    def pointer(self, ctx: Context, params: dict) -> dict:
        try:
            return self.h.agent(ctx, "agent.pointer", params, timeout=8.0)
        except BridgeError as e:
            if e.code == "busy":
                raise HandsError("The owner is using the mouse right now (holding a button or dragging a window). "
                                 "Wait a moment and try again.")
            if e.code == "not_found":
                raise HandsError("That point is not inside the window I meant to click (it moved or closed). "
                                 "Take a fresh screenshot.")
            if e.code == "unsupported":
                raise HandsError("That spot belongs to the compositor itself, which I can't click.")
            raise HandsError(f"The click could not be delivered ({e.code}: {e.message[:80]}).")


def _with_note(content: str, note: str | None) -> str:
    return content + ("\n" + note if note else "")


def register(reg: Registry, h: Hands, a: A11y) -> Screen:
    sc = Screen(h, a)
    gate = sc.gate = Gate(h, a)

    # ======================================================================== tier 2
    @reg.tool("ui_tree",
              "Read an app window's controls as a compact outline (role, \"name\", =value, {state}, @x,y wxh "
              "relative to the window) with refs like e12 for ui_act. Prefer this to screenshots for normal "
              "apps: exact, cheap, and the owner's mouse is not needed. Use find to search a big window by "
              "text, root to expand one part (root=<text field ref> shows its whole text), region to limit to an area. Not useful for Blender, games, "
              "Roblox Studio or canvas-drawn content: use screenshot there.",
              {"window": {"type": "string", "description": "Window id (w3), app name or title; default: active window."},
               "find": {"type": "string", "maxLength": 200, "description": "Only elements whose name/value contains this text."},
               "root": {"type": "string", "description": "Ref of an element to show only its subtree."},
               "region": {"type": "array", "items": {"type": "number"}, "maxItems": 4,
                          "description": "[x,y,w,h] window-relative area to include."},
               "max_items": {"type": "integer", "minimum": 10, "maximum": 600},
               "bounds": {"type": "boolean", "description": "Include @x,y wxh (default true)."}},
              risk="read", read_only=True, title="Read app controls")
    def ui_tree(ctx: Context, window: str | None = None, find: str | None = None, root: str | None = None,
                region: list | None = None, max_items: int | None = None, bounds: bool = True) -> Result:
        h.guard(ctx, acting=False)
        if region is not None and len(region) != 4:
            raise HandsError("region must be [x, y, w, h].")
        text, stats = a.snapshot(ctx, window, root=root, find=find, max_items=max_items, region=region, bounds=bounds)
        return Result.text("Use the refs with ui_act (or click ref=…).", text)

    @reg.tool("ui_act",
              "Operate an element from ui_tree by its ref, without the mouse: press (buttons, menu items, "
              "links), open (a file/item in a list, like a double-click), set_text (replace a text field's content), append_text, set_value (sliders, spin "
              "boxes; or choose an option of a combobox by its text), select (list items, tabs, tree "
              "items), toggle (checkboxes), expand/collapse, focus, scroll_to, show_menu. Returns the "
              "element's new state, what has focus and any window change.",
              {"ref": {"type": "string"},
               "action": {"type": "string", "enum": ["press", "open", "set_text", "append_text", "set_value", "select",
                                                       "toggle", "expand", "collapse", "focus", "scroll_to", "show_menu"]},
               "text": {"type": "string", "maxLength": 100000},
               "value": {"type": ["number", "string"]},
               "intent": INTENT_PROPERTY, "risk": RISK_PROPERTY},
              ["ref", "action"], risk="reversible", title="Operate control")
    def ui_act(ctx: Context, ref: str, action: str, text: str | None = None, value=None, intent: str | None = None,
               risk: str | None = None) -> Result:
        h.guard(ctx)
        a.ensure()
        n = a.node(ref)
        acc = n.acc
        role = a.role_name(acc)
        if not role:
            raise HandsError("That element no longer exists (the window changed). Take a fresh ui_tree.")
        win = None
        if h.bridge.ensure():
            try:
                win = h.window_by_id(n.win_id) if n.win_id else None
            except HandsError:
                win = None
            if win is not None:
                check_window(win, h.protected, typing=action in ("set_text", "append_text"))
        app = a.safe(acc.get_application)
        if app is not None and is_protected_app(a.safe(app.get_name, "") or "", h.protected):
            raise HandsError(PROTECTED_MSG)
        if action in ("set_text", "append_text") and role == "password text":
            raise HandsError(AUTH_MSG)
        note = None
        if action in ("press", "open", "toggle", "select"):
            # hands.md §10: a risky-looking element runs only with a matching declared risk
            note = gate.check_element("ui_act", acc, win, risk, intent)
        before = None
        try:
            before = h.windows() if h.bridge.connected() else None
        except HandsError:
            pass
        # the cursor goes to the element so the owner can follow, even without a pointer event
        if h.bridge.connected():
            h.begin_session(intent or "Kristall")
        frame = None
        if win is not None:
            try:
                frame, _ = a.frame_for(win, None)
            except HandsError:
                frame = None
        pt = a.to_global(win, frame, a.extents(acc)) if frame is not None else None
        nm = n.name or a.safe(acc.get_name, "") or ""
        top = a.top_of(acc)
        title_before = (a.safe(top.get_name, "") or "") if top is not None else ""
        line_before = a.describe(acc, role, bounds=False)[0]
        if pt:
            h.cursor.move_to(ctx, pt[0], pt[1], sc.label(intent, f"{_verb_de(action)} „{nm[:40]}“", f"{_verb_en(action)} “{nm[:40]}”"))
        ctx.check()
        done = None
        if action in ("press", "toggle", "expand", "collapse", "show_menu"):
            want = {"press": PRESS_ACTIONS, "toggle": ["toggle", "click", "press", "activate"],
                    "expand": ["expand", "expand or contract", "open", "toggle", "click"],
                    "collapse": ["collapse", "expand or contract", "close", "toggle", "click"],
                    "show_menu": ["showmenu", "show menu", "menu", "context menu"]}[action]
            if action == "collapse" and "expanded" not in a.states(acc):
                done = "already collapsed"
            elif action == "expand" and "expandable" in a.states(acc) and "expanded" in a.states(acc):
                done = "already expanded"
            else:
                h.cursor.pulse("click")
                done = a.do_named(acc, want)
                if done is None and action == "press" and a.select_in_parent(acc):
                    done = "selected"
                if done is None and pt and h.bridge.connected() and h.bridge.has("agentInput"):
                    sc.pointer(ctx, {"type": "click", "x": pt[0], "y": pt[1], "button": "right" if action == "show_menu" else "left",
                                     "count": 1, "windowId": n.win_id})
                    done = "clicked at its position"
            if done is None:
                raise HandsError(f"This element can't be {action}ed through its controls. Try click with a screenshot.")
        elif action in ("set_text", "append_text"):
            if text is None:
                raise HandsError("Give the text in 'text'.")
            h.cursor.pulse("type", output=preview(text))
            ok = False
            if "EditableText" in a.ifaces(acc):
                if action == "set_text":
                    ok = a.set_text(acc, text)
                else:
                    ok = a.insert_text(acc, a.char_count(acc), text)
                if ok and text:
                    # verify: some widgets accept the call and ignore it
                    got = a.text_of(acc)
                    ok = text in got if action == "append_text" else got == text or got.strip() == text.strip()
            if not ok:
                # fall back to focusing it and typing through the bridge
                if not (h.bridge.connected() and h.bridge.has("agentText")):
                    raise HandsError("This text field can't be filled through its controls and keyboard input is not "
                                     "available right now.")
                a.grab_focus(acc)
                wid = n.win_id
                foc = a.focused_in(frame) if frame is not None else None
                if foc is not None and a.role_name(foc) == "password text":
                    raise HandsError(AUTH_MSG)
                if action == "set_text":
                    h.agent(ctx, "agent.key", {"keys": "ctrl+a", "windowId": wid})
                    if text == "":
                        h.agent(ctx, "agent.key", {"keys": "delete", "windowId": wid})
                if text:
                    send_text(h, ctx, text, wid)
                ok = True
            done = "text set" if action == "set_text" else "text appended"
            log.info("ui_act %s on %s (%d chars)", action, role, len(text))
        elif action == "set_value":
            if value is None:
                raise HandsError("Give the value in 'value'.")
            h.cursor.pulse("click")
            val = a.value(acc)
            if role == "combo box" or isinstance(value, str) and val is None:
                opt = a.find_option(acc, str(value))
                if opt is None:
                    raise HandsError(f"No option “{str(value)[:40]}” found here. Expand it and read the options with ui_tree.")
                done = a.do_named(opt, ["click", "press", "activate", "select"]) or ("selected" if a.select_in_parent(opt) else None)
                if done is None:
                    raise HandsError("That option can't be chosen through its controls. Try click.")
            elif val is not None:
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    raise HandsError("This control needs a number.")
                _, lo, hi = val
                if lo is not None and hi is not None and not (lo <= v <= hi):
                    raise HandsError(f"The value must be between {lo:g} and {hi:g}.")
                if not a.set_value(acc, v):
                    raise HandsError("The value was not accepted.")
                done = f"value {v:g}"
            else:
                raise HandsError("This element has no value to set.")
        elif action == "open":
            h.cursor.pulse("double_click")
            done = a.do_named(acc, ["open", "activate", "jump", "invoke", "doubleclick", "default"])
            if done is None and h.bridge.connected() and h.bridge.has("agentInput"):
                if a.select_in_parent(acc):
                    a.grab_focus(acc)
                    h.agent(ctx, "agent.key", {"keys": "return", "windowId": n.win_id})
                    done = "selected and opened with Return"
                elif pt:
                    sc.pointer(ctx, {"type": "click", "x": pt[0], "y": pt[1], "button": "left", "count": 2, "windowId": n.win_id})
                    done = "double-clicked"
            if done is None:
                if a.select_in_parent(acc):
                    raise HandsError("I could select it but not open it without keyboard input (not available right "
                                     "now). Try press, or the app's Open command.")
                raise HandsError("This element can't be opened through its controls. Try click with count 2.")
        elif action == "select":
            h.cursor.pulse("click")
            if role in ("page tab", "radio button", "radio menu item"):
                # tabs switch on their own action; selecting them in the tab list is not always honoured
                done = a.do_named(acc, ["press", "click", "switch", "activate", "select"]) or \
                    ("selected" if a.select_in_parent(acc) else None)
            else:
                done = "selected" if a.select_in_parent(acc) else a.do_named(acc, ["select", "click", "press", "activate", "switch"])
            if done is None:
                raise HandsError("This element can't be selected through its controls. Try click.")
        elif action == "focus":
            if not a.grab_focus(acc):
                raise HandsError("This element can't take the focus.")
            done = "focused"
        elif action == "scroll_to":
            if not a.scroll_to(acc):
                raise HandsError("This element can't be scrolled into view this way. Try scroll.")
            done = "scrolled into view"
        h.touch()
        # feedback: the element's new state, focus, window changes
        a.safe(acc.clear_cache)
        new_role = a.role_name(acc)
        if new_role:
            line, _, _ = a.describe(acc, new_role, bounds=False)
            state = f"{ref} now: {line}"
        else:
            state = f"{ref} is gone (the view changed)"
        ch = sc.changes(ctx, before, n.win_id, settle=0.3)
        hint = ""
        if action in ("press", "open", "toggle", "select", "expand", "collapse") and new_role:
            title_after = (a.safe(top.get_name, "") or "") if top is not None else ""
            if title_after == title_before and line.replace("{focused}", "") == line_before.replace("{focused}", "") \
                    and (before is None or ch.startswith("no visible window change") or ch.startswith("focus:")):
                hint = (" Nothing visible changed. If the app ignored it (some custom controls do), use click with "
                        f"ref=\"{ref}\" for a real click.")
        return Result.text(f"Done ({done}).{hint}", _with_note(state + "\n" + ch, note))

    # ======================================================================== tier 3
    def max_dims() -> tuple[int, int]:
        s = h.cfg().get("screenshot", {})
        return int(s.get("max_width", 1280) or 1280), int(s.get("max_height", 800) or 800)

    @reg.tool("screenshot",
              "See a window (default: the active one) or the whole screen as an image, for apps whose "
              "controls ui_tree can't read (Blender, games, canvas content) or to check the result "
              "visually. Coordinates for click/drag/scroll are pixels in this image. Costs many tokens: "
              "don't take one after every step, actions already report what changed.",
              {"target": {"type": "string", "enum": ["window", "screen"]},
               "window": {"type": "string", "description": "Window id, app name or title (target window)."}},
              risk="read", read_only=True, title="Screenshot")
    def screenshot(ctx: Context, target: str = "window", window: str | None = None) -> Result:
        h.guard(ctx, acting=False)
        mw, mh = max_dims()
        h.need_bridge("screenshot")
        if target == "screen":
            data, meta = sc.capture("desktop", mw, mh)
            label = "the whole screen"
            win = None
        else:
            win = h.resolve_window(window)
            check_window(win, h.protected)
            data, meta = sc.capture({"window": win["id"]}, mw, mh)
            label = f"window {h.alias(win['id'])}"
        sid = sc.store(meta, "screen" if target == "screen" else "window", label, None if win is None else win["id"])
        s = sc.shots[sid]
        txt = (f"Screenshot {sid} of {label}: {s['w']}x{s['h']} px (1 px = {1 / s['sx']:.2f} logical px). "
               f"Give click/drag/scroll coordinates in this image's pixels; use zoom for small text.")
        res = Result.text(txt, h.describe_window(win) if win else None)
        res.add_image(data)
        return res

    @reg.tool("zoom",
              "Look closer at part of a screenshot at full detail: x0,y0 (top left) to x1,y1 (bottom right) in "
              "pixels of that screenshot. Coordinates you use afterwards stay in the original screenshot's "
              "pixels unless you pass image=<zoom id>.",
              {"x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"}, "y1": {"type": "number"},
               "image": {"type": "string", "description": "Screenshot id (default: the last one)."}},
              ["x0", "y0", "x1", "y1"], risk="read", read_only=True, title="Zoom")
    def zoom(ctx: Context, x0: float, y0: float, x1: float, y1: float, image: str | None = None) -> Result:
        h.guard(ctx, acting=False)
        if x1 <= x0 or y1 <= y0:
            raise HandsError("x1,y1 must be below and right of x0,y0.")
        gx0, gy0, sid = sc.to_global(x0, y0, image)
        gx1, gy1, _ = sc.to_global(x1, y1, sid)
        mw, mh = max_dims()
        data, meta = sc.capture({"region": {"x": gx0, "y": gy0, "w": gx1 - gx0, "h": gy1 - gy0}}, mw, mh)
        zid = sc.store(meta, "zoom", f"zoom of {sid}", sc.shots[sid].get("window"))
        z = sc.shots[zid]
        res = Result.text(f"Zoom {zid}: region ({x0:g},{y0:g})–({x1:g},{y1:g}) of {sid}, {z['w']}x{z['h']} px. "
                          f"Keep using {sid} pixel coordinates, or pass image=\"{zid}\" to point in this image.")
        res.add_image(data)
        return res

    def resolve_point(x, y, image, ref) -> tuple[float, float, str, str | None]:
        """Global point, a name for the label, and the window the point is meant for (if known)."""
        if ref:
            n = a.node(ref)
            win = h.window_by_id(n.win_id) if n.win_id else h.active_window()
            frame, _ = a.frame_for(win, None)
            pt = a.to_global(win, frame, a.extents(n.acc))
            if pt is None:
                raise HandsError("That element has no position on screen. Use ui_act instead.")
            return pt[0], pt[1], n.name or ref, (win or {}).get("id")
        if x is None or y is None:
            raise HandsError("Give x and y (pixels in the last screenshot) or a ref from ui_tree.")
        gx, gy, sid = sc.to_global(float(x), float(y), image)
        return gx, gy, "", sc.shots[sid].get("window")

    def precheck(gx: float, gy: float, typing: bool = False) -> tuple[list[dict], dict | None]:
        wins = h.windows()
        target = sc.window_at(gx, gy, wins)
        if target is not None:
            check_window(target, h.protected, typing=typing)
            if is_auth_window(target, h.protected):
                raise HandsError(AUTH_MSG)
        return wins, target

    @reg.tool("click",
              "Click at a point of the last screenshot (x,y in its pixels) or on a ui_tree element (ref) "
              "with the assistant's own pointer; the owner's mouse does not move. button left/right/middle, "
              "count 2 for double-click, modifiers like [\"ctrl\"]. Set risk truthfully for clicks that send, "
              "buy, delete or install. Returns what changed (focus, new windows).",
              {"x": {"type": "number"}, "y": {"type": "number"},
               "image": {"type": "string", "description": "Screenshot/zoom id the coordinates refer to (default: last screenshot)."},
               "ref": {"type": "string", "description": "Element ref from ui_tree instead of x,y."},
               "button": {"type": "string", "enum": ["left", "right", "middle", "back", "forward"]},
               "count": {"type": "integer", "minimum": 1, "maximum": 3},
               "modifiers": {"type": "array", "items": {"type": "string", "enum": ["ctrl", "shift", "alt", "meta"]}, "maxItems": 4},
               "intent": INTENT_PROPERTY, "risk": RISK_PROPERTY},
              risk="reversible", title="Click")
    def click(ctx: Context, x: float | None = None, y: float | None = None, image: str | None = None, ref: str | None = None,
              button: str = "left", count: int = 1, modifiers: list | None = None, intent: str | None = None,
              risk: str | None = None) -> Result:
        h.guard(ctx)
        h.need_bridge("agentInput")
        gx, gy, what, meant = resolve_point(x, y, image, ref)
        wins, target = precheck(gx, gy)
        note = None
        if button == "left":
            # hands.md §10: what would this click activate?
            if ref:
                n = a.node(ref)
                note = gate.check_element("click", n.acc, h.window_by_id(n.win_id) if n.win_id else target, risk, intent)
            else:
                note = gate.check_point("click", gx, gy, risk, intent)
        h.begin_session(intent or "Kristall")
        verb_de = {1: "Klicke", 2: "Doppelklick", 3: "Dreifachklick"}[count] if button == "left" else "Rechtsklick"
        h.cursor.move_to(ctx, gx, gy, sc.label(intent, f"{verb_de}{' auf „' + what[:40] + '“' if what else ''}",
                                                f"Click{' on “' + what[:40] + '”' if what else ''}"))
        pulse = "double_click" if count == 2 else ("right_click" if button == "right" else "click")
        h.cursor.pulse(pulse)
        params = {"type": "click", "x": gx, "y": gy, "button": button, "count": count, "modifiers": modifiers or []}
        if meant:
            params["windowId"] = meant
        r = sc.pointer(ctx, params)
        h.touch()
        tgt = (r.get("target") or {})
        ch = sc.changes(ctx, wins, tgt.get("windowId") or (target or {}).get("id"))
        where = f"window {h.alias(tgt['windowId'])}" if tgt.get("windowId") else "the desktop/shell"
        if r.get("dismissedPopups"):
            return Result.text("That click only closed an open menu or popup; it did not reach what was under it. "
                               "Click again if needed.", ch)
        return Result.text(f"Clicked ({button}{' x' + str(count) if count > 1 else ''}) in {where}.", _with_note(ch, note))

    @reg.tool("drag",
              "Drag with the assistant's pointer from (x,y) to (x2,y2), pixels of the last screenshot (or "
              "image). For moving items, sliders, selecting text.",
              {"x": {"type": "number"}, "y": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"},
               "image": {"type": "string"}, "intent": INTENT_PROPERTY, "risk": RISK_PROPERTY},
              ["x", "y", "x2", "y2"], risk="reversible", title="Drag")
    def drag(ctx: Context, x: float, y: float, x2: float, y2: float, image: str | None = None,
             intent: str | None = None, risk: str | None = None) -> Result:
        h.guard(ctx)
        h.need_bridge("agentInput")
        gx, gy, sid = sc.to_global(x, y, image)
        gx2, gy2, _ = sc.to_global(x2, y2, sid)
        wins, target = precheck(gx, gy)
        precheck(gx2, gy2)
        # hands.md §10: pressing on, or releasing over, a risky element
        notes = [gate.check_point("drag", gx, gy, risk, intent), gate.check_point("drag", gx2, gy2, risk, intent)]
        h.begin_session(intent or "Kristall")
        h.cursor.move_to(ctx, gx, gy, sc.label(intent, "Ziehe", "Dragging"))
        h.cursor.pulse("drag_start")
        dur = h.cursor.glide_ms(((gx2 - gx) ** 2 + (gy2 - gy) ** 2) ** 0.5)
        h.link.cursor(x=round(gx2, 1), y=round(gy2, 1), visible=True, duration_ms=dur)
        try:
            h.agent(ctx, "agent.drag", {"from": {"x": gx, "y": gy}, "to": {"x": gx2, "y": gy2},
                                        "button": "left", "durationMs": max(300, dur)}, timeout=15.0)
        except BridgeError as e:
            if e.code == "busy":
                raise HandsError("The owner is using the mouse right now. Wait a moment and try again.")
            raise HandsError(f"The drag did not work ({e.code}).")
        h.cursor.pos = (round(gx2, 1), round(gy2, 1))
        h.cursor.pulse("drag_end")
        h.touch()
        note = "from " + notes[0].replace("target: ", "", 1) + "; to " + notes[1].replace("target: ", "", 1)
        return Result.text("Dragged.", _with_note(sc.changes(ctx, wins, (target or {}).get("id")), "target: " + note))

    @reg.tool("scroll",
              "Scroll at a point of the last screenshot (or a ref) with the assistant's pointer: direction "
              "up/down/left/right, amount in wheel notches (default 3).",
              {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
               "amount": {"type": "integer", "minimum": 1, "maximum": 50},
               "x": {"type": "number"}, "y": {"type": "number"}, "image": {"type": "string"}, "ref": {"type": "string"},
               "intent": INTENT_PROPERTY},
              ["direction"], risk="reversible", title="Scroll")
    def scroll(ctx: Context, direction: str, amount: int = 3, x: float | None = None, y: float | None = None,
               image: str | None = None, ref: str | None = None, intent: str | None = None) -> Result:
        h.guard(ctx)
        h.need_bridge("agentInput")
        if x is None and y is None and ref is None:
            win = h.active_window()
            if not win:
                raise HandsError("Where should I scroll? Give x,y or a ref.")
            gx, gy = win["x"] + win["w"] / 2, win["y"] + win["h"] / 2
        else:
            gx, gy, _, _ = resolve_point(x, y, image, ref)
        wins, target = precheck(gx, gy)
        h.begin_session(intent or "Kristall")
        h.cursor.move_to(ctx, gx, gy, sc.label(intent, "Scrolle", "Scrolling"))
        h.cursor.pulse("scroll")
        dx = {"left": -amount, "right": amount}.get(direction, 0)
        dy = {"up": -amount, "down": amount}.get(direction, 0)
        sc.pointer(ctx, {"type": "scroll", "x": gx, "y": gy, "dx": dx, "dy": dy})
        h.touch()
        return Result.text(f"Scrolled {direction} by {amount}.", sc.changes(ctx, wins, (target or {}).get("id"), settle=0.25))

    def keyboard_target(window: str | None) -> dict:
        win = h.resolve_window(window)
        check_window(win, h.protected, typing=True)
        if is_auth_window(win, h.protected):
            raise HandsError(AUTH_MSG)
        if a.mode() != "off" and a.password_focused(win):
            raise HandsError(AUTH_MSG)
        return win

    def caret_point(win: dict) -> tuple[float, float]:
        try:
            frame, _ = a.frame_for(win, None)
            f = a.focused_in(frame, cap=500)
            if f is not None:
                pt = a.to_global(win, frame, a.extents(f))
                if pt:
                    return pt
        except Exception:
            pass
        if h.cursor.visible and h.cursor.pos:
            return h.cursor.pos
        return win["x"] + win["w"] / 2, win["y"] + min(win["h"] / 2, 120)

    @reg.tool("type_text",
              "Type text into a window (default: the active one) where its text cursor is, like a keyboard, with "
              "any characters (ä ö ü ß € emoji, line breaks). A text field must have the focus: open a document or "
              "click into the field first. enter=true presses Return afterwards. Passwords and login prompts are "
              "refused. Set risk if pressing Return sends something.",
              {"text": {"type": "string", "maxLength": 20000},
               "window": {"type": "string"}, "enter": {"type": "boolean"},
               "force": {"type": "boolean", "description": "Type even though no text field seems to have focus (games, drawing apps)."},
               "intent": INTENT_PROPERTY, "risk": RISK_PROPERTY},
              ["text"], risk="reversible", title="Type text")
    def type_text(ctx: Context, text: str, window: str | None = None, enter: bool = False, force: bool = False,
                  intent: str | None = None, risk: str | None = None) -> Result:
        h.guard(ctx)
        h.need_bridge("agentText")
        win = keyboard_target(window)
        focus, frole, editable = (None, "", None) if a.mode() == "off" else a.keyboard_focus(win)
        if focus is not None and editable is False and not force:
            line, _, _ = a.describe(focus, frole, bounds=False, with_value=False)
            return Result.error("No text field has the keyboard focus in that window, so typing would go nowhere or "
                                "trigger shortcuts. Focus is on: " + untrusted(line) + "\nOpen or click into the "
                                "text field first (or ui_act set_text on it); use force=true only for apps without "
                                "readable controls.")
        note = None
        multi = focus is not None and "multi-line" in a.states(focus)
        if enter or ("\n" in text and not multi):
            # hands.md §10: Return can press a default "Senden" button
            note = gate.check_keys("type_text", win, "return", risk, intent)
        h.begin_session(intent or "Kristall")
        px, py = caret_point(win)
        h.cursor.move_to(ctx, px, py, sc.label(intent, "Tippe", "Typing"), output=preview(text))
        h.cursor.pulse("type", output=preview(text))
        before = h.windows()
        try:
            send_text(h, ctx, text + ("\n" if enter else ""), win["id"], intent or "Kristall")
        except BridgeError as e:
            if e.code == "busy":
                raise HandsError("The owner is typing or using the mouse right now. Wait a moment and try again.")
            raise HandsError(f"Typing did not work ({e.code}).")
        log.info("typed %d chars into %s", len(text), win.get("appId"))
        h.touch()
        ch = sc.changes(ctx, before, win["id"], settle=0.25)
        msg = f"Typed {len(text)} characters{' and pressed Return' if enter else ''}."
        if focus is not None and editable:
            tail, _ = a.text_tail(focus, 400)
            want = text.rstrip("\r\n")[-40:].replace("\r\n", "\n")
            if want and want not in tail and not enter:
                msg += " Warning: the text field does not show the typed text at its end; check it with ui_tree."
            else:
                msg += " Verified in the text field."
        elif focus is None and a.mode() != "off":
            msg += " (Could not verify: the window does not report its text fields.)"
        return Result.text(msg, _with_note(ch, note))

    @reg.tool("press_keys",
              "Press a key or shortcut in a window (default: the active one): e.g. ctrl+s, ctrl+shift+t, alt+f4, "
              "return, escape, tab, f5, page_down. repeat presses it several times. Set risk for shortcuts "
              "that send, delete or quit.",
              {"keys": {"type": "string", "maxLength": 60}, "window": {"type": "string"},
               "repeat": {"type": "integer", "minimum": 1, "maximum": 50},
               "intent": INTENT_PROPERTY, "risk": RISK_PROPERTY},
              ["keys"], risk="reversible", title="Press keys")
    def press_keys(ctx: Context, keys: str, window: str | None = None, repeat: int = 1, intent: str | None = None,
                   risk: str | None = None) -> Result:
        h.guard(ctx)
        h.need_bridge("agentInput")
        chord = normalize_keys(keys)
        win = keyboard_target(window)
        # hands.md §10: Return, Ctrl+Return, Ctrl+S and Space activate the focused or default button
        note = gate.check_keys("press_keys", win, chord, risk, intent)
        h.begin_session(intent or "Kristall")
        px, py = caret_point(win)
        h.cursor.move_to(ctx, px, py, sc.label(intent, f"Drücke {chord}", f"Pressing {chord}"))
        before = h.windows()
        for i in range(repeat):
            ctx.check()
            h.cursor.pulse("type", output=chord)
            try:
                h.agent(ctx, "agent.key", {"keys": chord, "windowId": win["id"]})
            except BridgeError as e:
                if e.code == "unsupported":
                    raise HandsError(f"The key “{chord}” is not on the keyboard layout.")
                if e.code == "invalid":
                    raise HandsError(f"The compositor does not know the key “{chord}”.")
                if e.code == "busy":
                    raise HandsError("The owner is typing right now. Wait a moment and try again.")
                raise HandsError(f"The key press did not work ({e.code}).")
            if repeat > 1:
                ctx.sleep(0.05)
        h.touch()
        return Result.text(f"Pressed {chord}{f' {repeat} times' if repeat > 1 else ''}.",
                           _with_note(sc.changes(ctx, before, win["id"], settle=0.3), note))

    @reg.tool("save_screenshot",
              "Save a screenshot for the owner as a PNG in their Pictures folder (Bilder/Bildschirmfotos): the "
              "whole screen or one window. Returns the file path.",
              {"target": {"type": "string", "enum": ["screen", "window"]}, "window": {"type": "string"}},
              risk="reversible", title="Save screenshot")
    def save_screenshot(ctx: Context, target: str = "screen", window: str | None = None) -> Result:
        h.guard(ctx, acting=False)
        folder = os.path.join(pictures_dir(), "Bildschirmfotos" if h.lang() == "de" else "Screenshots")
        os.makedirs(folder, exist_ok=True)
        name = ("Bildschirmfoto " if h.lang() == "de" else "Screenshot ") + dt.datetime.now().strftime("%Y-%m-%d %H-%M-%S") + ".png"
        dest = os.path.join(folder, name)
        if h.bridge.ensure() and h.bridge.has("screenshot"):
            if target == "window":
                win = h.resolve_window(window)
                check_window(win, h.protected)
                data, _ = sc.capture({"window": win["id"]})
            else:
                data, _ = sc.capture("desktop")
            with open(dest, "wb") as f:
                f.write(data)
        else:
            exe = shutil.which("spectacle")
            if not exe:
                raise HandsError("Screenshots are not available right now.")
            mode = "--activewindow" if target == "window" else "--fullscreen"
            r = subprocess.run([exe, "--background", "--nonotify", mode, "--output", dest], capture_output=True, timeout=20)
            if r.returncode != 0 or not os.path.exists(dest):
                raise HandsError("The screenshot could not be saved.")
        os.chmod(dest, 0o644)
        return Result.text(f"Saved: {dest}")

    return sc


def _verb_de(action: str) -> str:
    return {"press": "Drücke", "open": "Öffne", "toggle": "Schalte", "set_text": "Schreibe in", "append_text": "Schreibe in",
            "set_value": "Stelle ein", "select": "Wähle", "expand": "Öffne", "collapse": "Schließe",
            "focus": "Gehe zu", "scroll_to": "Scrolle zu", "show_menu": "Menü von"}.get(action, "Bediene")


def _verb_en(action: str) -> str:
    return {"press": "Pressing", "open": "Opening", "toggle": "Toggling", "set_text": "Writing in", "append_text": "Writing in",
            "set_value": "Setting", "select": "Selecting", "expand": "Opening", "collapse": "Closing",
            "focus": "Focusing", "scroll_to": "Scrolling to", "show_menu": "Menu of"}.get(action, "Using")
