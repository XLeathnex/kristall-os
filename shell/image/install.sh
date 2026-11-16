#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# shell-core: installs the Kristall shell (Quickshell config + helper + units + Plasma integration).
# Component contract: docs/ARCHITECTURE.md §3. Run by image/build.sh as root with cwd = shell/.
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
share="$PREFIX/share/kristall/shell"
lib="$PREFIX/lib/kristall/shell"
libexec="$PREFIX/libexec/kristall"

# Runtime packages, by name (all in Fedora 45): Quickshell, the SVG image plugin (symbols), Inter,
# GObject introspection for the helper (Gio/D-Bus), xdg-open for the Go menu, gdbus for the fallback.
dnf5 install -y --setopt=install_weak_deps=False \
    quickshell qt6-qtsvg rsms-inter-fonts python3-gobject-base glib2 xdg-utils libnotify

# The QML tree (modules/ stays: later components install their own modules/<name>/ next to it)
install -d "$share" "$lib" "$libexec" "$PREFIX/bin"
for d in core services bar gallery strings icons; do
    rm -rf "${share:?}/$d"
    cp -a "$here/$d" "$share/$d"
done
install -m 0644 "$here/shell.qml" "$here/modules.list" "$share/"
install -d "$share/modules"
find "$share" -name '__pycache__' -prune -exec rm -rf {} +
find "$share" -type d -exec chmod 0755 {} + ; find "$share" -type f -exec chmod 0644 {} +

# helper (one long-lived process per session) and its path for the QML side
install -m 0755 "$here/helper/kristall-shell-helper" "$lib/kristall-shell-helper"
install -d "$share/helper"
ln -sfn "$lib/kristall-shell-helper" "$share/helper/kristall-shell-helper"

# programs
install -m 0755 "$here/bin/kristall-shell" "$libexec/kristall-shell"
install -m 0755 "$here/bin/kristall-shell-fallback" "$libexec/kristall-shell-fallback"
install -m 0755 "$here/bin/kristall-shellctl" "$PREFIX/bin/kristall-shellctl"

# systemd user units, enabled for every user through our preset
install -d "$PREFIX/lib/systemd/user" "$PREFIX/lib/systemd/user-preset"
install -m 0644 "$here/systemd/kristall-shell.service" "$here/systemd/kristall-shell-fallback.service" "$PREFIX/lib/systemd/user/"
install -m 0644 "$here/systemd/50-kristall-shell.preset" "$PREFIX/lib/systemd/user-preset/50-kristall-shell.preset"

# Plasma: our look-and-feel package carries the default layout without panels (desktop only)
install -d "$PREFIX/share/plasma/look-and-feel"
rm -rf "$PREFIX/share/plasma/look-and-feel/org.kristall.desktop"
cp -a "$here/plasma/look-and-feel/org.kristall.desktop" "$PREFIX/share/plasma/look-and-feel/"
# select it for every user: merge [KDE] LookAndFeelPackage into /etc/xdg/kdeglobals (keep other keys)
python3 - /etc/xdg/kdeglobals <<'PY'
import sys, configparser, os
path = sys.argv[1]
cp = configparser.RawConfigParser(strict=False, interpolation=None)
cp.optionxform = str
if os.path.exists(path):
    cp.read(path, encoding="utf-8")
if not cp.has_section("KDE"):
    cp.add_section("KDE")
cp.set("KDE", "LookAndFeelPackage", "org.kristall.desktop")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path + ".tmp", "w", encoding="utf-8") as f:
    cp.write(f, space_around_delimiters=False)
os.replace(path + ".tmp", path)
PY
# global shortcuts, system-wide (kglobalacceld reads share/kglobalaccel/*.desktop)
install -d "$PREFIX/share/kglobalaccel"
install -m 0644 "$here/plasma/kglobalaccel/org.kristall.shell.desktop" "$PREFIX/share/kglobalaccel/org.kristall.shell.desktop"

# settings defaults: appearance, accessibility, bar
install -d "$PREFIX/share/kristall/defaults/settings.d"
install -m 0644 "$here/image/settings.json" "$PREFIX/share/kristall/defaults/settings.d/50-shell.json"

# contracts for the owner's machine (documentation only)
install -d "$PREFIX/share/doc/kristall/contracts"
ctx="${KRISTALL_CTX:-/ctx}"
for c in design shell; do
    if [[ -f $ctx/docs/contracts/$c.md ]]; then
        install -m 0644 "$ctx/docs/contracts/$c.md" "$PREFIX/share/doc/kristall/contracts/"
    fi
done
install -m 0644 "$here/ASSETS.md" "$share/ASSETS.md"
install -m 0644 "$here/icons/phosphor/LICENSE" "$share/icons/phosphor/LICENSE"

# sanity: the helper parses and the QML entry point exists
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$lib/kristall-shell-helper"
test -f "$share/shell.qml"
echo "shell: installed to $share"
