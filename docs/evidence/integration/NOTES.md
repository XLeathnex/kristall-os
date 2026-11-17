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
- PUBLISHED round 2 (see git log in kristall-os).
- ISO decisions (round 2): build-iso.yml mkdir output before Titanoboa (realpath w/o -m); build-live.sh embeds NO Flatpaks
  (apps install at first start; INSTALL.md already says it needs internet) and deletes speech models + assistant venv from the
  LIVE rootfs only; OS payload (offline install) kept. apps.md embed_in_iso reworded. INSTALL.md size "8–12 GB" to update
  once CI reports the real size.
- Step 8 plan: daemon in --demo via drop-in (no real Claude login; never copy my own credentials); tools/hands.py drives
  /usr/bin/kristall-hands over MCP with the daemon's real Policy (like hands' test_riskgate_e2e); riskwin.py for "Senden".
- Step 12 startup (fresh container, llvmpipe, scale 1.0 at start): session start→KWin started 1.8 s; plasmashell 14.0 s; graphical-session.target 17.0 s; kristall-shell started 17.2 s; dock module loaded 22.5 s; bar+Dock mapped 23.6 s; no frames for 2 s from 24.4 s. Kristall's own part ≈ 6.4 s (shell start → mapped), rest is Plasma/KWin startup on software GL.
- Step 8 (session 3, demo daemon): Option+Space (physical Win+Space) → panel + edge light + streamed demo text + permission
  card + agent cursor (08a–08c); owner cursor stayed at (1500,600). hands over MCP with real Policy (tools/hands.py flow8.py):
  open_app Texteditor → ui_tree → ui_act New File → screenshot → click (agent cursor) → type_text German multi-line list with
  umlauts: "Verified in the text field" (08d); owner cursor unchanged (1574,401) before/after.
  Firefox: Fedora's redhat prefs already set intl.locale.requested "" → my pref was redundant, REVERTED. First Firefox start
  stays English + "Firefox spricht Ihre Sprache" (Fedora wrapper links the langpack into the profile; active from 2nd start) → open.
  KWrite started by hands showed its in-window menu (English), bar had minimal menus → check menus topic after restart.
- Step 8 riskgate: hands refuses click on 'Senden' (16 ms, guiding error), retry with risk:send → policy ask „Darf ich etwas in deinem Namen senden?“ → allow once → Clicked; riskwin log confirms (08e/08f). FIX theme: gtk-hint-font-metrics only in gtk-4.0 settings (GTK3 warned every start) + theme test.
- Step 8 more: hands read Firefox (opened before hands) tree: 72 lines, German labels (Tab schließen…). Copilot key (fake
  input Meta+Shift+F23, Mac keyboard on) did NOT open the assistant — remapper keeps Meta for F23 (remapper.cpp:763), cause
  not found, UNVERIFIED on hardware → open. Hold-to-talk: release not observable in logs → unverified.
  FIX daemon: agent cursor stayed on screen after a demo turn was cancelled mid-path (label "Bilder"): _finish_turn hides
  a visible cursor when no turn remains + test_cancelled_turn_hides_the_agent_cursor.
- Step 9: kristall-power status --json OK (mode balanced, reason auto, power_source none); doctor runs (German, real sysfs of
  the sandbox; top wakers gmenudbusmenuproxy 2/s, firefox, dbus, tuned 1/s, tuned-ppd 1/s); kristall-update status --json OK
  (state unknown, bootc false). Settings Batterie page (09a): mode Automatisch + reason; "Batterie" heading empty without
  battery (cosmetic). Window title "System Settings" English (KDE).
