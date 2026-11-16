#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mock session-bus services for the panels tests (run on the session bus of the test):

  org.kde.ScreenBrightness            one internal display "display0" (max 10000), like PowerDevil 6.8
  org.kde.Solid.PowerManagement       …/Actions/KeyboardBrightnessControl (max 3)
  org.freedesktop.ScreenSaver         GetActive / ActiveChanged (the screen locker)
  org.mpris.MediaPlayer2.kristallmock a music player (with --media)

Options: --no-backlight, --no-kbd, --media, --art PATH.
Control (org.kristall.MockSession /org/kristall/MockSession): SetBrightness(i) and SetKbd(i) as
if changed elsewhere (keys, another app), SetLocked(b), SetPlaying(b), Osd(s icon, i percent) /
OsdText(s icon, s text) emit org.kde.osdService signals as plasmashell does, Calls() -> s JSON.
Prints "ready" when the names are owned.
"""
import json
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

PROPS = "org.freedesktop.DBus.Properties"
CALLS = []


class Props(dbus.service.Object):
    def __init__(self, bus, path, ifaces):
        super().__init__(bus, path)
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
        if hasattr(self, "on_set"):
            self.on_set(name, value)

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


SB = "org.kde.ScreenBrightness"


class Brightness(Props):
    def __init__(self, bus):
        super().__init__(bus, "/org/kde/ScreenBrightness", {SB: {"DisplaysDBusNames": dbus.Array(["display0"], signature="s")}})

    @dbus.service.signal(SB, signature="siss")
    def BrightnessChanged(self, display, value, client, context):
        pass

    @dbus.service.signal(SB, signature="sii")
    def BrightnessRangeChanged(self, display, mx, value):
        pass


class Display(Props):
    def __init__(self, bus, root):
        super().__init__(bus, "/org/kde/ScreenBrightness/display0", {SB + ".Display": {
            "Label": "Eingebauter Bildschirm", "IsInternal": dbus.Boolean(True), "MaxBrightness": dbus.Int32(10000),
            "Brightness": dbus.Int32(6000)}})
        self.root = root

    def set_value(self, value, client):
        self.ifaces[SB + ".Display"]["Brightness"] = dbus.Int32(value)
        self.root.BrightnessChanged("display0", dbus.Int32(value), client, "")

    @dbus.service.method(SB + ".Display", in_signature="iu")
    def SetBrightness(self, value, flags):
        CALLS.append({"method": "SetBrightness", "value": int(value), "flags": int(flags)})
        self.set_value(int(value), "kristall")


KBD = "org.kde.Solid.PowerManagement.Actions.KeyboardBrightnessControl"


class Keyboard(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, "/org/kde/Solid/PowerManagement/Actions/KeyboardBrightnessControl")
        self.value, self.max = 1, 3

    @dbus.service.method(KBD, out_signature="i")
    def keyboardBrightness(self):
        return self.value

    @dbus.service.method(KBD, out_signature="i")
    def keyboardBrightnessMax(self):
        return self.max

    @dbus.service.method(KBD, out_signature="i")
    def keyboardBrightnessSteps(self):
        return self.max

    @dbus.service.method(KBD, in_signature="i")
    def setKeyboardBrightness(self, v):
        CALLS.append({"method": "setKeyboardBrightness", "value": int(v)})
        self.value = int(v)
        self.keyboardBrightnessChanged(self.value)

    @dbus.service.method(KBD, in_signature="i")
    def setKeyboardBrightnessSilent(self, v):
        CALLS.append({"method": "setKeyboardBrightnessSilent", "value": int(v)})
        self.value = int(v)
        self.keyboardBrightnessChanged(self.value)

    @dbus.service.signal(KBD, signature="i")
    def keyboardBrightnessChanged(self, v):
        pass

    @dbus.service.signal(KBD, signature="i")
    def keyboardBrightnessMaxChanged(self, v):
        pass


class PmRoot(dbus.service.Object):
    """org.kde.Solid.PowerManagement exists even on machines without a keyboard backlight"""
    def __init__(self, bus):
        super().__init__(bus, "/org/kde/Solid/PowerManagement")


class ScreenSaver(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, "/ScreenSaver")
        self.active = False

    @dbus.service.method("org.freedesktop.ScreenSaver", out_signature="b")
    def GetActive(self):
        return self.active

    @dbus.service.signal("org.freedesktop.ScreenSaver", signature="b")
    def ActiveChanged(self, on):
        pass


MP = "org.mpris.MediaPlayer2"


class Player(Props):
    def __init__(self, bus, art):
        meta = dbus.Dictionary({
            "mpris:trackid": dbus.ObjectPath("/org/kristall/track/1"), "xesam:title": "Morgenlicht",
            "xesam:artist": dbus.Array(["Die Kristalle"], signature="s"), "xesam:album": "Klare Tage",
            "mpris:length": dbus.Int64(214 * 1000000)}, signature="sv")
        if art:
            meta["mpris:artUrl"] = "file://" + art
        super().__init__(bus, "/org/mpris/MediaPlayer2", {
            MP: {"Identity": "Musik", "DesktopEntry": "org.kde.elisa", "CanQuit": dbus.Boolean(False), "CanRaise": dbus.Boolean(True),
                 "HasTrackList": dbus.Boolean(False), "SupportedUriSchemes": dbus.Array([], signature="s"),
                 "SupportedMimeTypes": dbus.Array([], signature="s"), "CanSetFullscreen": dbus.Boolean(False), "Fullscreen": dbus.Boolean(False)},
            MP + ".Player": {"PlaybackStatus": "Playing", "LoopStatus": "None", "Rate": 1.0, "Shuffle": dbus.Boolean(False),
                             "Metadata": meta, "Volume": 1.0, "Position": dbus.Int64(42 * 1000000), "MinimumRate": 1.0, "MaximumRate": 1.0,
                             "CanGoNext": dbus.Boolean(True), "CanGoPrevious": dbus.Boolean(True), "CanPlay": dbus.Boolean(True),
                             "CanPause": dbus.Boolean(True), "CanSeek": dbus.Boolean(True), "CanControl": dbus.Boolean(True)}})
        self.track = 1

    def playing(self, on):
        self.update(MP + ".Player", PlaybackStatus="Playing" if on else "Paused")

    @dbus.service.method(MP)
    def Raise(self):
        CALLS.append({"method": "Raise"})

    @dbus.service.method(MP)
    def Quit(self):
        pass

    @dbus.service.method(MP + ".Player")
    def PlayPause(self):
        CALLS.append({"method": "PlayPause"})
        self.playing(self.ifaces[MP + ".Player"]["PlaybackStatus"] != "Playing")

    @dbus.service.method(MP + ".Player")
    def Play(self):
        CALLS.append({"method": "Play"})
        self.playing(True)

    @dbus.service.method(MP + ".Player")
    def Pause(self):
        CALLS.append({"method": "Pause"})
        self.playing(False)

    @dbus.service.method(MP + ".Player")
    def Stop(self):
        self.playing(False)

    @dbus.service.method(MP + ".Player")
    def Next(self):
        CALLS.append({"method": "Next"})
        self.track += 1
        meta = dict(self.ifaces[MP + ".Player"]["Metadata"])
        meta["mpris:trackid"] = dbus.ObjectPath(f"/org/kristall/track/{self.track}")
        meta["xesam:title"] = "Abendrot"
        self.update(MP + ".Player", Metadata=dbus.Dictionary(meta, signature="sv"), Position=dbus.Int64(0))

    @dbus.service.method(MP + ".Player")
    def Previous(self):
        CALLS.append({"method": "Previous"})

    @dbus.service.method(MP + ".Player", in_signature="x")
    def Seek(self, offset):
        pass

    @dbus.service.method(MP + ".Player", in_signature="ox")
    def SetPosition(self, track, pos):
        CALLS.append({"method": "SetPosition", "pos": int(pos)})
        self.ifaces[MP + ".Player"]["Position"] = dbus.Int64(pos)
        self.Seeked(dbus.Int64(pos))

    @dbus.service.signal(MP + ".Player", signature="x")
    def Seeked(self, pos):
        pass


class Osd(dbus.service.Object):
    """stands in for plasmashell's /org/kde/osdService signals (in tests without plasmashell)"""
    def __init__(self, bus):
        super().__init__(bus, "/org/kde/osdService")

    @dbus.service.signal("org.kde.osdService", signature="siis")
    def osdProgress(self, icon, percent, maximum, text):
        pass

    @dbus.service.signal("org.kde.osdService", signature="ss")
    def osdText(self, icon, text):
        pass


