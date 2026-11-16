#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds the plugin and the test clients into $KRISTALL_BRIDGE_BUILD (default /tmp/kristall-bridge-build).
# Runs inside the kristall-devenv container.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bridge="$(dirname "$here")"
out="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-bridge-build}"
mkdir -p "$out/plugins/kwin/plugins" "$out/bin"
cmake -S "$bridge" -B "$out/cmake" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr >"$out/cmake.log" 2>&1 \
    || { cat "$out/cmake.log"; exit 1; }
if ! ninja -C "$out/cmake" >"$out/build.log" 2>&1; then
    grep -E "error|Error" -A3 "$out/build.log" | head -80
    exit 1
fi
grep -E "warning:" "$out/build.log" | sort -u | head -40 || true
cp "$out/cmake/bin/kristall_bridge.so" "$out/plugins/kwin/plugins/" 2>/dev/null || cp "$out/cmake/kristall_bridge.so" "$out/plugins/kwin/plugins/"
# a deliberately broken build for the fail-soft test
if [ "${KRISTALL_BRIDGE_SKIP_BROKEN:-0}" != 1 ]; then
    cmake -S "$bridge" -B "$out/cmake-broken" -G Ninja -DCMAKE_BUILD_TYPE=Release -DKRISTALL_BRIDGE_TEST_BROKEN=ON >/dev/null 2>&1
    ninja -C "$out/cmake-broken" >/dev/null 2>&1
    mkdir -p "$out/plugins-broken/kwin/plugins"
    cp "$out/cmake-broken/bin/kristall_bridge.so" "$out/plugins-broken/kwin/plugins/" 2>/dev/null || cp "$out/cmake-broken/kristall_bridge.so" "$out/plugins-broken/kwin/plugins/"
fi
# test clients
make -s -C "$here/clients" OUT="$out/bin"
# kwin_wayland carries file capabilities (cap_sys_nice) that a container may not grant; a copy
# without them behaves identically apart from real-time scheduling
cp /usr/bin/kwin_wayland "$out/kwin_wayland"
gcc -shared -fPIC -O2 -o "$out/fake_udmabuf.so" "$here/support/fake_udmabuf.c" -ldl
echo "built: $out/plugins/kwin/plugins/kristall_bridge.so"
