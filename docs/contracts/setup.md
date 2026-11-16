# Contract: `setup` — Setup Assistant, Kristall's settings pages, the Mac keyboard

Owner: `setup/` and `shell/modules/setup/`. Consumers: the shell (request bus, `keyboard.commandKey`),
the assistant interface (`setup claude-signin`), the image (unit, presets, `/etc/xdg` fragments),
anyone who needs to know whether first-run setup is finished. Normative.

## 1. Pieces (installed)

| What | Where |
|---|---|
| Setup Assistant (shell module) | `/usr/share/kristall/shell/modules/setup/` (surfaces `kristall-setup-main`, Overlay, exclusive keyboard on the main output) |
| First-login unit | user `kristall-setup.service` (oneshot, `graphical-session.target`, preset `50-kristall-setup.preset`; `ConditionKernelCommandLine=!rd.live.image`, `ConditionPathExists=!/etc/kristall/live`, `ConditionUser=!@system`) → `/usr/libexec/kristall/kristall-setup-start` |
| Helper | `/usr/bin/kristall-setup-helper` (§5) |
| Keyboard plugin | `/usr/lib64/qt6/plugins/kwin/plugins/kristall_keyboard.so`, enabled in `/etc/xdg/kwinrc` `[Plugins] kristall_keyboardEnabled=true` |
| Settings pages | System Settings modules `kcm_kristall_{about,update,assistant,appearance,dock,notifications,energy,keyboard}` (`/usr/lib64/qt6/plugins/plasma/kcms/systemsettings/`), category `kristall` (`/usr/share/systemsettings/categories/settings-kristall-general.desktop`), QML backend `org.kristall.settings` |
| Hidden System Settings pages | `/etc/xdg/kdeglobals` `[KDE Control Module Restrictions]` (merged): look-and-feel, Plasma style, splash, decorations, application style, effects, KWin scripts/rules/options, Xwayland, background services, activities, feedback, KRunner plugins, Plasma notifications, session, Qt Quick settings, Quick Settings landing page |
| KInfoCenter's own About | `/etc/xdg/kcm-about-distrorc` (merged): our mark, variant "Kristall OS" |
| Defaults | `/usr/share/kristall/defaults/settings.d/50-setup.json` (keys `keyboard`, `setup`) |

Open a page directly: `systemsettings kcm_kristall_<page>`.

## 2. Settings keys owned

| Key | Type | Default | Meaning |
|---|---|---|---|
| `setup.done` | bool | `false` | first-run setup finished or skipped; the unit does nothing once true |
| `setup.running` | bool | `false` | the Setup Assistant was opened and not finished: a shell (re)start resumes it |
| `setup.step` | string | `""` | the step on screen (resume point) |
| `setup.skipped` | bool | `false` | "Set up later" was chosen (all defaults kept) |
| `setup.version` | int | `1` | |
| `keyboard.macShortcuts` | bool | `true` | the key beside the space bar acts as Command (§4) |
| `keyboard.commandKey` | `"ctrl"` \| `""` | `"ctrl"` | **derived**, written together with `macShortcuts` by the Setup Assistant and the Keyboard page: `"ctrl"` = apps' Ctrl shortcuts are pressed with Command, so menus draw Control as ⌘ (design.md §12). Readers that need the switch read `macShortcuts` |
| `keyboard.passthroughApps` | array of app ids (lower case, `*` wildcards) | `[]` | apps that get ordinary PC keys, in addition to the built-in list (§4.3) |
| `keyboard.terminalApps` | array | `[]` | additional terminals (§4.3) |

Written by the Setup Assistant and the pages but owned by others: `appearance.{theme,accent,glass,reduceTransparency}`,
`accessibility.*`, `bar.*` (shell-core), `dock.*` (dock), `panels.focus.until`, `panels.mutedApps` (panels),
`assistant.{name,language,speak_replies,speaking_rate}`, `assistant.ui.light.*`, `assistant.hands.accessibility`,
`power.{automatic,chargeLimit,dimOnBattery,batteryRefreshRate}`.

## 3. Setup Assistant

### 3.1 Requests (ShellBus target `setup`; `kristall-shellctl setup <action> [arg]`)

