# Kristall OS — architecture and shared rules

Working name: **Kristall OS**. This file is the single source of truth every contributor works from.
Read all of it before writing anything. If your work forces a change to something stated here,
change this file in the same piece of work and say so in your final report.

## 1. Who this is for (this drives every decision)

One person, their own laptop, **not a Linux user and does not want to become one**. Their words:
"I want this to feel like I installed macOS on my laptop." So:

- **No terminal, ever, for the owner.** Installing, first setup, Wi-Fi, updates, installing apps,
  signing in to Claude, changing any setting we add: all of it has a graphical path. If a feature
  needs a command to be typed by the owner, it is not finished.
- **It behaves like an appliance.** Updates arrive by themselves, never break the desktop, and can
  be rolled back. Nothing is compiled or configured on the laptop.
- **It looks and behaves like macOS 27** (see §6), built only from assets we are allowed to use.
- **Fast, cool, quiet, long battery life** are product features, not tuning afterthoughts (§7).
- The owner speaks German and writes English. Every user-visible string we author exists in
  **German and English** (German is the default for the assistant; system language is chosen at setup).

Hardware: Intel Core i9-13900H (Raptor Lake-H, 6 P-cores + 8 E-cores, 20 threads), 16 GB DDR5,
Intel Iris Xe integrated graphics only, 1 TB NVMe SSD, 2880×1800 16:10 internal panel (likely OLED,
likely 120 Hz — detect, never assume), exact laptop model unknown. Uses: AI-assisted coding
("vibecoding", Claude Code), Blender, Roblox Studio + Roblox, light gaming, video/music.

## 2. What we are building

An **image-based operating system**: a bootable container image (bootc / Fedora Atomic) derived from
`ghcr.io/ublue-os/kinoite-main` (Fedora 45 Kinoite: KDE Plasma **6.8.2**, KWin **6.8.2** Wayland,
Qt **6.11.2**, kernel 7.3, `plasma-login-manager` as display manager — not SDDM —, `tuned` +
`tuned-ppd` for power profiles, Flatpak, bootc 1.17). The image is built by GitHub Actions from this
repository, published to a registry, and turned into an installer ISO. The laptop only ever
receives finished, tested images.

Verified facts about the base (image component, 2026-11-15, from the published `kinoite-main:45`
manifest and rpmdb): the `:45` tag is the Fedora 45 stream (same digest as `:latest`), kernel
`7.3.3-300.fc45`, Python **3.15** (`/usr/bin/python3`; the assistant daemon's private environment
runs on Fedora's `python3.14` instead, because its pinned, tested speech library sherpa-onnx 1.13.8
has no build for 3.15 — decided 2026-11-16, revisit with sherpa-onnx 2.x), Firefox is an RPM, `plasma-setup` (KDE's
first-boot account wizard) is included, the negativo17 `fedora-multimedia` repo is enabled (full
ffmpeg, Intel `iHD` VA-API driver), `plasma-discover` is present. Plasma 6.8.3 is already in
Fedora's updates repo and arrives with the next base rebuild. Universal Blue **re-packages**
Fedora's kernel (it adds its own signature to `vmlinuz` and rebuilds the RPM); Fedora's Secure
Boot signature stays on `vmlinuz`, so Secure Boot works with Fedora's shim and no key enrolment, but
the kernel RPM is no longer GPG-signed by Fedora. The image build checks the `vmlinuz` signature.

Why this base: our compositor plugins are C++ compiled against KWin's unstable internal API. In an
image they are always built against the exact KWin they ship with; if a new KWin breaks them the
image build fails and the laptop simply stays on the last good image. A rolling distro would break
the owner's desktop instead.

Consequences every component must respect:

- `/usr` is read-only at runtime. Everything we ship lives under `/usr` (never `/usr/local`, never
  `/opt`): programs `/usr/bin/kristall-*`, private code `/usr/lib/kristall/<component>/`, data
  `/usr/share/kristall/<component>/`, system defaults `/usr/share/kristall/defaults/` or `/etc`.
- Per-user defaults come from `/etc/xdg` and `/etc/skel` (never "run this once per user" scripts
  unless driven by a systemd user unit we ship and preset-enable).
- User state: `~/.config/kristall/`, `~/.local/share/kristall/`, `~/.cache/kristall/`.
  Runtime sockets: `$XDG_RUNTIME_DIR/kristall/`.
- Long-running pieces are **systemd user services** bound to `graphical-session.target`,
  enabled through a preset file, restart-on-failure, and they must start in any order.
