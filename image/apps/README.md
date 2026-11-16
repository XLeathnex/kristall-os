# Kristall OS default apps

The machine-readable list is [`apps.json`](apps.json) (contract: [`docs/contracts/apps.md`](../../docs/contracts/apps.md)).
This file says **why** each app is there. Rule of thumb: what a Mac owner expects to find on a new
Mac, plus what this owner said they use, and nothing else. Everything else is one click away in
the App Center.

**Where an app comes from.** Part of the system (file manager, browser, terminal, screenshot,
settings) → RPM in the OS image: updated and rolled back together with the OS, always present.
Everything else → Flatpak from Flathub, installed on first start (or copied from the installer USB
stick), updated in the background by `kristall-update`. Flatpak IDs were checked against Flathub's
API on 2026-11-15 (`verified-flatpak-ids.txt`, refreshed by `image/tests/verify-flathub.sh`; CI
re-checks on every build). RPM names were checked against the Fedora 45 + fedora-multimedia
repositories the base uses (`image/tests/verify-fedora-packages.sh`).

## The set

| Shown as (en / de) | App | Source | Why this one |
|---|---|---|---|
| Files / Dateien | Dolphin | RPM (base) | Plasma's file manager; tabs, previews, network shares. Integrates with the desktop (trash, devices, "Open with"). |
| Firefox | Firefox | RPM (base) | Fedora's Firefox, built against the image's full ffmpeg and Intel VA-API driver, so **video in the browser is hardware-decoded** (we set `media.hardware-video-decoding.enabled` and `media.ffmpeg.vaapi.enabled`). It updates with the OS every day. A Flatpak Firefox would depend on Flatpak's separate codec/driver extensions. |
| Music / Musik | Elisa | Flatpak | KDE's music player: library view, album art, simple — the closest to the Mac's Music app without a store. |
| Video Player / Videoplayer | Haruna | RPM (added) | mpv-based, clean UI, hardware decoding is on by default (`hwdec=auto`). As an RPM it uses the same VA-API + ffmpeg stack as Firefox (Intel iHD driver and full ffmpeg from the base's fedora-multimedia repo), so **hardware decoding works the same way in the browser and the player**. |
| Image Viewer / Bildbetrachter | Gwenview | Flatpak | Fast viewer with basic edits (crop, rotate, resize, red-eye). |
| Document Viewer / Dokumentbetrachter | Okular | Flatpak | PDFs, e-books, annotations, form filling, signatures. |
| Text Editor / Texteditor | KWrite | RPM (base) | The simple editor (like TextEdit). Kate, its developer-oriented sibling, is hidden — VS Code covers that. |
| Calculator / Rechner | KCalc | Flatpak | Small, standard + scientific modes. |
| Screenshot / Bildschirmfoto | Spectacle | RPM (base) | Talks to KWin directly (region, window, screen, recording). Must be part of the system. |
| System Monitor / Systemmonitor | Plasma System Monitor | RPM (base) | The Activity-Monitor equivalent. |
| Archive Utility / Archivprogramm | Ark | RPM (base) | Opens/creates zip, 7z, tar … when the owner double-clicks one; hidden from the app list like the Mac's Archive Utility. |
| Terminal | Konsole | RPM (base) | Kept visible: the owner does AI-assisted coding (Claude Code runs in a terminal). |
| Visual Studio Code | VS Code | Flatpak | Requested by the owner. Microsoft's licence forbids us redistributing it, so it is **downloaded on the laptop from Flathub**, never put in our image or ISO. Its integrated terminal is pre-configured (`/etc/skel/.var/app/com.visualstudio.code/…/settings.json`) to open a real shell on the system (`flatpak-spawn --host bash -l`), so git, node, Claude Code etc. work exactly as in Konsole. |
| Blender | Blender | Flatpak | Requested. The official Blender Foundation build on Flathub (5.3 at the time of writing); on Iris Xe, EEVEE renders on the GPU and Cycles on the CPU (Blender's oneAPI GPU rendering targets Intel Arc, not Iris Xe), which is fine for learning and small scenes. |
| Roblox (Sober) | Sober | Flatpak | **Roblox player.** Roblox has no Linux client and blocks Wine since 2024 (Hyperion anti-cheat). Sober runs Roblox's official *Android* build natively — the only working route today. Requirements: x86-64 CPU with SSE4.2 (the i9-13900H has it), Vulkan 1.0 or OpenGL ES 3.0 (Iris Xe: yes). Limits, honestly: not supported by Roblox and may stop working at any time; closed source (VinegarHQ's choice, to avoid being blocked again), so it is **not embedded in the ISO** but downloaded on first start; on first launch it downloads the Roblox app itself; mobile-client quirks (some highlights look pixelated, occasional touch-style UI in a few experiences); voice chat and controller support depend on the current Sober release. |
| Roblox Studio (Vinegar) | Vinegar | Flatpak | **Roblox Studio.** Vinegar (GPL-3.0, actively maintained, release 1.9.4) downloads the official Windows Studio and runs it with Wine. Works for building and testing; limits: panels may not dock unless the "virtual desktop" option is enabled in Vinegar's settings, occasional flicker, Studio is sometimes wrongly killed as "not responding" (fix announced for the next release), and Roblox updates can break it for a few days. Playing (the player inside Studio's test mode works; joining games from the website uses Sober). TuxBlox, a newer Studio launcher praised on the Roblox developer forum, is **not on Flathub**, so we cannot ship or auto-update it. |
| Steam | Steam | Flatpak | Requested ("light gaming"). The Flathub build brings its own 32-bit graphics drivers and Proton, so nothing extra is needed in the OS image; game controllers work thanks to the `steam-devices` udev rules (RPM). Proprietary: downloaded on the laptop, not embedded. On Iris Xe expect older/indie titles and many 2D/light 3D games at 1080p-ish resolution; performance mode switching is the `power` component's job: it installs GameMode (the RPM, once, in `power/image/install.sh`) and turns a game that registers with it into an automatic Leistung on mains; Steam's Flatpak reaches it through the desktop portal (`gamemoderun %command%` in a game's launch options for games that do not ask by themselves). No overlays are shipped. |
| App Center / App-Center | Bazaar | Flatpak | The only app store the owner sees (Discover stays installed but hidden). Compared with Discover: Bazaar is Flathub-only (no confusing "sources", no system packages it could break on an image-based OS), fast, shows permissions in plain words, has curated pages, and Universal Blue's own KDE desktop (Aurora) made it its default store in 2025, keeping Discover hidden — the same arrangement we use. We hide its own auto-update switches (`/etc/bazaar/bazaar.yaml`) because Kristall OS updates apps by itself; Bazaar gets read access to `/etc` for that config via a Flatpak override. GTK app — the `theme` component styles it with the rest. |
| System Settings / Systemeinstellungen | Plasma System Settings | RPM (base) | Everything not yet covered by Kristall's own settings. |

Dock order: Files, Firefox, Music, VS Code, Blender, Roblox, Roblox Studio, Steam, App Center,
System Settings (the Mac's Dock also starts with the file manager and browser and ends with the
store and settings).

## What we hide (`image/hidden-apps.list`) and remove (`image/packages-remove.list`)

- **Removed** (nothing depends on them): Plasma Welcome (the Kristall Setup Assistant replaces it),
  the offline Help Center (KDE apps open the online handbook instead), Discover's update notifier
  (would announce updates `kristall-update` already handles).
- **Hidden** (`NoDisplay=true`; still installed so nothing breaks): Discover, Kate, htop, nvtop,
  debug settings, journal browser, partition manager, menu editor, wallet manager, colour-scheme
  editor, font viewer, bookmark editor, network-folder wizard, crash-report browser, KDE Connect's
  standalone window, remote-desktop servers, KFind, Filelight, character map, Ark (opens by itself),
  IBus input-method setup tools.

## Not in the default set (and why)

- **Mail, calendar, office suite**: the owner did not ask; browser-based services are the norm and
  LibreOffice / Thunderbird are one click away in the App Center.
- **Flatseal / Warehouse** (Flatpak management): developer tools; the App Center shows permissions.
- **MangoHud, Lutris, ProtonUp**: enthusiast tools. (GameMode is *not* in this list: the `power`
  component installs and configures it — `power/image/install.sh`, `/etc/gamemode.ini` — and its
  automatic mode turns a registered game into Leistung on mains; see `docs/contracts/power.md` §3
  and §5.2. No other component installs it; `image/tests/test_build.sh` checks that.)
- **VSCodium** instead of VS Code: the owner asked for VS Code.

## Developer basics (RPMs in the image, `image/packages.list`)

git (+ git-lfs), GitHub CLI `gh`, Node.js 26 LTS with npm (`nodejs26`, `nodejs26-bin`,
`nodejs26-npm`, `nodejs26-npm-bin`; Fedora 45's plain `nodejs` is still 22), Python 3 + uv,
ripgrep, fd, jq, podman, distrobox, gcc/g++/make (many npm and Python packages compile a native
part on install; without a compiler an AI-generated project fails with an obscure error), curl,
unzip, bubblewrap + socat (Claude Code's sandbox on Linux uses them).

Anthropic's official Claude Code installer (`curl -fsSL https://claude.ai/install.sh | bash`)
installs a self-contained native binary into the user's home directory: it needs `bash`, `curl`
and a writable `~/.local/bin`; ripgrep is used for search, bubblewrap + socat for its sandbox —
all present. **The Claude Code CLI
itself is not shipped**; the Setup Assistant runs the installer for the owner.

## Runtimes and extensions (`"runtimes"` in `apps.json`)

Installed by `kristall-apps provision` after the apps (once, best effort, retried; contract
`docs/contracts/apps.md`): `org.gtk.Gtk3theme.adw-gtk3` and `org.gtk.Gtk3theme.adw-gtk3-dark`
(Flathub, branch 3.22, LGPL-2.1-only) — the theme component styles GTK 3 with adw-gtk3 on the host
(`theme/`), and GTK 3 Flatpak apps only see a host theme when the matching `org.gtk.Gtk3theme.*`
extension is installed. Both exist on Flathub (`github.com/flathub/org.gtk.Gtk3theme.adw-gtk3`,
`…-dark`; checked 2026-11-16); `verify-flathub.sh` checks application IDs only.