| Action | Arg | Effect |
|---|---|---|
| `start` | optional step id | opens the Setup Assistant: resumes at `setup.step` when `setup.running && !setup.done`, else at the welcome, or at the given step. Sets `setup.running`. Refused (logged) in the live session |
| `claude-signin` | free (`sign_in`, `install_cli`, `update_cli`, `settings`) | the sign-in step alone ("Sign in with Claude" sheet; Done/Escape/Not Now close it; `setup.*` unchanged). If the Setup Assistant is open, it goes to its sign-in step |
| `close` | — | closes without finishing (resumes at the next `start` or shell start) |

Publishes `ShellBus.setOpen("setup", "", open)`. (Do not use an action named `show`: see the shell
defect in §7.)

### 3.2 State machine

Steps, in order: `welcome → network → appearance → glass → display → keyboard → trackpad →
assistant → voice → microphone → privacy → energy → done`. `network` applies only while offline
(and stays in the list once shown); `trackpad` only when KWin reports a touchpad; all others always.
Each step has a default; Continue (button or Return) applies the default or the choice shown.

```
             unit / start                     Continue …                 "Start using Kristall"
 not started ───────────► running(step=welcome) ──► running(step=…) ─────► done (setup.done=true,
 (done=false)                 │      ▲  every step change writes setup.step     running=false)
                              │      └── shell crash/restart, re-login: resume at setup.step
                              └── "Set up later" (welcome) ─────────────► done + skipped
 live session (/etc/kristall/live or rd.live.image): never starts, never resumes.
```

Choices are applied the moment they are made (theme, accent, glass, display scale, keyboard, voice,
energy), so a crash never loses them and the desktop behind the card shows them live.

### 3.3 Back ends used

`kristall-assistant-account` (sign-in: `status`, `install`, `login --open`, code on stdin),
`assistant.sock` (microphone check: a voice `invoke` with `speak:false`, cancelled when the final
transcript arrives), `kristall-setup-helper` (Wi-Fi, displays, touchpads), `kristall-power status --json`,
`/var/lib/kristall/apps/status.json` (inotify). Test overrides: `KRISTALL_SETUP_HELPER`,
`KRISTALL_ASSISTANT_ACCOUNT`, `KRISTALL_POWER_CMD`, `KRISTALL_APPS_STATUS`, `KRISTALL_SETUP_LIVE_MARKER`,
`KRISTALL_SETUP_CMDLINE`, `KRISTALL_ASSISTANT_SOCKET`, `KRISTALL_SETUP_FORCE_STEPS`.

## 4. Mac keyboard (`kristall_keyboard`, KWin plugin)

### 4.1 Mechanism

