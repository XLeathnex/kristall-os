#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# gtkprobe: GTK 3 test client for kristall-bridge. A window with a menu bar (File > Open) and an
# entry and a multi-line text view; logs the entry and text-view contents, menu activations and its
# layout as JSON lines.
import json
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

T0 = time.monotonic()


def log(**kw):
    kw["t"] = round((time.monotonic() - T0) * 1000, 3)
    print(json.dumps(kw, ensure_ascii=False), flush=True)


title = sys.argv[1] if len(sys.argv) > 1 else "gtkprobe"
win = Gtk.Window(title=title)
win.set_default_size(500, 300)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
bar = Gtk.MenuBar()
file_item = Gtk.MenuItem(label="File")
menu = Gtk.Menu()
open_item = Gtk.MenuItem(label="Open")
open_item.connect("activate", lambda *_: log(ev="action", name="Open"))
menu.append(open_item)
file_item.set_submenu(menu)
bar.append(file_item)
box.pack_start(bar, False, False, 0)
entry = Gtk.Entry()
entry.connect("changed", lambda e: log(ev="line", text=e.get_text()))
box.pack_start(entry, False, False, 0)
view = Gtk.TextView()
view.set_size_request(-1, 120)
view.get_buffer().connect("changed", lambda b: log(ev="textview", text=b.get_text(b.get_start_iter(), b.get_end_iter(), True)))
box.pack_start(view, True, True, 0)
win.add(box)
win.connect("destroy", Gtk.main_quit)
win.show_all()


def layout():
    a = entry.get_allocation()
    m = bar.get_allocation()
    v = view.get_allocation()
    log(ev="layout", backend=type(win.get_display()).__name__,
        line={"x": a.x, "y": a.y, "w": a.width, "h": a.height}, menubar={"x": m.x, "y": m.y, "w": m.width, "h": m.height},
        view={"x": v.x, "y": v.y, "w": v.width, "h": v.height})
    return False


GLib.timeout_add(500, layout)
log(ev="started")
Gtk.main()