- Step 10: resilience (kill -9): quickshell back 1.26 s, usable (bridge+glass) 2.26 s; helper 0.55 s; assistant daemon 3.26 s; appearance 2.21 s; power session 2.28 s. CRITICAL FIX: one shell crash triggered OnFailure= fallback (systemd fires it per crash before restart): Plasma panel appeared + plasmashell took org.freedesktop.Notifications + 'Menüleiste ausgefallen' notification. Fix: RestartMode=direct + fallback script refuses while SubState auto-restart/running + cleanup re-requested on helper ready; static tests; shell.md §8. Verified: crash → no panel/marker (10c).
- Step 10 KWin: kill -9 kwin_wayland → wrapper restarted it in 115 ms; shell back on bridge+glass 2.1 s; kristall_glass loaded; keyboard plugin running (reason on); KWrite/Settings survived; FIREFOX CRASHED (English 'Firefox Crash Reporter' dialog — upstream, no Wayland reconnect). Ctrl+Up opens Overview after KWin restart (new kglobalaccel file read) → Overview fix VERIFIED (10e). Plasma kept org.freedesktop.Notifications (pid plasmashell) after the earlier fallback panel removal → open (real fallback case).
- Step 11 EN: setup Welcome + Get Online (11a/11b), menu bar 'Files File Go Window', CC English (DND label truncated 'Do Not Dist…'), assistant panel English 'Before Kristall can help, Claude needs to be set up once' (11c/11d). PASS.
- Idle 2 (EN session, 60 s): 0 frames in 30 s (1 in 60 s); Kristall total 1621 MB RSS; daemon 1055 MB RSS right after start (speech models loaded eagerly) and 2.8 % CPU in that minute; quickshell 356 MB; helpers ~15-34 MB each.
- RESTART #3. Round-2 CI: image SUCCESS; Component tests FAIL in shell (shortcuts: test _qt_key had no "Up"), theme (accent:
  --accent-color doesn't store AccentColor → now written after; Selection expectation was exact token, now "green-dominant"),
  panels (image-path arrives as image://icon//abs/path → my icon-name rule ate it; now paths excluded). All three FIXED in tree,
  re-run of shortcuts+panels was killed by the restart → rerun. ISO 43995804272 running.
- NEW TASK (coordinator): lazy speech models (ASR/TTS/VAD load on first use, unload after assistant.voice.unloadAfterSeconds
  default 300; warm ASR on invoke), document settings.md + assistant-ipc.md, measure idle RSS before/after and first-utterance
  latency cold/warm. Before: daemon 1055 MB RSS right after login.
- LAZY MODELS: design already lazy (39 MB RSS at login; my 1055 MB came from invoking right before measuring). Real defect:
  after unload RSS stayed 684 MB (glibc kept pages). FIX voice/models.py release_memory() (malloc_trim) after unload →
  1085 → 71 MB. test_unloaded_models_give_memory_back (needs models: passes in kristall-integ). Latency (transcribe,
  4.24 s German sentence, mic buffered while loading): models unloaded → final 0.74 s after speech end (first partial 2.26 s);
  loaded → 1.16 s. Page-cache-cold first load after container start took 29.5 s (sandbox overlay disk) — first use after boot
  on real NVMe unmeasured. Kept existing key assistant.models_unload_after_seconds (300) instead of a new voice.unloadAfterSeconds;
  assistant-ipc.md row updated.
- FIX bridge: org.kde.kappmenuview never claimed in a fresh session (old code set m_menuViewWanted before the bus check → lost forever; menus only after a shell restart). syncMenuView/retryMenuView (1 s, ≤30). test_application_menus passes; needs fresh-login verification in integ.
- ISO run 43995804272 SUCCESS: artifact Kristall-OS-Installer.iso 8,856,205,312 B (8.2 GiB), sha256 c8388d65…; live /usr 7.9 G,
  OS payload (oci, offline install) 4.6 G. INSTALL.md size → "8–9 GB". Removed invalid `remove-codeql` input (warning).
  Getting ≤6 GB needs dropping the offline payload (network install from ghcr.io) → decision for coordinator.
- panels suite ALL PASS (after image-path fix). Theme suite run was interrupted (re-run).
- Bridge menu fix VERIFIED fresh session: kappmenuview owned by kwin at login, Dolphin menu exported; daemon 39 MB at login.
- PUBLISHED round 3 49e282f.
- Part C: INSTALL.md build times 20–30 min (CI measured 17/15 min), footer: no Flatpaks on stick. Full suites run started (kristall-integ-suites, scratchpad/suites).
- CI round 3 49e282f: Component tests 43998310990 SUCCESS (all 15 jobs). Local full run: image, power, glass, bridge, shell, panels pass so far.
- CI round 3: Build OS image 43998310979 SUCCESS; ISO run 44000971967 skipped build (installer from 43995804272 still current, <7 days).
- Local full run (kristall-devenv, sequential, --network none): all 15 suites exit 0 except setup (exit 1: keyboard
  system-chords, 5 global shortcuts not seen within 3 s after an xdg-document-portal/fuse activation in that run).
  keyboard:system re-run 3+10 times: all pass. Reproducing with full keyboard suite loop (kristall-integ-flake).
- voice: test_unloaded_models_give_memory_back flaky with real models (1/3 full-module runs). Diagnosis: onnxruntime
  frees the rest ~1 s after the last reference (742 MB → 254/489 MB without a trim), a second malloc_trim then →
  63 MB. FIX models.py: unload() schedules release_memory again after RELEASE_AGAIN_AFTER=2 s; test waits 2.5 s.
  3/3 full voice module with models pass; assistant/core suite 140 passed, 10 skipped (no models in devenv).
- setup flake ROOT CAUSE: the key test's logger desktop file claims the same keys as the stock Spectacle (Print
  chords), emoji picker (Meta+.) and KRunner (Alt+Space) files in /usr/share/kglobalaccel; kglobalaccel registration
  order decides the winner (exactly those 5 failed; Spectacle, a Qt app, then activated the portal → fuse error).
  FIX setup/tests/test_keyboard.py: shadow those three files with key-less ones in the test's XDG data dir + check
  "no stock owner competes" via KGlobalAccel.allComponents. keyboard:system passes; full setup suite re-running.
