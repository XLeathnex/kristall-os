# shell — the Kristall desktop shell (shell-core)

A Quickshell (QML) configuration running on KWin as layer-shell surfaces: the design system, the
shared services, the menu bar, and the skeleton other shell modules plug into. Plasma's panels are
removed (desktop/wallpaper containment stays). Contracts: [`docs/contracts/design.md`](../docs/contracts/design.md)
(tokens, components, menus) and [`docs/contracts/shell.md`](../docs/contracts/shell.md) (modules,
namespaces, IPC, services, start/restart).

```
shell.qml          entry point: per-output bar + menu/tooltip hosts, module loader, IPC "shell"
modules.list       module registry (reserved: panels dock search apps switcher assistant setup)
modules/<name>/    modules of later components (Module.qml, strings.json)
core/              design system: Theme (tokens), GlassSurface/GlassShape, K* components, Menus, MenuHost, Tooltips
services/          singletons: Settings Strings Helper Bridge GlassClient AppMenus Apps Power Audio Network
                   BluetoothStatus Session Updates Clock ShellBus Icons
bar/               the menu bar (Bar, BarButton, BarMenus, BatteryGlyph), BarRegistry, TestHooks
gallery/           every component in every state (kristall-shellctl gallery toggle)
helper/            kristall-shell-helper (Python/GIO): DBusMenu, update status, scheme, clock jumps, session actions, socket watch
bin/               kristall-shell (launcher, crash ladder), kristall-shellctl, kristall-shell-fallback
systemd/           user units + preset
plasma/            look-and-feel package (layout without panels), kdeglobals, kglobalaccel shortcuts
strings/           German + English strings
icons/             Phosphor (MIT) + our symbols; tools/ generates the mark and the shadow assets
image/             install.sh, settings defaults (appearance, accessibility, bar)
tests/             run.sh, test_shell.py, support/ (mock bridge, mock system services, Qt test app), evidence/
```

## Build and test (dev container)

```sh
docker run --rm -v "$PWD":/work kristall-devenv:latest shell/tests/run.sh            # everything, ~8 min
docker run --rm -v "$PWD":/work kristall-devenv:latest shell/tests/run.sh core appmenu
```

Sections: `shortcuts` (kglobalaccel files register with their default keys), `ctl` (arguments of
`kristall-shellctl`), `reconnect` (bridge/glass appearing late, crash-guard notice), `controls`
(binding-safe toggle), `menus` (submenu safe triangle), `reveal` (menu bar over full screen),
`static` (syntax, shellcheck, strings parity, settings defaults, unit files, launcher
ladder), `core` (services react to change, bar states, mark/window menus, idle), `appmenu` (a real
Qt Widgets app's DBusMenu end to end, a real StatusNotifierItem), `scale` (1.6× on 2880×1800),
`fallback` (no glass effect), `modules` (broken/throwing module isolated, safe mode), `restart`
(kill → back; three crashes → safe mode), `plasma` (headless plasmashell: our layout has no
panel), `gallery` (light/dark screenshots), `realbridge` (the real bridge plugin, if it builds). Numbers from the last run: `tests/evidence/results.json`.

Run the shell by hand in a session: `quickshell -p shell` (set `KRISTALL_SHELL_HELPER` if the helper
is not installed). Mock bridge for development: `python3 shell/tests/support/mockbridge.py serve`.

## Known limits

* Verified only headless (KWin 6.8.3 virtual backend, llvmpipe, Qt Quick software renderer for the
  shell). Not verified: real GPU cost and 120-Hz smoothness, real Wi-Fi/Bluetooth/battery/audio
  hardware (mocks: UPower, power-profiles, NetworkManager, PipeWire null sink), real fractional-scale
  panel crispness (1.6× was rendered and looked at, not seen on an OLED), real `kglobalacceld`
  pick-up of `share/kglobalaccel/` (not run), systemd's own restart handling (no systemd in the
  container: emulated with the unit's Restart=always/RestartSec=1 values), Plasma's
  `LogoutPrompt`, logind and the screen locker.
* Most tests run against `tests/support/mockbridge.py`; section `realbridge` runs the bar against
  the real `kwin/bridge` plugin (windows, front app, app menus of a Qt app with the KDE platform
  theme via the `menus` topic + kded's appmenu module, Window ▸ Zoom → dimmed bar).
* GTK 4 and most Electron apps export no menu: they get the minimal menus (app name, File/Window).
* Bluetooth is a service only (the bar shows no Bluetooth item, as macOS by default); it was seen
  reading the mock BlueZ adapter, but on/off reactivity is not tested.
* Differences from macOS 27: see design.md §14 (typeface, glass model, menu tint, safe triangle,
  estimated metrics); the bar does not reveal itself in full screen when the pointer reaches the
  top edge; no menu-bar overflow handling beyond clipping app menus that do not fit.
