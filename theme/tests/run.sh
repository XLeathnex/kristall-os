#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall theme test suite. Runs inside the dev container from the repository root:
#   docker run --rm -v "$PWD":/work kristall-devenv-theme:latest theme/tests/run.sh [section…]
# (kristall-devenv-theme = kristall-devenv plus GTK 3/4 demos, libadwaita, Firefox, KWrite,
#  kde-gtk-config, adw-gtk3, JetBrains Mono, Plymouth/dracut/kernel — theme/tests/Dockerfile.)
# In the plain kristall-devenv the sections needing those packages report SKIP.
# Sections: static install decoration apps csd menus switch screens pointer fallback plymouth
# (default: all). Evidence goes to theme/tests/evidence/ (kept under 6 MB).
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
export KRISTALL_BRIDGE_BUILD="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-bridge-build}"
export KRISTALL_THEME_STAGE="${KRISTALL_THEME_STAGE:-/tmp/kristall-theme-stage}"
echo "== build: glass effect and bridge (headless KWin), as the shell tests do"
if [[ ! -f $KRISTALL_GLASS_BUILD/plugins/kwin/effects/plugins/kristall_glass.so ]]; then
    "$repo/kwin/glass/tests/build.sh" >/dev/null || { echo "FAIL glass build"; exit 1; }
fi
if [[ ! -f $KRISTALL_BRIDGE_BUILD/plugins/kwin/plugins/kristall_bridge.so ]]; then
    KRISTALL_BRIDGE_SKIP_BROKEN=1 "$repo/kwin/bridge/tests/build.sh" >/dev/null 2>&1 || echo "INFO bridge did not build; app menus in the bar are skipped"
fi
cd "$repo" || exit 1
dbus-run-session -- python3 "$here/test_theme.py" "$@" 2>&1 | grep -v -E "Failed to set fd limit|org.kde.kded6|xdg-desktop-portal|dbus-daemon\[|Gtk-WARNING|^\s*$"
exit "${PIPESTATUS[0]}"