- GUI apps the owner installs are Flatpaks (Flathub). We do not layer packages at runtime.

## 3. Repository layout and ownership

```
Containerfile, .containerignore,      image + ISO pipeline            (image)
.github/workflows/, .github/actionlint.yaml
image/                                 base packages, apps, updates    (image)
docs/INSTALL.md                        owner's install guide (de/en)   (image)
power/                                 performance, battery, thermals  (power)
kwin/glass/                            Liquid Glass compositor effect  (glass)
kwin/bridge/                           window/input/screenshot bridge  (bridge)
shell/                                 the desktop shell (Quickshell)  (shell-core, shell-apps, assistant-ui)
assistant/core/                        assistant daemon: brain + voice (assistant-core)
assistant/hands/                       computer-control tool server    (hands)
theme/                                 app theming, login, lock, boot  (theme)
setup/                                 first-run Setup Assistant, Kristall settings, keyboard (setup)
tools/devenv/                          build/test container
docs/ARCHITECTURE.md, docs/contracts/  this file + interface specs
```

Work only inside the directories you own. If you need something from another component, use its
documented contract; if the contract is missing something, say so in your report rather than
editing someone else's code.

### Component contract (identical for every component directory `X/`)

- `X/image/install.sh` — executed as root during the OS image build with the repository mounted
  read-only at `/ctx` and network available. Installs build dependencies with `dnf5`, builds,
  installs into `/usr` and `/etc`, removes build-only dependencies it added. `set -euo pipefail`,
  non-interactive, idempotent, no reliance on `$HOME`, no writes to `/var` that must persist
  (`/var` is not part of the image), no `/usr/local`. Honour `KRISTALL_PREFIX` (default `/usr`).
  Run by `image/build.sh` in the order of `image/components.list` (image, power, kwin/glass,
  kwin/bridge, shell, shell/modules/panels, shell/modules/dock, shell/modules/search,
  shell/modules/apps, shell/modules/switcher, shell/modules/assistant, assistant/core,
  assistant/hands, theme, setup — the list's header states the ordering needs; a shell module with
  its own `image/install.sh` is a component directory of its own and gets a line there, unless the
  installer of a listed component runs it, as `setup` does for `shell/modules/setup`) with cwd = `X/` and
  `KRISTALL_CTX`, `KRISTALL_PREFIX`, `KRISTALL_COMPONENT`, `KRISTALL_STRICT` set. A non-zero exit
  fails the build naming `X`. Writing `/usr/local` or `/opt` is reported (fatal in strict builds);
  `/var` and `/tmp` are emptied afterwards. Never install a kernel, kernel module or `kmod-*`
  package (the build fails: Secure Boot must keep working without the owner doing anything).
- Enable units only through a preset file you add:
  `/usr/lib/systemd/system-preset/50-kristall-X.preset` and/or
  `/usr/lib/systemd/user-preset/50-kristall-X.preset`. After all components ran, the build applies
  every *added* preset file (`systemctl preset`, `systemctl --global preset` — the latter makes
  user units active for every user, including users created later). Do not edit base preset files.
- Units that start first-run flows or modify the system must not run in the installer's live
  session: add `ConditionKernelCommandLine=!rd.live.image` (the live system also has
  `/etc/kristall/live`).
- `X/README.md` — what it is, how to build and test it in the dev container, known limits.
- `X/tests/run.sh` — runs inside the dev container, exits non-zero on failure, prints what it checked.
- `docs/contracts/<name>.md` — the precise interface other components consume (sockets, message
  formats, file locations, CLI). Write it as a spec, not a tutorial. Keep it true.

### Shared settings

