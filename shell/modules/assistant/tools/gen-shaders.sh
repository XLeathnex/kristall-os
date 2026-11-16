#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Rebuilds shaders/*.qsb from their GLSL sources (Qt Shader Tools; run in the dev container).
# The .qsb files are committed so the image build needs no shader compiler.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
qsb="$(command -v qsb || echo /usr/lib64/qt6/bin/qsb)"
for f in "$here"/shaders/*.frag; do
    "$qsb" --glsl "100 es,120,150" --hlsl 50 --msl 12 -o "$f.qsb" "$f"
    echo "built $f.qsb"
done
