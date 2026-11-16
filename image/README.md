# image — the Kristall OS image pipeline and base system

Turns this repository into (a) a bootable, self-updating OS image and (b) an installer ISO.
Owns: `Containerfile`, `.containerignore`, `.github/workflows/`, `image/`, `docs/INSTALL.md`,
`docs/contracts/{settings,update,apps}.md`.

## What is where

| Path | What |
|---|---|
| `Containerfile` | `FROM ghcr.io/ublue-os/kinoite-main:45` (Fedora 45 Kinoite, Plasma 6.8). Mounts the repo at `/ctx`, runs `image/build.sh`, then `bootc container lint`. |
| `image/build.sh` | Orchestrator: prepare → each component's `image/install.sh` in `components.list` order → apply new systemd presets → final checks + cleanup. |
| `image/components.list` | Component order. Missing component = loud warning, or build failure with `KRISTALL_STRICT=1`. |
| `image/image/install.sh` | This component's own installer (packages, identity, session, updates, apps, settings tool). |
| `image/packages.list`, `packages-remove.list`, `hidden-apps.list` | RPMs added / removed, desktop entries hidden. |
| `image/rootfs/` | Files copied into the image (`usr/` → `$KRISTALL_PREFIX`, `etc/` → `/etc`). |
| `image/apps/` | App manifest `apps.json` + why each app is there (`README.md`). |
| `image/iso/` | The installer: live-system container (`Containerfile`, `build-live.sh`), Anaconda config, boot menu (`iso.yaml`). |
| `image/tests/` | `run.sh` (all offline tests), `smoke-image.sh` (runs inside the built image in CI), `verify-*.sh` (network checks of package names / Flatpak IDs). |
| `.github/workflows/build.yml` | Build + test + publish the image (push to main, daily, PRs build only). |
| `.github/workflows/build-iso.yml` | Build the ISO (after the first image, weekly, or by hand) and attach it to the run. |
| `.github/workflows/checks.yml` | Fast checks (called by build.yml). |
| `.github/workflows/components.yml` | Every component's `tests/run.sh` in the dev container (`tools/devenv/`), one job per component (push, PRs). The dev container is built only when `tools/devenv/` or the assistant's pinned requirements change and is kept in the Actions cache. |

Installed into the image: `/usr/bin/kristall-settings`, `/usr/bin/kristall-update`,
`/usr/bin/kristall-apps`, `/usr/libexec/kristall/plasma-setup-guard`, units
`kristall-update{,-check,-apply,-rollback,-rollback-cancel,-refresh}.service`,
`kristall-update.timer`, `kristall-apps-provision.{service,timer}`,
`kristall-plasma-setup-guard.service`, user units `kristall-update-notify.{path,service}`,
`/usr/share/polkit-1/rules.d/50-kristall-update.rules`, `/usr/share/kristall/apps/apps.json`,
`/usr/share/kristall/defaults/settings.json` + `settings.d/`, `/etc/bazaar/bazaar.yaml`.

## Decisions

- **Base pinning.** `FEDORA_VERSION=45` selects the `kinoite-main:45` stream (verified: on
  2026-11-15 `:45` and `:latest` were the same digest, Fedora 45, kernel 7.3.3, Plasma 6.8.2).
  The daily build follows that stream, so Fedora security fixes arrive without anyone acting.
  Moving to Fedora 46 is one deliberate edit. `BASE_DIGEST` can pin an exact base for a rebuild.
- **Kernel / Secure Boot.** We install no kernel and no kernel modules (`dnf --exclude=kernel*`).
  The base's kernel is Fedora's build; Universal Blue re-packages it and *adds* its own signature
  to `vmlinuz`, keeping Fedora's. `build.sh` fails the build if `vmlinuz` lacks the Fedora Secure
  Boot signature, if any `kmod-*`/`akmod-*` is installed, or if any `.ko` file does not come from
  the kernel packages. Fedora's shim + GRUB boot it with Secure Boot on, no key enrolment.
- **Identity.** `NAME`, `PRETTY_NAME`, `VARIANT`, `IMAGE_ID`, `IMAGE_VERSION`, `DEFAULT_HOSTNAME=kristall`,
  URLs change in `/usr/lib/os-release`; `ID=fedora`, `VERSION_ID`, `VARIANT_ID=kinoite`,
  `PLATFORM_ID`, `CPE_NAME` stay (dnf, flatpak, Anaconda, distrobox key off them). Boot menu
  entries are named from `PRETTY_NAME` by ostree.
