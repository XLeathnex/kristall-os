#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall shell test suite. Run inside the dev container from the repository root:
#   docker run --rm -v "$PWD":/work kristall-devenv:latest shell/tests/run.sh [section…]
# Sections: static core appmenu scale fallback modules restart plasma gallery realbridge (default: all).
# Builds the glass plugin (kwin/glass/tests/build.sh: headless KWin with the effect) and the Qt test
# app, then runs tests/test_shell.py under a private session bus. Exit status non-zero on failure.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1   # never write __pycache__ into the glass component's directory
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
export KRISTALL_SHELL_BUILD="${KRISTALL_SHELL_BUILD:-/tmp/kristall-shell-build}"
echo "== build: glass effect (for the headless KWin) and the Qt test app"
if [[ ! -f $KRISTALL_GLASS_BUILD/plugins/kwin/effects/plugins/kristall_glass.so ]]; then
    "$repo/kwin/glass/tests/build.sh" >/dev/null || { echo "FAIL glass build"; exit 1; }
fi
export KRISTALL_BRIDGE_PLUGINS="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-bridge-build}/plugins"
if [[ -x $repo/kwin/bridge/tests/build.sh && ! -f $KRISTALL_BRIDGE_PLUGINS/kwin/plugins/kristall_bridge.so ]]; then
    # optional: the real bridge plugin, if it builds (section "realbridge" is skipped otherwise)
    KRISTALL_BRIDGE_SKIP_BROKEN=1 "$repo/kwin/bridge/tests/build.sh" >/dev/null 2>&1 || echo "INFO bridge plugin did not build; realbridge skipped"
fi
mkdir -p "$KRISTALL_SHELL_BUILD"
# shellcheck disable=SC2046
g++ -std=c++17 -O1 -fPIC -o "$KRISTALL_SHELL_BUILD/menuapp" "$here/support/menuapp.cpp" $(pkg-config --cflags --libs Qt6Widgets) \
    || { echo "FAIL menuapp build"; exit 1; }
cd "$repo" || exit 1
dbus-run-session -- python3 "$here/test_shell.py" "$@" 2>&1 | grep -v -e "Failed to set fd limit" -e "org.kde.kded6"
exit "${PIPESTATUS[0]}"
