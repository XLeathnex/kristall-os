#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs INSIDE the freshly built OS image:
#   podman run --rm -v "$PWD/image:/k:ro" localhost/kristall-os bash /k/tests/smoke-image.sh
# Checks that the image component's promises hold in the real image. Exit != 0 on any failure.
set -uo pipefail
fails=0
ok() { printf 'ok    %s\n' "$*"; }
bad() {
  printf '::error title=Image smoke test::%s\n' "$*"
  fails=$((fails + 1))
}
check() { # description, command...
  local d=$1
  shift
  if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi
}

# Identity: display names changed, machine identifiers kept.
osr() { sed -n "s/^$1=//p" /usr/lib/os-release | tr -d '"'; }
check "os-release NAME is Kristall OS" test "$(osr NAME)" = "Kristall OS"
check "os-release ID/VARIANT_ID kept (fedora/kinoite)" test "$(osr ID)/$(osr VARIANT_ID)" = fedora/kinoite
check "os-release VERSION_ID present" test -n "$(osr VERSION_ID)"
check "default hostname" test "$(osr DEFAULT_HOSTNAME)" = kristall

# Tools
check "kristall-settings runs" kristall-settings get
check "kristall-settings defaults valid" kristall-settings check-defaults
check "kristall-update runs" kristall-update status --json
check "kristall-apps manifest valid" kristall-apps validate
check "update contract installed" test -f /usr/share/doc/kristall/contracts/update.md

# Packages promised by image/packages.list
mapfile -t pkgs < <(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "${1:-/k}/packages.list" 2>/dev/null || true)
if ((${#pkgs[@]})); then
  for p in "${pkgs[@]}"; do check "package $p" rpm -q "$p"; done
fi
for p in plasma-welcome khelpcenter plasma-discover-notifier; do
  if rpm -q "$p" >/dev/null 2>&1; then bad "$p should have been removed"; else ok "$p removed"; fi
done
for c in git gh node npm python3 uv rg fd jq podman distrobox curl bwrap socat; do
  check "command $c" command -v "$c"
done

# Session and first boot
check "only Plasma Wayland session" test "$(find /usr/share/wayland-sessions /usr/share/xsessions -name '*.desktop' 2>/dev/null)" = /usr/share/wayland-sessions/plasma.desktop
check "plasma-setup enabled" systemctl is-enabled plasma-setup.service
check "plasma-login-manager present" test -f /usr/lib/systemd/system/plasmalogin.service

# Updates
check "kristall-update.timer enabled" systemctl is-enabled kristall-update.timer
check "kristall-apps-provision.timer enabled" systemctl is-enabled kristall-apps-provision.timer
check "kristall-update-refresh enabled" systemctl is-enabled kristall-update-refresh.service
check "notify path enabled for every user" systemctl --global is-enabled kristall-update-notify.path
for t in rpm-ostreed-automatic.timer flatpak-system-update.timer; do
  if systemctl is-enabled "$t" >/dev/null 2>&1; then bad "$t still enabled"; else ok "$t disabled"; fi
done
check "bootc auto-reboot timer masked" test "$(systemctl is-enabled bootc-fetch-apply-updates.timer 2>/dev/null)" = masked
check "polkit rule installed" test -f /usr/share/polkit-1/rules.d/50-kristall-update.rules

# Every user preset shipped by any component took effect (systemctl --global).
while read -r verb unit; do
  [[ $verb == enable ]] || continue
  [[ $unit == *'*'* ]] && continue
  check "user preset: $unit enabled globally" systemctl --global is-enabled "$unit"
done < <(cat /usr/lib/systemd/user-preset/*kristall*.preset 2>/dev/null | sed -e 's/#.*//' -e '/^[[:space:]]*$/d')

# Hidden entries
for f in org.kde.discover.desktop org.kde.kate.desktop htop.desktop; do
  if [[ -f /usr/share/applications/$f ]]; then
    check "$f hidden" grep -q '^NoDisplay=true' "/usr/share/applications/$f"
  fi
done

# Nothing in /usr/local, /opt, /var (beyond the base's skeleton)
check "/usr/local empty" test -z "$(find -L /usr/local -mindepth 1 -type f 2>/dev/null | head -1)"
check "no Kristall state baked into /var" test ! -e /var/lib/kristall

if ((fails)); then
  echo "$fails check(s) failed"
  exit 1
fi
echo "all image smoke checks passed"
