# Contract: `shell` — the Kristall shell and how modules plug in

Owner: **shell-core** (`shell/` except `shell/modules/<reserved>/`). Consumers: the agents that
build `panels` (Control Center, notifications, HUDs), `dock`, `search`, `apps`, `switcher`,
`assistant` (assistant UI), `setup` (Setup Assistant), and anything that drives the shell
(`kristall-shellctl`, global shortcuts, the assistant). The visual rules are in
`docs/contracts/design.md`. This document is normative.

## 1. What runs

| Piece | Where (installed) | Source |
|---|---|---|
| Quickshell config (QML) | `/usr/share/kristall/shell/` (`shell.qml`, `core/`, `services/`, `bar/`, `gallery/`, `strings/`, `icons/`, `modules/`, `modules.list`) | `shell/` |
| Helper (one per session, JSON lines on stdin/stdout) | `/usr/lib/kristall/shell/kristall-shell-helper` | `shell/helper/` |
| Launcher (ExecStart; crash ladder) | `/usr/libexec/kristall/kristall-shell` | `shell/bin/` |
| Last-resort fallback | `/usr/libexec/kristall/kristall-shell-fallback` | `shell/bin/` |
| CLI | `/usr/bin/kristall-shellctl` | `shell/bin/` |
| User units | `kristall-shell.service`, `kristall-shell-fallback.service`; preset `50-kristall-shell.preset` | `shell/systemd/` |
| Plasma look-and-feel package (default layout without panels) | `/usr/share/plasma/look-and-feel/org.kristall.desktop/`, selected in `/etc/xdg/kdeglobals` | `shell/plasma/` |
| Global shortcuts of shell-core | `/usr/share/kglobalaccel/org.kristall.shell.desktop` | `shell/plasma/kglobalaccel/` |
| Settings defaults | `/usr/share/kristall/defaults/settings.d/50-shell.json` (`appearance`, `accessibility`, `bar`) | `shell/image/settings.json` |

One process (`quickshell -p /usr/share/kristall/shell`), plus the helper and one
`kristall-settings watch`. Logs: `journalctl --user -t kristall-shell`.

## 2. Modules

A module is a directory `shell/modules/<name>/` (installed to
`/usr/share/kristall/shell/modules/<name>/`) with:

* `Module.qml` — **required**. Root type: `Scope` (from `Quickshell`) or any non-visual
  `QtObject`-derived type; it creates its own windows (`PanelWindow`, one per output with
  `Variants { model: Quickshell.screens }` where needed).
* `strings.json` — optional, `{"en": {"<name>.key": "…"}, "de": {…}}`; keys start with the module
  name. Loaded (synchronously) before `Module.qml` is created.
* any other QML/JS/assets the module needs, referenced relatively.

**Registering:** one line with the name in `shell/modules.list`. The reserved names are already
listed (`panels`, `dock`, `search`, `apps`, `switcher`, `assistant`, `setup`) — those agents only add
their directory. A listed module without a directory is skipped silently; the order of the list is
the load order.

**Installing:** each component's `image/install.sh` copies its module directory to
`$KRISTALL_PREFIX/share/kristall/shell/modules/<name>/` (shell-core's install never deletes
`modules/`). A new, unreserved module also needs its line in `modules.list` (a one-line change to
shell-core's file; say so in your report).

**Importing the core** (Quickshell 0.2.1 `qs.` imports resolve against the shell root):

```qml
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core       // Theme, GlassSurface, GlassShape, K* components, Menus, Tooltips
import qs.services   // Settings, Strings, Bridge, GlassClient, Apps, Power, Audio, Network, …
Scope { … }
```

Do not import `qs.bar` or another module's directory; talk to other modules through `ShellBus`.

**Isolation:** a module that fails to compile, or whose creation throws, is logged
(`kristall-shell: module <name> failed to load and is skipped`) and skipped; the bar and other
modules keep running. JavaScript errors at runtime are logged and do not stop the shell. A crash of
the whole process is handled by the restart ladder (§8): after three starts within 60 s the shell
starts in **safe mode** (core and menu bar only, no modules). `kristall-shellctl status` reports
each module as `loaded`, `failed` or `absent`.

**Settings:** read with `Settings.get("<key>.<path>", fallback)`; write with
`Settings.set(path, value)` (runs `kristall-settings set`). Use only your component's top-level key
(ARCHITECTURE §3) and contribute defaults via your own `settings.d` drop-in.

**Strings:** `Strings.t("dock.keepInDock", {app: name})`, `Strings.tn(key, n)` (`.one`/`.other`),
`Strings.pick({"de":…,"en":…})`, `Strings.lang` (`"de"`|`"en"`), `Strings.locale` (Qt locale for
dates and numbers). German typography follows Apple's German style (ellipsis with a space:
"Einstellungen …"; key `common.ellipsis`).

