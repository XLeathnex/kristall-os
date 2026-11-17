# Contract: `theme` — application theming, appearance switch, login/lock/boot

Owner: **theme** (`theme/`). Consumers: `setup` (first-run assistant and Kristall settings
screens), shell-core and shell modules (they read the same settings), `image` (Flatpak
provisioning, kernel arguments), anyone who needs to know what the owner sees outside our shell.
Visual numbers come from `docs/contracts/design.md`; `theme/tokens/tokens.json` is the machine
copy (the static tests compare it with `shell/core/Theme.qml`). This document is normative.

## 1. Settings it reacts to

Read through `kristall-settings` (watch), never written by the theme:

| Key | Owner | Effect |
|---|---|---|
| `appearance.theme` `light`\|`dark`\|`auto` | shell-core | `light`/`dark`: Plasma colour scheme `KristallLight`/`KristallDark`, look-and-feel id `org.kristall.desktop`/`org.kristall.desktop.dark`, Plasma's automatic switching off. `auto`: Plasma's own day/night switching (kded `lookandfeelautoswitcher`, kdeglobals `[KDE] AutomaticLookAndFeel=true`, `DefaultLight/DarkLookAndFeel` = our two packages); the service follows what Plasma applies. |
| `appearance.accent` (8 names, design.md §6) | shell-core | kdeglobals `[General] AccentColor` = the token for the current mode (light hex in light, dark hex in dark), GTK CSS accent, GNOME `accent-color` (nearest libadwaita name). |
| `accessibility.reduceMotion` | shell-core | kdeglobals `[KDE] AnimationDurationFactor=0` (KWin, Qt, GTK via kde-gtk-config, portal `reduced-motion`); removed again when false. |

`appearance.glass`, `glassQuality`, `reduceTransparency` belong to the glass effect; the theme does
not touch them. The theme adds **no settings keys** and ships no `settings.d` drop-in.

## 2. `kristall-appearance` (user service and CLI)

`/usr/bin/kristall-appearance` → `/usr/lib/kristall/theme/kristall-appearance` (Python 3, stdlib +
python3-gobject). User unit `kristall-appearance.service` (`WantedBy=graphical-session.target`,
`Restart=on-failure`, preset `50-kristall-theme.preset`). Logs: `journalctl --user -t kristall-appearance`.

| Command | Result |
|---|---|
| `run` | the service: applies once, then watches settings and `~/.config/kdeglobals` (inotify via GIO; no polling) |
| `apply` | apply current settings once; prints `{"theme","mode","accent","accentHex","ms","steps"}` |
| `status [--json]` | `{"theme","accent","mode","colorScheme","lookAndFeel","automatic","accentColor"}` |
| `accents --json` | `[{"id","light","dark","name":{"en","de"}}]` in display order (design.md §6) |
| `wallpapers --json` | `[{"id","name":{"en","de"},"path","preview","hasDark":true}]` |
| `wallpaper set ID` | desktop (all screens, `plasma-apply-wallpaperimage`) and lock screen; exit 0/1 |

What one change reaches, in one pass (measured ≈ 0.25 s for the service's own work; apps repaint
as they receive the change — KWin cross-fades the screen over 300 ms, `BlendChanges`):

| Target | Mechanism |
|---|---|
| Qt/KDE apps, window decoration, plasmashell, lock screen | `plasma-apply-colorscheme` (KConfig notify), then once more `KGlobalSettings.notifyChange(PaletteChanged)`: Plasma 6.8's tool announces the palette ~20 ms *before* it writes kdeglobals, so running Qt processes reloaded the previous colours (one change behind; the shell's folder icons kept the old accent until a restart). *Added 2026-11-17.* |
| Wallpaper variant (desktop, lock screen, login splash) | our wallpaper packages carry `images/` and `images_dark/`; Plasma picks by colour scheme — nothing to do |
| GTK 3 and GTK 4/libadwaita | `~/.config/gtk-{3,4}.0/kristall.css` (+ glyphs in `kristall/`), imported from `gtk.css` (the line is added, the file is otherwise left to kde-gtk-config); GTK theme `adw-gtk3`/`adw-gtk3-dark` via kde-gtk-config's D-Bus `org.kde.GtkConfig.setGtkTheme` (settings.ini, gsettings, xsettings); gsettings `color-scheme`, `accent-color`, `gtk-theme`, `button-layout`. Open GTK 3 windows reload `kristall.css` through our GTK module `kristall-reload-gtk-module` (`GTK_MODULES`, like kde-gtk-config's colorreload module); GTK 4 reloads user CSS itself |
| Portal (Flatpak apps, Firefox) | xdg-desktop-portal-kde derives `org.freedesktop.appearance` `color-scheme`, `accent-color` (exact RGB), `reduced-motion` from kdeglobals; xdg-desktop-portal-gtk serves the GNOME keys |
| Terminal | per-user `~/.local/share/konsole/Kristall.profile` `ColorScheme`, open sessions reloaded over D-Bus (`setProfile`) unless the owner chose another scheme |
| Text editor | KTextEditor's automatic light/dark theme (`katerc`/`kwriterc`) |
| Pointer | unchanged (dark arrow with white edge works on both) |

