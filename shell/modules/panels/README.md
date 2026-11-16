# panels — Control Center, notifications, HUDs (Kristall shell module)

A module of the Kristall shell (`docs/contracts/shell.md` §2), owned by the `panels` component.
Everything here is drawn with shell-core's design system (`docs/contracts/design.md`).

```
Module.qml              requests (ShellBus target "panels"), which surface is open where, HUD from Plasma's OSDs
ControlCenter.qml       Control Center window; CcMainPage (module grid) + Cc*Page (expanded modules)
Banners.qml             notification banners; NotifCard (one notification on glass)
NotificationCenter.qml  history grouped by app + widgets (CalendarWidget, BatteryWidget, MediaWidget)
Hud.qml                 volume / brightness / keyboard-backlight HUD (and Plasma's other OSDs as text)
Notifs.qml              the notification server, history, banners policy, Do Not Disturb, muting
Hw.qml Media.qml PanelsUtil.qml   Wi-Fi list, Bluetooth devices, outputs, mic use, backlights, MPRIS, power modes
PanelsHelper.qml + helper/kristall-panels-helper   D-Bus where Quickshell has no service (below)
PanelMetrics.qml        layout numbers design.md does not have yet (candidates for Theme)
qmldir                  the module's types (see "Quickshell note")
plasma/osd/…            no-op replacement of Plasma's OSD QML module; plasma/systemd/ the plasmashell drop-in
kglobalaccel/           shortcuts: Meta+Alt+C Control Center, Meta+Alt+N Notification Centre
image/                  install.sh, settings defaults (top-level key "panels")
tests/                  run.sh, test_panels.py, support/ (mocks, owner input, notification client), evidence/
```

## Requests

