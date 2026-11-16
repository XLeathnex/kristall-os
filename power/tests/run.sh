#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# power component tests. Runs in the dev container (kristall-devenv): everything; on a plain host
# with Python 3 the tuned validation and the D-Bus session test are skipped (and say so).
#   docker run --rm -v /home/user/kristall:/work:ro kristall-devenv:latest bash /work/power/tests/run.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
POWER=$(dirname "$HERE")
REPO=$(dirname "$POWER")
fails=0
step() { printf '\n== %s\n' "$*"; }
result() { if [[ $1 -eq 0 ]]; then echo "PASS: $2"; else echo "FAIL: $2"; fails=$((fails + 1)); fi; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=$TMP/pycache

step "shellcheck"
shell_files=("$POWER/image/install.sh" "$POWER/tuned/script.sh" "$POWER/systemd/system-generators/kristall-power-ecores"
  "$POWER/systemd/system-sleep/kristall-power" "$POWER/libexec/usb-autosuspend" "$POWER/tests/run.sh"
  "$POWER/tests/fakes/bin/systemctl")
if command -v shellcheck >/dev/null; then
  shellcheck -x "${shell_files[@]}"
  result $? "shellcheck (${#shell_files[@]} files)"
else
  echo "SKIP: shellcheck not installed"
fi

step "python syntax"
python3 -m py_compile "$POWER"/lib/kristall_power/*.py "$POWER"/tests/*.py "$POWER"/tests/fakes/*.py "$POWER/bin/kristall-power" \
  "$POWER/tests/fakes/bin/kscreen-doctor"
result $? "all Python files compile"

step "settings defaults"
python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
assert list(d) == ["power"], "only the power key"
p = d["power"]
assert p["automatic"] is True and p["batteryBase"] == "quiet" and p["batteryRefreshRate"] in ("auto", "max") and 50 <= p["chargeLimit"] <= 100
assert isinstance(p["dimOnBattery"], bool) and isinstance(p["lowBatteryQuiet"], bool) and p["heavyApps"]
' "$POWER/config/50-power.json"
result $? "settings.d/50-power.json: only 'power', complete and typed"
if [[ -x $REPO/image/rootfs/usr/bin/kristall-settings ]]; then
  mkdir -p "$TMP/dropins" && cp "$POWER/config/50-power.json" "$TMP/dropins/"
  printf '{}\n' >"$TMP/defaults.json"
  out=$(KRISTALL_SETTINGS_DEFAULTS=$TMP/defaults.json KRISTALL_SETTINGS_DROPIN_DIRS=$TMP/dropins \
    "$REPO/image/rootfs/usr/bin/kristall-settings" check-defaults 2>&1)
  ! grep -q ERROR <<<"$out"
  result $? "kristall-settings check-defaults accepts the drop-in"
fi

step "unit tests (policy, display, automatic mode)"
python3 "$HERE/test_display.py" 2>&1 | tail -3
result "${PIPESTATUS[0]}" "test_display.py"
python3 "$HERE/test_auto.py" 2>&1 | tail -3
result "${PIPESTATUS[0]}" "test_auto.py"

step "levers on fake hardware (6 laptop personalities)"
python3 "$HERE/test_levers.py" 2>&1 | tail -3
result "${PIPESTATUS[0]}" "test_levers.py"

step "tuned profiles and ppd.conf through tuned's own code"
if python3 -c 'import tuned' 2>/dev/null; then
  python3 "$HERE/validate_tuned.py" --profiles "$POWER/tuned" --ppd "$POWER/config/ppd.conf" >"$TMP/vt.log" 2>&1
  r=$?
  grep -c '^ok' "$TMP/vt.log" | sed 's/^/checks passed: /'
  grep '^FAIL' "$TMP/vt.log"
  result $r "validate_tuned.py"
  # negative control: the validator must catch a misspelt option and a broken mapping
  cp -r "$POWER/tuned" "$TMP/badtuned"
  sed -i 's/^energy_performance_preference=/energy_performance_preferences=/' "$TMP/badtuned/kristall-quiet/tuned.conf"
  sed 's/^balanced=kristall-balanced-battery/balanced=kristall-quiet-battery/' "$POWER/config/ppd.conf" >"$TMP/bad-ppd.conf"
  r=1
  if ! python3 "$HERE/validate_tuned.py" --profiles "$TMP/badtuned" --ppd "$TMP/bad-ppd.conf" >"$TMP/vt-bad.log" 2>&1 &&
    grep -q "unknown: \['energy_performance_preferences'\]" "$TMP/vt-bad.log" &&
    grep -q 'Duplicate profile mapping' "$TMP/vt-bad.log"; then
    r=0
  fi
  result $r "validator rejects a misspelt option and a non-injective ppd mapping"
else
  echo "SKIP: python module 'tuned' not available (run in kristall-devenv)"
fi

step "polkit rule"
if command -v node >/dev/null; then
  node "$HERE/polkit_test.js" "$POWER/polkit/50-kristall-power.rules"
  result $? "polkit rule allows exactly charge@50..100 and doctor for the local active user"
else
  echo "SKIP: node not installed"
fi

step "udev rules"
if command -v udevadm >/dev/null; then
  udevadm verify "$POWER/udev/60-kristall-power.rules" >/dev/null 2>&1
  result $? "udevadm verify"
fi

step "install.sh into a scratch prefix"
KRISTALL_CTX=$REPO KRISTALL_PREFIX=$TMP/usr KRISTALL_POWER_ETC=$TMP/etc KRISTALL_POWER_SKIP_PACKAGES=1 \
  KRISTALL_POWER_SKIP_VERIFY=1 bash "$POWER/image/install.sh" >"$TMP/install.log" 2>&1
r=$?
for f in bin/kristall-power lib/kristall/power/kristall_power/session.py lib/tuned/profiles/kristall-quiet/script.sh \
  lib/tuned/profiles/kristall-common/tuned.conf lib/systemd/system/kristall-power.service lib/systemd/user/kristall-power-session.service \
  lib/systemd/system-preset/50-kristall-power.preset lib/systemd/user-preset/50-kristall-power.preset \
  lib/systemd/system/kristall-update.service.d/50-kristall-power.conf lib/systemd/system-generators/kristall-power-ecores \
  lib/udev/rules.d/60-kristall-power.rules share/polkit-1/rules.d/50-kristall-power.rules lib/sysctl.d/60-kristall-power.conf \
  lib/systemd/zram-generator.conf.d/50-kristall-power.conf share/kristall/defaults/settings.d/50-power.json \
  lib/tmpfiles.d/kristall-power.conf libexec/kristall/power/usb-autosuspend; do
  [[ -e $TMP/usr/$f ]] || { echo "missing: $f"; r=1; }
done
[[ -f $TMP/etc/tuned/ppd.conf && -f $TMP/etc/gamemode.ini ]] || r=1
[[ ! -e $TMP/usr/lib/tuned/profiles/kristall-common/script.sh ]] || r=1
grep -q 'ConditionKernelCommandLine=!rd.live.image' "$TMP/usr/lib/systemd/system/kristall-power.service" \
  "$TMP/usr/lib/systemd/user/kristall-power-session.service" || r=1
[[ $r -eq 0 ]] || cat "$TMP/install.log"
result $r "install.sh installs every file (live-session condition present)"

step "session daemon end to end on private D-Bus buses"
if python3 -c 'import dbus, gi' 2>/dev/null && command -v dbus-daemon >/dev/null; then
  python3 "$HERE/test_session_dbus.py" 2>&1 | grep -v 'fd limit' | tail -3
  result "${PIPESTATUS[0]}" "test_session_dbus.py"
else
  echo "SKIP: python3-dbus / dbus-daemon not available (run in kristall-devenv)"
fi

step "real tuned 2.28 + tuned-ppd with power/ installed (disposable container only)"
if [[ ${KRISTALL_POWER_REAL_TUNED:-0} == 1 ]]; then
  python3 "$HERE/test_real_tuned.py" 2>&1 | grep -v 'fd limit' | tail -3
  result "${PIPESTATUS[0]}" "test_real_tuned.py"
else
  echo "SKIP: installs into the running system; run with KRISTALL_POWER_REAL_TUNED=1 in a throwaway container"
fi

echo
if [[ $fails -eq 0 ]]; then echo "power: all checks passed"; else echo "power: $fails check(s) FAILED"; fi
exit $((fails > 0))
