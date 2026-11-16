#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""riskwin: a GTK 3 test window for the risky-target gate (tests/test_riskgate_e2e.py).

A "new message" window with a text entry and the buttons Senden (the window's default button, so
Return in the entry sends), Abbrechen, In den Papierkorb, Text löschen and Aufräumen…; the last one
opens a modal dialog "Möchtest du 3 Dateien endgültig löschen?" with Abbrechen and OK (OK is the
default).  Every activation is logged on stdout as a JSON line.  (GTK 4 and PyQt are not in the dev
container; GTK 3 exposes its widgets to AT-SPI through its built-in ATK bridge.)"""
import json
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

T0 = time.monotonic()
GLib.set_prgname("riskwin")


def log(**kw):
    kw["t"] = round((time.monotonic() - T0) * 1000, 1)
    print(json.dumps(kw, ensure_ascii=False), flush=True)


title = sys.argv[1] if len(sys.argv) > 1 else "Neue Nachricht – Testpost"
win = Gtk.Window(title=title)
win.set_default_size(620, 220)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
box.set_border_width(12)
label = Gtk.Label(label="Nachricht an Oma:")
label.set_xalign(0)
box.pack_start(label, False, False, 0)
entry = Gtk.Entry()
entry.set_text("Hallo Oma, bis Sonntag!")
entry.set_activates_default(True)
entry.connect("changed", lambda e: log(ev="text", text=e.get_text()))
box.pack_start(entry, False, False, 0)
row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)


def clicked(b):
    log(ev="clicked", name=b.get_label())
    if b.get_label() == "Text löschen":
        entry.set_text("")
    elif b.get_label() == "Aufräumen…":
        open_dialog()


buttons = {}
for name in ("Senden", "Abbrechen", "In den Papierkorb", "Text löschen", "Aufräumen…"):
    b = Gtk.Button(label=name)
    b.connect("clicked", clicked)
    row.pack_start(b, False, False, 0)
    buttons[name] = b
box.pack_start(row, False, False, 0)
win.add(box)
send = buttons["Senden"]
send.set_can_default(True)
win.set_default(send)
win.connect("destroy", Gtk.main_quit)
win.show_all()
entry.grab_focus()


def open_dialog():
    d = Gtk.MessageDialog(transient_for=win, modal=True, message_type=Gtk.MessageType.WARNING,
                          buttons=Gtk.ButtonsType.NONE, text="Möchtest du 3 Dateien endgültig löschen?")
    d.set_title("Aufräumen")
    d.format_secondary_text("Urlaub.jpg, Rechnung.pdf und Notizen.txt werden nicht in den Papierkorb gelegt.")
    d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)

    def response(dlg, rid):
        log(ev="dialog", response={Gtk.ResponseType.OK: "ok", Gtk.ResponseType.CANCEL: "cancel"}.get(rid, str(int(rid))))
        dlg.destroy()
    d.connect("response", response)
    d.show_all()
    log(ev="dialog_open")


log(ev="started", title=title)
Gtk.main()
