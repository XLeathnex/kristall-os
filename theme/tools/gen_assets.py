#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Raster assets of the Kristall theme (called by gen-theme.py --assets; needs numpy + pillow):

  share/wallpapers/<Name>/            Plasma wallpaper packages, light (images/) + dark (images_dark/)
  share/icons/Kristall/               pointer theme (cursors.py)
  share/plymouth/themes/kristall/     boot splash images (two-step plugin)
  share/plasma/look-and-feel/org.kristall.desktop/contents/splash/images/   login splash backgrounds
  share/sounds/kristall/              restrained event sounds (sounds.py)
"""
import json
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import cursors
import sounds
import wallpapers

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MARK_SVG = os.path.join(REPO, "shell", "icons", "kristall", "mark.svg")

# Plasma picks the image closest to the screen; 16:10 at 4K-class plus 16:9 for external screens
WALLPAPER_SIZES = [(3840, 2400), (2880, 1800), (1920, 1200), (3840, 2160)]
DEFAULT_WALLPAPER = "kristall"


def wallpaper_dirname(name):
    return "Kristall" if name == "kristall" else "Kristall-" + name.capitalize()


def mark_polygons():
    """the shell's mark (a 24-unit SVG of filled polygons with fill-opacity)"""
    svg = open(MARK_SVG, encoding="utf-8").read()
    polys = []
    for op, d in re.findall(r'fill-opacity="([0-9.]+)" d="([^"]+)"', svg):
        pts = [tuple(float(v) for v in p.split(",")) for p in re.findall(r"[-0-9.]+,[-0-9.]+", d)]
        polys.append((float(op), pts))
    return polys


def render_mark(size, color=(255, 255, 255), opacity=1.0, ss=8):
    big = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    k = size * ss / 24.0
    for op, pts in mark_polygons():
        layer = Image.new("L", big.size, 0)
        ImageDraw.Draw(layer).polygon([(x * k, y * k) for x, y in pts], fill=int(255 * op * opacity))
        col = Image.new("RGBA", big.size, color + (0,))
        col.putalpha(layer)
        big = Image.alpha_composite(big, col)
    return big.resize((size, size), Image.LANCZOS)


def wallpaper_packages(share, sizes=WALLPAPER_SIZES, quality=92):
    out = []
    for name in wallpapers.WALLPAPERS:
        d = os.path.join(share, "wallpapers", wallpaper_dirname(name))
        meta = {
            "KPlugin": {
                "Authors": [{"Name": "Kristall OS"}],
                "Id": wallpaper_dirname(name),
                "License": "GPL-3.0-or-later",
                "Name": wallpapers.NAMES[name]["en"],
                "Name[de]": wallpapers.NAMES[name]["de"],
            },
            "KPackageStructure": "Wallpaper/Images",
        }
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "metadata.json"), "w") as f:
            json.dump(meta, f, indent=4, ensure_ascii=False)
        for dark in (False, True):
            sub = os.path.join(d, "contents", "images_dark" if dark else "images")
            os.makedirs(sub, exist_ok=True)
            # render once at the largest 16:10 size; smaller sizes are downscaled, 16:9 is cropped
            big = Image.fromarray(wallpapers.render(name, dark, *sizes[0]))
            for w, h in sizes:
                if (w, h) == big.size:
                    img = big
                elif abs(w / h - big.width / big.height) < 0.01:
                    img = big.resize((w, h), Image.LANCZOS)
                else:
                    ch = int(round(big.width * h / w))
                    top = (big.height - ch) // 2
                    img = big.crop((0, top, big.width, top + ch)).resize((w, h), Image.LANCZOS)
                img.save(os.path.join(sub, f"{w}x{h}.jpg"), quality=quality, optimize=True, progressive=True, subsampling=0)
            if not dark:
                big.resize((400, 250), Image.LANCZOS).save(os.path.join(d, "contents", "screenshot.jpg"), quality=88)
        out.append(d)
    return out


def splash_backgrounds(share):
    """blurred default wallpaper for the login splash (KSplash), so the hand-over from the login
    screen (blurred wallpaper) to the desktop (sharp wallpaper) reads as one continuous image"""
    d = os.path.join(share, "plasma", "look-and-feel", "org.kristall.desktop", "contents", "splash", "images")
    os.makedirs(d, exist_ok=True)
    for dark in (False, True):
        arr = wallpapers.render(DEFAULT_WALLPAPER, dark, 1920, 1200)
        im = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(28))
        im.save(os.path.join(d, f"background-{'dark' if dark else 'light'}.jpg"), quality=86, optimize=True)
    render_mark(128).save(os.path.join(d, "mark.png"))


