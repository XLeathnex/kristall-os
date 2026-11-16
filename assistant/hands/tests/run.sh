#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# assistant/hands test suite. Inside the dev container:
#   docker run --rm -v "$PWD":/work kristall-devenv:latest /work/assistant/hands/tests/run.sh
# On any Linux with Python >= 3.11 the unit tests run too; the rest is skipped with a reason.
# Exit status is non-zero if any check fails.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
hands="$(dirname "$here")"
repo="$(dirname "$(dirname "$hands")")"
status=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; status=1; }
skip() { echo "SKIP $*"; }

echo "== unit tests (mocked services, mock bridge from the contract, MCP conformance)"
echo "   tier1     every direct action against a fake D-Bus / fake wpctl, wl-clipboard, kwriteconfig6,"
echo "             the real kristall-settings; German fuzzy app names; timers; secret masking"
echo "   pointing  coordinate mapping at scale 1.0 and 1.6 with synthetic images, typing, keys, owner"
echo "             busy, Escape, lock screen, auth prompts, no bridge, agent-cursor choreography"
echo "   protocol  initialize, tools/list, tools/call, errors, ping during a call, cancellation"
(cd "$here" && python3 -m unittest test_tier1 test_pointing test_protocol 2>&1 | grep -v "ResourceWarning\|tracemalloc")
if [ "${PIPESTATUS[0]}" = 0 ]; then pass "unit tests"; else fail "unit tests"; fi

in_devenv=0
[ -e /devenv-missing.txt ] && command -v kwin_wayland >/dev/null && in_devenv=1

echo "== accessibility against real Qt apps (Kate, Dolphin) in headless KWin; Firefox started before hands"
if [ "$in_devenv" = 1 ]; then
  (cd "$here" && dbus-run-session -- python3 -m unittest -v test_a11y test_session_a11y 2>&1 | grep -v "fd limit\|dbus-daemon\|SpiRegistry\|ResourceWarning\|tracemalloc\|DeprecationWarning\|get_action_name")
  if [ "${PIPESTATUS[0]}" = 0 ]; then pass "accessibility"; else fail "accessibility"; fi
else
  skip "accessibility: needs the kristall-devenv container"
fi

echo "== install.sh into a scratch prefix"
if command -v gcc >/dev/null && command -v python3-config >/dev/null; then
  pfx="$(mktemp -d)"
  if KRISTALL_PREFIX="$pfx/usr" KRISTALL_SRC="$hands" KRISTALL_SKIP_SYSTEM_PACKAGES=1 bash "$hands/image/install.sh" >/dev/null \
     && [ "$("$pfx/usr/bin/kristall-hands" --version)" = 1.0.0 ] \
     && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["mcpServers"]["hands"]["command"].endswith("/usr/bin/kristall-hands")' \
        "$pfx/usr/share/kristall/assistant/mcp.d/50-hands.json" \
     && [ -f "$pfx/usr/lib/systemd/user/kristall-hands-session.service" ] \
     && [ -f "$pfx/usr/share/kristall/defaults/settings.d/50-assistant-hands.json" ] \
     && [ -x "$pfx/usr/lib/systemd/user-environment-generators/60-kristall-accessibility" ]; then
    pass "install.sh (launcher, package, drop-in, unit, defaults)"
  else
    fail "install.sh"
  fi
  rm -rf "$pfx"
else
  skip "install.sh: gcc / python3-devel not available"
fi

echo "== against the real kristall-bridge plugin (installed /usr/bin/kristall-hands, development mode off)"
if [ "$in_devenv" = 1 ] && [ -f "$repo/kwin/bridge/tests/build.sh" ] && [ -w /usr/bin ] && [ "${KRISTALL_HANDS_SKIP_BRIDGE:-0}" != 1 ]; then
  export KRISTALL_BRIDGE_BUILD="${KRISTALL_BRIDGE_BUILD:-/tmp/kristall-hands-bridge}"
  if KRISTALL_BRIDGE_SKIP_BROKEN=1 bash "$repo/kwin/bridge/tests/build.sh" >/dev/null 2>&1 \
     && KRISTALL_SRC="$hands" KRISTALL_SKIP_SYSTEM_PACKAGES=1 bash "$hands/image/install.sh" >/dev/null; then
    for sc in 1.0 1.6; do
      (cd "$here" && KRISTALL_TEST_SCALE=$sc dbus-run-session -- python3 -m unittest test_real_bridge 2>&1 | grep -v "fd limit\|dbus-daemon\|SpiRegistry\|ResourceWarning\|tracemalloc\|kristall-hands INFO\|hands log")
      if [ "${PIPESTATUS[0]}" = 0 ]; then pass "real bridge at scale $sc"; else fail "real bridge at scale $sc"; fi
    done
  else
    fail "building the bridge or installing hands"
  fi
else
  skip "real bridge: needs the dev container (as root, throwaway) and kwin/bridge sources"
fi

echo "== shellcheck"
if command -v shellcheck >/dev/null; then
  if shellcheck "$hands/image/install.sh" "$here/run.sh" "$hands/data/kristall-accessibility-env"; then pass shellcheck; else fail shellcheck; fi
else
  skip "shellcheck not installed"
fi

[ "$status" = 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$status"
