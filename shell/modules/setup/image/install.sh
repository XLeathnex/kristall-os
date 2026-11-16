#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# The Setup Assistant's shell module (docs/contracts/shell.md §2): copies this directory to the
# shell's modules. Called by setup/image/install.sh (one components.list line, `setup`, is enough).
set -euo pipefail
PREFIX="${KRISTALL_PREFIX:-/usr}"
here="$(cd "$(dirname "$0")/.." && pwd)"
dest="$PREFIX/share/kristall/shell/modules/setup"
rm -rf "$dest"
install -d "$dest"
install -m 0644 "$here"/*.qml "$here/qmldir" "$here/strings.json" "$dest/"
echo "setup module: installed to $dest"
