#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mock system services for the Setup Assistant tests, on a private bus: shell-core's mocks
(UPower battery, power profiles, BlueZ — shell/tests/support/mocksystem.py) plus a NetworkManager
that can start *offline* with three networks around and that joins them like the real one:
AddAndActivateConnection, the password "richtig123" is accepted (anything else: the activation
fails with reason 9 = no secrets, as NetworkManager reports a refused key), open networks join.
Run: mocknm.py <bus address> offline|online   (prints "ready")."""
import os
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shell", "tests", "support"))
import mocksystem as ms  # noqa: E402

NM, NM_PATH = ms.NM, ms.NM_PATH
DEV = NM_PATH + "/Devices/3"
NETS = [("Zuhause", 78, True), ("Café Kristall", 55, False), ("Nachbarn", 31, True)]
PASSWORD = "richtig123"


def ap_path(i):
    return f"{NM_PATH}/AccessPoint/{i + 1}"


class AP(ms.MultiProps):
    def __init__(self, bus, i, ssid, strength, secured):
        super().__init__(bus, ap_path(i), {NM + ".AccessPoint": {
            "Ssid": ms.ssid_bytes(ssid), "Strength": dbus.Byte(strength), "Flags": dbus.UInt32(1 if secured else 0),
            "WpaFlags": dbus.UInt32(0), "RsnFlags": dbus.UInt32(0x188 if secured else 0), "Mode": dbus.UInt32(2),
            "Frequency": dbus.UInt32(5180), "HwAddress": f"11:22:33:44:55:6{i}", "MaxBitrate": dbus.UInt32(866000),
            "LastSeen": dbus.Int32(1)}})


class Active(ms.MultiProps):
    def __init__(self, bus, path, con, ap, ssid):
        super().__init__(bus, path, {NM + ".Connection.Active": {
            "Connection": dbus.ObjectPath(con), "SpecificObject": dbus.ObjectPath(ap), "Id": ssid,
            "Uuid": "0b6f1b0e-6a2f-4e44-9d55-5a7b6e2f3c%02d" % (abs(hash(path)) % 100), "Type": "802-11-wireless",
            "Devices": dbus.Array([dbus.ObjectPath(DEV)], signature="o"), "State": dbus.UInt32(1),
            "StateFlags": dbus.UInt32(0), "Default": dbus.Boolean(True), "Vpn": dbus.Boolean(False)}})

    @dbus.service.signal(NM + ".Connection.Active", signature="uu")
    def StateChanged(self, state, reason):
        pass


class Conn(ms.MultiProps):
    def __init__(self, bus, path, ssid, world):
        super().__init__(bus, path, {NM + ".Settings.Connection": {"Unsaved": dbus.Boolean(False), "Flags": dbus.UInt32(0), "Filename": ""}})
        self.ssid, self.world, self.path = ssid, world, path

    @dbus.service.method(NM + ".Settings.Connection", out_signature="a{sa{sv}}")
    def GetSettings(self):
        return {"connection": {"id": self.ssid, "uuid": "1b6f1b0e-6a2f-4e44-9d55-5a7b6e2f3c11", "type": "802-11-wireless"},
                "802-11-wireless": {"ssid": ms.ssid_bytes(self.ssid), "mode": "infrastructure"}}

    @dbus.service.method(NM + ".Settings.Connection")
    def Delete(self):
        self.world.forget(self)


class Manager(ms.NetworkManager):
    def __init__(self, bus, world):
        super().__init__(bus)
        self.world = world

    @dbus.service.method(NM, in_signature="a{sa{sv}}oo", out_signature="oo")
    def AddAndActivateConnection(self, settings, device, specific):
        return self.world.join(settings, specific)

    @dbus.service.method(NM, in_signature="ooo", out_signature="o")
    def ActivateConnection(self, connection, device, specific):
        c = self.world.conns.get(str(connection))
        return self.world.activate(c.ssid if c else NETS[0][0], str(connection), ok=True)


class Wifi(ms.WifiDevice):
    @dbus.service.method(NM + ".Device.Wireless", out_signature="ao")
    def GetAccessPoints(self):
        return [dbus.ObjectPath(ap_path(i)) for i in range(len(NETS))]

    @dbus.service.method(NM + ".Device.Wireless", out_signature="ao")
    def GetAllAccessPoints(self):
        return [dbus.ObjectPath(ap_path(i)) for i in range(len(NETS))]


class Settings(ms.MultiProps):
    def __init__(self, bus, world):
        super().__init__(bus, NM_PATH + "/Settings", {NM + ".Settings": {
            "Connections": dbus.Array([], signature="o"), "Hostname": "kristall", "CanModify": dbus.Boolean(True)}})
        self.world = world

    @dbus.service.method(NM + ".Settings", out_signature="ao")
    def ListConnections(self):
        return [dbus.ObjectPath(p) for p in self.world.conns]

    @dbus.service.signal(NM + ".Settings", signature="o")
    def NewConnection(self, path):
        pass

    @dbus.service.signal(NM + ".Settings", signature="o")
    def ConnectionRemoved(self, path):
        pass


class World:
    def __init__(self, bus, online):
        self.bus = bus
        self.n = 10
        self.conns = {}
        self.actives = {}
        self.nm = Manager(bus, self)
        self.dev = Wifi(bus)
        self.aps = [AP(bus, i, s, st, sec) for i, (s, st, sec) in enumerate(NETS)]
        self.settings = Settings(bus, self)
        self.dev.update(NM + ".Device.Wireless", AccessPoints=dbus.Array([dbus.ObjectPath(ap_path(i)) for i in range(len(NETS))], signature="o"),
                        ActiveAccessPoint=dbus.ObjectPath("/"))
        self.offline()
        if online:
            con = self.add_conn("Zuhause")
            self.activate("Zuhause", con, ok=True, delay=0)

    def offline(self):
        self.nm.update(NM, State=dbus.UInt32(20), Connectivity=dbus.UInt32(1), ActiveConnections=dbus.Array([], signature="o"),
                       PrimaryConnection=dbus.ObjectPath("/"))
        self.dev.update(NM + ".Device", State=dbus.UInt32(30), ActiveConnection=dbus.ObjectPath("/"),
                        AvailableConnections=dbus.Array([], signature="o"))

    def add_conn(self, ssid):
        self.n += 1
        path = f"{NM_PATH}/Settings/{self.n}"
        self.conns[path] = Conn(self.bus, path, ssid, self)
        self.settings.update(NM + ".Settings", Connections=dbus.Array([dbus.ObjectPath(p) for p in self.conns], signature="o"))
        self.settings.NewConnection(dbus.ObjectPath(path))
        return path

    def forget(self, conn):
        self.conns.pop(conn.path, None)
        conn.remove_from_connection()
        self.settings.update(NM + ".Settings", Connections=dbus.Array([dbus.ObjectPath(p) for p in self.conns], signature="o"))
        self.settings.ConnectionRemoved(dbus.ObjectPath(conn.path))

    def join(self, settings, specific):
        ssid = bytes(settings.get("802-11-wireless", {}).get("ssid", b"")).decode() if "802-11-wireless" in settings else ""
        if not ssid and str(specific) not in ("/", ""):
            i = int(str(specific).rsplit("/", 1)[1]) - 1
            ssid = NETS[i][0]
        net = next((x for x in NETS if x[0] == ssid), None)
        psk = str(settings.get("802-11-wireless-security", {}).get("psk", ""))
        ok = net is not None and (not net[2] or psk == PASSWORD)
        con = self.add_conn(ssid or "?")
        return dbus.ObjectPath(con), dbus.ObjectPath(self.activate(ssid, con, ok))

    def activate(self, ssid, con, ok, delay=800):
        self.n += 1
        path = f"{NM_PATH}/ActiveConnection/{self.n}"
        i = next((k for k, x in enumerate(NETS) if x[0] == ssid), 0)
        a = Active(self.bus, path, con, ap_path(i), ssid)
        self.actives[path] = a

        def finish():
            if ok:
                a.update(NM + ".Connection.Active", State=dbus.UInt32(2))
                a.StateChanged(dbus.UInt32(2), dbus.UInt32(0))
                self.nm.update(NM, State=dbus.UInt32(70), Connectivity=dbus.UInt32(4),
                               ActiveConnections=dbus.Array([dbus.ObjectPath(path)], signature="o"), PrimaryConnection=dbus.ObjectPath(path))
                self.dev.update(NM + ".Device", State=dbus.UInt32(100), ActiveConnection=dbus.ObjectPath(path),
                                AvailableConnections=dbus.Array([dbus.ObjectPath(con)], signature="o"))
                self.dev.update(NM + ".Device.Wireless", ActiveAccessPoint=dbus.ObjectPath(ap_path(i)))
                self.dev.StateChanged(dbus.UInt32(100), dbus.UInt32(30), dbus.UInt32(0))
            else:
                a.update(NM + ".Connection.Active", State=dbus.UInt32(4))
                a.StateChanged(dbus.UInt32(4), dbus.UInt32(9))
            return False
        if delay:
            GLib.timeout_add(delay, finish)
        else:
            finish()
        return path


def main(address, mode):
    DBusGMainLoop(set_as_default=True)
    bus = dbus.bus.BusConnection(address)
    names = [dbus.service.BusName(n, bus) for n in ("org.freedesktop.UPower", "org.freedesktop.UPower.PowerProfiles",
                                                     "net.hadess.PowerProfiles", "org.bluez", "org.kristall.Mock", NM)]
    world = World(bus, mode == "online")
    upower = ms.UPower(bus)
    devices = [ms.Device(bus, "/org/freedesktop/UPower/devices/DisplayDevice", 76.0, 2),
               ms.Device(bus, "/org/freedesktop/UPower/devices/battery_BAT0", 76.0, 2)]
    pp = [ms.PowerProfiles(bus, "/org/freedesktop/UPower/PowerProfiles", "org.freedesktop.UPower.PowerProfiles"),
          ms.PowerProfiles(bus, "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")]
    adapter = ms.Adapter(bus)
    root = ms.BluezRoot(bus, adapter)
    ctl = ms.Control(bus, upower, devices, adapter)
    keep = (names, world, pp, root, ctl)  # noqa: F841
    print("ready", flush=True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "offline")
