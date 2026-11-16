# SPDX-License-Identifier: GPL-3.0-or-later
"""Tier 2 against real Qt apps (Kate, Dolphin) in a headless KWin session.  Dev container only
(needs KWin, AT-SPI, python3-gobject); run under dbus-run-session (tests/run.sh does)."""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

try:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi  # noqa: F401
    HAVE = os.path.exists("/usr/bin/kwin_wayland") and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
except (ImportError, ValueError):
    HAVE = False

from kristall_hands import dbus  # noqa: E402
from kristall_hands.bridge import Bridge  # noqa: E402
from kristall_hands.core import Hands  # noqa: E402
from kristall_hands.link import Link  # noqa: E402
from kristall_hands.server import build  # noqa: E402
from kristall_hands.tooling import Context, HandsError, Result  # noqa: E402

SIZES = []


def tokens(text: str) -> int:
    return round(len(text) / 4)          # estimate; see README (no tokenizer offline)


@unittest.skipUnless(HAVE, "needs the dev container (KWin, AT-SPI) under dbus-run-session")
class RealApps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.session import Session
        cls.tmp = tempfile.mkdtemp(prefix="kristall-a11y-")
        cls.doc = os.path.join(cls.tmp, "einkauf.txt")
        with open(cls.doc, "w") as f:
            f.write("Milch\nEier\n")
        cls.s = Session(name="a11y").start()
        os.environ.update({"XDG_RUNTIME_DIR": cls.s.run, "WAYLAND_DISPLAY": cls.s.wayland,
                           "KRISTALL_HANDS_LOG_STDERR": "1", "KRISTALL_SETTINGS_BIN": "/nonexistent"})
        cls.h = Hands(bridge=Bridge(path=os.path.join(cls.tmp, "no-bridge.sock")),
                      link=Link(path=os.path.join(cls.tmp, "no-daemon.sock")))
        cls.reg, _, cls.a = build(cls.h)
        # accessibility starts off, as in a fresh session; hands switches it on when needed
        bus = dbus.session()
        bus.set("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled", "b", False)
        cls.s.app(["kate", "-n", cls.doc], name="kate")
        cls.s.app(["dolphin", "--new-window", "/usr/share"], name="dolphin")
        time.sleep(6)

    @classmethod
    def tearDownClass(cls):
        cls.a.restore()
        cls.s.stop()
        print("\n   snapshot sizes (chars / ~tokens / elements / seconds):")
        for name, st in SIZES:
            print(f"     {name:45s} {st['chars']:6d} chars  ~{round(st['chars'] / 4):5d} tokens  "
                  f"{st['printed'] or st['matches']:4d} elements  {st['seconds']:.2f} s")

    def call(self, tool, **args):
        t = self.reg.tools[tool]
        p = t.validate(args)
        if p:
            return Result.error(p)
        try:
            return t.fn(Context(1, tool), **args)
        except HandsError as e:
            return Result.error(e.message)

    def text(self, r):
        return "\n".join(p["text"] for p in r.parts if p["type"] == "text")

    def tree(self, label, **args):
        r = self.call("ui_tree", **args)
        out = self.text(r)
        self.assertFalse(r.is_error, out)
        SIZES.append((label, dict(self.a.stats)))
        return out

    @staticmethod
    def ref(out, *needles):
        for line in out.splitlines():
            if all(n in line for n in needles):
                return line.split()[0] if line.split()[0].startswith("e") else line.strip().split()[0]
        raise AssertionError(f"no line with {needles} in:\n{out}")

    @staticmethod
    def title(o):
        return next((l for l in o.splitlines() if l.startswith("window ")), "")

    def wait(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            v = pred()
            if v:
                return v
            time.sleep(0.2)
        return pred()

    def test_1_kate_edit_and_toolbar(self):
        out = self.tree("Kate: whole window", window="kate")
        self.assertIn('text "einkauf.txt" ="Milch⏎Eier⏎"', out)
        self.assertIn("<screen-content-", out)
        ed = self.ref(out, 'text "einkauf.txt"')
        r = self.call("ui_act", ref=ed, action="set_text", text="Einkaufszettel:\n- Äpfel\n- Brot\n- Käse 🧀")
        self.assertFalse(r.is_error, self.text(r))
        out = self.tree("Kate: after set_text", window="kate")
        self.assertIn('="Einkaufszettel:⏎- Äpfel⏎- Brot⏎- Käse 🧀"', out)
        self.assertIn("einkauf.txt *", out)                    # Kate marks the document modified
        r = self.call("ui_act", ref=ed, action="append_text", text="\n- Butter")
        long = "\n".join(f"Zeile {i}: Brot" for i in range(60))
        self.call("ui_act", ref=ed, action="set_text", text=long)
        full = self.text(self.call("ui_tree", root=ed))
        self.assertIn("Zeile 59: Brot", full)                  # root=<text> reads the whole text
        self.call("ui_act", ref=ed, action="set_text", text="Einkaufszettel:\n- Äpfel\n- Brot\n- Käse 🧀\n- Butter")
        self.assertIn("Butter", self.text(self.call("ui_tree", window="kate", find="Butter")))
        new = self.ref(out, 'button "New"')
        r = self.call("ui_act", ref=new, action="press", intent="Neues Dokument")
        self.assertFalse(r.is_error, self.text(r))
        out = self.wait(lambda: (lambda o: o if "Untitled" in o else None)(self.text(self.call("ui_tree", window="kate"))))
        self.assertIn('tab "Untitled"', out)
        SIZES.append(("Kate: two documents", dict(self.a.stats)))
        # select the first tab again
        tab = self.ref(out, 'tab "einkauf.txt')
        r = self.call("ui_act", ref=tab, action="select")
        self.assertFalse(r.is_error, self.text(r))
        out = self.wait(lambda: (lambda o: o if "einkauf.txt" in self.title(o) else None)(
            self.text(self.call("ui_tree", window="kate"))))
        self.assertTrue(out, self.text(r) + "\n" + self.text(self.call("ui_tree", window="kate")))

    def test_2_kate_search_field(self):
        out = self.tree("Kate: find 'Find' (searches closed menus)", window="kate", find="Find")
        self.assertIn('menuitem "Find', out)
        # menus can't be opened through AT-SPI on Wayland, but their items can be triggered directly
        edit = self.ref(self.tree("Kate: find 'Edit'", window="kate", find="Edit"), 'menuitem "Edit"')
        menu = self.tree("Kate: Edit menu (root=)", root=edit)
        find = self.ref(menu, 'menuitem "Find…"')
        r = self.call("ui_act", ref=find, action="press", intent="Suche öffnen")
        self.assertFalse(r.is_error, self.text(r))
        out = self.wait(lambda: (lambda o: o if 'label "Find:"' in o else None)(
            self.text(self.call("ui_tree", window="kate"))))
        self.assertTrue(out, "search bar did not appear:\n" + self.text(self.call("ui_tree", window="kate")))
        SIZES.append(("Kate: window with search bar", dict(self.a.stats)))
        lines = [l.strip() for l in out.splitlines() if l.strip().split(" ")[1:2] == ["text"] and "einkauf" not in l]
        self.assertTrue(lines, out)
        field = lines[0].split()[0]
        r = self.call("ui_act", ref=field, action="set_text", text="Brot")
        print("\n   search field:", lines[0], "->", self.text(r).splitlines()[0])
        self.assertFalse(r.is_error, self.text(r))
        self.assertIn('"Brot"', self.text(self.call("ui_tree", window="kate", root=field)))

    def test_3_dolphin_navigate(self):
        out = self.tree("Dolphin: whole window", window="dolphin")
        self.assertIn('list "share"', out)
        self.assertIn("more items not shown", out)
        self.assertNotIn('"zsh"', out)                     # scrolled-away items are not listed
        up = self.ref(out, 'button "usr"')
        r = self.call("ui_act", ref=up, action="press", intent="Gehe zu usr")
        res = self.text(r)
        print("\n   breadcrumb press:", res.splitlines()[0])
        navigated = self.wait(lambda: 'usr — Dolphin' in self.title(self.text(self.call("ui_tree", window="dolphin"))), 3)
        if not navigated:
            # KUrlNavigator buttons react to mouse events only: hands must say so, so the model clicks
            self.assertIn("use click with ref", res)
        # select an item in the file view
        out = self.tree("Dolphin: after press", window="dolphin")
        item = self.ref(out, 'item "applications"')
        r = self.call("ui_act", ref=item, action="select")
        self.assertFalse(r.is_error, self.text(r))
        self.assertIn("selected", self.text(self.call("ui_tree", window="dolphin", root=item)))
        # find also reaches items scrolled out of view, and says so
        out = self.tree("Dolphin: find='zsh'", window="dolphin", find="zsh")
        self.assertIn('item "zsh"', out)
        self.assertIn("scrolled out of view", out)
        z = self.ref(out, 'item "zsh"')
        r = self.call("ui_act", ref=z, action="scroll_to")
        print("   scroll_to:", self.text(r).splitlines()[0])
        r = self.call("ui_act", ref=z, action="select")
        self.assertIn("selected", self.text(self.call("ui_tree", window="dolphin", root=z)))
        # a Places entry
        home = self.ref(self.tree("Dolphin: find='Trash'", window="dolphin", find="Trash"), 'item "Trash"')
        r = self.call("ui_act", ref=home, action="press")
        moved = self.wait(lambda: 'Trash — Dolphin' in self.title(self.text(self.call("ui_tree", window="dolphin"))), 3)
        print("   places 'Trash' press:", self.text(r).splitlines()[0], "| navigated:", bool(moved))

    def test_4_errors(self):
        r = self.call("ui_act", ref="e999999", action="press")
        self.assertIn("Take a fresh ui_tree", self.text(r))
        r = self.call("ui_tree", window="Photoshop")
        self.assertTrue(r.is_error)


if __name__ == "__main__":
    unittest.main()
