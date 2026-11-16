#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mock system services for shell tests, on a private bus (pass its address in
DBUS_SYSTEM_BUS_ADDRESS): UPower (one laptop battery as the display device), the power-profiles
API (org.freedesktop.UPower.PowerProfiles and net.hadess.PowerProfiles, as tuned-ppd provides)
and BlueZ (one adapter). The machine-independent shape of what the shell reads; values change
through org.kristall.Mock:
    SetBattery(d percentage, u state, b on_battery)   state: 1 charging, 2 discharging, 4 full
    SetAdapterPowered(b)
Run: mocksystem.py <bus address>   (prints "ready" when the names are owned)
"""
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

PROPS = "org.freedesktop.DBus.Properties"


class PropObject(dbus.service.Object):
    def __init__(self, bus, path, iface, props, writable=()):
        super().__init__(bus, path)
        self.iface, self.props, self.writable = iface, props, set(writable)

    def update(self, **changes):
        self.props.update(changes)
        self.PropertiesChanged(self.iface, changes, [])

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.props[name]

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return self.props if iface in (self.iface, "") else {}

    @dbus.service.method(PROPS, in_signature="ssv")
    def Set(self, iface, name, value):
        if name not in self.writable:
            raise dbus.exceptions.DBusException("read-only", name="org.freedesktop.DBus.Error.PropertyReadOnly")
        self.update(**{name: value})

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


class UPower(PropObject):
    def __init__(self, bus):
        super().__init__(bus, "/org/freedesktop/UPower", "org.freedesktop.UPower", {
            "DaemonVersion": "1.90.9", "OnBattery": dbus.Boolean(True), "LidIsClosed": dbus.Boolean(False),
            "LidIsPresent": dbus.Boolean(True)})

    @dbus.service.method("org.freedesktop.UPower", out_signature="ao")
    def EnumerateDevices(self):
        return [dbus.ObjectPath("/org/freedesktop/UPower/devices/battery_BAT0")]

    @dbus.service.method("org.freedesktop.UPower", out_signature="o")
    def GetDisplayDevice(self):
        return dbus.ObjectPath("/org/freedesktop/UPower/devices/DisplayDevice")

    @dbus.service.method("org.freedesktop.UPower", out_signature="s")
    def GetCriticalAction(self):
        return "PowerOff"

    @dbus.service.signal("org.freedesktop.UPower", signature="o")
    def DeviceAdded(self, path):
        pass

    @dbus.service.signal("org.freedesktop.UPower", signature="o")
    def DeviceRemoved(self, path):
        pass


def battery_props(pct, state):
    return {
        "NativePath": "BAT0", "Vendor": "Mock", "Model": "Mock Battery", "Serial": "1", "UpdateTime": dbus.UInt64(0),
        "Type": dbus.UInt32(2), "PowerSupply": dbus.Boolean(True), "HasHistory": dbus.Boolean(False),
        "HasStatistics": dbus.Boolean(False), "Online": dbus.Boolean(False), "Energy": dbus.Double(pct * 0.7),
        "EnergyEmpty": dbus.Double(0), "EnergyFull": dbus.Double(70), "EnergyFullDesign": dbus.Double(75),
        "EnergyRate": dbus.Double(8.5), "Voltage": dbus.Double(15.4), "ChargeCycles": dbus.Int32(120),
        "Luminosity": dbus.Double(0), "TimeToEmpty": dbus.Int64(int(pct * 0.7 / 8.5 * 3600) if state == 2 else 0),
        "TimeToFull": dbus.Int64(3600 if state == 1 else 0), "Percentage": dbus.Double(pct),
        "Temperature": dbus.Double(30), "IsPresent": dbus.Boolean(True), "State": dbus.UInt32(state),
        "IsRechargeable": dbus.Boolean(True), "Capacity": dbus.Double(93), "Technology": dbus.UInt32(1),
        "WarningLevel": dbus.UInt32(1), "BatteryLevel": dbus.UInt32(1), "IconName": "battery-good-symbolic",
    }


class Device(PropObject):
    def __init__(self, bus, path, pct, state):
        super().__init__(bus, path, "org.freedesktop.UPower.Device", battery_props(pct, state))

    @dbus.service.method("org.freedesktop.UPower.Device")
    def Refresh(self):
        pass


PROFILES = dbus.Array([
    dbus.Dictionary({"Profile": "power-saver", "Driver": "tuned", "PlatformDriver": "tuned", "CpuDriver": "tuned"}, signature="sv"),
    dbus.Dictionary({"Profile": "balanced", "Driver": "tuned", "PlatformDriver": "tuned", "CpuDriver": "tuned"}, signature="sv"),
    dbus.Dictionary({"Profile": "performance", "Driver": "tuned", "PlatformDriver": "tuned", "CpuDriver": "tuned"}, signature="sv"),
], signature="a{sv}")


class PowerProfiles(PropObject):
    def __init__(self, bus, path, iface):
        super().__init__(bus, path, iface, {
            "ActiveProfile": "balanced", "PerformanceInhibited": "", "PerformanceDegraded": "",
            "Profiles": PROFILES, "Actions": dbus.Array([], signature="s"),
            "ActiveProfileHolds": dbus.Array([], signature="a{sv}"), "Version": "0.30"}, writable=("ActiveProfile",))


class Adapter(PropObject):
    def __init__(self, bus):
        super().__init__(bus, "/org/bluez/hci0", "org.bluez.Adapter1", {
            "Address": "00:11:22:33:44:55", "AddressType": "public", "Name": "kristall", "Alias": "kristall",
            "Class": dbus.UInt32(0), "Powered": dbus.Boolean(True), "PowerState": "on", "Discoverable": dbus.Boolean(False),
            "DiscoverableTimeout": dbus.UInt32(180), "Pairable": dbus.Boolean(True), "PairableTimeout": dbus.UInt32(0),
            "Discovering": dbus.Boolean(False), "UUIDs": dbus.Array([], signature="s"), "Modalias": "usb:mock"},
            writable=("Powered", "Discoverable", "Pairable", "Alias"))


class BluezRoot(dbus.service.Object):
    def __init__(self, bus, adapter):
        super().__init__(bus, "/")
        self.adapter = adapter

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return {dbus.ObjectPath("/org/bluez/hci0"): {"org.bluez.Adapter1": self.adapter.props}}

    @dbus.service.signal("org.freedesktop.DBus.ObjectManager", signature="oa{sa{sv}}")
    def InterfacesAdded(self, path, ifaces):
        pass

    @dbus.service.signal("org.freedesktop.DBus.ObjectManager", signature="oas")
    def InterfacesRemoved(self, path, ifaces):
        pass


class Control(dbus.service.Object):
    def __init__(self, bus, upower, devices, adapter):
        super().__init__(bus, "/org/kristall/Mock")
        self.upower, self.devices, self.adapter = upower, devices, adapter

    @dbus.service.method("org.kristall.Mock", in_signature="dub")
    def SetBattery(self, pct, state, on_battery):
        for d in self.devices:
            d.update(**{k: v for k, v in battery_props(pct, state).items() if k in ("Percentage", "State", "Energy", "TimeToEmpty", "TimeToFull")})
        self.upower.update(OnBattery=dbus.Boolean(on_battery))

    @dbus.service.method("org.kristall.Mock", in_signature="y")
    def SetWifiStrength(self, strength):
        self.nm[2].update(NM + ".AccessPoint", Strength=dbus.Byte(strength))

    @dbus.service.method("org.kristall.Mock", in_signature="b")
    def SetWifiEnabled(self, on):
        self.nm[0].update(NM, WirelessEnabled=dbus.Boolean(on))

    @dbus.service.method("org.kristall.Mock", in_signature="b")
    def SetAdapterPowered(self, on):
        self.adapter.update(Powered=dbus.Boolean(on), PowerState="on" if on else "off")


class MultiProps(dbus.service.Object):
    """an object with several interfaces' properties: {iface: {name: value}}"""
    def __init__(self, bus, path, ifaces):
        super().__init__(bus, path)
        self.ifaces = ifaces

    def update(self, iface, **changes):
        self.ifaces[iface].update(changes)
        self.PropertiesChanged(iface, changes, [])

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.ifaces[iface][name]

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return self.ifaces.get(iface, {})

    @dbus.service.method(PROPS, in_signature="ssv")
    def Set(self, iface, name, value):
        self.update(iface, **{name: value})

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
DEV = NM_PATH + "/Devices/3"
AP = NM_PATH + "/AccessPoint/1"
AC = NM_PATH + "/ActiveConnection/1"
CON = NM_PATH + "/Settings/1"


