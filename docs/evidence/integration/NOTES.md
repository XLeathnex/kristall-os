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
- PUBLISHED 9deab88 (round 1). Watch Build OS image.
- Session works: start-container.sh → prepare.sh (kwin shim must be named kwin_wayland; QPA checks) → start-session.sh. u = run as owner w/ session env. o.py = owner input (logical coords = shot1440 × 1.25 at scale 1.6). Scale 1.6 set via kscreen-doctor (virtual output has no EDID size).
- WALKTHROUGH step 1 in progress (shots in scratchpad/integ/shots; copy best to docs/evidence/integration as JPEG at the end).
  Fixes so far: StepDisplay re-queries displays when shown; SetupWindow dots no longer overlap long buttons;
  setup steps can yieldToApps (sign-in: card to lower right, no dim, input only on card, keyboard OnDemand);
  account.py: no double browser open (CLI opens itself) + children die with helper (PDEATHSIG, SIGTERM → exit)
  [tests: assistant/core test_account_login_opens_the_browser_once, test_account_cancel_ends_the_cli]; image: firefox-langpacks.
  Observed: container HAS internet (Claude installer really ran: claude 2.1.326 in ~/.local/bin). Firefox bar
  "Speech Dispatcher library is missing" (English) on claude.ai.
- Step 1 DONE (pass with fixes): every setup step in German via keyboard+pointer; mic test with PipeWire pipe-source
  + Piper TTS WAV → transcript "Wie wird das Wetter morgen?" (real local ASR). Sign-in: real installer ran, OAuth URL correct
  (claude.com/cai/oauth/authorize, client_id, PKCE S256, redirect localhost / platform.claude.com), cancel + Jetzt nicht path ok.
  More fixes: KText property `st` shadowed setup steps' `id: st` → "{name}" shown verbatim (renamed typeStyle; setup smoke checks
  no {placeholder}); SetupTestHooks.texts().
  Open: setup card over a white browser shows the browser text through it (legibility); Return activates the focused
  "Noch einmal" not Weiter; Firefox UI English until langpacks (added) + its English "Speech Dispatcher" bar; Firefox CSD
  buttons are not traffic lights. Dock folder icon kept old accent until shell restart.
- Step 3 findings+fixes: (1) CRITICAL: apps started from Dock/Apps/Search were children of kristall-shell.service →
  `systemctl --user restart kristall-shell` (or a crash, Restart=always) KILLED all apps. Fix: Apps.launchDesktopId (kstart
  --application → app-<id>@.service), runScoped (systemd-run --scope) for actions; AppCatalog/DockMenus use them; shell static
  test; shell.md §7. Verified: dolphin/systemsettings survive shell restart. (2) Dock stuck magnified + label after Apps
  overlay open/close: Dock resets hover on ShellBus.openChanged + sets hovering on motion. (3) kdesystemsettings.desktop
  (NotShowIn=KDE, not evaluated by Quickshell) listed twice → hidden-apps.list. (4) container stripped translations
  (%_install_langs) → reinstalled pkgs in session (sandbox artefact, not image).
  Open: System Settings opens on "Plasma Systemeinstellungen" placeholder (KDE branding); kxkbrc reload didn't switch
  layout live (owner typing US); Firefox CSD; window titles show "Dolphin"/"KWrite".
- CI round 1 (9deab88): Build OS image 43987258165 SUCCESS, Component tests 43987257978 SUCCESS; ISO 43990164711 running (Find the published image passed → package already public).
- Step 3 more: Cmd-Tab (physical Alt) → glass switcher PASS (03h). Minimise via yellow → tile in Dock, restore from tile PASS;
  minimise ANIMATION not testable: KWin loads no animation effects on llvmpipe (magiclamp/scale/maximize absent from
  loadedEffects; animationsSupported false on software GL) → unverified. Green = maximise (zoom) PASS; Ctrl+Cmd+F full screen PASS.
  FIX: full-screen menu-bar reveal never slid away (bar moved Top→Overlay under resting pointer, no enter → no leave) →
  Bar.qml revealWatch (bridge cursor.get, 2 Hz only while revealed & unhovered). Verified slides away.
  FIX: Ctrl+Up Overview missing (KWin ignores extra keys for its Overview action from /etc/xdg) → switcher
  kglobalaccel/org.kristall.switcher.desktop (invokeShortcut Overview). Overview itself works (03o) but KDE-looking
  (desktop bar "Desktop 1" +, English "Search..." from stripped translations).
  OPEN: maximised GTK3 CSD window (mousepad): traffic lights not vertically centred, half under the menu bar (theme gtk css).
  kglobalaccel in real session: KRunner = [Search, Alt+F2] (no Alt+Space); assistant-talk = Alt+Space, Meta+Shift+F23, Meta+Shift+TouchpadOn.
- Step 4 PASS: Cmd+Space search apps (dolph→Dateien), settings (tastatur→Tastatur; wlan has no page: plasma-nm absent in devenv), files (baloo: Rechnung-Fahrrad-2026.txt), Ask hand-off → assistant panel 'Melde dich ... an' (not signed in). Web search row → Firefox Google.
- Step 5: CC opens (05a); banners for notify-send (05b) and Flatpak-style libnotify (05c); FIX NotifEntry: icon-name image (image://icon/<name>) → app icon slot, not checkerboard image (+panels test). DND via Focus page switch: no banner, in Notification Center (05e-05g), off → banner (05h). Portal (org.freedesktop.portal.Notification) from a host process: nothing shown — UNVERIFIED for real Flatpak (no Flathub here). Leftover notification 'Die Menüleiste ist ausgefallen' from my rapid manual shell restarts (StartLimitBurst counts systemctl restarts).
- Step 6: Settings→Erscheinungsbild Dunkel+Lila: within ~2 s shell, Settings, Firefox, GTK3 mousepad, wallpaper, decorations dark (06c). OPEN: Dock/Apps folder-type icons (Files, Downloads) keep the old accent until the shell restarts — shell process's QIcon/KIconEngine pixmaps not recoloured on palette change; cache-busting URLs (tried, reverted) did not help. Lock screen check pending (step 7).
- Step 6 more: ACCENT ONE CHANGE BEHIND in running Qt apps (sidebar/Firefox showed the previous accent): kristall-appearance
  set_scheme pre-writes kdeglobals AccentColor (notify=False) then runs `plasma-apply-colorscheme --accent-color` → it sees no
  change. Fix in progress: pre-write only when the scheme also switches.
- Step 7 (partial): Ctrl+Cmd+Q locks (07a big clock, dark variant); bridge hello locked:true and `bridgectl type` → "denied: the
  screen is locked"; unlock with password works (07b/07c). Lock screen shows KDE "Virtuelle Tastatur" button (plasma-keyboard).
  Shift+Cmd+Q produced no log-out dialog (to check). Remaining: logout dialog, steps 8–12.
- RESTART #2 (coordinator): containers killed. ISO run 43990164711 failed only at upload: titanoboa wrote
  _actions/ublue-os/titanoboa/<sha>/output/KRISTALL-OS.iso (11.8 GB!) not output/Kristall-OS-Installer.iso. TODO fix path + size.
