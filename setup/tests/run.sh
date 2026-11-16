#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# setup component tests. Inside the dev container, from the repository root:
#   docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest setup/tests/run.sh [suite…]
# Suites: static keyboard setup settings (default: all). A suite name may be followed by its
# sections after a colon, e.g. keyboard:table,altgr  setup:walk-de. Prints PASS/FAIL per check;
# exits non-zero on any failure.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export KRISTALL_SETUP_BUILD="${KRISTALL_SETUP_BUILD:-/tmp/kristall-setup-build}"
suites=("$@")
[[ ${#suites[@]} -eq 0 ]] && suites=(static keyboard setup settings)
status=0
filter() { grep -v -e "fd limit" -e "^dbus-daemon\[" -e "portal" -e "Gtk-WARNING" -e "ignoring unknown child"; }

needs_build=0
for s in "${suites[@]}"; do [[ ${s%%:*} != static ]] && needs_build=1; done
if [[ $needs_build == 1 ]]; then
    echo "== build"
    "$here/build.sh" || { echo "FAIL build"; exit 1; }
fi

for spec in "${suites[@]}"; do
    name=${spec%%:*}
    sections=()
    [[ $spec == *:* ]] && IFS=, read -r -a sections <<<"${spec#*:}"
    echo "== $name"
    case $name in
    static) python3 "$here/test_static.py" || status=1 ;;
    keyboard) dbus-run-session -- python3 "$here/test_keyboard.py" "${sections[@]}" 2>&1 | filter; [[ ${PIPESTATUS[0]} == 0 ]] || status=1 ;;
    setup) dbus-run-session -- python3 "$here/test_setup.py" "${sections[@]}" 2>&1 | filter; [[ ${PIPESTATUS[0]} == 0 ]] || status=1 ;;
    settings) dbus-run-session -- python3 "$here/test_settings.py" "${sections[@]}" 2>&1 | filter; [[ ${PIPESTATUS[0]} == 0 ]] || status=1 ;;
    *) echo "unknown suite $name"; status=2 ;;
    esac
done
[[ $status == 0 ]] && echo "== setup tests: ALL PASSED" || echo "== setup tests: FAILURES"
exit $status
