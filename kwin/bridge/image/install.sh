#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# kwin/bridge image installer (component contract, docs/ARCHITECTURE.md §3).
# Runs as root during the OS image build with cwd = kwin/bridge (read-only) and network.
# Builds the KWin plugin against the KWin the image ships, installs it, the Python client module
# and kristall-bridgectl, and enables the plugin for every user via /etc/xdg/kwinrc.
set -euo pipefail

PREFIX=${KRISTALL_PREFIX:-/usr}
SRC=$(cd "$(dirname "$0")/.." && pwd)

note() { printf '==> kwin/bridge: %s\n' "$*"; }

# ------------------------------------------------------------------ build dependencies
BUILD_DEPS=(gcc-c++ cmake ninja-build extra-cmake-modules kwin-devel qt6-qtbase-devel qt6-qtbase-private-devel
    qt6-qtdeclarative-devel kdecoration-devel kf6-kconfig-devel kf6-kcoreaddons-devel wayland-devel
    wayland-protocols-devel plasma-wayland-protocols-devel libxkbcommon-devel libxcb-devel systemd-devel
    # KWinConfig.cmake's own find_dependency() list (kwin-devel does not pull these in)
    libepoxy-devel libdrm-devel vulkan-headers vulkan-loader-devel kf6-kwindowsystem-devel
    # the GTK 3 app-menu module (appmenu/gtk)
    gtk3-devel)
ADDED=()
for p in "${BUILD_DEPS[@]}"; do
  rpm -q "$p" >/dev/null 2>&1 || ADDED+=("$p")
done
if ((${#ADDED[@]})); then
  note "installing build dependencies: ${ADDED[*]}"
  dnf5 install -y --setopt=install_weak_deps=False "${ADDED[@]}"
fi
cleanup() {
  rm -rf "${BUILD:-}"
  if ((${#ADDED[@]})); then
    note "removing build dependencies"
    dnf5 remove -y "${ADDED[@]}" >/dev/null || true
  fi
}
trap cleanup EXIT

# The plugin must match the compositor exactly (KWin checks the plugin interface version).
KWIN_VERSION=$(rpm -q --qf '%{VERSION}' kwin)
note "building against KWin ${KWIN_VERSION}"

# ------------------------------------------------------------------ build and install
BUILD=$(mktemp -d /tmp/kristall-bridge-build.XXXXXX)
cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DBUILD_TESTING=OFF
ninja -C "$BUILD"
DESTDIR=${DESTDIR:-} ninja -C "$BUILD" install

install -Dm644 "$SRC/python/kristall_bridge.py" "$PREFIX/lib/kristall/bridge/python/kristall_bridge.py"
# app side of global menus (README "Global menus"): Qt platform theme + GTK 3 module, for the session
install -Dm644 "$SRC/appmenu/environment.d.conf" "$PREFIX/lib/environment.d/50-kristall-appmenu.conf"
install -Dm755 "$SRC/tools/kristall-bridgectl" "$PREFIX/bin/kristall-bridgectl"

PLUGIN=$(find "$PREFIX"/lib*/qt6/plugins/kwin/plugins -name 'kristall_bridge.so' -print -quit)
[[ -n $PLUGIN ]] || { echo "kwin/bridge: plugin was not installed" >&2; exit 1; }
note "installed $PLUGIN"
# app side of global menus: both are needed for menus in the menu bar (and the in-window fallback)
for f in qt6/plugins/platformthemes/kristall_appmenu.so gtk-3.0/modules/libkristall-appmenu-gtk-module.so; do
  found=$(find "$PREFIX"/lib*/ -path "*/$f" -print -quit 2>/dev/null)
  [[ -n $found ]] || { echo "kwin/bridge: $f was not installed" >&2; exit 1; }
  note "installed $found"
done

# ------------------------------------------------------------------ enable for every user
# The plugin's metadata already says EnabledByDefault; the explicit key keeps it enabled even if
# KWin's defaults change. kwinrc is shared with other components: only our key is touched.
KWINRC=/etc/xdg/kwinrc
mkdir -p /etc/xdg
touch "$KWINRC"
if command -v kwriteconfig6 >/dev/null 2>&1; then
  kwriteconfig6 --file "$KWINRC" --group Plugins --key kristall_bridgeEnabled true
else
  python3 - "$KWINRC" <<'EOF'
import sys
path = sys.argv[1]
lines = open(path, encoding="utf-8").read().splitlines()
out, in_plugins, done, seen = [], False, False, False
for line in lines:
    s = line.strip()
    if s.startswith("[") and s.endswith("]"):
        if in_plugins and not done:
            out.append("kristall_bridgeEnabled=true")
            done = True
        in_plugins = s == "[Plugins]"
        seen = seen or in_plugins
    elif in_plugins and s.split("=", 1)[0].strip() == "kristall_bridgeEnabled":
        line, done = "kristall_bridgeEnabled=true", True
    out.append(line)
if in_plugins and not done:
    out.append("kristall_bridgeEnabled=true")
elif not seen:
    out += ["", "[Plugins]", "kristall_bridgeEnabled=true"]
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
EOF
fi
grep -q '^kristall_bridgeEnabled=true' "$KWINRC" || { echo "kwin/bridge: could not enable the plugin in $KWINRC" >&2; exit 1; }
note "enabled in $KWINRC"
