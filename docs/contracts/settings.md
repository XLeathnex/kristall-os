# Contract: shared settings (`kristall-settings`)

Owner: `image` component. Implementation: `image/rootfs/usr/bin/kristall-settings` (Python 3,
standard library only, ~35 ms per call including process start). Tests: `image/tests/test_settings.py`.

## Files and merge order

| Order | File | Written by |
|---|---|---|
| 1 | `/usr/share/kristall/defaults/settings.json` | image (ships `{}`) |
| 2 | `/usr/share/kristall/defaults/settings.d/*.json`, sorted by file name | each component, at image build |
| 3 | `/etc/kristall/settings.d/*.json`, sorted by file name | machine administrator (optional) |
| 4 | `$XDG_CONFIG_HOME/kristall/settings.json` (default `~/.config/kristall/settings.json`) | `kristall-settings set/unset` only |

Merging is a **deep merge**: JSON objects merge key by key, recursively; any other value (string,
number, boolean, null, array) replaces the earlier one. A later layer wins.

Each file must contain one JSON object (UTF-8). A missing file is `{}`. An unreadable or invalid
file is ignored with a warning on stderr (fail soft); the build fails instead if a file in
`settings.d/` is invalid (`kristall-settings check-defaults`).

### Contributing defaults (components)

- Install exactly one file `/usr/share/kristall/defaults/settings.d/NN-<component>.json`
  (`$KRISTALL_PREFIX/share/...`) from your `image/install.sh`. `NN` is two digits; use `50` unless
  you must override another component's default (then use a higher number and say why).
- Put only the keys your component owns (table below). `<component>` in the file name is the owner
  name in that table: the file name is how `check-defaults` knows who is speaking.
- Defaults must be complete enough that a reader never needs a hard-coded fallback.

### Ownership

*(Revised 2026-11-16, additive: second-level ownership, the `owners` command, enforcement.)*
Every top-level key has one owner — the only component that ships defaults for it. Where several
components share a top-level key, ownership is declared **at the second level**: `assistant.hands`
and `assistant.ui` belong to their components, `assistant.*` (every other second-level key) to
`assistant-core`. `kristall-settings check-defaults` enforces this for every drop-in in layer 2:

- a drop-in named `NN-<component>.json` that sets a key (or, for a shared key, a second-level key)
  owned by another component → `ERROR`, exit 3 (the image build fails);
- a shared top-level key that is not an object → `ERROR`;
- a key nobody has declared yet → `WARN` (add a row here and to `OWNERS` in `kristall-settings`
  in the same change); a file not named `NN-<component>.json` → `WARN`, not checked;
- the same owned key in two drop-ins → `WARN` (later wins);
- layer 3 (`/etc/kristall/settings.d`, the machine administrator) may set anything.

`kristall-settings owners` prints the table as JSON (`{"<key>": "<owner>" | {"*": …, "<second>": …}}`);
`image/tests/test_settings.py` checks that it equals the table below.

