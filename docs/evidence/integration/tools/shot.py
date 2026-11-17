#!/usr/bin/python3
# shot.py NAME [x y w h]  — capture Virtual-0 through KWin's ScreenShot2 API, save /shots/NAME.jpg
# (whole screen scaled to 1440x900, or the given device-pixel crop at full resolution) + print size.
import os, sys
import dbus
import numpy as np
from PIL import Image

bus = dbus.SessionBus()
iface = dbus.Interface(bus.get_object("org.kde.KWin", "/org/kde/KWin/ScreenShot2"), "org.kde.KWin.ScreenShot2")
r, w = os.pipe()
opts = dbus.Dictionary({"native-resolution": dbus.Boolean(True), "include-cursor": dbus.Boolean(True)}, signature="sv")
try:
    meta = iface.CaptureScreen("Virtual-0", opts, dbus.types.UnixFd(w))
finally:
    os.close(w)
width, height, stride, fmt = int(meta["width"]), int(meta["height"]), int(meta["stride"]), int(meta["format"])
data = b""
with os.fdopen(r, "rb") as f:
    while len(data) < stride * height:
        c = f.read(stride * height - len(data))
        if not c:
            break
        data += c
a = np.frombuffer(data, np.uint8).reshape(height, stride)[:, :width * 4].reshape(height, width, 4)
# QImage formats: 4/5/6 = (A)RGB32 (bytes B,G,R,A on little-endian), 16/17/18 = RGB(A/X)8888 (R,G,B,A)
img = Image.fromarray((a[:, :, [2, 1, 0]] if fmt in (4, 5, 6) else a[:, :, :3]).copy())
name = sys.argv[1]
if len(sys.argv) >= 6:
    x, y, cw, ch = map(int, sys.argv[2:6])
    img = img.crop((x, y, x + cw, y + ch))
else:
    img = img.resize((1440, 900), Image.LANCZOS)
out = f"/shots/{name}.jpg"
img.save(out, quality=80, optimize=True)
os.chmod(out, 0o666)
print(out, img.size, os.path.getsize(out))