- Step 7 logout: no Mac chord for log out exists (none designed; ⇧⌘Q unbound) → via menu bar  menu 'kristall abmelden …' → Kristall logout dialog, German, 60 s countdown, Esc cancels (07e). Neustart … dialog also seen. (My earlier misclick came from assuming scale 1.6; this session runs at 1.0.)
- setup suite full re-run: ALL PASSED (with the shadowing fix). Final local totals: all 15 suites green.
- PUBLISHED round 4 bb65abb. Watching CI.
- Step 3 window arranging: drag title bar to the left edge → KWin edge-tile preview → left half between menu bar and Dock (03q). PASS. (o.py drag must be one invocation: fake-input client disconnect releases the button.) Lock screen in this container shows English 'Password'/'Virtual Keyboard' — kscreenlocker translations missing in the sandbox (stripped %_install_langs), not checked on the image.
- CI round 4 bb65abb: Build OS image 44012814486 SUCCESS; Component tests 44012814473 FAIL: apps (↩ opens Kate; Dock
  tile opens Apps) and dock (pointer left: 1 compositor frame in 4 s). Both flaky, not round-4 changes.
  apps ROOT CAUSE (reproduced 2/5 locally, timestamped): the 'Deinstallieren' check really ran xdg-open appstream://…,
  which in the dev container is Firefox; its window mapped ~1 s later and took the keyboard, so ↩ went to Firefox.
  FIX test: stub x-scheme-handler/appstream (NoDisplay desktop file + mimeapps.list). 10/10 behaviour runs pass.
  (Image: Discover stays installed hidden and handles appstream:// until Bazaar is there.)
  dock: Dock frames 0 and shell CPU 0; the one compositor frame came from Kate/Konsole under the resting pointer
  (late hover repaint). FIX test: start the 4 s window after the compositor was quiet for 1 s (max 4 s). Looping.
- dock idle: settle alone still failed 1/4 locally ({"compositor_frames": 1, "shell_cpu_ms": 10}): the menu bar clock
  repaints on the minute. Added: window kept clear of the minute tick (start ≥ :54 → wait to :01) + started_at_second in
  the result. perf section 8/8 pass, all zero.
- PUBLISHED round 5.
- CI round 5 e02d225: Component tests 44018331785 SUCCESS (15/15). Session container removed; kristall-integ:latest image kept for reproduction.
- CI round 5: Build OS image 44018331818 SUCCESS. Final report delivered.
