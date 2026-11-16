#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Minimal com.canonical.AppMenu.Registrar for tests: Qt apps export their menu bar over DBusMenu
# once a registrar exists and call RegisterWindow; we print "REGISTER <sender> <path>" so the test
# can tell the mock bridge where the window's menu is (the real bridge learns it from KWin).
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

IFACE = "com.canonical.AppMenu.Registrar"


class Registrar(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, "/com/canonical/AppMenu/Registrar")
        self.menus = {}

    @dbus.service.method(IFACE, in_signature="uo", sender_keyword="sender")
    def RegisterWindow(self, wid, path, sender=None):
        self.menus[int(wid)] = (sender, str(path))
        print("REGISTER", sender, path, flush=True)

    @dbus.service.method(IFACE, in_signature="u")
    def UnregisterWindow(self, wid):
        self.menus.pop(int(wid), None)

    @dbus.service.method(IFACE, in_signature="u", out_signature="so")
    def GetMenuForWindow(self, wid):
        s, p = self.menus.get(int(wid), ("", "/"))
        return s, dbus.ObjectPath(p)


DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
name = dbus.service.BusName(IFACE, bus)
r = Registrar(bus)
print("ready", flush=True)
GLib.MainLoop().run()
