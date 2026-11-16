#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds what the setup tests need, inside kristall-devenv: the keyboard plugin (and a deliberately
# broken copy for the fail-safe test), the settings modules for System Settings, the X11 key
# logger, and — through their own build scripts — the bridge plugin with its test clients and the
# glass effect. Output: $KRISTALL_SETUP_BUILD (default /tmp/kristall-setup-build).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
setup="$(dirname "$here")"
repo="$(dirname "$setup")"
out="${KRISTALL_SETUP_BUILD:-/tmp/kristall-setup-build}"
export KRISTALL_BRIDGE_BUILD="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-bridge-build}"
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
mkdir -p "$out/plugins/kwin/plugins" "$out/plugins-broken/kwin/plugins" "$out/bin"

build() { # src builddir [cmake args…]
    local src=$1 dir=$2
    shift 2
    cmake -S "$src" -B "$dir" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr "$@" >"$dir.cmake.log" 2>&1 ||
        { cat "$dir.cmake.log"; return 1; }
    if ! ninja -C "$dir" >"$dir.build.log" 2>&1; then
        grep -E "error|Error" -A3 "$dir.build.log" | head -60
        return 1
    fi
    grep -E "warning:" "$dir.build.log" | sort -u | head -20 || true
}

if [[ ! -f $KRISTALL_BRIDGE_BUILD/plugins/kwin/plugins/kristall_bridge.so || ! -x $KRISTALL_BRIDGE_BUILD/bin/owner ]]; then
    KRISTALL_BRIDGE_SKIP_BROKEN=1 "$repo/kwin/bridge/tests/build.sh" >/dev/null
fi
if [[ ${KRISTALL_SETUP_NO_GLASS:-0} != 1 && ! -f $KRISTALL_GLASS_BUILD/plugins/kwin/effects/plugins/kristall_glass.so ]]; then
    "$repo/kwin/glass/tests/build.sh" >/dev/null
fi

build "$setup/keyboard" "$out/keyboard"
build "$setup/keyboard" "$out/keyboard-broken" -DKRISTALL_KEYBOARD_TEST_BROKEN=ON
cp "$out/keyboard/bin/kristall_keyboard.so" "$out/plugins/kwin/plugins/"
cp "$out/keyboard-broken/bin/kristall_keyboard.so" "$out/plugins-broken/kwin/plugins/"
# the bridge next to it (agent typing while the mapping is on)
cp "$KRISTALL_BRIDGE_BUILD/plugins/kwin/plugins/kristall_bridge.so" "$out/plugins/kwin/plugins/"
cp "$KRISTALL_BRIDGE_BUILD/plugins/kwin/plugins/kristall_bridge.so" "$out/plugins-broken/kwin/plugins/"

if [[ ${KRISTALL_SETUP_NO_SETTINGS:-0} != 1 ]]; then
    build "$setup/settings" "$out/settings"
    DESTDIR="$out/settings-root" ninja -C "$out/settings" install >/dev/null
fi

# shellcheck disable=SC2046  # pkg-config prints several words on purpose
gcc -O2 -Wall -o "$out/bin/xkeylog" "$here/clients/xkeylog.c" $(pkg-config --cflags --libs x11 xkbcommon)
echo "built: $out"
