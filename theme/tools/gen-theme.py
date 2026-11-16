#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the Kristall theme's derived files from tokens/tokens.json into OUT (a staging tree
whose layout mirrors the install prefix: OUT/share/... -> /usr/share/...).

    gen-theme.py OUT [--assets]      --assets also renders wallpapers, pointer, boot splash and
                                     sounds (needs python3-numpy and python3-pillow)

Everything the theme ships that is not hand-written is produced here, so it is reproducible.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
THEME = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kristall_colors as kc  # noqa: E402


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, mode)


def konsole_profile(dark=False):
    return "\n".join([
        "# SPDX-License-Identifier: GPL-3.0-or-later",
        "# Kristall terminal profile (light: \"Kristall\", dark: \"Kristall Dark\"). kristall-appearance",
        "# switches open sessions and the default profile between the two with the system appearance.",
        "[Appearance]",
        "ColorScheme=" + ("KristallDark" if dark else "KristallLight"),
        "Font=JetBrains Mono,9.75,-1,5,400,0,0,0,0,0,0,0,0,0,0,1",
        "AntiAliasFonts=true",
        "BoldIntense=false",
        "UseFontLineChararacters=true",
        "",
        "[General]",
        "Name=" + ("Kristall Dark" if dark else "Kristall"),
        "Parent=FALLBACK/",
        "TerminalColumns=80",
        "TerminalRows=24",
        "TerminalMargin=8",
        "TerminalCenter=false",
        "",
        "[Scrolling]",
        "HistoryMode=2",
        "ScrollBarPosition=1",
        "",
        "[Terminal Features]",
        "BlinkingCursorEnabled=false",
        "UrlHintsModifiers=67108864",
        "",
    ])


def generate(out, assets=False):
    tokens = kc.load_tokens()
    share = os.path.join(out, "share")
    for mode, name in (("light", "KristallLight"), ("dark", "KristallDark")):
        write(os.path.join(share, "color-schemes", name + ".colors"), kc.colorscheme(tokens, mode) + "\n")
        write(os.path.join(share, "konsole", name + ".colorscheme"), kc.konsole_scheme(tokens, mode) + "\n")
    write(os.path.join(share, "konsole", "Kristall.profile"), konsole_profile())
    write(os.path.join(share, "konsole", "Kristall Dark.profile"), konsole_profile(dark=True))
    # the light scheme's colour groups become the system default in /etc/xdg/kdeglobals
    light = kc.colorscheme(tokens, "light")
    frag = [l for l in light.splitlines() if not l.startswith("#")]
    # [General] Name/ColorScheme of a .colors file do not belong into kdeglobals
    keep, skip = [], False
    for l in frag:
        if l.startswith("["):
            skip = l in ("[General]", "[KDE]")
        if not skip:
            keep.append(l)
    write(os.path.join(out, "xdg-generated", "kdeglobals"), "\n".join(keep) + "\n")
    os.makedirs(os.path.join(share, "kristall", "theme"), exist_ok=True)
    shutil.copy(os.path.join(THEME, "tokens", "tokens.json"), os.path.join(share, "kristall", "theme", "tokens.json"))
    if assets:
        import gen_assets  # noqa: E402  (numpy/pillow)
        gen_assets.generate(out, tokens)
    print(f"gen-theme: wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    generate(sys.argv[1], "--assets" in sys.argv[2:])
