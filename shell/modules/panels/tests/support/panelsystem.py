#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mock system services for the panels tests, on a private bus (pass its address; the shell gets
it as DBUS_SYSTEM_BUS_ADDRESS). Builds on shell-core's mocksystem.py (UPower, power profiles)
and replaces its NetworkManager and BlueZ with richer ones:

  NetworkManager: one Wi-Fi device with four access points — "Zuhause" (known, connected),
    "Büro" (known, WPA2), "Café Sonne" (open), "Nachbar" (WPA2, unknown). ActivateConnection,
    AddAndActivateConnection (the password "richtig123" works, anything else fails with
    NO_SECRETS like a refused key), DeactivateConnection, Settings.Connection.Delete.
  BlueZ: an adapter with "AirPods Kristall" (paired, connected, battery 80 %) and "Maus" (paired).

Options: --no-wifi (NetworkManager without a Wi-Fi device), --no-bluetooth, --no-battery.
Control (org.kristall.Mock on the same bus): SetBattery(d,u,b), SetWifiEnabled(b),
SetAdapterPowered(b), SetDeviceConnected(s name, b), SetApStrength(s ssid, y), Calls() -> s (JSON).
Prints "ready" when the names are owned.
"""
import json
import os
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "tests", "support"))
import mocksystem as core  # noqa: E402  shell-core's mock (UPower, power profiles, PropObject)

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
PROPS = "org.freedesktop.DBus.Properties"
DEV = NM_PATH + "/Devices/3"
CALLS = []


def ssid_bytes(name):
    return dbus.Array([dbus.Byte(b) for b in name.encode()], signature="y")


class Multi(dbus.service.Object):
    """an object with several interfaces' properties"""
    def __init__(self, bus, path, ifaces):
        super().__init__(bus, path)
        self.path = path
        self.ifaces = ifaces

    def update(self, iface, **changes):
        self.ifaces[iface].update(changes)
        self.PropertiesChanged(iface, changes, dbus.Array([], signature="s"))

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.ifaces[iface][name]

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary(self.ifaces.get(iface, {}), signature="sv")

    @dbus.service.method(PROPS, in_signature="ssv")
    def Set(self, iface, name, value):
        CALLS.append({"set": name, "value": str(value)})
        self.update(iface, **{name: value})

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


class AccessPoint(Multi):
    def __init__(self, bus, n, ssid, strength, secured):
        super().__init__(bus, f"{NM_PATH}/AccessPoint/{n}", {NM + ".AccessPoint": {
            "Ssid": ssid_bytes(ssid), "Strength": dbus.Byte(strength), "Flags": dbus.UInt32(1 if secured else 0),
            "WpaFlags": dbus.UInt32(0), "RsnFlags": dbus.UInt32(0x188 if secured else 0), "Mode": dbus.UInt32(2),
            "Frequency": dbus.UInt32(5180), "HwAddress": f"11:22:33:44:55:{n:02x}", "MaxBitrate": dbus.UInt32(866000),
            "LastSeen": dbus.Int32(1)}})
        self.ssid = ssid


class SettingsConnection(Multi):
    def __init__(self, bus, n, ssid, mgr, secured=True):
        super().__init__(bus, f"{NM_PATH}/Settings/{n}", {NM + ".Settings.Connection": {
            "Unsaved": dbus.Boolean(False), "Flags": dbus.UInt32(0), "Filename": ""}})
        self.ssid, self.mgr, self.n, self.secured = ssid, mgr, n, secured

    @dbus.service.method(NM + ".Settings.Connection", out_signature="a{sa{sv}}")
    def GetSettings(self):
        s = {"connection": {"id": self.ssid, "uuid": f"0b6f1b0e-6a2f-4e44-9d55-5a7b6e2f3c{self.n:02d}", "type": "802-11-wireless"},
             "802-11-wireless": {"ssid": ssid_bytes(self.ssid), "mode": "infrastructure"}}
        if self.secured:
            s["802-11-wireless"]["security"] = "802-11-wireless-security"
            s["802-11-wireless-security"] = {"key-mgmt": "wpa-psk"}
        return s

    @dbus.service.method(NM + ".Settings.Connection")
    def Delete(self):
        CALLS.append({"method": "Delete", "ssid": self.ssid})
        self.mgr.forget(self)

    @dbus.service.signal(NM + ".Settings.Connection")
    def Removed(self):
        pass

    @dbus.service.signal(NM + ".Settings.Connection")
    def Updated(self):
        pass


