# kwin/glass — Liquid Glass for Kristall OS

A KWin 6.8 effect (Wayland) that draws **refracting** glass inside the compositor, from the live
screen content, for shapes the shell declares over `$XDG_RUNTIME_DIR/kristall/glass.sock`, and
for every surface that asks for background blur (it replaces KWin's stock blur effect).
The interface other components use is specified in [`docs/contracts/glass.md`](../../docs/contracts/glass.md).

```
src/            effect (C++/GLSL): glasseffect.* (windows, bindings, damage, animation, legibility)
                glassrenderer.* (GPU passes), glassserver.* (socket protocol), glassshape.* (shape
                model), glasssettings.* (settings.json, Plasma scheme, UPower), surfacetracker.*
                (layer-shell namespaces), crashguard.*, shaders/
tools/          kristall-glass-ctl — CLI for scripts and tests (Python, stdlib only)
demo/           Quickshell demo + the reference QML client (GlassClient/GlassSurface/GlassShape)
image/          install.sh (component contract)
tests/          run.sh, build.sh, test_protocol.py, test_render.py, test_failsafe.py, support/,
                evidence/ (screenshots + results.json from the last run)
```

## How the material is built

Per glass window, per output, in `drawWindow` before the window's own pixels:

1. **Geometry (CPU).** Shapes → global device pixels (output scale, window scale/translation and
   opacity from KWin's paint data are applied, so sliding/fading windows keep their glass).
   Shapes of one `group` within `merge` distance become one *body* (smooth union, ≤ 8 shapes).
   Bodies whose reach overlaps share one *capture cluster*; capture rects snap to a 32-logical-px
   grid so a magnifying Dock keeps the same capture.
2. **Capture** (`glBlitFramebuffer`, pixel-exact): only when the background behind the cluster
   changed, and only the repainted part. "Changed" is decided per frame from KWin's own damage:
   windows below the glass window with pending item repaints, other effects' layer repaints,
   window moves/closes/stacking changes, and the glass window's own transforms. Our own shape
   updates repaint through the glass window's item and therefore never invalidate the cache.
3. **Light blur**: Dual Kawase (derived from KWin's blur), 1–4 iterations chosen from the
   requested radius (`2 + 8·slider` logical px for regular glass, `1 + 2·slider` for clear),
   result at ½ resolution (¼ in the efficient tier). Skipped when the capture is cached.
4. **Composite** (`composite.frag`, the only per-frame cost when something moves):
   signed distance to the outline (circular or p-norm "continuous curvature" corners, G2 with
   the edges; capsules), outward normal, lens profile `displacement = depth·(1−t)²` over the
   bezel (flat interior, content from just outside is pulled into the rim and compressed,
   following the outline around corners), R/B sampled at ±7 % depth in the rim (chromatic
   split), saturation 1.3, tint, a legibility luminance band per text scheme, inner shadow,
   specular rim from the upper left plus a softer counter-light, pointer glow, pressed state,
   triangular dither, premultiplied output with 1-px anti-aliasing.
5. **Legibility**: after a re-blur, a 16-tap average under each tracked shape is written to a
   64×1 strip and read back **asynchronously** (PBO + fence, polled by a 16 ms single-shot timer,
   never on the paint path). Hysteresis + 600 ms dwell decide light/dark; the glass cross-fades
   in 300 ms and the shell gets a `legibility` event.

Idle: with nothing changing KWin does not paint and the effect does nothing (no timers run).
Animations (pressed, scheme fade) schedule repaints only while they run.

## Build and test (dev container)

```sh
docker run --rm -v "$PWD":/work kristall-devenv:latest kwin/glass/tests/run.sh        # everything, ~15 min
docker run --rm -v "$PWD":/work kristall-devenv:latest kwin/glass/tests/run.sh quick  # protocol + refraction + idle
```

The sandbox has no GPU, no `/dev/dri` and no `/dev/udmabuf`. KWin 6.8 only creates its llvmpipe
"software render device" when `/dev/udmabuf` exists, so the tests preload
`tests/support/fake_udmabuf.c` (pretends the device exists and hands the memfd back as the
"dmabuf"; llvmpipe maps it). `kwin_wayland` is copied without its file capabilities (containers
refuse `cap_sys_nice`). Output scales are set with `kscreen-doctor` (the virtual backend's
`--scale` only changes the mode size). Screenshots come from KWin's `ScreenShot2` D-Bus API.

What `run.sh` checks (numbers from the last run are in `tests/evidence/results.json`):

* compile (warnings shown), shellcheck, glslang on every shader, CLI compiles;
* protocol: malformed input, atomic rejection, 3000 rapid updates, `sync:"commit"`, client
  SIGKILL, reconnect, >1 MiB line, non-reading client, 40 connections, surface destroyed and
  re-created, 12 surfaces;
* refraction measured from images (isolate mode, line patterns) against a numpy port of the lens
  (`tests/support/lensmodel.py`) at 1.0× and 1.6×: straight edges, interior, top edge and the
  continuous-curvature corner;
* slider and theme change the result; legibility flips over white vs black content in both themes;
* idle (0 frames, 0 effect work, 0 CPU over 5 s), blur cache hits for shape-only changes and a
  growing Dock, invalidation when the background changes;
* per-pass timing via the debug switch, both tiers; multi-output with `output` matching;
* fail-soft: unloadable plugin (built with an unresolved symbol) and the crash guard;
* evidence PNGs of the demo over a busy background (1.0×/1.6×, light/dark, clear/tinted).

Manual: `quickshell -p kwin/glass/demo` in a session; `kristall-glass-ctl status|watch|debug --timing on`.

## Fail-soft: why a broken plugin cannot take the session down

* **Image build**: `install.sh` builds against the image's own KWin and then `dlopen`s the result
  with `RTLD_NOW`; any unresolved symbol fails the image build, so the laptop keeps its last
  good image.
* **Load failure at runtime** (unresolved data symbol, missing file): KWin logs "Did not get
  KPluginFactory" and composites without the effect; the socket does not exist and clients fall
  back. Tested (`test_failsafe.py`, plugin built with `-DKRISTALL_GLASS_TEST_BROKEN=ON`).
* **Caveat found while testing**: Qt loads plugins with lazy binding, so a missing *function*
  is not a load failure — KWin crashes when it is first called. That and any other crash during
  start-up is caught by the crash guard: after two consecutive crashes within 30 s of start the
  effect stays inert (`state:"disabled"`) for the session, so `kwin_wayland_wrapper`'s restart
  loop (up to 10 restarts, then the session dies) never runs out. Tested by aborting in the
  constructor (`KRISTALL_GLASS_TEST_CRASH=1`) across emulated wrapper restarts: crash, crash,
  then KWin runs with glass disabled.
* **No OpenGL / shader failure**: the effect is unsupported or reports `state:"failed"`; KWin
  draws normally.

## Upstream code and licences

* `src/glassrenderer.cpp`, `src/shaders/downsample.frag`, `src/shaders/upsample.frag`: the
  capture → Dual-Kawase structure and the two blur kernels are derived from KWin's blur effect
  (`src/plugins/blur/`, KWin 6.8.2/6.8.3, © Fredrik Höglund, Alex Nemeth, KWin team,
  **GPL-2.0-or-later**); headers keep that licence and attribution.
* `src/glasseffect.cpp`: collecting blur requests (surface blur region, `kwin_blur`, decoration
  blur region) and the skip rules follow the same blur effect (GPL-2.0-or-later).
* Everything else is new Kristall code, GPL-3.0-or-later; the built plugin as a whole is
  GPL-3.0-or-later.
* `4v3ngR/kwin-effects-glass` and `xarblu/kwin-effects-better-blur-dx` were studied (both refract
  inside the stock blur's on-screen pass, window-wide, rounded rectangles only, KWin ≤ 6.7); no
  code was taken. Lessons kept: clamp refracted lookups to the captured area, keep the dispersion
  small, and never refract with the full-strength blur result alone (it turns into fog).

## Known limits

* Verified only on llvmpipe in a headless KWin 6.8.3. Not measured on Iris Xe, at 120 Hz, or on
  a real fractional-scale panel (see the estimate in the final report / contract §6).
* Colour management: glass math happens in the render target's encoding (like KWin's blur). With
  HDR or an ICC-managed output the tint/legibility values are approximate.
* Rotated outputs: capture goes through KWin's logical-rect blit, up to ½ device px off at
  fractional scales (normal and flipped targets are exact).
* Windows painted through an offscreen effect (e.g. wobbly/magic lamp) or rotated/3-D
  transforms show no glass for the duration (same as the stock blur).
* Glass does not refract other glass (each body samples the screen below the glass window).
* A change hidden under an opaque window above the glass is not re-captured until it repaints.
* Xwayland apps asking for blur via `_KDE_NET_WM_BLUR_BEHIND_REGION` get no glass.
* The layer-shell namespace of surfaces created *before* the effect loaded is recovered through
  Qt private API (connection list of the window); the image always builds against its own Qt.
