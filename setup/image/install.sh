#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# setup: the Setup Assistant (shell module + first-login unit), Kristall's pages in System
# Settings, the Mac keyboard (KWin plugin). Component contract: docs/ARCHITECTURE.md §3.
# Run by image/build.sh as root with cwd = setup/; builds against the image's own KWin and Qt.
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
repo="$(dirname "$here")"
libexec="$PREFIX/libexec/kristall"
share="$PREFIX/share/kristall/setup"
build="$(mktemp -d /tmp/kristall-setup-build.XXXXXX)"
trap 'rm -rf "$build"' EXIT

# build dependencies: only those not already in the image are installed, and removed again
deps=(cmake ninja-build gcc-c++ extra-cmake-modules kwin-devel qt6-qtbase-devel qt6-qtbase-private-devel
      qt6-qtdeclarative-devel kf6-kcmutils-devel kf6-kconfig-devel kf6-kcoreaddons-devel libxkbcommon-devel
      wayland-devel
      # KWinConfig.cmake's own find_dependency() list (kwin-devel does not pull these in)
      libepoxy-devel libdrm-devel vulkan-headers vulkan-loader-devel kf6-kwindowsystem-devel)
added=()
for p in "${deps[@]}"; do
    rpm -q "$p" >/dev/null 2>&1 || added+=("$p")
done
skip_pkgs="${KRISTALL_SKIP_SYSTEM_PACKAGES:-0}"     # 1: a scratch install where the packages are present
if [[ $skip_pkgs != 1 ]]; then
    if (( ${#added[@]} )); then
        dnf5 install -y --setopt=install_weak_deps=False "${added[@]}"
    fi
    # runtime: kscreen-doctor (display size), Plasma's wallpaper tool, GObject for the helper
    dnf5 install -y --setopt=install_weak_deps=False libkscreen plasma-workspace python3-gobject-base
fi

for part in keyboard settings; do
    cmake -S "$here/$part" -B "$build/$part" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX"
    ninja -C "$build/$part"
    ninja -C "$build/$part" install
done

# programs and data
install -Dm0755 "$here/bin/kristall-setup-helper" "$PREFIX/bin/kristall-setup-helper"
install -Dm0755 "$here/bin/kristall-setup-start" "$libexec/kristall-setup-start"
install -Dm0644 "$here/data/kristall-mark.svg" "$share/kristall-mark.svg"
install -Dm0644 "$here/data/50-setup.json" "$PREFIX/share/kristall/defaults/settings.d/50-setup.json"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$PREFIX/share/kristall/defaults/settings.d/50-setup.json"

# first-login unit, enabled for every user through our preset
install -Dm0644 "$here/systemd/kristall-setup.service" "$PREFIX/lib/systemd/user/kristall-setup.service"
install -Dm0644 "$here/systemd/50-kristall-setup.preset" "$PREFIX/lib/systemd/user-preset/50-kristall-setup.preset"

# system-wide KDE configuration, merged (other components' keys are kept)
for f in kwinrc kdeglobals kcm-about-distrorc; do
    python3 "$here/image/merge-ini" "/etc/xdg/$f" "$here/data/xdg/$f"
done

# the Setup Assistant's shell module
KRISTALL_PREFIX="$PREFIX" bash "$repo/shell/modules/setup/image/install.sh"

# the contract, for the machine's documentation
if [[ -f ${KRISTALL_CTX:-/ctx}/docs/contracts/setup.md ]]; then
    install -Dm0644 "${KRISTALL_CTX:-/ctx}/docs/contracts/setup.md" "$PREFIX/share/doc/kristall/contracts/setup.md"
fi

if [[ $skip_pkgs != 1 ]] && (( ${#added[@]} )); then
    dnf5 remove -y "${added[@]}"
fi
echo "setup: installed (keyboard plugin, System Settings pages, Setup Assistant)"