Inside the compositor: each input device's `keyChanged` is disconnected from KWin's
`KeyboardInputRedirection::processKey` and routed through the plugin, which calls `processKey` with
the translated keys. KWin's xkb state, the modifiers clients receive, global shortcuts and the
switcher's hold-and-release all see one consistent keyboard. The keymap is not changed. Input that
does not come from a device (the bridge's `agent.key`/`agent.text`, input methods) is not touched.

Physical roles (German PC keyboard): left **Alt** = Command, left **Windows** key = Option (sent as
Alt), **Ctrl** = Control, **AltGr** untouched.

### 4.2 Translation (focused window's class decides at key press)

| Physical | App | Terminal | Passthrough |
|---|---|---|---|
| Command (alone, with mouse) | Ctrl | Ctrl | Alt |
| Command + letter/digit/punctuation | Ctrl + key | letters: Ctrl+Shift+key; others Ctrl+key | Alt + key |
| Command + Space / Tab / ` / < | Meta + key, Meta held until Command is released (Search, switcher, window cycling) | same | Alt + key |
| Command + Shift + 3 / 4 / 5 | Shift+Print / Meta+Shift+Print / Print (Spectacle: screen / region / tool) | same | — |
| Command + H / M | hide the app (minimise its windows) / minimise the window | same | — |
| Control + Command + Q / F / Space | lock / full screen / emoji picker (Meta+.) | same | — |
| Command + ← → / ↑ ↓ | Home / End; Ctrl+Home / Ctrl+End (Shift kept) | same | — |
| Command + Backspace | Shift+Home, Backspace | Ctrl+U | — |
| Command + , | KDE apps (`org.kde.*`): Ctrl+Shift+, ; others Ctrl+, | | |
| Option + ← → / Backspace / Delete | Ctrl + key (by word) | same | Meta + key |
| Option + other | Alt + key | Alt + key | Meta + key |
| Control first, then Command (Ctrl+Alt+Del, Ctrl+Alt+F-keys) | as printed (Alt) | same | same |

Passthrough: the lock screen, any surface with an active keyboard-shortcuts inhibitor, and app ids
matching `*.exe`, `wine*`, `steam_app_*`, `gamescope`, Sober/Vinegar (Roblox), `minecraft*`,
emulators, VM and remote-desktop viewers, plus `keyboard.passthroughApps`. Terminals: Konsole, foot,
kitty, Alacritty, WezTerm, Ghostty, GNOME Terminal/Console, Ptyxis, xterm, Yakuake, Tilix, Black Box,
plus `keyboard.terminalApps`.

### 4.3 Status and fail-safe

`$XDG_RUNTIME_DIR/kristall/keyboard.json` (atomic): `{"version":1,"running":bool,"active":bool,
"reason":"on"|"off"|"crash-guard"|"not-loaded"|"no-input"|"stopped","devices":int}`. Settings are
re-read on change (inotify, 50 ms coalescing). If the plugin is not loaded, cannot reroute a device,
or KWin started more than three times within three minutes with it loaded (`keyboard.guard`), keys are
stock. Unloading releases every key it holds and gives the devices back. Log category `kristall.keyboard`.

## 5. `kristall-setup-helper`

JSON lines on stdout, the last `{"event":"result","ok":…}`; exit 0 iff ok.

| Command | Result |
|---|---|
| `displays` | `outputs: [{name, internal, widthPx, heightPx, widthMm, scale, recommended, choices:[{scale, looksLike:[w,h]}]}]` — five sizes "Larger Text … More Space" around the scale that gives ~127 logical px per inch (a Mac's default density); around the current scale without a physical size |
| `display-scale OUTPUT SCALE` | sets the scale (kscreen-doctor, 0.05 steps) |
| `touchpads` / `touchpad-set [--natural on\|off] [--tap on\|off]` | KWin `org.kde.KWin.InputDevice` (KWin persists them) |
| `wifi-connect SSID SECURITY` | password as one line on stdin; NetworkManager `AddAndActivateConnection`, owned by the user; a refused key deletes the profile; events `{"event":"wifi","state":"connecting"|"connected"|"failed","reason"}` |
| `wallpapers` | `wallpapers: [{name, path, preview, kristall}]` (Plasma wallpaper packages and pictures; ours first). Applied with `plasma-apply-wallpaperimage` |
| `system-info` | `info: {osName, osVersion, processor, cores, memoryGB, graphics[], storageTotal, storageFree, model, kernel}` (no serial numbers) |
| `live` | exit 0 in the live session |

## 6. Settings pages

Changes apply immediately (no Apply button) through `kristall-settings set`; pages follow outside
changes through one `kristall-settings watch --full`. Commands: `kristall-update status|check|apply|restart|rollback [--cancel]`,
`kristall-power status|mode|doctor --json --out DIR`, `kristall-assistant-account status|logout`;
sign-in goes through `kristall-shellctl setup claude-signin`. "Save Report" copies the doctor's
`doctor.json` to the desktop as `Kristall-Bericht-YYYY-MM-DD.json` (`Kristall-Report-…` in English).
"Always allow" grants are removed from `~/.config/kristall/assistant/permissions.json` (atomic, 0600).

## 7. Known issues in what this builds on

* `Session.aboutThisComputer()` opens KInfoCenter; it should open `systemsettings kcm_kristall_about`.
  `Session.openSystemSettings()` without a module shows System Settings' blank start (the Quick
  Settings landing page is hidden because its global-theme switch would bring Plasma's panels back);
  it should open `kcm_kristall_appearance` or the last page.
* Global-shortcut desktop files with `NoDisplay=true` are ignored by kglobalaccel; `kristall-shellctl <target> show`
  is swallowed by Quickshell's argument parser — the setup module accepts `start`, not `show`.
