#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall OS image build step for the glass component (component contract, ARCHITECTURE.md §3).
# Runs as root with the repository at /ctx (read-only) and network access. Builds the KWin
# effect against the KWin the image ships, installs it under $KRISTALL_PREFIX (default /usr),
# enables it and disables KWin's stock blur for every user via /etc/xdg/kwinrc, then removes
# the build dependencies it added. Idempotent.
set -euo pipefail

prefix="${KRISTALL_PREFIX:-/usr}"
ctx="${KRISTALL_CTX:-/ctx}"
src="$ctx/kwin/glass"
build="$(mktemp -d /tmp/kristall-glass-build.XXXXXX)"
trap 'rm -rf "$build"' EXIT

log() { echo "[kristall-glass] $*"; }

# ---- build dependencies (only the ones that are missing get installed, and removed again) ----
deps=(gcc-c++ cmake ninja-build extra-cmake-modules kwin-devel qt6-qtbase-devel qt6-qtbase-private-devel
      qt6-qtdeclarative-devel kf6-kconfig-devel kf6-kcoreaddons-devel kf6-kwindowsystem-devel kdecoration-devel
      libepoxy-devel wayland-devel libdrm-devel vulkan-headers vulkan-loader-devel)
added=()
for p in "${deps[@]}"; do
    rpm -q "$p" >/dev/null 2>&1 || added+=("$p")
done
if [ "${#added[@]}" -gt 0 ]; then
    log "installing build dependencies: ${added[*]}"
    dnf5 install -y --setopt=install_weak_deps=False "${added[@]}"
fi

# ---- build against exactly the KWin in this image ----
kwin_version="$(rpm -q --qf '%{VERSION}' kwin)"
log "building against KWin $kwin_version"
cmake -S "$src" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DKRISTALL_PREFIX="$prefix"
ninja -C "$build"
cmake --install "$build"

# reference QML client (GlassClient/GlassSurface/GlassShape) and the demo configuration
install -d "$prefix/share/kristall/glass/demo"
install -m 0644 "$src"/demo/*.qml "$prefix/share/kristall/glass/demo/"

# ---- enable for all users through system-wide configuration ----
# KConfig cascades /etc/xdg/kwinrc below each user's ~/.config/kwinrc. Only our two keys are
# written; other components' settings in the same file are kept.
install -d /etc/xdg
conf=/etc/xdg/kwinrc
if command -v kwriteconfig6 >/dev/null 2>&1; then
    kwriteconfig6 --file "$conf" --group Plugins --key kristall_glassEnabled true
    kwriteconfig6 --file "$conf" --group Plugins --key blurEnabled false
else
    python3 - "$conf" <<'PY'
import configparser, sys
p = sys.argv[1]
c = configparser.RawConfigParser(strict=False)
c.optionxform = str
c.read(p)
if not c.has_section("Plugins"):
    c.add_section("Plugins")
c.set("Plugins", "kristall_glassEnabled", "true")
c.set("Plugins", "blurEnabled", "false")
with open(p, "w") as f:
    c.write(f, space_around_delimiters=False)
PY
fi

# ---- sanity: the plugin must resolve against this KWin, or the image build fails here ----
plugin="$(find "$prefix" -name kristall_glass.so -path '*kwin/effects/plugins*' | head -1)"
[ -n "$plugin" ] || { log "plugin was not installed"; exit 1; }
python3 - "$plugin" <<'PY'
import ctypes, sys
ctypes.CDLL("libkwin.so.6", mode=ctypes.RTLD_GLOBAL)
ctypes.CDLL(sys.argv[1], mode=2)  # RTLD_NOW: every symbol must resolve
PY
log "installed $plugin (KWin $kwin_version)"

# ---- remove what we added ----
if [ "${#added[@]}" -gt 0 ]; then
    log "removing build dependencies"
    dnf5 remove -y "${added[@]}"
fi