Login: the colour scheme and GTK files persist from the last session, so apps start in the right
appearance. In `auto`, `startplasma` applies the right package before the session starts once
Plasma has stored a day/night schedule (from the second login on); on the very first login at night
the session starts light and switches within seconds.

## 3. Windows

Decoration plugin `org.kristall.decoration` (KDecoration3, built in the image against the shipped
KDecoration; `/etc/xdg/kwinrc [org.kde.kdecoration2] library=org.kristall.decoration`).

| Metric (logical px) | Value |
|---|---|
| title bar | 28, colour = scheme `[WM]`/Header (one surface with the toolbar), title Inter 13 bold centred |
| buttons | close, minimise, zoom on the left (`ButtonsOnLeft=XIA`, `ButtonsOnRight=` empty); 12 Ø, 8 gap, first circle 12 from the edge; colours `#FF5F57/#FEBC2E/#28C840`, grey `#DCDCDE`/`#4A4A4C` inactive or disabled; symbols on all three while the pointer is over the group; inactive windows show colours on hover |
| corner radius | 20 resizable main windows, 16 modal/fixed-size (design.md §5), all four corners (KWin clips the client), 0 when maximised/tiled; circular arcs (KWin has no continuous-curvature clip) |
| outline | one device pixel, black 15 % (light) / white 20 % (dark) |
| shadow | design.md §7 window (48/16/0.32, dark ×1.6) + contact layer (3/1/0.18); inactive 55 %, 70 % size |
| resize | 6 px invisible margin outside the window |
| title text | the app's own title, except that a trailing ` — <product name>` Qt appends for the apps we rename ("Home — Dolphin") shows our name ("Home — Dateien"): the app manifest's `product_names` (apps.md), read once per KWin start (`titles.cpp`). *Added 2026-11-17.* |

**Zoom** maximises and restores (left click only). Mac's green button enters full screen; here the
menu bar is our shell and full-screen windows cover it, the bar's "dims when maximised" behaviour
(design.md §9) is built around maximise, and maximise keeps the Dock and bar reachable. Full screen
stays available from the window menu (right-click on the title bar) and the bar's Window menu;
`setup` may bind KWin's "Make Window Fullscreen" to Ctrl+⌘+F.

Fail soft: plugin missing or not loadable → KWin uses Breeze. Crash guard: each KWin start that
loads the plugin is counted in `$XDG_RUNTIME_DIR/kristall/decoration.guard`; a start that lives
30 s clears it; the third start after two short-lived ones hands out Breeze decorations for the
rest of the login session (delete the file to retry). `KRISTALL_DECORATION_FORCE_FALLBACK=1` forces it.