class Control(dbus.service.Object):
    def __init__(self, bus, display, kbd, ss, player, osd):
        super().__init__(bus, "/org/kristall/MockSession")
        self.display, self.kbd, self.ss, self.player, self.osd = display, kbd, ss, player, osd

    @dbus.service.method("org.kristall.MockSession", in_signature="i")
    def SetBrightness(self, v):
        if self.display:
            self.display.set_value(int(v), "powerdevil")

    @dbus.service.method("org.kristall.MockSession", in_signature="i")
    def SetKbd(self, v):
        if self.kbd:
            self.kbd.value = int(v)
            self.kbd.keyboardBrightnessChanged(int(v))

    @dbus.service.method("org.kristall.MockSession", in_signature="b")
    def SetLocked(self, on):
        self.ss.active = bool(on)
        self.ss.ActiveChanged(bool(on))

    @dbus.service.method("org.kristall.MockSession", in_signature="b")
    def SetPlaying(self, on):
        if self.player:
            self.player.playing(bool(on))

    @dbus.service.method("org.kristall.MockSession", in_signature="si")
    def Osd(self, icon, percent):
        self.osd.osdProgress(icon, percent, 100, "")

    @dbus.service.method("org.kristall.MockSession", in_signature="ss")
    def OsdText(self, icon, text):
        self.osd.osdText(icon, text)

    @dbus.service.method("org.kristall.MockSession", out_signature="s")
    def Calls(self):
        out = json.dumps(CALLS)
        CALLS.clear()
        return out


def main(opts):
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    names = ["org.kristall.MockSession", "org.freedesktop.ScreenSaver", "org.kde.Solid.PowerManagement"]
    display = kbd = player = None
    keep = []
    if "--no-backlight" not in opts:
        names.append(SB)
        root = Brightness(bus)
        display = Display(bus, root)
        keep.append(root)
    pm = PmRoot(bus)
    if "--no-kbd" not in opts:
        kbd = Keyboard(bus)
    ss = ScreenSaver(bus)
    if "--media" in opts:
        names.append(MP + ".kristallmock")
        art = opts[opts.index("--art") + 1] if "--art" in opts else ""
        player = Player(bus, art)
    osd = Osd(bus)
    keep += [dbus.service.BusName(n, bus) for n in names]
    ctl = Control(bus, display, kbd, ss, player, osd)
    keep += [pm, ctl, display, kbd, ss, player, osd]
    print("ready", flush=True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main(sys.argv[1:])
