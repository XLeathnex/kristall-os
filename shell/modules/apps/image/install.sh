#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# shell-apps / apps: installs the Apps grid module and its global shortcut (Meta+A, every user).
# Needs shell-core's AppCatalog (shell, listed before this one).
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
dest="$PREFIX/share/kristall/shell/modules/apps"
rm -rf "$dest"
install -d "$dest"
install -m 0644 "$here"/*.qml "$here/qmldir" "$here/strings.json" "$dest/"
install -Dm0644 "$here/kglobalaccel/org.kristall.apps.desktop" "$PREFIX/share/kglobalaccel/org.kristall.apps.desktop"
test -f "$PREFIX/share/kristall/shell/core/AppCatalog.qml" || echo "apps: WARNING shell-core (core/AppCatalog.qml) is not installed (install shell first)" >&2
echo "apps: installed to $dest"