One file: `~/.config/kristall/settings.json`, defaults in `/usr/share/kristall/defaults/settings.json`
(merged: user file overrides defaults key by key). Keys are owned by components (the full table, with
every key below them, is `docs/contracts/settings.md` § Ownership):
`appearance` (shell-core: theme light|dark|auto, `glass`: 0.0 ultra-clear … 1.0 fully tinted, accent
colour, `glassQuality`: auto|high|efficient, `reduceTransparency`: bool — the glass keys are specified
in `docs/contracts/glass.md` §2), `accessibility` (shell-core: `reduceMotion`, `increaseContrast`;
Reduce Transparency stays `appearance.reduceTransparency`), `bar` (shell-core), `dock` (Dock module),
`panels` (shell module panels: Do Not Disturb `panels.focus.until`, muted apps —
`shell/modules/panels/README.md`), `assistant` — **shared, owned at the second level**:
`assistant.hands` (hands), `assistant.ui` (the assistant interface), every other `assistant.*`
(assistant-core) —, `power` (power, incl. `power.batteryBase`), `keyboard` and `setup` (setup).
Search, Apps, the switcher, theme, glass and the bridge own no key. Owning means shipping the
default; other components may still *write* a key at runtime as the owner-facing control for it
where the settings contract lists them (Search and Control Center write `appearance.theme` and
`panels.focus.until`, hands writes appearance and Do Not Disturb). Writers replace the file
atomically (write temp + rename); readers watch it and apply changes live. The `image` component
ships `/usr/bin/kristall-settings` (`get <path>`, `set <path> <json>`, `watch`, `check-defaults`,
`owners`) so shell scripts and QML (via a process) share one implementation.
Components contribute their defaults as drop-ins `/usr/share/kristall/defaults/settings.d/NN-<component>.json`
(only the keys they own; `check-defaults` enforces it and fails the image build otherwise), deep-merged in file-name order on top of `settings.json`, then
`/etc/kristall/settings.d/*.json`, then the user file. Only `kristall-settings` writes the user file.
Spec: `docs/contracts/settings.md`. Other image-level contracts: `docs/contracts/update.md`
(`kristall-update`, update status for the settings UI) and `docs/contracts/apps.md` (default app
manifest for the Dock and the Setup Assistant, first-boot app installation progress).

### First start (hand-off between installer, image and setup)

The installer only asks for language and disk. On first boot KDE's **Plasma Setup** (part of the
base; the `theme` component styles it, `setup` may add pages to it as KPackage modules) asks
language, keyboard, time zone, Wi-Fi and creates the owner's account (in group `wheel`), then logs
them straight in. The `setup` component's Setup Assistant starts at that first login (a user unit
or autostart that runs once, e.g. conditioned on `~/.config/kristall/settings.json` → `setup.done`).
Meanwhile `kristall-apps-provision` installs the default Flatpaks; progress is in
`/var/lib/kristall/apps/status.json`.

## 4. The pieces and how they talk

```
                        ┌──────────────────────── KWin (Wayland compositor) ───────────────────────┐
                        │  kristall-glass  (effect: real Liquid Glass)     glass.sock             │
                        │  kristall-bridge (plugin: windows, agent input, screenshots) bridge.sock │
                        └──────────▲─────────────────────────▲───────────────────────▲────────────┘
                                   │ shapes                  │ windows/menus          │ input, screenshots
   Quickshell "Kristall Shell": menu bar · Dock · Control Center · notifications ·    │
   Search-or-Ask · Apps · assistant UI · agent cursor · Setup Assistant               │
                                   ▲ assistant.sock (state, transcript, replies, permission prompts)
                        kristall-assistant (daemon): speech-to-text ⇄ Claude Code (headless, Haiku 5.5) ⇄ speech
                                   │ MCP (stdio)
                        kristall-hands (tool server): see screen, read UI tree, click/type via bridge,
                        windows, apps, files, system settings
```

All three sockets live in `$XDG_RUNTIME_DIR/kristall/`, are mode 0600, speak **newline-delimited
JSON (UTF-8, one object per line)**, and every server must tolerate clients connecting before it is
ready, disconnecting at any time, and reconnecting (clients retry with backoff). Contracts:
`docs/contracts/glass.md`, `bridge.md`, `assistant-ipc.md`, `hands.md`, `design.md`, `shell.md`
(how shell modules plug in, layer-shell namespaces, `kristall-shellctl`, global shortcuts).

The Plasma session stays underneath (KWin, portals, polkit agent, power management, screen locker,
System Settings, the desktop/wallpaper containment of `plasmashell` with **all Plasma panels removed**:
shell-core's look-and-feel package `org.kristall.desktop` provides the panel-less default layout, see
`docs/contracts/shell.md` §10 — the `theme` component extends that package rather than replacing the
layout).
Our shell replaces the panels, launcher, notifications UI and OSDs.

## 5. Non-negotiable rules

1. **No Apple property.** No Apple fonts (SF Pro etc.), SF Symbols, Apple logo, macOS wallpapers,
   icons, sounds, or copied artwork; no Apple product names in our UI ("Siri", "Finder", "Spotlight",
   "Launchpad", "Mission Control"). We reproduce layout, behaviour and material; we draw or source
   our own assets under open licences (record source + licence in `X/ASSETS.md`). Typeface: Inter.
   Symbols: an openly licensed set. Neutral names: Search (Suche), Files (Dateien), Apps,
   Overview (Übersicht), Assistant.
