#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# panels: Control Center, notifications and HUDs for the Kristall shell (shell/modules/panels).
# Component contract: docs/ARCHITECTURE.md §3. Run by image/build.sh as root with cwd = shell/modules/panels.
# No packages of its own: it runs inside shell-core's Quickshell and uses python3-gobject-base
# (installed by shell-core), PowerDevil, KWin, plasmashell, spectacle and kwriteconfig6 (Kinoite base).
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mod="$PREFIX/share/kristall/shell/modules/panels"
data="$PREFIX/share/kristall/panels"

# the module (QML, qmldir, strings, helper) — shell-core's install never deletes modules/
rm -rf "$mod"
install -d "$mod/helper"
install -m 0644 "$here"/*.qml "$here/qmldir" "$here/strings.json" "$mod/"
install -m 0755 "$here/helper/kristall-panels-helper" "$mod/helper/kristall-panels-helper"
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$mod/helper/kristall-panels-helper"

# Plasma's on-screen display replaced by a no-op QML module (plasmashell 6.8 creates its OSD from
# org.kde.plasma.workspace.osd); our plasmashell unit drop-in puts it first on QML_IMPORT_PATH.
# Plasma keeps handling the keys and announces each OSD on D-Bus; our HUD shows it.
rm -rf "$data/plasma-qml"
install -d "$data/plasma-qml/org/kde/plasma/workspace/osd"
install -m 0644 "$here/plasma/osd/org/kde/plasma/workspace/osd/qmldir" "$here/plasma/osd/org/kde/plasma/workspace/osd/Osd.qml" \
    "$data/plasma-qml/org/kde/plasma/workspace/osd/"
install -d "$PREFIX/lib/systemd/user/plasma-plasmashell.service.d"
sed "s|/usr/share/kristall/panels/plasma-qml|$data/plasma-qml|" "$here/plasma/systemd/50-kristall-osd.conf" \
    >"$PREFIX/lib/systemd/user/plasma-plasmashell.service.d/50-kristall-osd.conf"
chmod 0644 "$PREFIX/lib/systemd/user/plasma-plasmashell.service.d/50-kristall-osd.conf"

# global shortcuts (Control Center, Notification Centre), for every user
install -d "$PREFIX/share/kglobalaccel"
install -m 0644 "$here/kglobalaccel/org.kristall.panels.desktop" "$PREFIX/share/kglobalaccel/org.kristall.panels.desktop"

# settings defaults: the top-level key "panels"
install -d "$PREFIX/share/kristall/defaults/settings.d"
install -m 0644 "$here/image/settings.json" "$PREFIX/share/kristall/defaults/settings.d/50-panels.json"

# Notifications: our shell owns org.freedesktop.Notifications. Plasma's activation file for that
# name (org.kde.plasma.Notifications.service → plasma_waitforname) only waits for an owner, so a
# message sent while the shell restarts is delivered once it is back; nothing to change there.

install -m 0644 "$here/README.md" "$mod/README.md"
test -f "$mod/Module.qml"
echo "panels: installed to $mod"
