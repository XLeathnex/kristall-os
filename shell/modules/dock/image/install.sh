#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# shell-apps / dock: installs the Dock module, the code shared by the shell-apps modules
# (modules/dock/common), its settings defaults and the system-wide KWin setting for minimising
# into the Dock. Component contract: docs/ARCHITECTURE.md §3 (cwd = shell/modules/dock).
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
dest="$PREFIX/share/kristall/shell/modules/dock"

# Runtime packages (Fedora 45 names; all already in Kinoite): the launcher-entry helper uses
# PyGObject + GIO; emptying the Trash uses ktrash6 (kde-cli-tools) with gio as fallback; KWin's
# Magic Lamp effect is built into kwin.
dnf5 install -y --setopt=install_weak_deps=False python3-gobject-base glib2 kde-cli-tools

rm -rf "$dest"
install -d "$dest"
cp -a "$here/Module.qml" "$here/qmldir" "$here/strings.json" "$here/common" "$here/helper" "$dest/"
for f in "$here"/*.qml; do install -m 0644 "$f" "$dest/"; done
find "$dest" -type d -exec chmod 0755 {} + ; find "$dest" -type f -exec chmod 0644 {} +
chmod 0755 "$dest/helper/kristall-dock-launcher-entries"

# settings defaults (`dock`)
install -Dm0644 "$here/image/settings.json" "$PREFIX/share/kristall/defaults/settings.d/50-dock.json"

# minimise into the Dock: merge into the system-wide kwinrc (never overwrite: others write it too)
python3 "$here/image/merge-ini" /etc/xdg/kwinrc "$here/kwin/kwinrc"

python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$dest/helper/kristall-dock-launcher-entries"
test -f "$dest/Module.qml" && test -f "$dest/common/AppCatalog.qml"
echo "dock: installed to $dest"
