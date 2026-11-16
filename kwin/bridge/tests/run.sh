#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# kwin/bridge tests. Runs inside the kristall-devenv container (needs no network):
#   docker run --rm -v /home/user/kristall:/work kristall-devenv:latest /work/kwin/bridge/tests/run.sh [filter ...]
# Builds the plugin and the test clients, installs kristall-bridgectl and the Python module into
# the (throw-away) container's /usr so the access-control test can use a real installed binary,
# then runs every test file in its own D-Bus session against headless KWin instances.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bridge="$(dirname "$here")"

echo "== build"
"$here/build.sh"
install -Dm755 "$bridge/tools/kristall-bridgectl" /usr/bin/kristall-bridgectl
install -Dm644 "$bridge/python/kristall_bridge.py" /usr/lib/kristall/bridge/python/kristall_bridge.py

echo "== static checks"
python3 -m py_compile "$bridge/python/kristall_bridge.py" "$bridge/tools/kristall-bridgectl" "$here"/*.py "$here/support/harness.py" "$here/clients/gtkprobe.py"
if command -v shellcheck >/dev/null; then
  shellcheck "$here/run.sh" "$here/build.sh" "$bridge/image/install.sh"
  echo "shellcheck: ok"
fi

log=/tmp/kristall-bridge-tests.log
: >"$log"
for t in test_pointer test_keyboard test_windows test_screenshot test_security; do
  echo "== $t" | tee -a "$log"
  (cd "$here" && dbus-run-session -- python3 "$t.py" "$@" 2>&1) |
    grep -v -e "Failed to set fd limit" -e "^dbus-daemon\[" -e "SpiRegistry daemon" | tee -a "$log" || true
done
passed=$(grep -cE '^PASS test_.*s\)$' "$log" || true)
failed=$(grep -cE '^FAIL test_[a-z0-9_]+: ' "$log" | awk '{print int($1/2)}')
echo
echo "== overall: $passed tests passed, $failed failed"
[ "$failed" -eq 0 ]
