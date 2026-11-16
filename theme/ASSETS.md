# theme — third-party and original assets

Nothing here is traced from, derived from or bundled with Apple artwork, and none of the popular
"Mac look-alike" Linux theme or icon packs is used (they trace Apple's icons, wallpapers and window
artwork). The Mac is reproduced in layout, metrics and behaviour; every drawing is ours or an
openly licensed KDE/GNOME/Google/JetBrains asset that ships with Fedora.

## Original (this repository, GPL-3.0-or-later)

| Asset | Where it comes from | Installed to |
|---|---|---|
| Wallpapers *Kristall*, *Welle*, *Horizont* (light + dark) | drawn by `tools/wallpapers.py` at build time (numpy; no source images, fixed seeds) | `/usr/share/wallpapers/Kristall{,-Welle,-Horizont}/` |
| Pointer theme *Kristall* (24 shapes, SVG + XCursor) | drawn by `tools/cursors.py` from simple geometry (arrow, glove, I-beam, neutral spinner, resize arrows) | `/usr/share/icons/Kristall/` |
| Sound theme *kristall* (19 short sounds + silent login/logout) | synthesised by `tools/sounds.py` (sine partials and filtered noise) | `/usr/share/sounds/kristall/` |
| Boot splash images (mark, password field, lock, bullet) | `tools/gen_assets.py` | `/usr/share/plymouth/themes/kristall/` |
| Login splash backgrounds (blurred default wallpaper) | `tools/gen_assets.py` | look-and-feel package `contents/splash/images/` |
| Colour schemes, terminal colours, GTK styling | `tools/kristall_colors.py` from `tokens/tokens.json` (= design.md) | `/usr/share/color-schemes/`, `/usr/share/konsole/`, `~/.config/gtk-{3,4}.0/kristall.css` |
| Window decoration (buttons, shadow) | `decoration/` (C++; structure after KDE's Breeze decoration, no code copied) | `…/qt6/plugins/org.kde.kdecoration3/org.kristall.decoration.so` |
| Window-button glyphs for GTK (×, −, two triangles) | `tools/kristall_colors.py` (`GTK_GLYPHS`) | `~/.config/gtk-{3,4}.0/kristall/` |
| Kristall mark (crystal) | shell-core's `shell/icons/kristall/mark.svg` (`shell/tools/gen-mark.py`), rasterised by `tools/gen_assets.py` | boot splash, log-out dialog |
| Lock-screen clock, log-out dialog, login splash (QML) | `plasma/` | look-and-feel package, shell-package overlay |

The window-button colours (red/yellow/green circles) are plain sRGB values chosen to match the
look a Mac owner knows; no Apple image or glyph is used — the symbols are drawn by our code.

## Third party (used as installed by Fedora packages, not copied into this repository)

| Asset | Source (Fedora 45 package) | Licence | How we use it |
|---|---|---|---|
| Inter, Inter Display | `rsms-inter-fonts` (https://rsms.me/inter) | SIL OFL 1.1 | interface typeface everywhere |
| JetBrains Mono | `jetbrains-mono-fonts-all` (https://www.jetbrains.com/lp/mono/) | SIL OFL 1.1 | monospace (terminal, code, `fixed`) |
| Noto Color Emoji | `google-noto-color-emoji-fonts` | SIL OFL 1.1 | colour emoji |
| Breeze icons | `breeze-icon-theme` (KDE) | LGPL-3.0-or-later | app, folder, file and toolbar icons (folders follow the accent colour) |
| Breeze cursors | `breeze-cursor-theme` (KDE) | GPL-2.0-or-later | inherited for pointer shapes we do not draw |
| Breeze widget style | `plasma-breeze` (KDE) | GPL-2.0-or-later | Qt widget style, configured (`/etc/xdg/breezerc`), not modified |
| adw-gtk3 | `adw-gtk3-theme` (https://github.com/lassekongo83/adw-gtk3) | LGPL-2.1-or-later | GTK 3 base theme under our CSS |
| freedesktop sound theme | `sound-theme-freedesktop` | GPL-2.0-or-later / CC-BY-SA (per file) | fallback for sound names we do not define |
| Lock screen and log-out QML of Plasma | `plasma-desktop` (KDE) | GPL-2.0-or-later | copied from the installed package at image build time; the lock screen copy is patched (layout only) by `plasma/shell-overlay/build-overlay.py`, notices kept |
| Plymouth two-step plugin | `plymouth-plugin-two-step` | GPL-2.0-or-later | renders our boot splash images |
