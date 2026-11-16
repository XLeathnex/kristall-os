# Contract: system and app updates (`kristall-update`)

Owner: `image` component. Implementation: `image/rootfs/usr/bin/kristall-update` (Python 3,
standard library), systemd units in `image/rootfs/usr/lib/systemd/`, polkit rule
`/usr/share/polkit-1/rules.d/50-kristall-update.rules`. Tests: `image/tests/test_update.py`.

## Model

- The OS is a bootc image (`ghcr.io/<owner>/kristall-os:latest`). An update is downloaded in the
  background and **staged**; the running system is never changed. The staged version becomes active
  at the next restart (whenever the owner restarts; we never restart on our own).
- The previous version stays installed. **Rollback** queues it for the next start (one step).
- System-wide Flatpak apps are updated in the same run (running apps keep their old version until
  they are closed).
- Automatic runs: `kristall-update.timer` (15 min after boot, then every 6 h, ±30 min jitter) starts
  `kristall-update.service` → `kristall-update auto`, at idle CPU/IO priority. It **waits** (does
  nothing, records why) when: offline (NetworkManager connectivity none/portal/limited), on a
  metered connection (NM `Metered` yes/guess-yes), or on battery below `min_battery_percent`
  (default 30; peripheral batteries are ignored). A connected charger lifts the battery condition.
- Manual `apply` ignores the metered condition and only refuses below 10 % battery without charger.

## Command line

`kristall-update <command> [options]`. With `--json` the command prints exactly one line: the
**status object** (below). Exit code 0 = success, 1 = the operation failed (details in
`last_error`), 2 = usage error.

| Command | Who | Effect |
|---|---|---|
| `status [--json]` | anyone, no privileges | current state; human text (de/en by locale) without `--json` |
| `check [--json] [--no-wait]` | active local user, no password | ask the registry whether a newer image exists (metadata only, kilobytes) and count pending Flatpak updates |
| `apply [--json] [--no-wait] [--restart]` | active local user, no password | download + stage the OS update and update Flatpaks now; `--restart` then restarts (gracefully) if something was staged |
| `rollback [--json] [--restart]` | administrator password (graphical prompt, remembered ~5 min) | queue the previous version for the next start; no-op if already queued |
| `rollback --cancel [--json]` | administrator password | undo a queued rollback |
| `restart` | active local user | graceful restart: asks Plasma (`org.kde.Shutdown.logoutAndReboot`) so apps can save their work; falls back to `systemctl reboot` |
| `auto` | root (timer) | conditional automatic update |
| `refresh` | root (boot) | record the deployments for unprivileged `status` |
| `notify` | user session | desktop notification, see below |

Unprivileged `check`/`apply`/`rollback` start the matching oneshot unit
(`kristall-update-{check,apply,rollback,rollback-cancel}.service`) via `systemctl start`, which
waits for it (unless `--no-wait`; then poll `status` or watch the state file). The polkit rule
allows `start` of the check/apply units for `subject.active && subject.local` without
authentication, and requires `auth_admin_keep` for the rollback units. The prompt is shown by the
session's polkit agent (Plasma), never in a terminal. Only one root operation runs at a time
(`/run/kristall-update/lock`); others wait (manual) or skip (automatic).

## Status object (schema 1)

```json
{
  "schema": 1,
  "state": "up-to-date",
  "bootc": true,
  "booted":   {"version": "45.20261115.3", "image": "ghcr.io/owner/kristall-os:latest", "transport": "registry",
               "digest": "sha256:…", "timestamp": "2026-11-15T03:40:00Z", "pinned": false, "download_only": false},
  "staged":   null,
  "rollback": {"version": "45.20261114.2", "...": "same fields as booted"},
  "available": null,
  "can_rollback": true,
  "rollback_queued": false,
  "running": false,
  "operation": null,
  "last_check": "2026-11-15T09:12:03Z",
  "last_update": "2026-11-15T09:12:03Z",
  "last_result": "ok",
  "last_error": null,
  "waiting_reason": null,
  "flatpak": {"updates_pending": 0, "last_updated": "2026-11-15T09:12:03Z"},
  "automatic": true
}
```

`state` (exactly one; checked in this order):

| state | meaning | suggested UI |
|---|---|---|
| `checking` / `downloading` / `rolling-back` | an operation is running (`running: true`, `operation` = `check`/`auto`/`apply`/`rollback`/`rollback-cancel`) | spinner, "Searching…"/"Downloading…" |
| `rollback-queued` | previous version starts after the next restart | "Restart to go back" + Restart, "Undo" (`rollback --cancel`) |
| `restart-required` | an update is staged (`staged` set) | "Update ready – restart to finish" + Restart |
| `update-available` | registry has a newer image than booted/staged (`available` set, from the last check) | "Update available" + Install (`apply`) |
| `error` | last operation failed (`last_error`) | show `last_error.de`/`.en`, offer "Try again" (`check`) |
| `up-to-date` | none of the above | "Kristall OS is up to date", version, `last_check` |
| `unknown` | not a bootc system / no status recorded yet | hide the panel or show "unknown" |

`last_error`: `{"code": "...", "en": "...", "de": "...", "detail": "<tool output, max 2000 chars>"}`.
Codes: `offline`, `metered`, `battery-low`, `busy`, `not-bootc`, `download-failed`,
`flatpak-failed`, `no-rollback`, `rollback-failed`, `permission-denied`, `failed`.
`waiting_reason` (automatic runs that decided to wait): `offline`, `metered`, `battery-low`,
`auto-disabled`. Waiting is not an error.

Times are UTC ISO-8601 (`Z`). Unknown fields must be ignored by readers; new fields may appear
without a schema bump; a breaking change bumps `schema`.

## Files

| Path | Content | Access |
|---|---|---|
| `/var/lib/kristall/update/state.json` | persistent state (last check/result/error, flatpak counters) | world-readable, written atomically by root |
| `/var/lib/kristall/update/bootc-status.json` | last `bootc status --format=json` | world-readable |
| `/run/kristall-update/lock` | held while a root operation runs | world-readable |
| `/etc/kristall/update.json` | optional machine config: `{"automatic": true, "min_battery_percent": 30, "allow_metered": false, "update_flatpaks": true}` | root |

A settings screen can avoid polling by watching `state.json` with inotify (it is replaced by
rename on every change) and then calling `kristall-update status --json`.

## Notification

User units `kristall-update-notify.path` (watches `state.json`) and
`kristall-update-notify.service` (also run at session start), enabled for every user by preset.
They run `kristall-update notify`: when `state` is `restart-required` (or `rollback-queued`) and the
owner has not been told yet **in this login session** for this exact version, it shows a normal
notification ("Update ready" / "Update bereit") with the actions "Restart now" / "Later"
("Jetzt neu starten" / "Später"). "Restart now" performs the graceful restart.

## Not handled here

User-scope Flatpaks (`flatpak --user`) are updated by the base image's `flatpak-user-update.timer`.
Firmware updates (fwupd) are not automated. The base's `rpm-ostreed-automatic.timer` and
`flatpak-system-update.timer` are disabled, `bootc-fetch-apply-updates.timer` (reboots by itself)
is masked.