- **Session.** Only `wayland-sessions/plasma.desktop` remains. `plasma-login-manager` stays.
- **First boot / account.** The installer does *not* create the account. On first start KDE's
  **Plasma Setup** (in the base) asks language, keyboard, time zone, Wi-Fi and creates the account,
  then logs the owner straight in, where the `setup` component's Setup Assistant takes over. This
  is Fedora KDE 45's own flow; it keeps the installer to "language + disk" and does the personal
  choices on the machine itself, like a Mac. `kristall-plasma-setup-guard` skips the wizard on a
  machine that already has a user.
- **Presets.** After all components ran, `build.sh` runs `systemctl preset` /
  `systemctl --global preset` for every unit named in a preset file that a component *added*
  (files under `/usr/lib/systemd/{system,user}-preset/`). `--global` makes user units enabled
  for every user, including ones created later. Base preset files are never re-applied.
- **Updates.** Our own small `kristall-update` on top of `bootc` instead of uupd / rpm-ostreed's
  automatic mode: we need a stable JSON interface for the settings screen, the metered/battery
  rules, polkit-only authorisation and a notification. See `docs/contracts/update.md`.
- **Lint.** `bootc container lint` (current practice for bootc images). `build.sh` additionally
  empties `/var` (except the build cache mounts and base symlinks) and `/tmp`, and fails on any
  file in `/usr/local` or `/opt` (both live in `/var` on an installed system).
- **Small updates.** CI re-chunks the image (`rpm-ostree compose build-chunked-oci`, as in
  Universal Blue's image template) so an update downloads only changed packages.
- **Installer.** See `docs/INSTALL.md` and `image/iso/`: Titanoboa live ISO with Anaconda (Web
  UI), the OS image and the free default apps on the stick.

## Build and test

Offline tests (any machine with Python ≥ 3.9 and bash; shellcheck/actionlint/yamllint if present):

```sh
bash image/tests/run.sh
```

Inside the dev container: `docker run --rm -v /home/user/kristall:/work kristall-devenv:latest bash image/tests/run.sh`.

Network checks: `bash image/tests/verify-flathub.sh` and, in a Fedora 45 container,
`bash image/tests/verify-fedora-packages.sh /src`.

A real image needs ~15 GB of disk and is built in CI (`build.yml`). Locally (not in the sandbox):

```sh
podman build -t localhost/kristall-os:latest .                       # KRISTALL_STRICT=0
podman run --rm -v "$PWD/image:/k:ro" localhost/kristall-os bash /k/tests/smoke-image.sh
```

## Rules for other components (summary of the contract this orchestrator enforces)

- Ship `X/image/install.sh`; it runs as root with cwd = `X/`, `KRISTALL_CTX` (repo root, read-only),
  `KRISTALL_PREFIX` (`/usr`), `KRISTALL_COMPONENT`, `KRISTALL_STRICT` in the environment.
- A non-zero exit fails the image build with your component's name.
- Never write `/usr/local`, `/opt`; `/var` and `/tmp` are emptied after the build.
- Enable units through a preset file you add (`/usr/lib/systemd/{system,user}-preset/50-kristall-<component>.preset`).
- Never install a kernel, kernel module or `kmod-*` package (the build fails).
- Settings defaults: `/usr/share/kristall/defaults/settings.d/50-<component>.json`
  (`docs/contracts/settings.md`).
- First-run flows must not start in the installer's live session: add
  `ConditionKernelCommandLine=!rd.live.image` to such units (the live system also has `/etc/kristall/live`).

## Known limits

- The real image and ISO have never been built or booted in this sandbox (the base is 14 GB);
  CI is the proof. Everything that needs systemd, polkit, bootc, Anaconda or hardware is unverified
  until the first CI run and a test install.
- Image signing (cosign) runs only if a `SIGNING_SECRET` repository secret exists; installed
  systems do not yet enforce signatures (they trust ghcr.io over TLS).
- User-scope Flatpaks are updated by the base's `flatpak-user-update.timer`, not reported in
  `kristall-update status`.
