#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# shell-apps / switcher: the app switcher is KWin's own (hold/release in the compositor) with our
# layout; this installs the layout package, merges the switcher configuration into
# /etc/xdg/kwinrc and the shortcuts (Meta+Tab, Meta+`, Meta+W for Overview; Plasma's Meta+Tab
# "walk through activities" unbound) into /etc/xdg/kglobalshortcutsrc — merged, never overwritten.
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
dest="$PREFIX/share/kristall/shell/modules/switcher"
rm -rf "$dest"
install -d "$dest"
install -m 0644 "$here/Module.qml" "$here/qmldir" "$dest/"
pkg="$PREFIX/share/kwin/tabbox/org.kristall.switcher"
rm -rf "$pkg"
install -d "$pkg/contents/ui"
install -m 0644 "$here/kwin/tabbox/org.kristall.switcher/metadata.json" "$pkg/"
# Overview: Kristall's effect (a declarative KWin effect package; kwinrc below switches it on and
# KWin's own Overview off)
eff="$PREFIX/share/kwin/effects/kristall_overview"
rm -rf "$eff"
install -Dm0644 "$here/kwin/effects/kristall_overview/metadata.json" "$eff/metadata.json"
install -Dm0644 "$here/kwin/effects/kristall_overview/contents/ui/main.qml" "$eff/contents/ui/main.qml"
install -m 0644 "$here/kwin/tabbox/org.kristall.switcher/contents/ui/main.qml" "$here/kwin/tabbox/org.kristall.switcher/contents/ui/names.js" "$pkg/contents/ui/"
python3 "$here/../../image/merge-ini" /etc/xdg/kwinrc "$here/kwin/kwinrc"
python3 "$here/../../image/merge-ini" /etc/xdg/kglobalshortcutsrc "$here/kwin/kglobalshortcutsrc"
# Control + ↑ → Overview (kglobalacceld reads share/kglobalaccel/ for every user)
install -Dm0644 "$here/kglobalaccel/org.kristall.switcher.desktop" "$PREFIX/share/kglobalaccel/org.kristall.switcher.desktop"
echo "switcher: installed to $dest and $pkg"
