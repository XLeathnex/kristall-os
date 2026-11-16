#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Installer of the `power` component (component contract: docs/ARCHITECTURE.md §3).
# Runs as root during the OS image build with cwd = power/, repository at $KRISTALL_CTX (read-only).
# Installs: kristall-power (CLI + session daemon), the six Kristall tuned profiles and the tuned-ppd
# mapping, units/presets, udev/polkit/sysctl/zram/NetworkManager/GameMode configuration, settings
# defaults. Contract: docs/contracts/power.md.
set -euo pipefail

CTX=${KRISTALL_CTX:-/ctx}
PREFIX=${KRISTALL_PREFIX:-/usr}
SRC=$CTX/power
ETC=${KRISTALL_POWER_ETC:-/etc} # test hook: install /etc files elsewhere

note() { printf '  [power] %s\n' "$*"; }
die() {
  printf '::error title=power component::%s\n' "$*" >&2
  exit 1
}

# ----------------------------------------------------------------------------- packages
# tuned + tuned-ppd come with the base (power-profiles D-Bus API). GameMode is how games ask for
# full power; python3-dbus / python3-gobject-base are already there as tuned dependencies and are
# named here only to make the session daemon's dependency explicit.
if [[ ${KRISTALL_POWER_SKIP_PACKAGES:-0} != 1 ]]; then
  if rpm -q power-profiles-daemon >/dev/null 2>&1; then
    note "removing power-profiles-daemon (tuned-ppd provides the same API)"
    dnf5 -y remove power-profiles-daemon
  fi
  note "installing packages"
  dnf5 -y install --setopt=install_weak_deps=False \
    --exclude='kernel,kernel-core,kernel-modules,kernel-modules-core,kernel-modules-extra' \
    tuned tuned-ppd gamemode python3-dbus python3-gobject-base
fi

# ----------------------------------------------------------------------------- program
note "installing kristall-power"
install -d "$PREFIX/lib/kristall/power/kristall_power" "$PREFIX/libexec/kristall/power"
install -m0644 "$SRC"/lib/kristall_power/*.py "$PREFIX/lib/kristall/power/kristall_power/"
install -Dm0755 "$SRC/bin/kristall-power" "$PREFIX/bin/kristall-power"
install -m0755 "$SRC/libexec/usb-autosuspend" "$PREFIX/libexec/kristall/power/usb-autosuspend"
python3 -c "import compileall, sys; sys.exit(0 if compileall.compile_dir('$PREFIX/lib/kristall/power', quiet=1) else 1)" ||
  die "kristall_power does not compile"

# ----------------------------------------------------------------------------- tuned
note "installing tuned profiles"
for d in "$SRC"/tuned/kristall-*/; do
  name=$(basename "$d")
  install -Dm0644 "$d/tuned.conf" "$PREFIX/lib/tuned/profiles/$name/tuned.conf"
  if [[ $name != kristall-common ]]; then
    install -m0755 "$SRC/tuned/script.sh" "$PREFIX/lib/tuned/profiles/$name/script.sh"
  fi
done
install -Dm0644 "$SRC/config/ppd.conf" "$ETC/tuned/ppd.conf"
# First boot starts in Ausgewogen; tuned-ppd takes over as soon as it runs.
printf 'kristall-balanced\n' >"$ETC/tuned/active_profile"
printf 'manual\n' >"$ETC/tuned/profile_mode"
printf 'balanced\n' >"$ETC/tuned/ppd_base_profile"
# tuned's main loop wakes every sleep_interval seconds even with dynamic tuning off (it only waits
# for its stop event there); 10 s instead of 1 s removes 9 of 10 idle wake-ups, with no effect on
# profile switches (they signal the event directly).
if [[ -f $ETC/tuned/tuned-main.conf ]]; then
  sed -i -E 's/^(sleep_interval[[:space:]]*=[[:space:]]*)1[[:space:]]*$/\110/' "$ETC/tuned/tuned-main.conf"
  grep -qE '^dynamic_tuning[[:space:]]*=[[:space:]]*0' "$ETC/tuned/tuned-main.conf" ||
    note "warning: tuned dynamic_tuning is not 0 in tuned-main.conf"
