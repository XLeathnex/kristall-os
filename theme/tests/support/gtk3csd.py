#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test-only GTK 3 window with a client-side title bar, like Mousepad's: a GtkHeaderBar as the
window's titlebar that the app made compact (no minimum height, no vertical padding), a menu bar
and a white text area below. argv[1]: window title."""
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

css = Gtk.CssProvider()
css.load_from_data(b"headerbar { min-height: 0; padding-top: 0; padding-bottom: 0; }")
Gtk.StyleContext.add_provider_for_screen(__import__("gi.repository.Gdk", fromlist=["Gdk"]).Screen.get_default(), css,
                                         Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
win = Gtk.Window(title=sys.argv[1] if len(sys.argv) > 1 else "CSD-Test")
hb = Gtk.HeaderBar(title=win.get_title(), show_close_button=True, has_subtitle=False)
win.set_titlebar(hb)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
mb = Gtk.MenuBar()
for name in ("Datei", "Bearbeiten", "Hilfe"):
    mb.append(Gtk.MenuItem(label=name))
box.pack_start(mb, False, False, 0)
tv = Gtk.TextView()
box.pack_start(tv, True, True, 0)
win.add(box)
win.set_default_size(640, 420)
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