class NetworkManager(MultiProps):
    def __init__(self, bus):
        super().__init__(bus, NM_PATH, {NM: {
            "WirelessEnabled": dbus.Boolean(True), "WirelessHardwareEnabled": dbus.Boolean(True),
            "NetworkingEnabled": dbus.Boolean(True), "State": dbus.UInt32(70), "Connectivity": dbus.UInt32(4),
            "Devices": dbus.Array([dbus.ObjectPath(DEV)], signature="o"),
            "AllDevices": dbus.Array([dbus.ObjectPath(DEV)], signature="o"),
            "ActiveConnections": dbus.Array([dbus.ObjectPath(AC)], signature="o"),
            "PrimaryConnection": dbus.ObjectPath(AC), "Metered": dbus.UInt32(4), "Version": "1.54.0"}})

    @dbus.service.method(NM, out_signature="ao")
    def GetDevices(self):
        return [dbus.ObjectPath(DEV)]

    @dbus.service.method(NM, out_signature="ao")
    def GetAllDevices(self):
        return [dbus.ObjectPath(DEV)]

    @dbus.service.signal(NM, signature="o")
    def DeviceAdded(self, path):
        pass

    @dbus.service.signal(NM, signature="o")
    def DeviceRemoved(self, path):
        pass

    @dbus.service.method(NM, out_signature="u")
    def CheckConnectivity(self):
        return 4


