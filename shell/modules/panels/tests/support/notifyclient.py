#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A notification client for the panels tests: sends one notification over
org.freedesktop.Notifications and prints what the server reports back, one JSON object per line:
{"id": n} after sending, then {"action": key}, {"replied": text}, {"closed": reason}.

  notifyclient.py --app NAME --summary S --body B [--action KEY=LABEL]… [--reply PLACEHOLDER]
                  [--desktop-entry ID] [--image-data] [--urgency 0|1|2] [--wait SECONDS]
--reply offers an inline reply (KDE's "inline-reply" action); --image-data sends a raw image.
"""
import argparse
import json
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--app", default="Test")
p.add_argument("--icon", default="")
p.add_argument("--summary", default="")
p.add_argument("--body", default="")
p.add_argument("--action", action="append", default=[])
p.add_argument("--reply")
p.add_argument("--desktop-entry")
p.add_argument("--image-data", action="store_true")
p.add_argument("--urgency", type=int, default=1)
p.add_argument("--wait", type=float, default=0)
a = p.parse_args()

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
actions = []
for x in a.action:
    k, _, label = x.partition("=")
    actions += [k, label or k]
hints = {"urgency": GLib.Variant("y", a.urgency)}
if a.reply is not None:
    actions += ["inline-reply", "Antworten"]
    hints["x-kde-reply-placeholder-text"] = GLib.Variant("s", a.reply)
if a.desktop_entry:
    hints["desktop-entry"] = GLib.Variant("s", a.desktop_entry)
if a.image_data:
    w, h = 32, 32
    pix = bytearray()
    for y in range(h):
        for x in range(w):
            pix += bytes((40 + x * 6, 120, 220 - y * 5, 255))
    hints["image-data"] = GLib.Variant("(iiibiiay)", (w, h, w * 4, True, 8, 4, bytes(pix)))
loop = GLib.MainLoop()
nid = [0]


def on_signal(conn, sender, path, iface, signal, params):
    v = params.unpack()
    if v[0] != nid[0]:
        return
    if signal == "ActionInvoked":
        print(json.dumps({"action": v[1]}), flush=True)
    elif signal == "NotificationReplied":
        print(json.dumps({"replied": v[1]}), flush=True)
    elif signal == "NotificationClosed":
        print(json.dumps({"closed": v[1]}), flush=True)
        loop.quit()


for sig in ("ActionInvoked", "NotificationReplied", "NotificationClosed"):
    bus.signal_subscribe(None, "org.freedesktop.Notifications", sig, "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, on_signal)
r = bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                  GLib.Variant("(susssasa{sv}i)", (a.app, 0, a.icon, a.summary, a.body, actions, hints, -1)), GLib.VariantType("(u)"),
                  Gio.DBusCallFlags.NONE, 10000, None)
nid[0] = r.unpack()[0]
print(json.dumps({"id": nid[0]}), flush=True)
if a.wait > 0:
    GLib.timeout_add(int(a.wait * 1000), loop.quit)
    loop.run()
