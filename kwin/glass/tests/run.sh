#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall glass test suite. Run inside the dev container, e.g. from the repository root:
#   docker run --rm -v "$PWD":/work kristall-devenv:latest kwin/glass/tests/run.sh [quick]
# Builds the plugin, then runs: protocol stress, rendering measurements (refraction against the
# lens model at 1.0x and 1.6x, slider/theme, legibility, idle/cache, timing), multi-output,
# fail-soft (unloadable plugin, crash guard) and refreshes tests/evidence/*.png.
# Exit status is non-zero if any check fails.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
glass="$(dirname "$here")"
export KRISTALL_GLASS_BUILD="${KRISTALL_GLASS_BUILD:-/tmp/kristall-glass-build}"
export KRISTALL_GLASS_RESULTS="${KRISTALL_GLASS_RESULTS:-$KRISTALL_GLASS_BUILD/results.json}"
rm -f "$KRISTALL_GLASS_RESULTS"

echo "== build"
"$here/build.sh" || exit 1

echo "== static checks"
status=0
bash -n "$glass/image/install.sh" && echo "PASS install.sh parses" || { echo "FAIL install.sh syntax"; status=1; }
if command -v shellcheck >/dev/null; then
    shellcheck -S warning "$glass/image/install.sh" "$here/run.sh" "$here/build.sh" && echo "PASS shellcheck" || { echo "FAIL shellcheck"; status=1; }
fi
python3 -m py_compile "$glass/tools/kristall-glass-ctl" && echo "PASS kristall-glass-ctl compiles" || status=1
for f in "$glass"/src/shaders/*.frag "$glass"/src/shaders/*.vert; do
    # KWin's ShaderManager rewrites "#version 140" for GLES; validate the desktop variant here
    glslangValidator -S "$( [[ $f == *.vert ]] && echo vert || echo frag )" "$f" >/dev/null \
        && echo "PASS glslang $(basename "$f")" || { echo "FAIL glslang $(basename "$f")"; status=1; }
done

echo "== broken plugin for the load-failure test"
broken="$KRISTALL_GLASS_BUILD/broken"
cmake -S "$glass" -B "$broken/cmake" -G Ninja -DKRISTALL_GLASS_TEST_BROKEN=ON >/dev/null && ninja -C "$broken/cmake" >/dev/null
mkdir -p "$broken/plugins/kwin/effects/plugins" && cp "$broken/cmake/bin/kristall_glass.so" "$broken/plugins/kwin/effects/plugins/"
export KRISTALL_GLASS_BROKEN_PLUGINS="$broken/plugins"

run() {
    echo "== $1"
    shift
    dbus-run-session -- python3 "$@" 2>&1 | grep -v "Failed to set fd limit"
    [ "${PIPESTATUS[0]}" = 0 ] || status=1
}
run "protocol" "$here/test_protocol.py"
if [ "${1:-}" = quick ]; then
    run "rendering (quick)" "$here/test_render.py" refraction idle
else
    run "rendering" "$here/test_render.py" refraction refraction16 slider legibility idle timing multioutput internal evidence
fi
run "fail-soft" "$here/test_failsafe.py"

cp "$KRISTALL_GLASS_RESULTS" "$here/evidence/results.json" 2>/dev/null || true
echo "== results: $here/evidence/results.json"
[ "$status" = 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$status"