## 3. Surfaces: namespaces, layers, focus

Every shell surface is a wlr-layer-shell surface (`PanelWindow`). Its namespace starts with
`kristall-` and is unique per output within the shell process (the glass and bridge contracts
rely on it; bind glass with `output` set). Assigned and reserved namespaces:

| Namespace | Owner | Layer | Exclusive zone | Keyboard |
|---|---|---|---|---|
| `kristall-bar` | shell-core | Top | 24 | None |
| `kristall-menu` | shell-core (all glass menus) | Overlay, full output | — (Ignore) | Exclusive while open |
| `kristall-tooltip` | shell-core | Overlay, no input region | — | None |
| `kristall-gallery` | shell-core | Top | — | OnDemand |
| `kristall-dock` | dock | Top | its height (when not auto-hiding) | None |
| `kristall-cc`, `kristall-notifications`, `kristall-banners`, `kristall-hud` | panels | Overlay | — | OnDemand (cc, notifications), None (banners, hud) |
| `kristall-search`, `kristall-apps`, `kristall-switcher` | search, apps, switcher | Overlay | — | Exclusive while open |
| `kristall-assistant-*` | assistant UI (the bridge's `excludeShell` removes these) | Overlay | — | as needed |
| `kristall-setup-*` | setup | Overlay | — | Exclusive |

Rules:

* **Top** for persistent chrome (bar, Dock), **Overlay** for everything transient. Full-screen
  windows cover the Top layer (the bar disappears in full screen); Overlay stays above them.
* A popover that takes text input uses `WlrKeyboardFocus.Exclusive` while open and `None` when
  closed; others use `OnDemand`. Close on Escape and on a click outside (use a full-output transparent
  surface like `MenuHost`, or `HyprlandFocusGrab`-like grabs are not available on KWin).
* Map surfaces only while visible (`visible: open`), so idle costs nothing.
* For a glass surface: one `GlassSurface { key: "<name>-" + screen.name; layerNamespace;
  output: screen.name }` per window, shapes as `GlassShape { surface: … }`.
* Coordinates for menus and tooltips are in the **output's logical coordinates**. A surface
  anchored top-left can use `Menus.itemRect(item)`; others add their own offset
  (`Menus.itemRect(item, originX, originY)` — you know your anchors and margins).

## 4. Menus and tooltips (shared UI)

```qml
Menus.open({
    screen: screen.name,                         // output
    rect: Menus.itemRect(icon, dockX, dockY),    // anchor
    align: "center",                             // "left" | "right" | "center"
    owner: "dock:" + appId,                      // Menus.isOpen(owner) for highlighting / toggling
    keyboard: false,                             // true: first item selected
    source: Menus.list([
        { label: Strings.t("dock.open"), action: () => Apps.launch(id) },
        { label: Strings.t("dock.options"), children: [ { label: "…", toggle: "checkmark", checked: true, action: … } ] },
        { type: "separator" },
        { type: "header", label: "…" },
        { label: "…", enabled: false, shortcut: Theme.shortcutText([["Control", "Q"]]) },
        { type: "custom", component: myRow, height: 40, width: 260 }   // the Loader passes menuScheme/closeMenu()
    ]),
    onClosed: reason => { }                      // "activated" | "outside" | "escape" | "toggle" | "replaced" | …
});
Menus.close("why");
```

Other sources: `{kind: "dbus", key, item}` (a DBusMenu mirrored by `AppMenus.track(key, service,
path)`), `{kind: "qs", handle}` (a Quickshell `QsMenuHandle`, e.g. a tray item's `menu`). One menu
is open at a time across the shell. Tooltips: put `KTooltip { text: …; originX; originY }` inside
the control.

## 5. Requests: `kristall-shellctl`, `ShellBus`

```
kristall-shellctl <target> <action> [arg] [--output NAME]     # exit 0 delivered, 1 not running, 2 usage
kristall-shellctl status                                      # JSON: safeMode, modules, outputs, glass, bridge, helper, …
```

It calls the Quickshell IPC target `shell` (`quickshell ipc -p /usr/share/kristall/shell call shell
request <target> <action> <arg> <output>`), which emits `ShellBus.requested(target, action, arg,
output)`. A module handles its own target and calls `ShellBus.claim(target)` once:

```qml
Connections {
    target: ShellBus
    function onRequested(target, action, arg, output) { if (target === "panels" && action === "toggle-control-center") … }
}
```

| Target | Actions (arg) | Handled by | Sent by |
|---|---|---|---|
| `shell` | `close-menus` · (`status` via the CLI) | shell-core | shortcuts |
| `bar` | `focus` / `open-menu` (index; 0 = mark) | shell-core | Ctrl+F2 |
| `gallery` | `toggle`, `show`, `hide` | shell-core | developers |
| `panels` | `toggle-control-center`, `toggle-notifications`, `show-hud` (`volume`/`brightness`/…) | panels | bar buttons (with the bar's output), keys |
| `assistant` | `invoke` (`bar`, `shortcut`, `search`), `dismiss` | assistant UI | bar button, shortcut, search |
| `search` | `toggle`, `show` (query), `hide` | search | shortcut |
| `apps` | `toggle` | apps | shortcut, Dock |
| `switcher` | `next`, `previous`, `commit` | switcher | shortcuts |
| `dock` | `show`, `hide`, `bounce` (app id) | dock | — |
| `setup` | `start` | setup | the Setup Assistant's unit |

Modules publish what is open with `ShellBus.setOpen(name, output, isOpen)` (names:
`control-center`, `notifications`, `assistant`, `search`, `apps`); the bar highlights its Control
Center, assistant and clock items from it.

## 6. Global keyboard shortcuts (system-wide)

Shortcuts are registered with Plasma's `kglobalacceld` for **every user** by installing one desktop
file per module to `/usr/share/kglobalaccel/org.kristall.<module>.desktop` whose actions run
`kristall-shellctl`:

```ini
[Desktop Entry]
Type=Application
Name=Kristall Search
Exec=kristall-shellctl search toggle
NoDisplay=true
Actions=Toggle

[Desktop Action Toggle]
Name=Search
Exec=kristall-shellctl search toggle
X-KDE-Shortcuts=Meta+Space
```

`X-KDE-Shortcuts` is the default (the owner can change it in System Settings → Shortcuts, which
stores per-user overrides). Do not write `kglobalshortcutsrc`, do not use per-user scripts. A
module that takes over a Plasma default (e.g. KRunner's Alt+Space) changes that default for every
user in `/etc/xdg/kglobalshortcutsrc` (merge, never overwrite) and says so in its report.
shell-core registers: **Ctrl+F2** "Move focus to the menu bar"; "Close open menus" (no default).

## 7. Services (`import qs.services`)

All are singletons, event-driven, no polling. Absent hardware/services give "available: false"
and the bar hides or greys the item.

| Service | API |
|---|---|
| `Settings` | `data`, `loaded`, `get(path, fallback)`, `set(path, value)` |
| `Strings` | `lang`, `locale`, `t(key, args)`, `tn(key, n, args)`, `pick(obj)`, `addFile(path)` |
| `Bridge` | `connected`, `capabilities`, `locked`, `windows` (id → window), `activeId`, `activeWindow`, `frontId`/`frontWindow` (the last active *normal* window — use this for "the front app"; KWin reports no active window while a shell surface has keyboard focus), `stacking`, `outputs`, `revision`, `call(method, params, cb(result, error))`, `windowsOfApp(appId)`, `topWindowOn(output)`; signals `windowAdded/Removed/Changed` |
| `GlassClient` | `active`, `state`, `theme`, `glass`, `quality`, `boundWindows`, `isBound(key)`, signals `legibility`, `bound` (use `GlassSurface`/`GlassShape`, not this directly) |
| `AppMenus` | `track(key, service, path)`, `untrack(key)`, `trees`, `revision`, `node(key, id)`, `findItem(key, regex)`, `activate(key, id)`; the front window's menu is tracked as `"app"` |
| `Apps` | `apps` (manifest), `entry(appId)`, `byId(id)`, `displayName(appId)`, `desktopEntry(appId)`, `launch(appId)`, `launchKristall(id)` |
| `Power` | `hasBattery`, `percent`, `onBattery`, `charging`, `full`, `timeToEmpty`, `timeToFull`, `mode` (`quiet`/`balanced`/`performance` = Leise/Ausgewogen/Leistung = power-saver/balanced/performance), `setMode(m)`, `hasPerformance`, `modeName(m)` |
| `Audio` | `available`, `volume` (0..1), `muted`, `deviceName`, `setVolume(v)`, `setMuted(b)` |
| `Network` | `available`, `connected`, `hasWifi`, `wifiEnabled`, `wifiConnected`, `wifiName`, `wifiStrength`, `wifiBars` (0–3), `wiredConnected`, `setWifiEnabled(b)` |
| `BluetoothStatus` | `available`, `enabled`, `connectedCount`, `setEnabled(b)` |
| `Session` | `lock()`, `sleep()`, `restart()`, `shutDown()`, `logOut()` (Plasma's confirmation), `restartToUpdate()`, `openSystemSettings(kcm)`, `aboutThisComputer()`, `userName` |
| `Updates` | `status` (update contract's object), `state`, `restartRequired`, `stagedVersion`, `refresh()` |
| `Clock` | `date` (minute precision; seconds with `bar.showSeconds`), `barText(d)`, `longDate(d)`, `use24h` |
| `ShellBus` | §5 |
| `Icons` | `url(name, color)` (used by `KIcon`) |
| `Helper` | `request(op, params, cb)`, `event(ev)`, `last` — for shell-core services; ask before adding ops |

Native Quickshell services underneath: UPower and PowerProfiles (`Quickshell.Services.UPower`),
PipeWire, NetworkManager (`Quickshell.Networking`), BlueZ (`Quickshell.Bluetooth`),
StatusNotifierItem (`Quickshell.Services.SystemTray`), `SystemClock`, `DesktopEntries`.

## 8. Start, crash, restart, fallback

* `kristall-shell.service` (user, `WantedBy=graphical-session.target`, enabled for every user by
  preset) runs the launcher with `Restart=always`, `RestartSec=1`.
* The launcher counts starts in `$XDG_RUNTIME_DIR/kristall/shell-starts`; the fourth start within
  60 s runs in safe mode (`KRISTALL_SHELL_SAFE=1`: no modules).
* `StartLimitBurst=6` in 180 s; then `OnFailure=kristall-shell-fallback.service` adds a plain Plasma
  panel (launcher, task manager, clock, log out) through `org.kde.PlasmaShell.evaluateScript`,
  writes `~/.local/state/kristall/shell/fallback-panel` and notifies the owner. The next time the
  shell runs for 20 s it removes all Plasma panels again and deletes the marker.
* Glass, bridge or helper missing: the shell keeps working (fallback material, no app menus /
  window actions, minimal menus). Sockets are watched with inotify (helper) — no retry polling.

## 9. Helper protocol (shell-core internal)

JSON lines; requests `{"id"?, "op", …}` → `{"id", "ok", "error"?}`; events `{"event", …}`.
Ops: `menu.open {key, service, path}`, `menu.close {key}`, `menu.aboutToShow {key, item}`,
`menu.event {key, item, kind}`, `session {action: lock|sleep|restart|shutdown|logout|restart-update}`,
`update.refresh`, `watch.socket {path}`, `fallback.cleanup {delay}`. Events: `ready`,
`menu.layout {key, revision, menu}`, `menu.error`, `menu.activate`, `update {status}`,
`plasma {dark}`, `time.changed {reason}`, `socket {path, exists}`. At start it asks kded to load
its `appmenu` module (harmless if already loaded).

**Application menus end to end:** the shell's `Bridge` subscribes to the bridge topic `menus`; while
it is subscribed the bridge owns `org.kde.kappmenuview`, kded's `appmenu` module publishes
`com.canonical.AppMenu.Registrar`, Qt/KDE apps export their menus (and hide their in-window menu
bars) and announce them to KWin, and the bridge reports `window.menu`. `AppMenus` mirrors the front
window's menu through the helper (DBusMenu `GetLayout`/`AboutToShow`/`Event`). Apps started while
no shell was subscribed may keep their own menu bars until restarted.

## 10. Plasma integration

* Plasma's panels are removed for every user by the look-and-feel package `org.kristall.desktop`
  (selected in `/etc/xdg/kdeglobals` `[KDE] LookAndFeelPackage`), whose
  `contents/layouts/org.kde.plasma.desktop-layout.js` creates only the desktop containments with the
  image wallpaper. Missing parts of the package (splash, lock screen, defaults) fall back to Breeze.
  **The `theme` component may add its parts to this package** (it owns everything in it except
  `contents/layouts/` and the package id) or ship its own package that contains the same layout
  file and select that one instead.
* `plasmashell` stays for the wallpaper/desktop, Plasma's notification server and portals; the
  `panels` module replaces the notification UI.
* Existing users created before this image keep their saved layout (fresh installs only).

## 11. Quickshell 0.2.1 notes (learned the hard way)

1. A file is registered as a singleton only if no `{` or `}` appears before `pragma Singleton`
   (not even in comments). Put long comments after the imports.
2. In a delegate or child object, a binding like `panel: panel` refers to the object's *own*
   property, not the id — give ids distinct names (`menuPanel`, `barWindow`).
3. A property named `onSomething` is parsed as a signal handler.
4. Singletons are created on first use: an event emitted before that is lost — read
   `Helper.last.<event>` in `Component.onCompleted`.
5. `Theme.color()` returns `color` values; CSS `"rgba(…)"` strings are not colours in QML.
6. `FileView` loads lazily; use `blockLoading: true` and `text()` when you need the content now.
7. Qt apps export DBusMenu on Wayland only through KWin's app-menu protocol (no registrar call):
   the bridge's `window.menu` is the only source. Submenus of KDE apps are filled lazily — call
   `AppMenus.aboutToShow` before showing one (the menu host does).
8. While one of our layer surfaces has exclusive keyboard focus (an open menu), KWin reports
   `active.changed null`; use `Bridge.frontWindow`, not `activeWindow`, for the front app.

## 12. Testing (for the agents after shell-core)

* `shell/tests/run.sh [sections]` in the dev container. `shell/tests/support/shellsession.py`
  extends the glass harness (headless KWin with the effect): `ShellSession(...).start()`,
  `start_system()` (private system bus with mock UPower, power-profiles, NetworkManager, BlueZ —
  `mocksystem.py`), `start_audio()` (PipeWire with a null sink), `start_shell(path=…)`,
  `ipc(target, fn, …)`, `state()`, `screenshot()`, `save()`.
* `shell/tests/support/mockbridge.py`: the bridge protocol for windows/active/stacking/outputs/
  desktops (+ `menus`, `agent` topics; window fields `type`, `parentId`, `xwayland`, `content`,
  `namespace`), scriptable through `<socket>.ctl` (`open`, `close`, `activate`, `set`, `menu`,
  `outputs`, `agentPointer`, `agentState`, `state`, `calls`). Privileged methods return
  `unsupported`. Not modelled: the D-Bus side of `menus` (use the `menu` command), popups, the
  `active: null` KWin reports while a shell surface has keyboard focus (send `activate` with `null`).
* The real plugin: `run.sh realbridge` builds `kwin/bridge` and runs the bar against it (with
  `kded6` started in the session so app menus work end to end).
* `KRISTALL_SHELL_TEST=1` loads the `test` IPC target (`bar/TestHooks.qml`): `state`, `openMenu`,
  `key`, `press`/`pointer`/`release`, `itemRects`, `close`. Modules may add their own test targets
  the same way.
