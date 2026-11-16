# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal PNG encode/decode (8-bit RGB/RGBA, non-interlaced) for synthetic test images."""
import struct
import zlib


def encode(width: int, height: int, rgb: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def decode(data: bytes):
    """Returns (width, height, channels, bytes) with filters undone."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat = 8, b""
    w = h = ch = 0
    while pos < len(data):
        ln, t = struct.unpack(">I4s", data[pos:pos + 8])
        d = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if t == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", d)
            assert depth == 8 and inter == 0
            ch = {2: 3, 6: 4, 0: 1, 4: 2}[ctype]
        elif t == b"IDAT":
            idat += d
    raw = zlib.decompress(idat)
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0
            b = prev[x]
            c = prev[x - ch] if x >= ch else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, ch, bytes(out)


def find_color(img, color, tol=8):
    """Centroid (x, y) in pixel-centre coordinates of pixels close to color, or None."""
    w, h, ch, px = img
    sx = sy = n = 0
    for y in range(h):
        row = y * w * ch
        for x in range(w):
            o = row + x * ch
            if abs(px[o] - color[0]) <= tol and abs(px[o + 1] - color[1]) <= tol and abs(px[o + 2] - color[2]) <= tol:
                sx += x + 0.5
                sy += y + 0.5
                n += 1
    return (sx / n, sy / n) if n else None