def plymouth(share):
    """two-step theme images: the mark, the password field (for an encrypted disk) and a bullet"""
    d = os.path.join(share, "plymouth", "themes", "kristall")
    os.makedirs(d, exist_ok=True)
    render_mark(96, opacity=0.94).save(os.path.join(d, "watermark.png"))
    # password entry: a 280x36 capsule with a hairline, like the login field
    ss = 6
    W, H = 280, 36
    im = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, W * ss - 1, H * ss - 1], radius=H * ss // 2, fill=(255, 255, 255, 40),
                         outline=(255, 255, 255, 90), width=ss)
    im.resize((W, H), Image.LANCZOS).save(os.path.join(d, "entry.png"))
    b = Image.new("RGBA", (10 * ss, 10 * ss), (0, 0, 0, 0))
    ImageDraw.Draw(b).ellipse([ss, ss, 9 * ss, 9 * ss], fill=(255, 255, 255, 235))
    b.resize((10, 10), Image.LANCZOS).save(os.path.join(d, "bullet.png"))
    lk = Image.new("RGBA", (24 * ss, 24 * ss), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lk)
    dl.rounded_rectangle([4 * ss, 10 * ss, 20 * ss, 22 * ss], radius=3 * ss, fill=(255, 255, 255, 230))
    dl.arc([7 * ss, 3 * ss, 17 * ss, 15 * ss], 180, 360, fill=(255, 255, 255, 230), width=2 * ss)
    dl.line([7 * ss, 9 * ss, 7 * ss, 11 * ss], fill=(255, 255, 255, 230), width=2 * ss)
    dl.line([17 * ss - 1, 9 * ss, 17 * ss - 1, 11 * ss], fill=(255, 255, 255, 230), width=2 * ss)
    lk.resize((24, 24), Image.LANCZOS).save(os.path.join(d, "lock.png"))
    # capslock indicator, keyboard icon: tiny neutral glyphs
    cl = Image.new("RGBA", (24 * ss, 24 * ss), (0, 0, 0, 0))
    dc = ImageDraw.Draw(cl)
    dc.polygon([(12 * ss, 3 * ss), (21 * ss, 13 * ss), (16 * ss, 13 * ss), (16 * ss, 20 * ss), (8 * ss, 20 * ss),
                (8 * ss, 13 * ss), (3 * ss, 13 * ss)], outline=(255, 255, 255, 220), width=int(1.5 * ss))
    cl.resize((24, 24), Image.LANCZOS).save(os.path.join(d, "capslock.png"))
    kb = Image.new("RGBA", (24 * ss, 24 * ss), (0, 0, 0, 0))
    ImageDraw.Draw(kb).rounded_rectangle([2 * ss, 6 * ss, 22 * ss, 18 * ss], radius=2 * ss, outline=(255, 255, 255, 220), width=int(1.5 * ss))
    kb.resize((24, 24), Image.LANCZOS).save(os.path.join(d, "keyboard.png"))
    return d


def plymouth_preview(theme_dir, out_path, w=1440, h=900, progress=0.45):
    """what the two-step plugin draws with our configuration (for the evidence; not used at boot)"""
    im = Image.new("RGB", (w, h), (0, 0, 0))
    wm = Image.open(os.path.join(theme_dir, "watermark.png"))
    im.paste(wm, (int(w * 0.5 - wm.width * 0.5), int(h * 0.45 - wm.height * 0.45)), wm)
    bw, bh = 200, 4
    x0, y0 = int(w * 0.5 - bw * 0.5), int(h * 0.62 - bh * 0.62)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=2, fill=(0x3A, 0x3A, 0x3C))
    d.rounded_rectangle([x0, y0, x0 + int(bw * progress), y0 + bh], radius=2, fill=(0xF2, 0xF2, 0xF7))
    im.save(out_path, quality=88)


def marks(share):
    d = os.path.join(share, "kristall", "theme", "marks")
    os.makedirs(d, exist_ok=True)
    render_mark(112).save(os.path.join(d, "mark.png"))
    render_mark(112, color=(0x1D, 0x1D, 0x1F)).save(os.path.join(d, "mark-dark.png"))


def generate(out, tokens):
    share = os.path.join(out, "share")
    marks(share)
    wallpaper_packages(share)
    splash_backgrounds(share)
    cursors.generate(os.path.join(share, "icons"))
    plymouth(share)
    sounds.generate(os.path.join(share, "sounds"))
    print("gen_assets: wallpapers, splash, pointer, boot splash, sounds")


if __name__ == "__main__":
    import sys
    generate(sys.argv[1], None)