class ActiveConnection(Multi):
    def __init__(self, bus, n, con, ap, state):
        super().__init__(bus, f"{NM_PATH}/ActiveConnection/{n}", {NM + ".Connection.Active": {
            "Connection": dbus.ObjectPath(con.path), "SpecificObject": dbus.ObjectPath(ap.path), "Id": con.ssid,
            "Uuid": f"aa6f1b0e-6a2f-4e44-9d55-5a7b6e2f3c{n:02d}", "Type": "802-11-wireless",
            "Devices": dbus.Array([dbus.ObjectPath(DEV)], signature="o"), "State": dbus.UInt32(state),
            "StateFlags": dbus.UInt32(0), "Default": dbus.Boolean(True), "Vpn": dbus.Boolean(False)}})

    def set_state(self, state, reason):
        self.update(NM + ".Connection.Active", State=dbus.UInt32(state))
        self.StateChanged(dbus.UInt32(state), dbus.UInt32(reason))

    @dbus.service.signal(NM + ".Connection.Active", signature="uu")
    def StateChanged(self, state, reason):
        pass


class WifiDevice(Multi):
    def __init__(self, bus):
        super().__init__(bus, DEV, {
            NM + ".Device": {
                "DeviceType": dbus.UInt32(2), "State": dbus.UInt32(100),
                "StateReason": dbus.Struct((dbus.UInt32(100), dbus.UInt32(0)), signature="uu"),
                "Interface": "wlp0s20f3", "IpInterface": "wlp0s20f3", "HwAddress": "AA:BB:CC:DD:EE:FF", "Managed": dbus.Boolean(True),
                "Autoconnect": dbus.Boolean(True), "ActiveConnection": dbus.ObjectPath("/"), "Real": dbus.Boolean(True),
                "AvailableConnections": dbus.Array([], signature="o")},
            NM + ".Device.Wireless": {
                "HwAddress": "AA:BB:CC:DD:EE:FF", "Mode": dbus.UInt32(2), "Bitrate": dbus.UInt32(866000),
                "AccessPoints": dbus.Array([], signature="o"), "ActiveAccessPoint": dbus.ObjectPath("/"),
                "WirelessCapabilities": dbus.UInt32(0), "LastScan": dbus.Int64(0)}})
        self.aps = []

    @dbus.service.method(NM + ".Device.Wireless", out_signature="ao")
    def GetAccessPoints(self):
        return [dbus.ObjectPath(a.path) for a in self.aps]

    @dbus.service.method(NM + ".Device.Wireless", out_signature="ao")
    def GetAllAccessPoints(self):
        return [dbus.ObjectPath(a.path) for a in self.aps]

    @dbus.service.method(NM + ".Device.Wireless", in_signature="a{sv}")
    def RequestScan(self, options):
        CALLS.append({"method": "RequestScan"})
        # a scan finds the same access points again (NetworkManager bumps LastScan)
        self.update(NM + ".Device.Wireless", LastScan=dbus.Int64(int(GLib.get_monotonic_time() / 1000)),
                    AccessPoints=dbus.Array([dbus.ObjectPath(a.path) for a in self.aps], signature="o"))

    @dbus.service.method(NM + ".Device")
    def Disconnect(self):
        CALLS.append({"method": "Disconnect"})
        self.mgr.deactivate_current()

    @dbus.service.signal(NM + ".Device.Wireless", signature="o")
    def AccessPointAdded(self, path):
        pass

    @dbus.service.signal(NM + ".Device.Wireless", signature="o")
    def AccessPointRemoved(self, path):
        pass

    @dbus.service.signal(NM + ".Device", signature="uuu")
    def StateChanged(self, new, old, reason):
        pass