class WifiDevice(MultiProps):
    def __init__(self, bus):
        super().__init__(bus, DEV, {
            NM + ".Device": {
                "DeviceType": dbus.UInt32(2), "State": dbus.UInt32(100), "StateReason": dbus.Struct((dbus.UInt32(100), dbus.UInt32(0)), signature="uu"),
                "Interface": "wlp0s20f3", "IpInterface": "wlp0s20f3", "HwAddress": "AA:BB:CC:DD:EE:FF", "Managed": dbus.Boolean(True),
                "Autoconnect": dbus.Boolean(True), "ActiveConnection": dbus.ObjectPath(AC), "Real": dbus.Boolean(True),
                "AvailableConnections": dbus.Array([dbus.ObjectPath(CON)], signature="o")},
            NM + ".Device.Wireless": {
                "HwAddress": "AA:BB:CC:DD:EE:FF", "Mode": dbus.UInt32(2), "Bitrate": dbus.UInt32(866000),
                "AccessPoints": dbus.Array([dbus.ObjectPath(AP)], signature="o"), "ActiveAccessPoint": dbus.ObjectPath(AP),
                "WirelessCapabilities": dbus.UInt32(0), "LastScan": dbus.Int64(0)}})

    @dbus.service.method(NM + ".Device.Wireless", out_signature="ao")
    def GetAccessPoints(self):
        return [dbus.ObjectPath(AP)]

    @dbus.service.method(NM + ".Device.Wireless", out_signature="ao")
    def GetAllAccessPoints(self):
        return [dbus.ObjectPath(AP)]

    @dbus.service.method(NM + ".Device.Wireless", in_signature="a{sv}")
    def RequestScan(self, options):
        pass

    @dbus.service.signal(NM + ".Device.Wireless", signature="o")
    def AccessPointAdded(self, path):
        pass

    @dbus.service.signal(NM + ".Device.Wireless", signature="o")
    def AccessPointRemoved(self, path):
        pass

    @dbus.service.signal(NM + ".Device", signature="uuu")
    def StateChanged(self, new, old, reason):
        pass