KWin behaviour (`/etc/xdg/kwinrc`, merged): double-click title bar = maximise; edge tiling on
(top = maximise, sides = halves, corners = quarters); new windows centred; all screen edges and hot
corners off (overview's top-left corner too); open/close = scale effect 200 ms from 92 %; minimise
= magic lamp 350 ms toward the Dock icon (bridge sets the target); maximise animated.

## 4. Inside applications

* **Qt/KDE**: the stock Breeze widget style, configured (`/etc/xdg/breezerc`: translucent menus at
  82 % that request background blur → the glass effect draws them; window drag from empty areas;
  no mnemonics; centred tabs; no scroll-bar arrows), colours from our schemes, Inter 13 px
  (kdeglobals fonts in pt: 9.75), monochrome toolbar icons, no icons on buttons or in menus.
* **GTK 3**: `adw-gtk3` + our CSS; **GTK 4/libadwaita**: libadwaita + our CSS (user CSS is the only
  hook libadwaita honours: colours/accent as CSS variables and named colours, window radius 20, title
  buttons as 12-px circles with glyphs on hover, 8-px controls, 12-px popovers). GTK 3 client-side
  title bars (header-bar apps, `GTK_CSD=1`) are at least 28 px with the buttons centred, and GTK 3
  windows round only the corners GTK 3 actually draws (title bar top, window bottom; square when
  maximised or tiled — GTK 3's maximised CSD window is opaque, a radius left black wedges). Checked:
  theme `csd` section. Flatpak apps see
  the CSS through a system Flatpak override (`kristall-theme-flatpak.service` runs `flatpak override
  --system --filesystem=xdg-config/gtk-3.0:ro --filesystem=xdg-config/gtk-4.0:ro` at boot, because
  `/var/lib/flatpak/overrides` is not part of the image) and the colour scheme/accent through the portal.
  **For `image`**: please provision the Flathub runtime extensions `org.gtk.Gtk3theme.adw-gtk3` and
  `org.gtk.Gtk3theme.adw-gtk3-dark` with the default apps (GTK 3 Flatpaks need the theme inside the sandbox).
* **Firefox**: `/usr/lib64/firefox/browser/defaults/preferences/kristall-theme-prefs.js` (supported
  prefs only): tabs in the title bar, compact density, overlay scroll bars, KDE file dialog via portal,
  system light/dark. Its window buttons follow the GTK button layout (left, Mac order) but Firefox
  draws them itself (grey circles with symbols); no userChrome. They cannot be traffic lights
  through a supported route (checked with Firefox 160, 2026-11-17): Firefox styles them in its own
  chrome CSS (`appearance: none`, `-moz-symbolic-icon(window-close-symbolic)` …); the pref that used
  GTK's own drawing (`widget.gtk.non-native-titlebar-buttons.enabled`) is gone, enterprise policies
  and WebExtension themes cannot reach them, and `browser.tabs.inTitlebar=0` (KWin's title bar
  with our buttons) is not honoured on Wayland. The `image` component makes the first start German
  and silences the Speech Dispatcher bar (apps README).
* **Menus to the menu bar**: Qt/KDE apps export through KWin's app-menu protocol (bridge). GTK 3 apps
  export only under XWayland with `unity-gtk3-module` (installed and loaded for every GTK 3 app through `GTK_MODULES` in `/usr/lib/environment.d/50-kristall-theme.conf`)
  and `gmenudbusmenuproxy` (Plasma). We do **not** force GTK 3 apps onto
  XWayland: at the panel's fractional scale they would be blurry or wrongly sized. GTK 4/libadwaita
  and Firefox have no exportable menu bar; the bar shows the app name and the standard menus.
* **Files** (`/etc/xdg/dolphinrc`): icon view, double-click to open (kdeglobals `SingleClick=false`),
  no remembered tabs, no status bar, no in-window menu bar (exported), git integration.
  **Terminal**: profile *Kristall* (JetBrains Mono 13 px, 80×24, Kristall colours). **Text editor**:
  KWrite without line numbers, soft wrap, Inter.
* **Fonts**: `/usr/share/fontconfig/conf.avail/56-kristall.conf` (linked in `/etc/fonts/conf.d`):
  sans-serif/system-ui → Inter, monospace → JetBrains Mono, emoji → Noto Color Emoji; greyscale
  antialiasing (OLED-safe), no hinting, no embedded bitmaps. GNOME key defaults in
  `/usr/share/glib-2.0/schemas/90-kristall.gschema.override`. Flatpak apps see host fonts in
  `/usr/share/fonts` automatically.
* **Icons**: Breeze (folders follow the accent). **Pointer**: `Kristall` (`/usr/share/icons/Kristall`,
  SVG for KWin + XCursor for XWayland, inherits `breeze_cursors`), size 24. **Sounds**: `kristall`
  (19 quiet sounds, silent login/logout, inherits `freedesktop`).

## 5. Wallpapers

Packages `/usr/share/wallpapers/{Kristall,Kristall-Welle,Kristall-Horizont}/` (Plasma
`Wallpaper/Images`), each `images/` + `images_dark/` at 3840×2400, 2880×1800, 1920×1200 (16:10) and
3840×2160 (16:9), plus `contents/screenshot.jpg` (400×250) for choosers. Default: `Kristall`
(look-and-feel defaults `[Wallpaper] Image=Kristall`). Generated at image build by
`theme/tools/wallpapers.py`.

## 6. From power button to desktop

| Stage | What | Where |
|---|---|---|
| Boot | Plymouth theme `kristall` (two-step: the mark, a 200×4 progress bar, black; password field for an encrypted disk); kernel args `rhgb quiet loglevel=3 rd.udev.log_level=3 vt.global_cursor_default=0` | `/usr/share/plymouth/themes/kristall/`, `/etc/plymouth/plymouthd.conf`, `/usr/lib/bootc/kargs.d/50-kristall-theme.toml` |
| initramfs | rebuilt as Universal Blue images do (`dracut --no-hostonly --kver K --reproducible --add ostree`), to a temp file, replacing the original only if it lists our theme, the two-step plugin, `ostree`, every dracut module of the original and ≥ 98 % of its kernel modules; otherwise original and stock theme stay (`theme/image/plymouth.sh`) | |
| Login | plasma-login-manager 6.8's greeter is compiled-in QML (clock, user list with picture, password field, power buttons) and offers no theming beyond wallpaper, colours, font and pointer; we set the wallpaper (`/usr/lib/plasmalogin/plasmalogin.conf.d/50-kristall.conf`), the rest comes from `/etc/xdg` | |
| Login splash | KSplash `org.kristall.desktop/contents/splash/Splash.qml`: blurred default wallpaper + thin progress bar | look-and-feel package |
| Lock screen, log-out dialog | Plasma 6.8 loads them from the **shell** package `org.kde.plasma.desktop` (not the look-and-feel package). We ship a copy of the installed package with two changes in `/usr/share/kristall/theme/overlay/plasma/shells/` and put that directory first in `XDG_DATA_DIRS` (`/usr/lib/environment.d/50-kristall-theme.conf`). Lock screen: Plasma's `LockScreenUi.qml` patched by exact-text anchors (date + 96-px time at the top, picture/name/password lower, no sleep/hibernate/switch-user buttons, the "Virtual Keyboard" button only when KWin has an on-screen keyboard — i.e. a touchscreen, `setup.md` §4.4 —, media controls kept; authentication code untouched); anchors not matching → stock; patched file failing to load → stock (Loader); both failing → kscreenlocker's built-in locker. Log-out: our alert (`KristallLogout.qml`, de/en, 60-s countdown) with the stock dialog as Loader fallback. Report of what was applied: `…/contents/kristall-overlay.json`. | |

## 7. For `setup`

* Appearance screen: write `appearance.theme`/`appearance.accent` with `kristall-settings`; list the
  accents with `kristall-appearance accents --json` (names de/en, swatches light/dark); apply is
  automatic (the service watches). Wallpapers: `kristall-appearance wallpapers --json` and
  `kristall-appearance wallpaper set ID` (or any image path).
* Display scaling: offer the panel's scale as **"Larger text ↔ More space"** with 3–5 named steps
  (like the Mac's display settings), mapped to KScreen output scales in 1/8 steps that keep logical
  sizes whole on 2880×1800: 1.5 (1920×1200 "More space"), 1.6 (1800×1125, default), 1.75 (≈1646×1029),
  2.0 (1440×900 "Larger text"). Apply with `kscreen-doctor output.<name>.scale.<s>`; Qt, GTK 4 and
  KWin decorations render natively at fractional scales; XWayland apps are scaled by KWin.
* Plasma Setup pages (first boot) are themed by the same colour scheme, fonts and wallpaper.

## 8. Files installed (summary)

`/usr/lib64/qt6/plugins/org.kde.kdecoration3/org.kristall.decoration.so`;
`/usr/lib/kristall/theme/{kristall-appearance,kristall_colors.py,kini.py}`; `/usr/lib64/gtk-3.0/modules/libkristall-reload-gtk-module.so`; `/usr/bin/kristall-appearance`;
`/usr/share/kristall/theme/{tokens.json,ASSETS.md,marks/,overlay/}`; `/usr/share/color-schemes/Kristall{Light,Dark}.colors`;
`/usr/share/konsole/{Kristall.profile,Kristall{Light,Dark}.colorscheme}`; wallpapers, icons/Kristall, sounds/kristall,
plymouth/themes/kristall; additions to `/usr/share/plasma/look-and-feel/org.kristall.desktop/contents/{defaults,splash/}`
and the package `org.kristall.desktop.dark`; `/usr/lib/plasmalogin/plasmalogin.conf.d/50-kristall.conf`;
units `kristall-appearance.service` (user), `kristall-theme-flatpak.service` (system) + presets;
merged: `/etc/xdg/{kdeglobals,kwinrc,breezerc,dolphinrc,konsolerc,katerc,kwriterc,kcminputrc,ksplashrc,kscreenlockerrc}`,
`/etc/gtk-{3,4}.0/settings.ini`; `/etc/fonts/conf.d/56-kristall.conf`; `/usr/share/glib-2.0/schemas/90-kristall.gschema.override`;
`/usr/lib/environment.d/50-kristall-theme.conf`; `/usr/lib/bootc/kargs.d/50-kristall-theme.toml`; Firefox prefs.
Build-time knobs: `KRISTALL_THEME_PLYMOUTH=0` keeps the stock boot splash.