class SettingsRoot(Multi):
    def __init__(self, bus, mgr):
        super().__init__(bus, NM_PATH + "/Settings", {NM + ".Settings": {
            "Connections": dbus.Array([], signature="o"), "Hostname": "kristall", "CanModify": dbus.Boolean(True)}})
        self.mgr = mgr

    @dbus.service.method(NM + ".Settings", out_signature="ao")
    def ListConnections(self):
        return [dbus.ObjectPath(c.path) for c in self.mgr.cons]

    @dbus.service.signal(NM + ".Settings", signature="o")
    def NewConnection(self, path):
        pass

    @dbus.service.signal(NM + ".Settings", signature="o")
    def ConnectionRemoved(self, path):
        pass


class NetworkManager(Multi):
    def __init__(self, bus, wifi=True):
        super().__init__(bus, NM_PATH, {NM: {
            "WirelessEnabled": dbus.Boolean(True), "WirelessHardwareEnabled": dbus.Boolean(True),
            "NetworkingEnabled": dbus.Boolean(True), "State": dbus.UInt32(70), "Connectivity": dbus.UInt32(4),
            "Devices": dbus.Array([], signature="o"), "AllDevices": dbus.Array([], signature="o"),
            "ActiveConnections": dbus.Array([], signature="o"), "PrimaryConnection": dbus.ObjectPath("/"),
            "Metered": dbus.UInt32(4), "Version": "1.54.0"}})
        self.bus = bus
        self.cons, self.actives = [], []
        self.n_con = self.n_act = 0
        self.settings = SettingsRoot(bus, self)
        self.dev = None
        if wifi:
            self.dev = WifiDevice(bus)
            self.dev.mgr = self
            self.update(NM, Devices=dbus.Array([dbus.ObjectPath(DEV)], signature="o"), AllDevices=dbus.Array([dbus.ObjectPath(DEV)], signature="o"))
            for i, (ssid, strength, sec) in enumerate((("Zuhause", 78, True), ("Büro", 52, True), ("Café Sonne", 40, False), ("Nachbar", 22, True))):
                self.dev.aps.append(AccessPoint(bus, i + 1, ssid, strength, sec))
            self.dev.update(NM + ".Device.Wireless", AccessPoints=dbus.Array([dbus.ObjectPath(a.path) for a in self.dev.aps], signature="o"))
            for ssid in ("Zuhause", "Büro"):
                self.add_con(ssid)
            self.activate(self.cons[0], self.ap("Zuhause"), instant=True)

    def ap(self, ssid):
        return next((a for a in self.dev.aps if a.ssid == ssid), None)

    def add_con(self, ssid):
        self.n_con += 1
        ap = self.ap(ssid)
        c = SettingsConnection(self.bus, self.n_con, ssid, self, secured=bool(ap and int(ap.ifaces[NM + ".AccessPoint"]["RsnFlags"])))
        self.cons.append(c)
        paths = dbus.Array([dbus.ObjectPath(x.path) for x in self.cons], signature="o")
        self.settings.update(NM + ".Settings", Connections=paths)
        self.dev.update(NM + ".Device", AvailableConnections=paths)
        self.settings.NewConnection(dbus.ObjectPath(c.path))
        return c

    def forget(self, c):
        if c in self.cons:
            self.cons.remove(c)
        paths = dbus.Array([dbus.ObjectPath(x.path) for x in self.cons], signature="o")
        self.settings.update(NM + ".Settings", Connections=paths)
        self.dev.update(NM + ".Device", AvailableConnections=paths)
        c.Removed()
        self.settings.ConnectionRemoved(dbus.ObjectPath(c.path))
        c.remove_from_connection()

    def deactivate_current(self):
        for a in list(self.actives):
            a.set_state(4, 2)
            self.actives.remove(a)
        self.update(NM, ActiveConnections=dbus.Array([], signature="o"), PrimaryConnection=dbus.ObjectPath("/"))
        self.dev.update(NM + ".Device", ActiveConnection=dbus.ObjectPath("/"), State=dbus.UInt32(30))
        self.dev.update(NM + ".Device.Wireless", ActiveAccessPoint=dbus.ObjectPath("/"))
        self.dev.StateChanged(dbus.UInt32(30), dbus.UInt32(100), dbus.UInt32(39))

    def activate(self, con, ap, instant=False, fail=False):
        if self.actives:
            self.deactivate_current()
        self.n_act += 1
        a = ActiveConnection(self.bus, self.n_act, con, ap, 2 if instant else 1)
        self.actives.append(a)
        self.update(NM, ActiveConnections=dbus.Array([dbus.ObjectPath(a.path)], signature="o"))
        self.dev.update(NM + ".Device", ActiveConnection=dbus.ObjectPath(a.path), State=dbus.UInt32(100 if instant else 40))

        def finish():
            if fail:
                a.set_state(4, 9)          # NO_SECRETS: the key was refused
                self.actives.remove(a)
                self.update(NM, ActiveConnections=dbus.Array([], signature="o"))
                self.dev.update(NM + ".Device", ActiveConnection=dbus.ObjectPath("/"), State=dbus.UInt32(30))
                self.dev.StateChanged(dbus.UInt32(30), dbus.UInt32(60), dbus.UInt32(7))
            else:
                a.set_state(2, 0)
                self.update(NM, PrimaryConnection=dbus.ObjectPath(a.path))
                self.dev.update(NM + ".Device", State=dbus.UInt32(100))
                self.dev.update(NM + ".Device.Wireless", ActiveAccessPoint=dbus.ObjectPath(ap.path))
                self.dev.StateChanged(dbus.UInt32(100), dbus.UInt32(70), dbus.UInt32(0))
            return False
        if instant:
            self.dev.update(NM + ".Device.Wireless", ActiveAccessPoint=dbus.ObjectPath(ap.path))
        else:
            GLib.timeout_add(400, finish)
        return a

    @dbus.service.method(NM, out_signature="ao")
    def GetDevices(self):
        return [dbus.ObjectPath(DEV)] if self.dev else []

    @dbus.service.method(NM, out_signature="ao")
    def GetAllDevices(self):
        return [dbus.ObjectPath(DEV)] if self.dev else []

    @dbus.service.method(NM, in_signature="ooo", out_signature="o")
    def ActivateConnection(self, con, dev, specific):
        c = next((x for x in self.cons if x.path == str(con)), None)
        CALLS.append({"method": "ActivateConnection", "ssid": c.ssid if c else str(con)})
        if not c:
            raise dbus.exceptions.DBusException("unknown connection", name=NM + ".Error.UnknownConnection")
        a = self.activate(c, self.ap(c.ssid))
        return dbus.ObjectPath(a.path)

    @dbus.service.method(NM, in_signature="a{sa{sv}}oo", out_signature="oo")
    def AddAndActivateConnection(self, settings, dev, specific):
        wifi = settings.get("802-11-wireless", {})
        ssid = bytes(wifi.get("ssid", b"")).decode() if wifi.get("ssid") else ""
        if not ssid and str(specific) != "/":
            ap = next((a for a in self.dev.aps if a.path == str(specific)), None)
            ssid = ap.ssid if ap else ""
        sec = settings.get("802-11-wireless-security", {})
        psk = str(sec.get("psk", ""))
        perms = [str(p) for p in settings.get("connection", {}).get("permissions", [])]
        CALLS.append({"method": "AddAndActivateConnection", "ssid": ssid, "keyMgmt": str(sec.get("key-mgmt", "")),
                      "pskGiven": bool(psk), "permissions": perms})
        ap = self.ap(ssid)
        if not ap:
            raise dbus.exceptions.DBusException("no such network", name=NM + ".Error.UnknownDevice")
        secured = int(ap.ifaces[NM + ".AccessPoint"]["RsnFlags"]) != 0
        c = self.add_con(ssid)
        a = self.activate(c, ap, fail=secured and psk != "richtig123")
        return dbus.ObjectPath(c.path), dbus.ObjectPath(a.path)

    @dbus.service.method(NM, in_signature="o")
    def DeactivateConnection(self, active):
        CALLS.append({"method": "DeactivateConnection"})
        self.deactivate_current()

    @dbus.service.method(NM, out_signature="u")
    def CheckConnectivity(self):
        return 4

    @dbus.service.signal(NM, signature="o")
    def DeviceAdded(self, path):
        pass

    @dbus.service.signal(NM, signature="o")
    def DeviceRemoved(self, path):
        pass


