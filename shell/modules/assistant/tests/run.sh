#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# assistant-ui test suite. Run inside the dev container from the repository root:
#   docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest shell/modules/assistant/tests/run.sh [section…]
# Sections: static demo pointer errors ask typing robust idle cost timing scale looks fallback realbridge
# (default: all). Builds the glass effect (headless KWin with real glass) and the bridge plugin with its
# test clients (the owner's fake-input keyboard/pointer) unless already built, then runs
# tests/test_assistant.py under a private session bus. The assistant daemon runs from
# assistant/core in demo mode (it needs only Python and numpy, both in the dev container).
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
export KRISTALL_BRIDGE_BUILD="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-bridge-build}"
if [[ ! -f $KRISTALL_GLASS_BUILD/plugins/kwin/effects/plugins/kristall_glass.so ]]; then
    echo "== build: glass effect"
    "$repo/kwin/glass/tests/build.sh" >/dev/null || { echo "FAIL glass build"; exit 1; }
fi
if [[ ! -x $KRISTALL_BRIDGE_BUILD/bin/owner ]]; then
    echo "== build: bridge plugin and test clients"
    KRISTALL_BRIDGE_SKIP_BROKEN=1 "$repo/kwin/bridge/tests/build.sh" >/dev/null 2>&1 || { echo "FAIL bridge build (owner input client)"; exit 1; }
fi
cd "$repo" || exit 1
dbus-run-session -- python3 "$here/test_assistant.py" "$@" 2>&1 | grep -v -e "Failed to set fd limit" -e "org.kde.kded6" -e "dbus-run-session: ignoring"
exit "${PIPESTATUS[0]}"