`kristall-shellctl panels <action> [arg]`: `toggle-control-center` / `show-…` / `hide-…`,
`toggle-notifications` / `show-…` / `hide-…`, `close`, `show-hud volume|brightness|kbd|mic`,
`focus on|off|<minutes>`. `toggle-control-center` accepts an optional JSON arg `{"x","y","w","h"}`
(the button's rectangle on the output); with it the panel grows exactly out of the button.
Open state is published with `ShellBus.setOpen("control-center"|"notifications", output, …)`.

## Where the data comes from

| What | Interface |
|---|---|
| Wi-Fi on/off, networks, connect known/open | Quickshell.Networking (NetworkManager); our `Network` service |
| New protected network | helper → NetworkManager `AddAndActivateConnection` (key in the profile, `connection.permissions = user:<owner>`; refused key → profile deleted, sheet says so) |
| Bluetooth on/off, devices, battery, connect | Quickshell.Bluetooth (BlueZ, `Battery1`) |
| Volume, mute, outputs, microphone in use | Quickshell.Services.Pipewire (default sink, `preferredDefaultAudioSink`, capture streams) |
| Display brightness | helper → PowerDevil `org.kde.ScreenBrightness` (internal display first; set with flag 1 = no OSD) |
| Keyboard backlight | helper → PowerDevil `…/Actions/KeyboardBrightnessControl` (`setKeyboardBrightnessSilent`) |
| Night Light | helper → KWin `org.kde.KWin.NightLight` (inhibit/uninhibit like Plasma's applet; first use writes `kwinrc [NightColor] Active` with KConfig notification) |
| Appearance | setting `appearance.theme` (shell-core's key, written as the owner-facing control for it) |
| Power modes, battery | power contract: power-profiles API for Leise/Ausgewogen/Leistung, `kristall-power mode auto` for Automatisch, `$XDG_RUNTIME_DIR/kristall/power.json` (inotify) for "is automatic", `kristall-power status --json` for health/draw (read when the module is opened), UPower for percent and time |
| Now playing | Quickshell.Services.Mpris (position refreshed 1×/s only while the expanded player is visible and playing) |
| Screen lock | helper → `org.freedesktop.ScreenSaver` `ActiveChanged` |
| HUD | helper → plasmashell's `org.kde.osdService` signals `osdProgress` / `osdText`; levels from the live services |
| Notifications | Quickshell `NotificationServer` = `org.freedesktop.Notifications` (actions, images, inline reply, persistence, replaces_id, `value` progress hint) |
| Bring the app forward | shell `Bridge` `window.activate` (window by sender pid, desktop entry = app id, or app name) |

The helper has no timers and no polling; with nothing changing it does not wake up.

## Notification service: who owns it

plasmashell registers `org.freedesktop.Notifications` only through its notifications applet,
which lives in a panel; the Kristall layout has no panel, so plasmashell never claims it (tested
with a real plasmashell). The shell owns it from start. A message sent while the shell restarts
is held by D-Bus activation (`org.kde.plasma.Notifications.service` runs `plasma_waitforname`,
which only waits for an owner) and delivered when the shell is back, whatever the start order.
If someone else holds the name (shell-core's last-resort fallback panel brings Plasma's applet
back), the helper reports it, and the module claims the name again as soon as it is free.

## Do Not Disturb — the one place

* State: setting **`panels.focus.until`** (number, ms since the epoch): `0` off, `-1` on until
  switched off, `> now` on until then. Set it with `kristall-settings set panels.focus.until -1`
  (works with or without the shell running) or `kristall-shellctl panels focus on|off|<minutes>`.
* What it does: no banners (critical/"time-sensitive" notifications still show), everything goes
  to Notification Centre. It is honoured by our notification service only; Plasma's own
  `plasmanotifyrc [DoNotDisturb]` keys are not read (Plasma's server is not running).
* Per-app muting: `panels.mutedApps` (array of app keys = desktop entry id, lower case, or app
  name), set from a notification's context menu.

## Plasma's OSD

plasmashell 6.8 builds its OSD from the QML module `org.kde.plasma.workspace.osd` and announces each
OSD on D-Bus. We install a no-op module of that name in `/usr/share/kristall/panels/plasma-qml` and
put it first on plasmashell's `QML_IMPORT_PATH` (user-unit drop-in
`plasma-plasmashell.service.d/50-kristall-osd.conf`). Keys stay Plasma's (plasma-pa, PowerDevil);
our HUD draws what Plasma announces. Without the shell running there is no OSD at all (keys work).

## Settings (`panels`, defaults `settings.d/50-panels.json`)

`panels.focus.until` (0), `panels.mutedApps` ([]).

## Build and test (dev container)

```sh
docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest shell/modules/panels/tests/run.sh [static cc wifi notifications hud absent looks idle]
```

Tests run against a copy of the shell with only this module enabled, headless KWin with the glass
effect, shell-core's mock bridge, our mocks (`tests/support/panelsystem.py`: NetworkManager with four
networks, BlueZ with two devices, UPower, power profiles; `mocksession.py`: PowerDevil brightness and
keyboard light, screen locker, a music player; `mock-kristall-power`), PipeWire with two null sinks
and a null microphone, a real plasmashell (notifications, HUD), and the owner's real pointer and
keyboard through KWin's fake-input protocol (`kwin/bridge/tests/clients/owner.c`).
Screenshots: `tests/evidence/`, numbers: `tests/evidence/results.json`.

## Quickshell note

Quickshell 0.2.1 generates `qmldir`s only for directories reached through `import qs.…` from
`shell.qml`; a module loaded by URL (as shell.qml loads `modules/<name>/Module.qml`) cannot see its
own other files. This module ships its own `qmldir` (checked by `run.sh static`).

## Known limits

* Verified only headless (software Qt Quick rendering, llvmpipe KWin): no real radios, audio
  devices, backlight, keys, GPU timing of the morph animations.
* The Control Center grows from the top-right corner unless the bar sends the button's rectangle.
* A wrong Wi-Fi password may also make Plasma's own network agent (plasma-nm) ask, because
  NetworkManager asks every registered secret agent again after a refused key (not reproducible here).
* No AirDrop / Stage Manager / Screen Mirroring equivalents; no per-app notification settings
  page beyond muting; no "Summary" or notification grouping by thread.
* Album art and notification images are drawn with Canvas (works on every renderer); avatars of
  persisted notifications are not kept across a shell restart (they live in the old process).
