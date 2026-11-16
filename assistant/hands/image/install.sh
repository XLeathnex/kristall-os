#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# assistant/hands: install the assistant's computer-control tool server into the OS image.
#
# Runs as root at image build time with the repository at /ctx (read-only) and network.
# Installs:
#   $PREFIX/lib/kristall/hands/kristall_hands/        the Python package (standard library + python3-gobject)
#   $PREFIX/lib/kristall/hands/data/risky-targets.json  vocabulary of the risky-target gate
#   $PREFIX/bin/kristall-hands                        a small compiled launcher embedding the system Python,
#                                                     so the bridge sees /usr/bin/kristall-hands as the peer
#   $PREFIX/share/kristall/assistant/mcp.d/50-hands.json   drop-in for the assistant daemon
#   $PREFIX/share/kristall/defaults/settings.d/50-assistant-hands.json   defaults for assistant.hands
#   $PREFIX/lib/systemd/user/kristall-hands-session.service + preset   login hook (reminders, accessibility)
#   $PREFIX/lib/systemd/user-environment-generators/60-kristall-accessibility  toolkit accessibility at login
#
# Environment: KRISTALL_PREFIX (default /usr), KRISTALL_CTX (default /ctx),
#   KRISTALL_SRC (default $KRISTALL_CTX/assistant/hands),
#   KRISTALL_SKIP_SYSTEM_PACKAGES=1 (development only: do not call dnf5).
set -euo pipefail
umask 022

PREFIX="${KRISTALL_PREFIX:-/usr}"
SRC="${KRISTALL_SRC:-${KRISTALL_CTX:-/ctx}/assistant/hands}"
LIB="$PREFIX/lib/kristall/hands"
BIN="$PREFIX/bin"
SHARE="$PREFIX/share/kristall"
UNITDIR="$PREFIX/lib/systemd/user"
PRESETDIR="$PREFIX/lib/systemd/user-preset"

log() { printf 'assistant/hands: %s\n' "$*"; }

case "$PREFIX" in
  /usr/local|/usr/local/*|/opt|/opt/*) echo "KRISTALL_PREFIX must not be under /usr/local or /opt" >&2; exit 1 ;;
esac
[ -f "$SRC/kristall_hands/server.py" ] || { echo "cannot find sources in $SRC" >&2; exit 1; }

# --- packages. Runtime: Python with GObject introspection (D-Bus, Gio, AT-SPI), the AT-SPI
# stack, WirePlumber's wpctl, wl-clipboard, KConfig's kwriteconfig6. Build only: gcc, python3-devel.
added_build=()
if [ "${KRISTALL_SKIP_SYSTEM_PACKAGES:-0}" != 1 ]; then
  need=()
  for p in python3 python3-gobject-base at-spi2-core wireplumber wl-clipboard kf6-kconfig; do
    rpm -q "$p" >/dev/null 2>&1 || need+=("$p")
  done
  for p in gcc python3-devel; do
    if ! rpm -q "$p" >/dev/null 2>&1; then
      need+=("$p")
      added_build+=("$p")
    fi
  done
  if [ "${#need[@]}" -gt 0 ]; then
    log "installing ${need[*]}"
    dnf5 install -y --setopt=install_weak_deps=False "${need[@]}"
  fi
fi
PYTHON="$(command -v python3)"
"$PYTHON" -c 'import gi; gi.require_version("Gio", "2.0"); gi.require_version("Atspi", "2.0"); from gi.repository import Gio, Atspi' \
  || { echo "python3-gobject with Gio and Atspi typelibs is required" >&2; exit 1; }

# --- the package (rebuilt from scratch: idempotent)
rm -rf "$LIB"
mkdir -p "$LIB"
cp -r "$SRC/kristall_hands" "$LIB/kristall_hands"
# the risky-target vocabulary (hands.md §10), found by the package at ../data/
install -D -m 0644 "$SRC/data/risky-targets.json" "$LIB/data/risky-targets.json"
find "$LIB" -name '__pycache__' -prune -exec rm -rf {} +
"$PYTHON" -m compileall -q "$LIB/kristall_hands" >/dev/null
find "$LIB" -type d -exec chmod 0755 {} +
find "$LIB" -type f -exec chmod 0644 {} +

# --- the launcher (see launcher/kristall-hands.c for why it is compiled)
mkdir -p "$BIN"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
read -r -a pycflags <<<"$(python3-config --cflags --embed)"
read -r -a pyldflags <<<"$(python3-config --ldflags --embed)"
gcc -O2 -Wall -Wextra -DHANDS_LIB="\"$LIB\"" -o "$work/kristall-hands" "$SRC/launcher/kristall-hands.c" \
  "${pycflags[@]}" "${pyldflags[@]}"
install -m 0755 "$work/kristall-hands" "$BIN/kristall-hands"
"$BIN/kristall-hands" --version >/dev/null   # smoke test: interpreter and package load

# --- drop-in for the assistant daemon (generated from the tool registry, so risks stay in sync)
mkdir -p "$SHARE/assistant/mcp.d"
"$BIN/kristall-hands" dropin "$BIN/kristall-hands" > "$work/50-hands.json"
install -m 0644 "$work/50-hands.json" "$SHARE/assistant/mcp.d/50-hands.json"

# --- defaults under assistant.hands (docs/contracts/settings.md)
install -D -m 0644 "$SRC/data/settings-hands.json" "$SHARE/defaults/settings.d/50-assistant-hands.json"

# --- login hook: re-arm reminders, apply the accessibility mode
mkdir -p "$UNITDIR" "$PRESETDIR"
sed "s|@BIN@|$BIN|g" "$SRC/data/kristall-hands-session.service" > "$UNITDIR/kristall-hands-session.service"
chmod 0644 "$UNITDIR/kristall-hands-session.service"
install -m 0644 "$SRC/data/50-kristall-assistant-hands.preset" "$PRESETDIR/50-kristall-assistant-hands.preset"
# --- accessibility from the start of the session while the assistant is enabled (hands.md §5):
#     a user environment generator, gated on assistant.enabled / assistant.hands.accessibility
install -D -m 0755 "$SRC/data/kristall-accessibility-env" \
  "$(dirname "$UNITDIR")/user-environment-generators/60-kristall-accessibility"

# --- remove build-only packages this script added
if [ "${#added_build[@]}" -gt 0 ]; then
  log "removing build-only packages ${added_build[*]}"
  dnf5 remove -y "${added_build[@]}" >/dev/null
fi
if [ "${KRISTALL_SKIP_SYSTEM_PACKAGES:-0}" != 1 ]; then
  dnf5 clean all >/dev/null 2>&1 || true
fi
"$BIN/kristall-hands" --version >/dev/null   # still runs without the build packages

log "installed into $PREFIX"