2. **Licences.** Our code: GPL-3.0-or-later (KWin-derived code keeps its GPL-2.0-or-later headers
   and attribution). Third-party code/assets only with a licence that permits redistribution;
   keep notices. Do not bundle the Claude Code CLI or any proprietary binary into the image.
3. **Idle means idle.** No timers faster than 1 Hz, no animations, no polling loops, no repaints
   when nothing changes. Animate only in response to input or events, then stop. Anything that keeps
   the CPU out of deep sleep or forces the compositor to redraw every frame is a bug.
4. **Fail soft.** If the glass effect, the bridge, or the assistant is missing or crashes, the
   desktop stays usable: shell falls back to plain translucent materials, Dock still launches apps,
   assistant UI says it is unavailable. Never a black screen, never a crash loop.
5. **Security.** The bridge can inject input and capture the screen: only same-user peers, and the
   powerful calls only from our own installed binaries. The assistant asks before anything
   destructive, irreversible, costing money, or touching credentials. Never log secrets.
6. **Truthful reporting.** Say exactly what you ran and saw. Anything not exercised on real
   hardware (most of this) must be listed as unverified, with the reason.

## 6. The look: macOS 27 "Golden Gate", in our own materials

macOS 27 keeps macOS 26's Liquid Glass and refines it: more uniform refraction, better contrast,
a user slider from **ultra-clear to fully tinted**, uniform toolbars, sidebars that run edge to edge,
refined window shapes, redrawn menu-bar icons, a menu bar that dims when a window is maximised, and
Search with a **"Search or Ask"** mode that hands the question to the assistant.

What "real Liquid Glass" means here (and what separates it from "glassmorphism" = blur + tint):
the compositor **bends** the pixels behind a glass shape. Each shape is a rounded lens: flat in the
middle, curved toward the rim, so content near the edge is displaced and slightly magnified/compressed
following the shape's outline (including corners); a faint chromatic split along the rim; a bright
specular rim light and soft inner shadow that give thickness; background blur that is lighter than
classic frosted glass; a tint layer whose strength follows the user's slider; and automatic
legibility (glass over bright content darkens its tint, over dark content lightens it). Glass shapes
near each other may visually merge. It is computed live from the real screen content behind it.

Desktop anatomy to reproduce: translucent menu bar (app name in bold, the app's menus, status items,
Control Center, clock); centred floating Dock with magnification, running dots, launch bounce;
Control Center of glass tiles and thick capsule sliders; notification banners top-right and a
notification/widgets panel; centred Search field with results list; Apps grid; window "traffic
light" buttons top-left; large continuous-curvature window corners with soft layered shadows; Overview
of all windows; minimise that flows into the Dock; app switcher; volume/brightness HUD; full-screen
lock screen with large clock; login screen. Keyboard: Mac-style shortcuts with the key next to the
space bar acting as Command (configurable in setup).

`docs/contracts/design.md` (owned by shell-core) holds the measured design tokens — sizes, radii,
type scale, colours, motion curves, material parameters — that every visual component uses.

## 7. Performance, battery, heat, noise

Targets, in order: (1) silent and cool for light work — browsing, coding, video — on battery and on
AC; (2) instant-feeling UI (120 Hz where the panel has it, no dropped frames in shell animations on
Iris Xe); (3) full power on demand for Blender/games, automatically, without the owner choosing.
Three owner-facing modes: **Leise** (Quiet), **Ausgewogen** (Balanced), **Leistung** (Performance),
plus automatic switching by power source and workload (the default: Leise on battery from the
start, Ausgewogen on mains, Leistung on mains for games and busy heavy apps; `power.batteryBase`
makes battery Ausgewogen for owners who prefer speed). The `power` component owns this; everyone else
supports it by obeying rule 3 in §5 and by keeping GPU cost of visuals bounded (the glass effect
must not turn a static screen into a continuously rendering one, and must have a cheaper path on
battery). Contract: `docs/contracts/power.md` (modes ↔ power-profiles API, automatic mode and manual
choices, `kristall-power status --json` / `doctor`, settings `power.*`). System services that do
heavy work in the background (downloads, unpacking, indexing) belong in
`Slice=kristall-background.slice` (efficiency cores, low CPU share); the power component already puts
`kristall-update.service` and `kristall-apps-provision.service` there with drop-ins.

