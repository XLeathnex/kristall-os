# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake system and session D-Bus services for the session-daemon test:
system bus: UPower (+DisplayDevice), tuned-ppd (org.freedesktop.UPower.PowerProfiles, with the
hold semantics of tuned 2.28), logind; session bus: GameMode, the systemd user manager,
org.kde.ScreenBrightness, and org.test.Control to drive and inspect all of them.
Usage: fake_services.py SYSTEM_ADDR SESSION_ADDR READY_FILE [--no-ppd]
--no-ppd: leave org.freedesktop.UPower.PowerProfiles to the real tuned-ppd and put org.test.Control
on the system bus (test_real_tuned.py)."""
import json
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

PROPS = "org.freedesktop.DBus.Properties"


class PropObject(dbus.service.Object):
    def __init__(self, conn, path, iface, props):
        super().__init__(conn, path)
        self.iface = iface
        self.props = props

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.props[name]

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary(self.props, signature="sv")

    @dbus.service.method(PROPS, in_signature="ssv", out_signature="", sender_keyword="sender")
    def Set(self, iface, name, value, sender=None):
        self.setter(name, value, sender)

    def setter(self, name, value, sender):
        raise dbus.DBusException("read-only")

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass

    def update(self, **kw):
        self.props.update(kw)
        self.PropertiesChanged(self.iface, dbus.Dictionary(kw, signature="sv"), dbus.Array([], signature="s"))


class PPD(PropObject):
    IFACE = "org.freedesktop.UPower.PowerProfiles"

    def __init__(self, conn):
        super().__init__(conn, "/org/freedesktop/UPower/PowerProfiles", self.IFACE,
                         {"ActiveProfile": dbus.String("power-saver"), "ActiveProfileHolds": dbus.Array([], signature="a{sv}"),
                          "PerformanceDegraded": dbus.String("")})
        self.base = "power-saver"
        self.holds = {}
        self.cookie = 1000
        self.history = []

    def _switch(self, p):
        if self.props["ActiveProfile"] != p:
            self.history.append(p)
            self.update(ActiveProfile=dbus.String(p))

    def _holds_prop(self):
        self.update(ActiveProfileHolds=dbus.Array([{"Profile": p, "Reason": r, "ApplicationId": a}
                                                   for p, r, a, _ in self.holds.values()], signature="a{sv}"))

    def _effective(self):
        return "power-saver" if any(h[0] == "power-saver" for h in self.holds.values()) else "performance"

    def setter(self, name, value, sender):
        if name != "ActiveProfile":
            raise dbus.DBusException("read-only")
        for c in list(self.holds):
            del self.holds[c]
            self.ProfileReleased(dbus.UInt32(c))
        self._holds_prop()
        self._switch(str(value))
        self.base = str(value)

    @dbus.service.method(IFACE, in_signature="sss", out_signature="u", sender_keyword="sender")
    def HoldProfile(self, profile, reason, app, sender=None):
        self.cookie += 1
        self.holds[self.cookie] = (str(profile), str(reason), str(app), sender)
        self._holds_prop()
        self._switch(self._effective())
        return dbus.UInt32(self.cookie)

    @dbus.service.method(IFACE, in_signature="u", out_signature="", sender_keyword="sender")
    def ReleaseProfile(self, cookie, sender=None):
        if int(cookie) not in self.holds:
            raise dbus.DBusException("No active hold")
        del self.holds[int(cookie)]
        self.ProfileReleased(cookie)
        self._holds_prop()
        self._switch(self._effective() if self.holds else self.base)

    @dbus.service.signal(IFACE, signature="u")
    def ProfileReleased(self, cookie):
        pass


class Login(dbus.service.Object):
    IFACE = "org.freedesktop.login1.Manager"

    def __init__(self, conn):
        super().__init__(conn, "/org/freedesktop/login1")
        self.session = PropObject(conn, "/org/freedesktop/login1/session/_31", "org.freedesktop.login1.Session",
                                  {"LockedHint": dbus.Boolean(False)})

    @dbus.service.method(IFACE, in_signature="s", out_signature="o")
    def GetSession(self, sid):
        return dbus.ObjectPath("/org/freedesktop/login1/session/_31")

    @dbus.service.method(IFACE, in_signature="u", out_signature="o")
    def GetSessionByPID(self, pid):
        return dbus.ObjectPath("/org/freedesktop/login1/session/_31")

    @dbus.service.signal(IFACE, signature="b")
    def PrepareForSleep(self, going):
        pass


class GameMode(PropObject):
    IFACE = "com.feralinteractive.GameMode"

    def __init__(self, conn):
        super().__init__(conn, "/com/feralinteractive/GameMode", self.IFACE, {"ClientCount": dbus.Int32(0)})

    @dbus.service.signal(IFACE, signature="io")
    def GameRegistered(self, pid, path):
        pass

    @dbus.service.signal(IFACE, signature="io")
    def GameUnregistered(self, pid, path):
        pass


class Systemd(dbus.service.Object):
    IFACE = "org.freedesktop.systemd1.Manager"

    def __init__(self, conn):
        super().__init__(conn, "/org/freedesktop/systemd1")
        self.conn = conn
        self.units = {}

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Subscribe(self):
        pass

    @dbus.service.method(IFACE, in_signature="", out_signature="a(ssssssouso)")
    def ListUnits(self):
        return [(n, "", "loaded", "active", "running", "", dbus.ObjectPath(p), 0, "", dbus.ObjectPath("/"))
                for n, (p, _) in self.units.items()]

    @dbus.service.signal(IFACE, signature="so")
    def UnitNew(self, name, path):
        pass

    @dbus.service.signal(IFACE, signature="so")
    def UnitRemoved(self, name, path):
        pass

    def add(self, name, cgroup):
        path = "/org/freedesktop/systemd1/unit/" + "".join(c if c.isalnum() else "_" for c in name)
        iface = "org.freedesktop.systemd1.Scope" if name.endswith(".scope") else "org.freedesktop.systemd1.Service"
        obj = PropObject(self.conn, path, iface, {"ControlGroup": dbus.String(cgroup)})
        self.units[name] = (path, obj)
        self.UnitNew(name, dbus.ObjectPath(path))

    def remove(self, name):
        path, obj = self.units.pop(name)
        obj.remove_from_connection()
        self.UnitRemoved(name, dbus.ObjectPath(path))


class Brightness(PropObject):
    def __init__(self, conn):
        super().__init__(conn, "/org/kde/ScreenBrightness", "org.kde.ScreenBrightness",
                         {"DisplaysDBusNames": dbus.Array(["display0"], signature="s")})
        self.display = Display(conn)


class Display(PropObject):
    IFACE = "org.kde.ScreenBrightness.Display"

    def __init__(self, conn):
        super().__init__(conn, "/org/kde/ScreenBrightness/display0", self.IFACE,
                         {"IsInternal": dbus.Boolean(True), "Brightness": dbus.Int32(300), "MaxBrightness": dbus.Int32(400),
                          "Label": dbus.String("Built-in")})
        self.calls = []

    @dbus.service.method(IFACE, in_signature="iu", out_signature="")
    def SetBrightness(self, value, flags):
        self.calls.append((int(value), int(flags)))
        self.props["Brightness"] = dbus.Int32(value)


class Control(dbus.service.Object):
    IFACE = "org.test.Control"

    def __init__(self, conn, w):
        super().__init__(conn, "/org/test/Control")
        self.w = w

    @dbus.service.method(IFACE, in_signature="b", out_signature="")
    def SetOnBattery(self, b):
        self.w["upower"].update(OnBattery=dbus.Boolean(b))
        self.w["dd"].update(State=dbus.UInt32(2 if b else 1))

    @dbus.service.method(IFACE, in_signature="d", out_signature="")
    def SetPercent(self, p):
        self.w["dd"].update(Percentage=dbus.Double(p))

    @dbus.service.method(IFACE, in_signature="s", out_signature="")
    def OwnerSetProfile(self, p):
        self.w["ppd"].setter("ActiveProfile", p, ":owner")

    @dbus.service.method(IFACE, in_signature="b", out_signature="")
    def Game(self, start):
        gm = self.w["gm"]
        n = int(gm.props["ClientCount"]) + (1 if start else -1)
        gm.props["ClientCount"] = dbus.Int32(n)
        (gm.GameRegistered if start else gm.GameUnregistered)(dbus.Int32(4242), dbus.ObjectPath("/com/feralinteractive/GameMode/Games/4242"))

    @dbus.service.method(IFACE, in_signature="ss", out_signature="")
    def AddUnit(self, name, cgroup):
        self.w["systemd"].add(str(name), str(cgroup))

    @dbus.service.method(IFACE, in_signature="s", out_signature="")
    def RemoveUnit(self, name):
        self.w["systemd"].remove(str(name))

    @dbus.service.method(IFACE, in_signature="b", out_signature="")
    def Sleep(self, going):
        self.w["login"].PrepareForSleep(going)

    @dbus.service.method(IFACE, in_signature="b", out_signature="")
    def Lock(self, locked):
        self.w["login"].session.update(LockedHint=dbus.Boolean(locked))

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def State(self):
        ppd = self.w["ppd"]
        return json.dumps({"active": str(ppd.props["ActiveProfile"]), "base": ppd.base,
                           "holds": [[p, r, a] for p, r, a, _ in ppd.holds.values()], "history": ppd.history,
                           "brightness": int(self.w["br"].display.props["Brightness"]),
                           "brightness_calls": self.w["br"].display.calls})


def main():
    DBusGMainLoop(set_as_default=True)
    sysbus = dbus.bus.BusConnection(sys.argv[1])
    sesbus = dbus.bus.BusConnection(sys.argv[2])
    w = {}
    no_ppd = "--no-ppd" in sys.argv
    names = [dbus.service.BusName(n, sysbus) for n in ("org.freedesktop.UPower", "org.freedesktop.login1")]
    if not no_ppd:
        names.append(dbus.service.BusName("org.freedesktop.UPower.PowerProfiles", sysbus))
    names += [dbus.service.BusName(n, sesbus) for n in ("com.feralinteractive.GameMode", "org.freedesktop.systemd1",
                                                        "org.kde.ScreenBrightness")]
    names.append(dbus.service.BusName("org.test.Control", sysbus if no_ppd else sesbus))
    w["upower"] = PropObject(sysbus, "/org/freedesktop/UPower", "org.freedesktop.UPower",
                             {"OnBattery": dbus.Boolean(False), "LidIsClosed": dbus.Boolean(False)})
    w["dd"] = PropObject(sysbus, "/org/freedesktop/UPower/devices/DisplayDevice", "org.freedesktop.UPower.Device",
                         {"Type": dbus.UInt32(2), "IsPresent": dbus.Boolean(True), "Percentage": dbus.Double(80.0),
                          "State": dbus.UInt32(1)})
    if not no_ppd:
        w["ppd"] = PPD(sysbus)
    w["login"] = Login(sysbus)
    w["gm"] = GameMode(sesbus)
    w["systemd"] = Systemd(sesbus)
    w["br"] = Brightness(sesbus)
    w["ctl"] = Control(sysbus if no_ppd else sesbus, w)
    w["names"] = names
    with open(sys.argv[3], "w") as f:
        f.write("ready\n")
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
