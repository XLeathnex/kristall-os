#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# dock module tests. Inside the dev container, from the repository root:
#   docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest shell/modules/dock/tests/run.sh [section…]
# Headless KWin with the glass effect and the real bridge plugin, real apps, the owner's pointer
# and keys through KWin's fake input. Prints PASS/FAIL per check; exit status non-zero on failure.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
"$here/../../dock/tests/prepare.sh" || { echo "FAIL build of glass/bridge for the tests"; exit 1; }
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
export KRISTALL_BRIDGE_BUILD="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-bridge-build}"
dbus-run-session -- python3 "$here/test_dock.py" "$@" 2>&1 | grep -v -e "fd limit" -e "^dbus-daemon\[" -e "portal" -e "Gtk-WARNING" -e "ignoring unknown child"
exit "${PIPESTATUS[0]}"