class BtDevice(Multi):
    def __init__(self, bus, n, name, icon, connected, battery=None):
        ifaces = {"org.bluez.Device1": {
            "Address": f"00:1A:7D:DA:71:{n:02X}", "AddressType": "public", "Name": name, "Alias": name, "Icon": icon,
            "Class": dbus.UInt32(0x240404 if "audio" in icon else 0x2580), "Paired": dbus.Boolean(True), "Bonded": dbus.Boolean(True),
            "Trusted": dbus.Boolean(True), "Blocked": dbus.Boolean(False), "LegacyPairing": dbus.Boolean(False),
            "Connected": dbus.Boolean(connected), "UUIDs": dbus.Array([], signature="s"), "Adapter": dbus.ObjectPath("/org/bluez/hci0"),
            "ServicesResolved": dbus.Boolean(connected), "WakeAllowed": dbus.Boolean(False)}}
        if battery is not None:
            ifaces["org.bluez.Battery1"] = {"Percentage": dbus.Byte(battery), "Source": "mock"}
        super().__init__(bus, f"/org/bluez/hci0/dev_00_1A_7D_DA_71_{n:02X}", ifaces)
        self.name = name

    @dbus.service.method("org.bluez.Device1")
    def Connect(self):
        CALLS.append({"method": "bt.Connect", "name": self.name})
        GLib.timeout_add(200, lambda: (self.update("org.bluez.Device1", Connected=dbus.Boolean(True), ServicesResolved=dbus.Boolean(True)), False)[1])

    @dbus.service.method("org.bluez.Device1")
    def Disconnect(self):
        CALLS.append({"method": "bt.Disconnect", "name": self.name})
        self.update("org.bluez.Device1", Connected=dbus.Boolean(False), ServicesResolved=dbus.Boolean(False))


