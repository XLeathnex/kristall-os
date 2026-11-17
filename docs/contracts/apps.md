# Contract: default apps (`apps.json`, `kristall-apps`)

Owner: `image` component. Source: `image/apps/apps.json` (justification per app:
`image/apps/README.md`). Installed to `/usr/share/kristall/apps/apps.json`. Tool:
`/usr/bin/kristall-apps`. Tests: `image/tests/test_apps.py`.

Consumers: the Dock and Apps grid (`shell`), the Setup Assistant (`setup`), the installer ISO build.

## Manifest (schema 1)

```json
{
  "schema": 1,
  "apps": [
    {
      "id": "blender",
      "kind": "flatpak",
      "flatpak": {"id": "org.blender.Blender", "remote": "flathub", "branch": "stable",
                  "overrides": ["--filesystem=host-etc:ro"]},
      "embed_in_iso": true,
      "package": "dolphin",
      "desktop_id": "org.blender.Blender.desktop",
      "name": {"en": "Blender", "de": "Blender"},
      "category": "graphics",
      "default": true,
      "show_in_apps": true,
      "dock": 5,
      "license": "GPL-3.0-or-later",
      "proprietary": false
    }
  ]
}
```

| Field | Type | Rules |
|---|---|---|
| `id` | string | stable Kristall identifier, `^[a-z0-9][a-z0-9-]*$`, unique, never reused for a different app. Use it to store per-app user choices (e.g. a Dock customisation). |
| `kind` | `"rpm"` \| `"flatpak"` | `rpm`: part of the OS image. `flatpak`: installed from Flathub on first boot (or copied from the installer). |
| `package` | string | `rpm` only: RPM name in the image. |
| `flatpak.id` | string | `flatpak` only: Flathub application ID. |
| `flatpak.remote` | string | optional, default `flathub`. |
| `flatpak.branch` | string | optional, default: the remote's single branch (`stable`). |
| `flatpak.overrides` | string[] | optional `flatpak override --system` options applied after install. |
| `embed_in_iso` | bool | `flatpak` only: may be copied onto the installer USB stick. Always `false` for proprietary apps (we do not redistribute them). The current installer embeds **no** apps (2026-11-17: with them the ISO was 11.8 GB); every default app is installed on first start by `kristall-apps-provision` — the field marks what an offline edition would carry. |
| `desktop_id` | string | the `.desktop` file name to launch (`gtk-launch`/`KService` ID), unique. |
| `name.en`, `name.de` | string | display names we author (may differ from the app's own name, e.g. "Dateien"). |
| `product_names` | string[] | optional *(added 2026-11-17, additive)*: the names the app itself puts into its window titles — Qt appends its display name ("Home — Dolphin", "Unbenannt — KWrite", in German also "… — Systemeinstellungen"). Whoever shows a window title to the owner replaces a trailing ` — <product name>` (or a title that is only the product name) with `name.<lang>`: the window decoration (`theme`), the Dock's and menu bar's window lists (`shell`), the app switcher (`shell`), Overview (`kwin`/`shell` override). The app's own title is never changed. |
| `category` | enum | `system`, `internet`, `media`, `graphics`, `games`, `developer`, `utilities`, `productivity` |
| `default` | bool | part of the default installation. |
| `show_in_apps` | bool | `false`: works (file associations) but is not listed in Apps/Search; such entries also carry `NoDisplay=true`. |
| `dock` | int \| null | position in the default Dock, 1 = leftmost; positions are 1..N without gaps. A docked app must have `show_in_apps: true`. |
| `license` | string | SPDX expression or `LicenseRef-…`. |
| `proprietary` | bool | not free software. |

Array order = installation order for first-boot provisioning. Readers must ignore unknown fields.
Display: use `name.<lang>` with the system language; fall back to `en`. The icon is the one named
in the desktop file. An app may be absent on a given machine (owner removed it, download still
pending): check before showing it (`kristall-apps list --installed` or the desktop file's presence).

The manifest is validated at image build time; an invalid manifest fails the build.

## `kristall-apps`

| Command | Output |
|---|---|
| `list [--default] [--dock] [--embed] [--installed]` | `{"schema":1,"apps":[...]}` filtered; `--dock` sorts by `dock`; `--installed` adds `"installed": bool` per app |
| `list ... --flatpak-ids` | one Flatpak ID per line |
| `status [--json]` | provisioning progress (below); human text de/en without `--json` |
| `validate [FILE]` | exit 0 if valid, 3 with `ERROR …` lines otherwise |
| `provision` | root only (systemd): install missing default Flatpaks |

## First-boot provisioning

`kristall-apps-provision.timer` (45 s after boot, then every 10 min) starts
`kristall-apps-provision.service` → `kristall-apps provision` (low CPU/IO priority) until all default
Flatpaks are present; then it stops the timer for the rest of that boot (one cheap check per boot
afterwards). Behaviour:

- Apps already installed (e.g. copied from the installer ISO) are only marked done.
- Offline (NetworkManager connectivity < full): status `waiting-for-network`, retried later.
- A failed download is recorded per app and retried on the next run.
- Every app is installed **once**: if the owner later removes it, it is not reinstalled
  (`/var/lib/kristall/apps/state.json` → `provisioned`). New default apps added by a later image
  update are installed on the next boot.
- On Intel graphics the Flatpak VA-API driver extension is installed for each freedesktop runtime.
- *(addition, 2026-11-16)* Runtimes and extensions listed under the manifest's optional top-level
  `"runtimes"` (`[{"id": "<Flathub runtime/extension id>", "branch": "<branch>", "remote"?:
  "flathub", "why"?: "…"}]`) are installed after the apps as `runtime/<id>/<default arch>/<branch>`,
  once each (`state.json` → `runtimes_provisioned`; an owner's removal is respected), best effort:
  a failure is logged, retried on the next run, and does not count as a failed app (not in
  `status.json`). Today: `org.gtk.Gtk3theme.adw-gtk3` and `org.gtk.Gtk3theme.adw-gtk3-dark`
  (branch `3.22`), so GTK 3 Flatpak apps follow the theme component's adw-gtk3 look.
- Never runs in the installer's live session.

### Status file `/var/lib/kristall/apps/status.json` (world-readable, replaced atomically)

```json
{
  "schema": 1,
  "state": "installing",
  "total": 10,
  "done": 4,
  "current": {"id": "blender", "name": {"en": "Blender", "de": "Blender"}},
  "failed": [{"id": "steam", "error": "error: Unable to load summary from remote flathub"}],
  "reason": null,
  "items": [{"id": "music", "flatpak": "org.kde.elisa", "name": {"en": "Music", "de": "Musik"},
             "state": "installed"}],
  "updated": "2026-11-15T10:02:11Z"
}
```

`state`: `not-started` (no file yet; `status --json` synthesises it), `installing`,
`waiting-for-network` (`reason: "offline"`), `done`, `error` (some items failed; will retry).
Item `state`: `pending`, `installing`, `installed`, `skipped` (installed once before), `failed`.
`done` counts `installed` + `skipped`. Suggested text: "Installing your apps… {done} of {total}" /
"Deine Apps werden installiert … {done} von {total}". Watch the file with inotify instead of polling.
