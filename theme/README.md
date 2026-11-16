# theme — everything the owner sees that is not our shell

Application windows and what is inside them, the boot splash, login, lock and log-out screens,
wallpapers, pointer, fonts, sounds, and the one appearance switch that flips all of it at once.
Interface: [`docs/contracts/theme.md`](../docs/contracts/theme.md). Assets and licences:
[`ASSETS.md`](ASSETS.md).

## Routes chosen (and why)

| Area | Route | Why |
|---|---|---|
| Window decoration | own KDecoration3 plugin (`decoration/`, ~500 lines C++) | KDecoration3 in KWin 6.8 gives rounded corners on all four sides (KWin clips the client with the decoration's `BorderRadius`) and a one-device-pixel `BorderOutline` natively; only the Mac buttons, their group hover and the layered shadow needed code. Aurorae (SVG themes) cannot do the group hover or the outline; Breeze cannot put Mac buttons in Mac colours. KWin falls back to Breeze if the plugin is missing; a crash guard covers a plugin that loads but crashes KWin. |
| Qt/KDE apps | stock **Breeze** style, configured, + our colour schemes | Evaluated on Plasma 6.8 (screenshots in the dev container): **Union** (KDE's new CSS style engine, shipped in 6.8) renders Dolphin correctly and is very expressive, but it does not request background blur for menus (no glass) and is a preview; **Kvantum** cannot switch light/dark in running apps (restart needed) — that breaks the one-switch requirement; an **own style plugin** (a Breeze fork) would get closest in shapes but is ~20 k lines to keep alive. Breeze switches live, requests blur for translucent menus (→ glass), unifies title bar and toolbar through the Header colours, and is what every KDE app is tested with. Gap: Breeze's shapes (5-px radii, its buttons) — see below. |
| GTK 3 / GTK 4 | `adw-gtk3` + libadwaita, both under our user CSS written by the service | libadwaita only honours user CSS; using one CSS vocabulary (libadwaita's colours) for both gives GTK 3 and GTK 4 apps one look; title buttons are drawn by CSS (radial-gradient circles + our SVG glyphs). GTK 3 reads user CSS only at start, so a 40-line GTK module (`gtk-module/`) reloads it in open windows. |
| Appearance switch | `kristall-appearance` user service | Uses Plasma's own mechanisms: `plasma-apply-colorscheme` (KWin blends the change), Plasma's day/night look-and-feel auto switcher for `auto`, kde-gtk-config for GTK settings, the KDE portal for Flatpak apps and Firefox. |
| Lock screen / log-out | overlay copy of Plasma's shell package with a patched lock screen and our log-out alert | In Plasma 6.8 these live in the shell package, not the look-and-feel package; no setting points only them elsewhere. Patching by exact-text anchors keeps Plasma's authentication code and falls back to stock on any mismatch. |
| Login | plasma-login-manager configuration (wallpaper) + `/etc/xdg` (colours, font, pointer) | The 6.8 greeter's QML is compiled into the binary; there is no theme package to replace. |
| Boot splash | Plymouth two-step theme + verified initramfs rebuild | Established practice of Universal Blue images (Bazzite/Bluefin); the new initramfs replaces the old one only after checks, otherwise the stock splash stays. |

## Build and test

```sh
# the extra packages the tests need (GTK demos, libadwaita, Firefox, KWrite, kde-gtk-config,
# adw-gtk3, JetBrains Mono, Plymouth + dracut + kernel); ~310 MB on top of kristall-devenv
docker build --network host --build-arg HTTPS_PROXY="$HTTPS_PROXY" -t kristall-devenv-theme -f theme/tests/Dockerfile tools/devenv
docker run --rm -v "$PWD":/work kristall-devenv-theme:latest /work/theme/tests/run.sh            # all sections
docker run --rm -v "$PWD":/work kristall-devenv-theme:latest /work/theme/tests/run.sh static install
```

Sections: `static` (tokens vs design.md, contrast, INI/JSON/XML, qmllint, shellcheck, fontconfig
matching), `install` (install.sh into a staging root: merge keeps other components' keys,
idempotency, assets), `decoration`, `apps` (Files, System Settings, Text Editor, Terminal, GTK 3,
GTK 4/libadwaita, Firefox; light/dark × 1.0/1.6 with the Kristall menu bar), `menus` (glass
context menu), `switch` (timed live flip of every app, accent, Reduce Motion, auto), `screens`
(lock idle/prompt, log-out, login splash, login screen), `pointer`, `fallback` (each custom piece
removed or broken), `plymouth` (initramfs rebuild and rejection of a bad one). Evidence:
`tests/evidence/` (JPEG, < 6 MB). The plain `kristall-devenv` runs everything except the GTK,
Firefox and Plymouth parts (those report SKIP).

`tools/gen-theme.py OUT --assets` regenerates every derived file (colour schemes, wallpapers,
pointer, sounds, boot-splash images); the image build runs it, nothing generated is committed.

## Known limits (honest gaps versus macOS 27)

* Qt widgets keep Breeze's shapes: 5-px rounded rectangles, Breeze push buttons and check boxes,
  classic tabs; scroll bars are thin but not overlay scroll bars; focus is a coloured frame, not a
  3-px ring. Dolphin's toolbar (hamburger, Split) and Places panel are Dolphin's; the sidebar does
  not run under the title bar as in macOS 27.
* Window corners are circular arcs, not continuous-curvature (KWin's clip); toolbars are not merged
  into the title bar (the title bar is 28 px above the app's toolbar, same colour).
* libadwaita keeps its own widgets (we restyle colours, radii, title buttons); GTK 3 shows title-
  button symbols when the pointer is anywhere over the header bar, not only over the buttons.
* Firefox draws its own window buttons (grey circles, left side); no userChrome by design.
* The login screen layout is Plasma's (clock, user list, password field), only coloured, set in
  Inter and on our wallpaper.
* German UI of KDE apps depends on the image's language packs (the dev container has none, so
  screenshots show English app menus; our own strings are German/English).
