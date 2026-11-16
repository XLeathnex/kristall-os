#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Test helper: capture an output through KWin's org.kde.KWin.ScreenShot2 D-Bus API.
import os
import sys

import dbus
import numpy as np


def capture_screen(name=None, native=True):
    """Returns an HxWx4 uint8 RGBA array of the given output (default: active output)."""
    bus = dbus.SessionBus()
    obj = bus.get_object("org.kde.KWin", "/org/kde/KWin/ScreenShot2")
    iface = dbus.Interface(obj, "org.kde.KWin.ScreenShot2")
    r, w = os.pipe()
    opts = dbus.Dictionary({"native-resolution": dbus.Boolean(native), "include-cursor": dbus.Boolean(False)}, signature="sv")
    try:
        if name:
            meta = iface.CaptureScreen(name, opts, dbus.types.UnixFd(w))
        else:
            meta = iface.CaptureActiveScreen(opts, dbus.types.UnixFd(w))
    finally:
        os.close(w)
    width, height, stride, fmt = int(meta["width"]), int(meta["height"]), int(meta["stride"]), int(meta["format"])
    data = b""
    with os.fdopen(r, "rb") as f:
        while len(data) < stride * height:
            chunk = f.read(stride * height - len(data))
            if not chunk:
                break
            data += chunk
    raw = np.frombuffer(data, dtype=np.uint8)[: stride * height].reshape(height, stride)[:, : width * 4].reshape(height, width, 4)
    # QImage::Format_ARGB32(_Premultiplied)/RGB32 are stored as BGRA in little endian memory
    if fmt in (4, 5, 6):
        rgba = raw[:, :, [2, 1, 0, 3]].copy()
    elif fmt in (16, 17, 18):  # RGBX8888 / RGBA8888 (premultiplied)
        rgba = raw.copy()
    else:
        raise RuntimeError(f"unhandled QImage format {fmt}")
    rgba[:, :, 3] = 255
    return rgba


if __name__ == "__main__":
    from PIL import Image

    Image.fromarray(capture_screen()).save(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shot.png")
