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
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

T0 = time.monotonic()


def log(**kw):
    kw["t"] = round((time.monotonic() - T0) * 1000, 3)
    print(json.dumps(kw, ensure_ascii=False), flush=True)


title = sys.argv[1] if len(sys.argv) > 1 else "gtkprobe"
APP = "--app" in sys.argv   # GtkApplication with a GMenu menu bar (GtkApplicationWindow makes the bar)
if APP:
    from gi.repository import Gio  # noqa: E402

entry = Gtk.Entry()
entry.connect("changed", lambda e: log(ev="line", text=e.get_text()))
view = Gtk.TextView()
view.set_size_request(-1, 120)
view.get_buffer().connect("changed", lambda b: log(ev="textview", text=b.get_text(b.get_start_iter(), b.get_end_iter(), True)))
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
bar = None


def bar_state(w, *_):
    a = w.get_allocation()
    log(ev="menubar", h=a.height if w.get_mapped() else 0, mapped=w.get_mapped(), child_visible=w.get_child_visible())


def build_window(win):
    global bar
    win.set_default_size(500, 300)
    if not APP:
        bar = Gtk.MenuBar()
        accel = Gtk.AccelGroup()
        win.add_accel_group(accel)
        file_item = Gtk.MenuItem(label="File")
        menu = Gtk.Menu()
        open_item = Gtk.MenuItem(label="Open")
        open_item.connect("activate", lambda *_: log(ev="action", name="Open"))
        open_item.add_accelerator("activate", accel, Gdk.KEY_o, Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        menu.append(open_item)
        menu.append(Gtk.SeparatorMenuItem())
        wrap = Gtk.CheckMenuItem(label="Wrap")
        wrap.connect("toggled", lambda w: log(ev="toggled", name="Wrap", active=w.get_active()))
        menu.append(wrap)
        file_item.set_submenu(menu)
        bar.append(file_item)
        bar.connect("size-allocate", bar_state)
        bar.connect("map", bar_state)
        bar.connect("unmap", bar_state)
        box.pack_start(bar, False, False, 0)
    box.pack_start(entry, False, False, 0)
    box.pack_start(view, True, True, 0)
    win.add(box)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()


def layout():
    a = entry.get_allocation()
    m = bar.get_allocation() if bar else None
    v = view.get_allocation()
    b = box.get_allocation()
    log(ev="layout", backend=type(entry.get_display()).__name__,
        line={"x": a.x, "y": a.y, "w": a.width, "h": a.height},
        menubar={"x": m.x, "y": m.y, "w": m.width, "h": m.height if bar.get_mapped() else 0} if m else None,
        content_y=b.y, view={"x": v.x, "y": v.y, "w": v.width, "h": v.height})
    return False


def content_moved(w, a):
    log(ev="content", y=a.y)


if APP:
    app = Gtk.Application(application_id="org.kristall.GtkProbeApp", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def startup(a):
        act = Gio.SimpleAction.new("open", None)
        act.connect("activate", lambda *_: log(ev="action", name="Open"))
        a.add_action(act)
        a.set_accels_for_action("app.open", ["<Primary>o"])
        model = Gio.Menu()
        file_menu = Gio.Menu()
        file_menu.append("Open", "app.open")
        model.append_submenu("File", file_menu)
        a.set_menubar(model)

    def activate(a):
        win = Gtk.ApplicationWindow(application=a, title=title)
        box.connect("size-allocate", content_moved)
        build_window(win)
        GLib.timeout_add(500, layout)
        log(ev="started")

    app.connect("startup", startup)
    app.connect("activate", activate)
    app.run([sys.argv[0]])
else:
    win = Gtk.Window(title=title)
    build_window(win)
    GLib.timeout_add(500, layout)
    log(ev="started")
    Gtk.main()