fi
if python3 -c 'import tuned' 2>/dev/null; then
  python3 "$SRC/tests/validate_tuned.py" --profiles "$PREFIX/lib/tuned/profiles" --ppd "$ETC/tuned/ppd.conf" ||
    die "tuned profiles / ppd.conf failed validation"
else
  note "warning: python module 'tuned' not importable, profile validation skipped"
fi

# ----------------------------------------------------------------------------- system config
note "installing configuration"
install -Dm0644 "$SRC/config/gamemode.ini" "$ETC/gamemode.ini"
install -Dm0644 "$SRC/config/60-kristall-power.conf" "$PREFIX/lib/sysctl.d/60-kristall-power.conf"
install -Dm0644 "$SRC/config/zram-generator.conf" "$PREFIX/lib/systemd/zram-generator.conf.d/50-kristall-power.conf"
install -Dm0644 "$SRC/config/networkmanager-wifi-powersave.conf" "$PREFIX/lib/NetworkManager/conf.d/50-kristall-power.conf"
install -Dm0644 "$SRC/udev/60-kristall-power.rules" "$PREFIX/lib/udev/rules.d/60-kristall-power.rules"
install -Dm0644 "$SRC/polkit/50-kristall-power.rules" "$PREFIX/share/polkit-1/rules.d/50-kristall-power.rules"
install -Dm0644 "$SRC/config/50-power.json" "$PREFIX/share/kristall/defaults/settings.d/50-power.json"
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$PREFIX/share/kristall/defaults/settings.d/50-power.json" ||
  die "settings drop-in is not valid JSON"
install -d "$PREFIX/lib/tmpfiles.d"
cat >"$PREFIX/lib/tmpfiles.d/kristall-power.conf" <<'EOF'
# Kristall OS (power component): state written by root, readable by the owner's tools.
d /var/lib/kristall 0755 root root -
d /var/lib/kristall/power 0755 root root -
d /run/kristall-power 0755 root root -
EOF
chmod 0644 "$PREFIX/lib/tmpfiles.d/kristall-power.conf"
if [[ -f $CTX/docs/contracts/power.md ]]; then
  install -Dm0644 "$CTX/docs/contracts/power.md" "$PREFIX/share/doc/kristall/contracts/power.md"
fi

# ----------------------------------------------------------------------------- systemd
note "installing units"
SD=$PREFIX/lib/systemd
install -d "$SD/system" "$SD/user" "$SD/system-sleep" "$SD/system-generators" "$SD/system-preset" "$SD/user-preset"
for f in "$SRC"/systemd/system/*.service "$SRC"/systemd/system/*.timer "$SRC"/systemd/system/*.slice; do
  install -m0644 "$f" "$SD/system/"
done
for d in "$SRC"/systemd/system/*.d; do
  install -Dm0644 "$d/50-kristall-power.conf" "$SD/system/$(basename "$d")/50-kristall-power.conf"
done
install -m0644 "$SRC/systemd/user/kristall-power-session.service" "$SD/user/"
install -m0755 "$SRC/systemd/system-sleep/kristall-power" "$SD/system-sleep/kristall-power"
install -m0755 "$SRC/systemd/system-generators/kristall-power-ecores" "$SD/system-generators/kristall-power-ecores"
install -m0644 "$SRC/systemd/50-kristall-power.preset" "$SD/system-preset/50-kristall-power.preset"
install -m0644 "$SRC/systemd/50-kristall-power-user.preset" "$SD/user-preset/50-kristall-power.preset"

if command -v systemd-analyze >/dev/null 2>&1 && [[ ${KRISTALL_POWER_SKIP_VERIFY:-0} != 1 ]]; then
  # Syntax check only (unit dependencies outside this component may not exist at build time).
  systemd-analyze verify --man=no "$SD/system/kristall-power.service" "$SD/system/kristall-power-reapply.service" \
    "$SD/system/kristall-power-doctor.service" "$SD/system/kristall-power-doctor.timer" 2>&1 |
    grep -v -E 'not found|Failed to resolve|cannot be found|does not exist' || true
fi
note "done"
