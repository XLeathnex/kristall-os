# setup — Setup Assistant, Kristall's settings, the Mac keyboard

Three things decide whether the owner never needs a terminal; they live here. Interface:
[`docs/contracts/setup.md`](../docs/contracts/setup.md).

```
keyboard/        KWin plugin kristall_keyboard: the key beside the space bar acts as Command, per app
settings/        System Settings modules kcm_kristall_* (QML pages) + QML backend org.kristall.settings
bin/             kristall-setup-helper (Wi-Fi, displays, touchpads, wallpapers, about), kristall-setup-start (unit)
systemd/         kristall-setup.service (first login), preset
data/            settings defaults (keyboard, setup), /etc/xdg fragments (kwinrc, kdeglobals, kcm-about-distrorc), our mark
image/           install.sh (builds against the image's KWin/Qt; also installs shell/modules/setup), merge-ini
tests/           run.sh, test_static.py, test_keyboard.py, test_setup.py, test_settings.py, clients/, support/, evidence/
../shell/modules/setup/   the Setup Assistant (Quickshell module): Module.qml (state machine), SetupWindow.qml, Step*.qml
```

## Decisions

**Settings: our pages inside KDE System Settings.** One window, one sidebar: a "Kristall" group at
the top (About this computer, Software Update, Assistant, Appearance, Dock & Menu Bar, Notifications &
Focus, Battery & Energy, Mac Keyboard) above KDE's own Wi-Fi, Bluetooth, displays, sound, users …
Developer-oriented pages and pages that would break the desktop (global theme, Plasma style,
decorations, effects, scripts, KRunner plugins, Plasma's unused notification settings) are hidden with
KDE's own `[KDE Control Module Restrictions]`. A separate settings window that embeds or links to
KDE's pages would be a second settings app (the seam this project removes) and would have to
re-implement System Settings' module host. Pages apply changes at once, like the Mac.

**Keyboard: a KWin plugin, not keyd/xremap/Toshy.** Evidence-based comparison:

| | per-app | AltGr/German keys | games/Wine | bridge typing | testable here | image |
|---|---|---|---|---|---|---|
| XKB options (`altwin:*`, `ctrl:swap_lalt_lctl`) | no | yes | no (global) | yes | yes | trivial |
| keyd (C, MIT; `keyd-application-mapper` + KWin script) | via script, laggy | yes | via app rules | yes | **no** (evdev/uinput) | not in Fedora 45; root daemon + uinput |
| xremap (Rust, MIT; KWin script for app info) / Toshy (Python xwaykeyz) | yes | yes | rules | yes | no (evdev/uinput) | Rust toolchain / Python venv, root or input group |
| **KWin plugin routing device keys (ours)** | exact (focused surface) | keymap untouched | built in, + shortcut inhibitors | not routed through it | **yes** (fake input = real pipeline) | 1 small .so built against the image's KWin |

The plugin reroutes devices' `keyChanged` into its translator and feeds `processKey`, so xkb state,
client modifiers, global shortcuts and the switcher's hold semantics stay consistent. It cannot help
outside a KWin session (TTY, the Plasma Setup wizard runs KWin too, so it applies there with defaults),
and it depends on KWin's internal API (the image build fails if KWin changes it; the laptop keeps the
last good image).

## Build and test (dev container)

```sh
docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest setup/tests/run.sh            # everything (~45 min)
docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest setup/tests/run.sh static keyboard:table setup:walk-de
```

Suites: `static`; `keyboard` (table altgr bridge system terminal live failsafe); `setup` (walk-de
walk-en offline signin-fail signin-abandon resume skip live looks); `settings` (looks actions).
Evidence: `tests/evidence/` (screenshots, `keyboard-table.txt`, `keyboard-altgr.txt`).

## Known limits

* Not exercised on real hardware: a physical keyboard (fake input drives KWin's real pipeline, but
  not libinput), a real touchpad (the headless KWin has no `InputDevice` D-Bus objects), real Wi-Fi
  (mock NetworkManager), a real microphone (the assistant's demo daemon supplies the transcript), the
  real Anthropic sign-in in a browser (a fake `kristall-assistant-account` with the contract's events),
  the first boot after the installer, Spectacle itself (its shortcut chords are proven to reach
  kglobalaccel).
* The microphone check needs the owner to be signed in (the daemon refuses voice turns otherwise) and
  costs one cancelled Claude request; a "transcribe only" request in assistant-ipc would avoid both.
* Voice choice: one voice per language ships, so the step offers language and when to speak, not a voice.
* Cmd+Q relies on the app's Ctrl+Q; Cmd+, on the app's settings shortcut (Ctrl+Shift+, in KDE apps).
