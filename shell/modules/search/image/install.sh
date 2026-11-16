#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# shell-apps / search: installs the Search module, its global shortcut (Meta+Space, for every
# user) and the system-wide file-index setting it relies on. Needs modules/dock/common (installed
# by shell/modules/dock, listed before this one). Contract: docs/ARCHITECTURE.md §3.
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
dest="$PREFIX/share/kristall/shell/modules/search"

# Files are found through Baloo, the file index Plasma already runs (kf6-baloo-file: baloo_file,
# inotify-driven, idle IO priority; baloosearch6 queries its LMDB index).
dnf5 install -y --setopt=install_weak_deps=False kf6-baloo kf6-baloo-file

rm -rf "$dest"
install -d "$dest"
install -m 0644 "$here"/*.qml "$here"/*.js "$here/qmldir" "$here/strings.json" "$dest/"
install -Dm0644 "$here/kglobalaccel/org.kristall.search.desktop" "$PREFIX/share/kglobalaccel/org.kristall.search.desktop"

# Baloo: index file names only (content extraction is what costs battery), skip hidden folders
# (Baloo's default). Merged into /etc/xdg/baloofilerc, other keys kept.
tmp="$(mktemp)"
printf '[General]\nonly basic indexing=true\nindex hidden folders=false\n' >"$tmp"
python3 "$here/../dock/image/merge-ini" /etc/xdg/baloofilerc "$tmp"
rm -f "$tmp"

test -f "$PREFIX/share/kristall/shell/modules/dock/common/AppCatalog.qml" || echo "search: WARNING modules/dock/common is not installed (install shell/modules/dock first)" >&2
echo "search: installed to $dest"
