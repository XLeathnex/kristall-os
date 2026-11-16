#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Tests of the panels module. Run inside the dev container from the repository root:
#   docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest shell/modules/panels/tests/run.sh [section…]
# Sections: static cc wifi notifications hud absent looks idle (default: all).
# Builds the glass effect (headless KWin with it) and the owner's input client (kwin/bridge test
# clients), then runs test_panels.py under a private session bus. Exit status non-zero on failure.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
export KRISTALL_PANELS_BUILD="${KRISTALL_PANELS_BUILD:-/tmp/kristall-panels-build}"
echo "== build: glass effect (headless KWin) and the owner input client"
if [[ ! -f $KRISTALL_GLASS_BUILD/plugins/kwin/effects/plugins/kristall_glass.so ]]; then
    "$repo/kwin/glass/tests/build.sh" >/dev/null || { echo "FAIL glass build"; exit 1; }
fi
mkdir -p "$KRISTALL_PANELS_BUILD"
if [[ ! -x $KRISTALL_PANELS_BUILD/owner ]]; then
    make -s -C "$repo/kwin/bridge/tests/clients" OUT="$KRISTALL_PANELS_BUILD" "$KRISTALL_PANELS_BUILD/owner" >/dev/null \
        || { echo "FAIL owner client build"; exit 1; }
fi
cd "$repo" || exit 1
# services the session activates (e.g. KWin's night-time helper) can outlive dbus-run-session:
# write to a file instead of a pipe so they cannot hold the output open, then clean them up
log="$(mktemp)"
dbus-run-session -- python3 -u "$here/test_panels.py" "$@" >"$log" 2>&1
status=$?
pkill -f /usr/libexec/knighttimed 2>/dev/null || true
grep -v -e "Failed to set fd limit" -e "org.kde.kded6" -e "xdg-desktop-portal" -e "Gtk-WARNING" -e "dbus-daemon\[" -e "^$" "$log"
rm -f "$log"
exit "$status"