class BluezRoot(dbus.service.Object):
    def __init__(self, bus, adapter, devices):
        super().__init__(bus, "/")
        self.adapter, self.devices = adapter, devices

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        out = {dbus.ObjectPath("/org/bluez/hci0"): {"org.bluez.Adapter1": self.adapter.props}}
        for d in self.devices:
            out[dbus.ObjectPath(d.path)] = d.ifaces
        return out

    @dbus.service.signal("org.freedesktop.DBus.ObjectManager", signature="oa{sa{sv}}")
    def InterfacesAdded(self, path, ifaces):
        pass

    @dbus.service.signal("org.freedesktop.DBus.ObjectManager", signature="oas")
    def InterfacesRemoved(self, path, ifaces):
        pass


class DesktopUPower(core.UPower):
    """UPower on a desktop: no battery devices"""
    @dbus.service.method("org.freedesktop.UPower", out_signature="ao")
    def EnumerateDevices(self):
        return dbus.Array([], signature="o")


class Control(dbus.service.Object):
    def __init__(self, bus, upower, batteries, adapter, nm, devices):
        super().__init__(bus, "/org/kristall/Mock")
        self.upower, self.batteries, self.adapter, self.nm, self.devices = upower, batteries, adapter, nm, devices

    @dbus.service.method("org.kristall.Mock", in_signature="dub")
    def SetBattery(self, pct, state, on_battery):
        for d in self.batteries:
            d.update(**{k: v for k, v in core.battery_props(pct, state).items() if k in ("Percentage", "State", "Energy", "TimeToEmpty", "TimeToFull")})
        self.upower.update(OnBattery=dbus.Boolean(on_battery))

    @dbus.service.method("org.kristall.Mock", in_signature="b")
    def SetWifiEnabled(self, on):
        self.nm.update(NM, WirelessEnabled=dbus.Boolean(on))

    @dbus.service.method("org.kristall.Mock", in_signature="sy")
    def SetApStrength(self, ssid, strength):
        self.nm.ap(ssid).update(NM + ".AccessPoint", Strength=dbus.Byte(strength))

    @dbus.service.method("org.kristall.Mock", in_signature="b")
    def SetAdapterPowered(self, on):
        if self.adapter:
            self.adapter.update(Powered=dbus.Boolean(on), PowerState="on" if on else "off")

    @dbus.service.method("org.kristall.Mock", in_signature="sb")
    def SetDeviceConnected(self, name, on):
        for d in self.devices:
            if d.name == name:
                d.update("org.bluez.Device1", Connected=dbus.Boolean(on), ServicesResolved=dbus.Boolean(on))

    @dbus.service.method("org.kristall.Mock", out_signature="s")
    def Calls(self):
        out = json.dumps(CALLS)
        CALLS.clear()
        return out