| Key | Owner (drop-in) | Keys below it (from the drop-ins, 2026-11-16) | Also written at runtime by |
|---|---|---|---|
| `appearance` | `shell` | `theme` auto\|light\|dark, `glass` 0..1, `accent`, `glassQuality` auto\|high\|efficient, `reduceTransparency` (glass keys: `glass.md` §2) | Control Center and Search (`theme`), hands (`theme`, `glass`, `reduceTransparency`), setup |
| `accessibility` | `shell` | `reduceMotion`, `increaseContrast` | setup |
| `bar` | `shell` | `showSeconds`, `showDate`, `showDayOfWeek`, `showBatteryPercentage`, `clock`, `dimWhenMaximized`, `showAssistant`, `showControlCenter` | setup |
| `dock` | `dock` | `size`, `magnification`, `magnifiedSize`, `autoHide`, `minimizeToApp`, `pinned` (null = the app manifest's default) | setup |
| `panels` | `panels` | `focus.until` (Do Not Disturb: 0 off, -1 until switched off, else ms since the epoch), `mutedApps` | Search, hands (`focus.until`) |
| `assistant.*` | `assistant-core` | `enabled`, `name`, `language`, `owner_name`, `voice.de`, `voice.en`, `speaking_rate`, `input_mode`, `speak_replies`, `recognizer`, `barge_in`, `wake_word`, `duck_other_audio`, `model`, `effort`, `conversation_window_seconds`, `end_of_speech_ms`, `no_speech_timeout_seconds`, `max_utterance_seconds`, `models_unload_after_seconds`, `brain_unload_after_seconds`, `permission_timeout_seconds` | setup, the assistant interface |
| `assistant.hands` | `assistant-hands` | `cursor.enabled`, `cursor.speed`, `cursor.linger_seconds`, `accessibility`, `screenshot.max_width`, `screenshot.max_height`, `snapshot.max_items`, `snapshot.max_depth`, `protected_apps` (`hands.md` §7) | setup |
| `assistant.ui` | `assistant-ui` | `light.enabled`, `light.intensity`, `light.maxFps`, `light.cornerRadius`, `holdMs` | setup |
| `power` | `power` | `automatic`, `batteryBase` quiet\|balanced, `batteryRefreshRate`, `dimOnBattery`, `chargeLimit`, `lowBatteryQuiet`, `heavyApps` (`power.md` §8) | setup, Control Center |
| `keyboard` | `setup` | `macShortcuts`, `commandKey`, `passthroughApps`, `terminalApps` (`setup/data/settings.json`) | — |
| `setup` | `setup` | `done`, `running`, `step`, `skipped`, `version` | the shell's setup module |

Components and their drop-ins: `shell` = shell-core `50-shell.json`; `dock` = `shell/modules/dock`
`50-dock.json`; `panels` = `shell/modules/panels` `50-panels.json`; `assistant-core` =
`assistant/core` `50-assistant-core.json`; `assistant-hands` = `assistant/hands`
`50-assistant-hands.json`; `assistant-ui` = `shell/modules/assistant` `60-assistant-ui.json`;
`power` = `power` `50-power.json`; `setup` = `setup` (its drop-in is `NN-setup.json`; not installed
yet on 2026-11-16). Search, Apps, the switcher, `theme`, `glass` and the bridge own no key (Search and
the theme only read or write the keys above).

**Runtime writes** are not ownership: any component may change another component's key with
`kristall-settings set` where the last column lists it (an owner-facing control for that setting),
and readers must accept every value the owner's row allows. Writing a key not listed there needs a
row change here first. Nobody but the owner ships a default for it.

## Paths

A PATH is dot-separated object keys, e.g. `appearance.glass`. Each segment matches
`[A-Za-z0-9_-]+`. A purely numeric segment indexes an array when reading (`bar.items.0`); writes
always treat segments as object keys. Keys containing `.` cannot be addressed (do not create them).
An empty PATH (or `.`) means the whole document.

## Command line

All output goes to stdout as compact JSON on one line, UTF-8, terminated by `\n`.
Diagnostics go to stderr.

| Command | Effect | Output |
|---|---|---|
| `get [PATH]` | effective value (all layers merged) | the JSON value |
| `get --defaults [PATH]` | layers 1–3 only | the JSON value |
| `get --user [PATH]` | layer 4 only | the JSON value |
| `set PATH JSON` | store the value in the user file | none |
| `set --string PATH TEXT` | store TEXT as a JSON string (no quoting) | none |
| `unset PATH` | remove PATH from the user file; empty parent objects are pruned | none |
| `watch [--full] [--initial] [PATH...]` | stream changes, never exits on its own | JSON lines (below) |
| `check-defaults` | validate layers 1–3: JSON, and key ownership (§ Ownership) | `OK/WARN/ERROR <file>[: reason]` lines |
| `owners` | the ownership table *(addition)* | JSON object |
| `paths` | files read, in merge order | `{"defaults":[...],"user":"..."}` |
| `--version` | interface version | `1` |

`set` with a value equal to the current user-file value does not touch the file (no watch event).
`set PATH` on the empty path replaces the whole user file and requires an object.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | `get`: PATH does not exist (nothing printed on stdout) |
| 2 | usage error (unknown command/option, invalid PATH) |
| 3 | `set`: VALUE is not valid JSON / `check-defaults`: a defaults file is invalid or sets a key its component does not own |
| 4 | I/O error (e.g. cannot write the user file) |

## Writes

- Only the user file is ever written. Writers take an exclusive `flock` on
  `~/.config/kristall/.settings.lock`, read the user file, modify, write a temporary file in the same
  directory, `fsync`, `rename` over `settings.json`, `fsync` the directory. Readers never lock and
  always see either the old or the new complete file.
- The user file is mode 0600, pretty-printed with sorted keys.
- If the user file is not valid JSON when a write happens, it is moved to
  `settings.json.broken-<unix time>` and a fresh file is started (warning on stderr).
- Programs other than `kristall-settings` must not write the user file. Reading it directly is
  allowed but discouraged (you would have to re-implement the merge).

## `watch`

Uses inotify on the directories of all layers (no polling; idle cost is zero CPU). Bursts of file
events within 50 ms are coalesced. After each change the effective document is recomputed and
compared with the previous one.

Default output, one line per changed **leaf** (a leaf is a scalar, an array, or an empty object),
sorted by path:

```json
{"path":"appearance.theme","value":"dark"}
{"path":"dock.size","value":null,"removed":true}
```

`removed: true` appears only when the path no longer exists in any layer.

With PATH arguments only leaves at or below one of those paths are reported (a change of a parent
that replaces the filtered path is reported too). `--initial` first prints every current leaf
(filtered) as if it had just changed. `--full` prints the whole effective document instead, one
line per change: `{"settings":{...}}`; with PATH filters `{"settings":{"<path>":<value or null>,...}}`.

`watch` creates `~/.config/kristall/` if missing, survives the user file being deleted, renamed or
replaced, notices drop-in files appearing in `settings.d`, exits 0 on SIGTERM/SIGINT or when its
stdout is closed.

### From QML

```qml
Process {
    command: ["kristall-settings", "watch", "--initial", "appearance"]
    running: true
    stdout: SplitParser { onRead: line => root.apply(JSON.parse(line)) }
}
// write: Quickshell.execDetached(["kristall-settings", "set", "appearance.glass", "0.4"])
```

### From shell

```sh
theme=$(kristall-settings get appearance.theme)      # -> "dark" (JSON, with quotes)
kristall-settings set --string appearance.theme dark
kristall-settings watch power | while read -r line; do ...; done
```

## Test hooks (not for production use)

`KRISTALL_SETTINGS_DEFAULTS` (layer-1 file), `KRISTALL_SETTINGS_DROPIN_DIRS` (colon-separated,
replaces layers 2–3), `KRISTALL_SETTINGS_FILE` (user file), `XDG_CONFIG_HOME`.
