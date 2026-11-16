#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds what the shell-apps tests need (inside kristall-devenv): the glass effect and a headless
# KWin copy (kwin/glass/tests/build.sh) and the real bridge plugin with its test clients
# (kwin/bridge/tests/build.sh), each only if not built yet.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../../../.." && pwd)"
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
export KRISTALL_BRIDGE_BUILD="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-bridge-build}"
if [[ ! -f $KRISTALL_GLASS_BUILD/plugins/kwin/effects/plugins/kristall_glass.so ]]; then
    "$repo/kwin/glass/tests/build.sh" >/dev/null
fi
if [[ ! -f $KRISTALL_BRIDGE_BUILD/plugins/kwin/plugins/kristall_bridge.so || ! -x $KRISTALL_BRIDGE_BUILD/bin/owner ]]; then
    KRISTALL_BRIDGE_SKIP_BROKEN=1 "$repo/kwin/bridge/tests/build.sh" >/dev/null
fi
