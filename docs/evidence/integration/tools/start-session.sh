#!/bin/bash
# Inside the container, as root: start the owner's Plasma session the way plasmalogin does
# (the session file's Exec line, as the user, inside their systemd user manager).
set -euo pipefail
LANGV=${1:-de_DE.UTF-8}
loginctl enable-linger kristall
for i in $(seq 1 30); do [ -S /run/user/1000/bus ] && break; sleep 0.5; done
date +%s.%N >/run/integ-session-start
systemd-run -q -M kristall@ --user --unit=integ-plasma-session --collect \
  --setenv=LANG="$LANGV" --setenv=XDG_SESSION_TYPE=wayland --setenv=XDG_SESSION_DESKTOP=KDE --setenv=XDG_CURRENT_DESKTOP=KDE \
  /usr/libexec/plasma-dbus-run-session-if-needed /usr/bin/startplasma-wayland
echo started