def ssid_bytes(name):
    return dbus.Array([dbus.Byte(b) for b in name.encode()], signature="y")


class AccessPoint(MultiProps):
    def __init__(self, bus, ssid, strength):
        super().__init__(bus, AP, {NM + ".AccessPoint": {
            "Ssid": ssid_bytes(ssid), "Strength": dbus.Byte(strength), "Flags": dbus.UInt32(1),
            "WpaFlags": dbus.UInt32(0), "RsnFlags": dbus.UInt32(0x188), "Mode": dbus.UInt32(2),
            "Frequency": dbus.UInt32(5180), "HwAddress": "11:22:33:44:55:66", "MaxBitrate": dbus.UInt32(866000),
            "LastSeen": dbus.Int32(1)}})


class ActiveConnection(MultiProps):
    def __init__(self, bus, ssid):
        super().__init__(bus, AC, {NM + ".Connection.Active": {
            "Connection": dbus.ObjectPath(CON), "SpecificObject": dbus.ObjectPath(AP), "Id": ssid,
            "Uuid": "0b6f1b0e-6a2f-4e44-9d55-5a7b6e2f3c11", "Type": "802-11-wireless",
            "Devices": dbus.Array([dbus.ObjectPath(DEV)], signature="o"), "State": dbus.UInt32(2),
            "StateFlags": dbus.UInt32(0), "Default": dbus.Boolean(True), "Vpn": dbus.Boolean(False)}})


class SettingsRoot(MultiProps):
    def __init__(self, bus):
        super().__init__(bus, NM_PATH + "/Settings", {NM + ".Settings": {
            "Connections": dbus.Array([dbus.ObjectPath(CON)], signature="o"), "Hostname": "kristall", "CanModify": dbus.Boolean(True)}})

    @dbus.service.method(NM + ".Settings", out_signature="ao")
    def ListConnections(self):
        return [dbus.ObjectPath(CON)]


class SettingsConnection(MultiProps):
    def __init__(self, bus, ssid):
        super().__init__(bus, CON, {NM + ".Settings.Connection": {"Unsaved": dbus.Boolean(False), "Flags": dbus.UInt32(0), "Filename": ""}})
        self.ssid = ssid

    @dbus.service.method(NM + ".Settings.Connection", out_signature="a{sa{sv}}")
    def GetSettings(self):
        return {"connection": {"id": self.ssid, "uuid": "0b6f1b0e-6a2f-4e44-9d55-5a7b6e2f3c11", "type": "802-11-wireless"},
                "802-11-wireless": {"ssid": ssid_bytes(self.ssid), "mode": "infrastructure"}}


def main(address):
    DBusGMainLoop(set_as_default=True)
    bus = dbus.bus.BusConnection(address)
    names = [dbus.service.BusName(n, bus) for n in ("org.freedesktop.UPower", "org.freedesktop.UPower.PowerProfiles",
                                                     "net.hadess.PowerProfiles", "org.bluez", "org.kristall.Mock", NM)]
    nm = [NetworkManager(bus), WifiDevice(bus), AccessPoint(bus, "Zuhause", 78), ActiveConnection(bus, "Zuhause"),
          SettingsRoot(bus), SettingsConnection(bus, "Zuhause")]
    upower = UPower(bus)
    devices = [Device(bus, "/org/freedesktop/UPower/devices/DisplayDevice", 76.0, 2),
               Device(bus, "/org/freedesktop/UPower/devices/battery_BAT0", 76.0, 2)]
    pp = [PowerProfiles(bus, "/org/freedesktop/UPower/PowerProfiles", "org.freedesktop.UPower.PowerProfiles"),
          PowerProfiles(bus, "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")]
    adapter = Adapter(bus)
    root = BluezRoot(bus, adapter)
    ctl = Control(bus, upower, devices, adapter)
    keep = (names, pp, root, ctl, nm)  # noqa: F841
    ctl.nm = nm
    print("ready", flush=True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main(sys.argv[1])
