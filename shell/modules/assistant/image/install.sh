#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# assistant-ui: installs the assistant's shell module (light, panel, cursor), its global shortcut
# and its settings defaults. Component contract: docs/ARCHITECTURE.md §3; run by image/build.sh as
# root with cwd = shell/modules/assistant. Needs nothing beyond the shell's own runtime packages
# (Quickshell, qt6-qtsvg, Inter); the shader ships precompiled (tools/gen-shaders.sh).
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
dest="$PREFIX/share/kristall/shell/modules/assistant"

rm -rf "$dest"
install -d "$dest" "$dest/shaders" "$dest/assets"
install -m 0644 "$here"/*.qml "$here/Markdown.js" "$here/qmldir" "$here/strings.json" "$dest/"
install -m 0644 "$here/shaders/edgelight.frag.qsb" "$dest/shaders/"
install -m 0644 "$here/assets/cursor.svg" "$dest/assets/"

# global shortcut (kglobalaccel picks up desktop files from share/kglobalaccel for every user)
install -d "$PREFIX/share/kglobalaccel"
install -m 0644 "$here/kglobalaccel/org.kristall.assistant.desktop" "$PREFIX/share/kglobalaccel/org.kristall.assistant.desktop"

# defaults for assistant.ui (settings.d drop-in, docs/contracts/settings.md)
install -d "$PREFIX/share/kristall/defaults/settings.d"
install -m 0644 "$here/image/settings.json" "$PREFIX/share/kristall/defaults/settings.d/60-assistant-ui.json"

# KRunner's Alt+Space default would take our shortcut: keep KRunner on Alt+F2 and Meta for every
# user by merging its default into /etc/xdg/kglobalshortcutsrc (other keys are preserved)
if [ "$PREFIX" = /usr ]; then
    python3 - /etc/xdg/kglobalshortcutsrc <<'PY'
import configparser, os, sys
path = sys.argv[1]
cp = configparser.RawConfigParser(strict=False, interpolation=None, delimiters=("=",))
cp.optionxform = str
if os.path.exists(path):
    cp.read(path, encoding="utf-8")
sec = "services][org.kde.krunner.desktop"
if not cp.has_section(sec):
    cp.add_section(sec)
cp.set(sec, "_launch", r"Alt+F2\tSearch")   # KConfig escapes the separator as \t
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path + ".tmp", "w", encoding="utf-8") as f:
    cp.write(f, space_around_delimiters=False)
os.replace(path + ".tmp", path)
PY
fi
echo "assistant-ui: installed into $dest"
