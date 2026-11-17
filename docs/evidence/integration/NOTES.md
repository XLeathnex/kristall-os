# Integration notes (working log; survives restarts)

Brief: /tmp/claude-0/-home-user/86b195bd-b2b0-5fa6-8457-b161a4db30d9/scratchpad/brief-integration.md

## State
- CI at start: Build OS image 43981971715 + Component tests 43981971761 (snapshot b4e361d) in progress.
- kristall-integ image: Dockerfile in this directory (copy also in scratchpad integ/). Build from
  /home/user/kristall with `-f docs/evidence/integration/Dockerfile` (it carries its own .dockerignore).
  - build1 failed: devenv's nodejs 22 conflicts with image's nodejs26 → Dockerfile removes nodejs/nodejs-npm first.
  - build2 killed by container restart.

## Bridge defect: X11 key lost after agent.text (in progress)
Cause (analysis): for an XWayland target, `workspace()->activateWindow()` only *requests* X focus
(XSetInputFocus on KWin's X11 connection); KWin marks the window active when X's FocusIn comes back
(X11Window::focusInEvent). The bridge sent wl_keyboard keys immediately, and released focus
(activate previous window → SetInputFocus elsewhere) in the next event-loop turn. Xwayland reads its
X11 and Wayland sockets in arbitrary order → key delivered to the old X focus / none.
Fix plan: wait for Workspace::windowActivated(target) (timeout) before sending to an XWayland target;
settle ~50 ms before releasing focus from an XWayland target. Code written (agentkeyboard.cpp whenXFocused/sendKey/startJob; kXReleaseSettleMs). Test written:
test_x11_keys_after_clipboard_text. Running it against OLD code (scratch oldbridge copy) to prove it fails.
Test: bridge test_keyboard alternating
text(clipboard)/key on X11; setup test_keyboard: drop the retry.

## Coordinator messages
- hands parallel agent FINISHED: assistant/hands open to edit. Added riskgate.py + data/risky-targets.json
  (activating tools refuse "Senden"/"Kaufen"/"endgültig löschen" targets unless `risk` declared; retry goes
  through owner prompt). hands.md §10, assistant-ipc.md §7.1 line, prompt.py sentence.
  -> Walkthrough step 8: also show one gated action (e.g. "Senden" button): refusal → owner prompt → allowed.
  Open limits: Chromium/Electron/Flatpak/Flathub Firefox untested; Firefox hit-testing at scale 1.6 wrong (bounds fallback).

## Done
(nothing committed yet)

## Todo (brief order)
A CI green; B walkthrough 1-12; known defects (X11 key, flaky hover test); shell leftovers
(switcher glass, pointerLocked/Constrained, KRunner Alt+Space, merge-ini dup, search p95, edge-light);
C INSTALL.md, all suites totals.

## Progress log
- X11 key fix: new test FAILS on old code (deterministic, '1ö' lost after native key: X focus not yet set).
  Running full test_keyboard with the fix (bg task).
- merge-ini: setup/image/merge-ini + dock forwarder deleted; setup install.sh + tests use shell/image/merge-ini. (setup suite to re-run)
- search: machine_factor() calibration (ref 35 ms loop in sandbox devenv, clamp 1..3) scales 8.3 ms / 25 ms / 8 ms / 2 ms budgets. (search suite to re-run)
- Coordinator: Build OS image b4e361d failed in finalize: false-positive kmod-libs; coordinator fixed
  image/build.sh check_kernel (filter ^kmod-(libs|devel)-[0-9]) and published only that; KEEP that change. New image build running.
- Edge light review: per-frame CPU work = FrameAnimation JS (constant: spring ≤25 steps, 4 uniforms), no geometry
  rebuild (ShaderEffect 1x1 mesh, strips resize only with output). Resolution-scaled cost = fragment shading of
  4 strips (~1.26 Mpx at 2880x1800, depth 90 logical) → on llvmpipe that is CPU, on Iris Xe GPU. Nothing to fix CPU-side.
- build.sh: coordinator (or other) also changed check_kernel: kpkgs list + /lib→/usr/lib sed + awk instead of head (SIGPIPE exit 141 in run 43983388390). Keep.
- Coordinator published aed44aa (build.sh check_kernel /lib→/usr/lib + awk) — new image build running. Keep build.sh.
- X11 key fix v2: X round-trip barrier (xBarrier: GetInputFocus on KWin's X conn after wl flush; whenXFocused loops until
  focus==target; whenXDelivered before release). x11 test 5/5 on X side; native-side lag fixed in test with wait_until.
  Needs libxcb (CMake pkg xcb, installer dep libxcb-devel).
- qtprobe: app-wide keypress log (diagnostics). wlprobe: --lock/--confine/--lock-on-key (pointer-constraints).
- bridge windows: pointerLocked/pointerConstrained fields (surface lockedPointer()/Region, signals) — TEST + bridge.md TODO.
- KRunner Alt+Space: helper free_from_krunner() (shortcutKeys/setForeignShortcutKeys) before doRegister; test in shell
  `shortcuts` section (running). shell.md §6 TODO.
- integ image built OK (kristall-integ:latest, 8.5 GB, strict, all 15 components, presets applied, finalize-minus-kernel OK).
  Built from tree BEFORE my fixes → reinstall changed components inside the session container.
- DONE bridge pointerLocked/Constrained: test_pointer_constraint_fields PASS; bridge.md + shell.md updated.
- DONE KRunner: shell `shortcuts` section ALL PASS incl. new helper start 1/2 checks (stock KRunner held Alt+Space; helper freed it; idempotent). shell.md §6/§9 updated.
- DONE hover flake: test-timing (probe log lag; bridge sends restore in one batch before reply). settled_focus() in test_pointer: 6/6 PASS under 8x `yes` load (was 2/3 FAIL).
- DONE X11 key: whole test_keyboard PASS; README + bridge.md updated; setup test retry removed.
- glass kristallGlass on internal windows: glasseffect.cpp readInternalGlass/watchInternalGlass/internalGlassChanged,
  kristallGlassActive handshake; test_render.py `internal` PASS (evidence internal-window-glass.png); glass.md §1.1.
  Switcher main.qml declares it; test_switcher check added (running → scratchpad switcher.log). README updated.
- CI 43985233172: image build + bootc lint PASSED (lint warning /run/dnf, /run/systemd); smoke test failed
  "no Kristall state baked into /var" (/var/lib/kristall exists although clean_mutable ran). Smoke now prints the
  listing and fails only on files (tmpfiles-declared empty dirs are harmless). Root cause unknown until listing seen.
- integ systemd: works with private cgroup2 mount (host is cgroup v1). systemd-pam missing → Dockerfile.update adds it.
  Tools in scratchpad/integ/tools (start-container.sh, prepare.sh, start-session.sh, u.sh, shot.py).
- smoke /var: coordinator diagnosis = the smoke script's own tool calls create /var/lib/kristall. Moved the strict check to the top (before tools run).