## 8. The assistant

A system-wide assistant in the role Siri plays on a Mac, powered by **Claude Haiku 5.5**
(`claude-haiku-5-5`) through the owner's **own Claude Code installation and subscription login**:
the daemon drives the official `claude` CLI in non-interactive streaming mode (not `--bare`, which
ignores the subscription login) and gives it our tool server over MCP. We never read, copy or
transmit the owner's Claude credentials ourselves, and we do not ship the CLI: the Setup Assistant
installs it with Anthropic's official installer and walks the owner through "Sign in with Claude".
Default name shown to the owner: "Kristall" (changeable). German first, English equally good.

It can talk (local speech recognition and speech synthesis, no cloud audio), type, see the screen,
operate any app, manage windows/files/settings, search the web, and it acts with **its own on-screen
cursor** while the owner's pointer stays where it is.

How (details in `docs/contracts/assistant-ipc.md`): the daemon uses Anthropic's Python Agent SDK,
installed from its source distribution because its wheels bundle the CLI binary. Tool servers
(`hands`) register by installing one drop-in `/usr/share/kristall/assistant/mcp.d/NN-<name>.json`
that also declares each tool's risk for the permission policy; they publish agent-cursor events by
connecting to `assistant.sock` as a `tool` client. The Setup Assistant's sign-in step uses
`kristall-assistant-account` (JSON-lines progress), never a terminal. Speech models are
downloaded and checksum-verified at image build time (`assistant/core/ASSETS.md`).

## 9. Build and test environment (cloud sandbox)

- Container image **`kristall-devenv:latest`** (`tools/devenv/`): Fedora 45 with KWin/Plasma 6.8,
  Qt 6.11, KWin/KF6/Qt headers, compilers, Quickshell, Python, test tools. `/devenv-missing.txt`
  inside it lists packages that could not be installed. Use it for anything needing KWin/Qt/Plasma:
  `docker run --rm -v /home/user/kristall:/work kristall-devenv:latest <cmd>`.
  KWin runs headless with software rendering: `kwin_wayland --virtual --width W --height H …`
  inside `dbus-run-session`, with `XDG_RUNTIME_DIR` set; screenshots via KWin's screenshot D-Bus API
  or a tool you write.
  Three things are needed for that to actually composite with OpenGL here (all in
  `kwin/glass/tests/support/` and `kwin/glass/tests/support/harness.py`, reuse them): KWin 6.8 only
  creates its llvmpipe render device when `/dev/udmabuf` exists, which the sandbox lacks — preload
  `fake_udmabuf.c`; run a *copy* of `/usr/bin/kwin_wayland` (the original carries
  `cap_sys_nice`, which containers refuse to exec); the virtual backend's `--scale` only
  multiplies the mode size — set the output scale with `kscreen-doctor output.Virtual-0.scale.1.6`.
  Note: the dev container (Fedora 45 as of 2026-11-15) already ships KWin/Plasma **6.8.3**, not
  6.8.2; plugins build against whatever KWin the image contains. No GPU, no audio hardware, no real input devices, no systemd inside.
  Without an input device the seat advertises no pointer/keyboard and clients create none; to get
  devices and to play the owner, use `org_kde_kwin_fake_input` (`kwin/bridge/tests/clients/owner.c`):
  it drives KWin's real input pipeline (cursor, focus, hover, shortcuts). Note that KWin 6.8 grants
  that protocol to every unsandboxed client without asking.
- The sandbox reaches the internet only through an HTTPS proxy on the host's loopback. Containers
  cannot reach it unless run with `--network host`, and such runs may be refused by the sandbox's
  safety policy. Prefer containers **without** network; if you need a package that is not in the
  image, add it to `tools/devenv/Dockerfile` in your report instead of fighting the policy
  (Python-only work can run directly on the sandbox host: Python 3.13, `pip` works).
- **Disk is small (~25 GB free for everyone).** Keep your scratch under 2 GB, delete build
  directories, downloaded models and pip caches when done, never pull other large images.
- Other agents are working in sibling directories at the same time. Do not run `git commit`,
  `git stash`, `git checkout` or anything that touches the index or other directories; just leave
  your files in place. Do not kill processes or containers you did not start; name your containers
  `kristall-<component>-…`.
- Nothing here can be tested on the real laptop. Design for that: detect hardware at runtime,
  never hard-code the panel, sensors, or vendor; log clearly (`journalctl --user -t kristall-<x>`).
