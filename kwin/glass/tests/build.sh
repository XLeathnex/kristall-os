#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds everything the tests need into $KRISTALL_GLASS_BUILD (default /tmp/kristall-glass-build).
# Runs inside the kristall-devenv container.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
glass="$(dirname "$here")"
out="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
mkdir -p "$out/plugins/kwin/effects/plugins"
cmake -S "$glass" -B "$out/cmake" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr >"$out/cmake.log" 2>&1 \
    || { cat "$out/cmake.log"; exit 1; }
ninja -C "$out/cmake" 2>&1 | tee "$out/build.log" | grep -E "warning|error" || true
[ "${PIPESTATUS[0]}" = 0 ] || exit 1
cp "$out/cmake/bin/kristall_glass.so" "$out/plugins/kwin/effects/plugins/"
gcc -shared -fPIC -O2 -o "$out/fake_udmabuf.so" "$here/support/fake_udmabuf.c" -ldl
# kwin_wayland carries file capabilities (cap_sys_nice) that a container may not grant; a copy
# without them behaves identically apart from real-time scheduling
cp /usr/bin/kwin_wayland "$out/kwin_wayland"
echo "built: $out/plugins/kwin/effects/plugins/kristall_glass.so"