def main(address, opts):
    DBusGMainLoop(set_as_default=True)
    bus = dbus.bus.BusConnection(address)
    names = ["org.freedesktop.UPower", "org.freedesktop.UPower.PowerProfiles", "net.hadess.PowerProfiles", "org.kristall.Mock", NM]
    if "--no-bluetooth" not in opts:
        names.append("org.bluez")
    keep = [dbus.service.BusName(n, bus) for n in names]
    nm = NetworkManager(bus, wifi="--no-wifi" not in opts)
    upower = DesktopUPower(bus) if "--no-battery" in opts else core.UPower(bus)
    batteries = []
    if "--no-battery" in opts:
        # a desktop: the display device is not a battery
        d = core.Device(bus, "/org/freedesktop/UPower/devices/DisplayDevice", 0.0, 0)
        d.props.update(Type=dbus.UInt32(0), IsPresent=dbus.Boolean(False), PowerSupply=dbus.Boolean(False))
        upower.props["OnBattery"] = dbus.Boolean(False)
        batteries = [d]
    else:
        batteries = [core.Device(bus, "/org/freedesktop/UPower/devices/DisplayDevice", 76.0, 2),
                     core.Device(bus, "/org/freedesktop/UPower/devices/battery_BAT0", 76.0, 2)]
    pp = [core.PowerProfiles(bus, "/org/freedesktop/UPower/PowerProfiles", "org.freedesktop.UPower.PowerProfiles"),
          core.PowerProfiles(bus, "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")]
    adapter, devices, root = None, [], None
    if "--no-bluetooth" not in opts:
        adapter = core.Adapter(bus)
        devices = [BtDevice(bus, 1, "AirPods Kristall", "audio-headphones", True, 80), BtDevice(bus, 2, "Maus", "input-mouse", False)]
        root = BluezRoot(bus, adapter, devices)
    ctl = Control(bus, upower, batteries, adapter, nm, devices)
    keep += [pp, root, ctl, nm, upower, batteries]
    print("ready", flush=True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
