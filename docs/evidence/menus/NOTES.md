# Menus round notes (working log; survives restarts)

Task: every app's menu bar only in our top bar (global menu), German, fallback in-window when our bar can't show it.
Tools: scratchpad/menus/tools (copy of polish tools), containers kristall-menus-*.

## Progress log
- start: read integration/polish notes; bridge owns org.kde.kappmenuview while a `menus` subscriber exists.
- integ container kristall-menus-os (tools scratchpad/menus/tools; prepare.sh now sets a password + no autolock).
  Container lacks translations (%_install_langs) → `dnf5 reinstall` of KDE/GTK pkgs inside container (sandbox artefact).
- ROOT CAUSE (confirmed, Qt 6.11 source): QGenericUnixTheme::isDBusGlobalMenuAvailable() is a function-static,
  evaluated ONCE per process at the first QMenuBar (com.canonical.AppMenu.Registrar present?). Registrar exists only
  while org.kde.kappmenuview is owned; the bridge owned it only while the shell was subscribed to `menus`.
  → app started while the shell is not (yet) subscribed (login before shell, shell restart) keeps an in-window bar
  forever (repro: stop shell, start kwrite, start shell → kwrite menu=None, in-window bar; 01a). Conversely apps
  already native never got the in-window bar back when the shell went away (no fallback at all).
- System Settings exports an EMPTY menubar (KMainWindow, actions only in its QML hamburger) → bar shows standard menus.
- Mousepad (GTK3 native Wayland): in-window bar, menu=None (gmenudbusmenuproxy is X11-only).
- before shots saved: 01a kwrite, 02a mousepad, 03a systemsettings (scale 1.6).
- PLAN: bridge owns kappmenuview always (registrar from KWin start); new name org.kristall.AppMenuView owned while
  `menus` subscribers; Qt platform-theme piggyback plugin "kristall" (returns the real kde theme, adds a guard that
  toggles QMenuBar::nativeMenuBar on AppMenuView presence = in-window fallback); GTK3 Wayland module exporting
  GtkMenuBar via libdbusmenu-gtk3 + org_kde_kwin_appmenu, hide/show by AppMenuView.
- ROOT CAUSE 2 (found in integ): KWin's decoration Settings::readSettings (startup + EVERY reconfigure) calls
  ApplicationMenu::setViewEnabled(false) (no title-bar app-menu button) → unregisterService(org.kde.kappmenuview)
  on KWin's own D-Bus connection — the same connection the bridge plugin used → the bridge's ownership is dropped
  silently (registrar gone) on every KWin reconfigure (appearance/accent switch, kwinrc change). My first build
  (claim at plugin init on KWin's connection) lost it at startup. FIX: BusNameClaim on a private connection
  (kristall-bridge-names, opened on a worker thread). TODO: show on old code that reconfigure drops it.
- Qt fallback VERIFIED in integ: shell stopped → after grace both KWrites show German in-window bars (m10);
  shell started → bars hidden, menus back in our bar at /MenuBar/3 (m11). Autostart KWrite at login: menu exported.
- SHELL BUG found+fixed: a quick click/tap on a menu title (press+release before the kristall-menu layer surface is
  configured) ACTIVATED THE FIRST ITEM (KWrite: Datei→Neu new doc; Auswahl→Alles auswählen). Cause: panel placed
  against a 0×0 window at (6,6), release on the title hit row 0. Fix core/MenuHost.qml (panel `placed`, hit() skips
  unplaced panels; title release only selects after a drag into the menus) + Menus.dragRelease(fromTitle).
  Test: shell appmenu "quick click / tap on a title…" (TestHooks.quickClick) FAILS old (TRIGGERED Neu) / PASSES new.
- PROVEN on old bridge code (scratch test test_oldreconf.py): shell subscribed → kappmenuview owned → one
  `org.kde.KWin.reconfigure` → name gone (registrar gone). New bridge tests (test_windows: application_menus,
  menu_view_names, menus_of_apps_started_before_the_shell, qt_menu_bar_fallback) FAIL 4/4 on old code, PASS 4/4 new.
- GTK: wrote kwin/bridge/appmenu/gtk/kristall-appmenu-gtk.c (own DBusMenu over GDBus from GtkMenuBar widgets,
  org_kde_kwin_appmenu on the window surface, class-vfunc size 0 + child-visible off while AppMenuView owned,
  gtk-shell-shows-menubar forced off in-process so GtkApplicationWindow bars are made and exported).
  bridge test_gtk_wayland_menus PASS (plain GtkMenuBar + GtkApplication GMenu bar, accel→shortcut, check item, fallback).
- devenv: tools/devenv/Dockerfile new layer gtk3-devel + mousepad; local kristall-devenv:latest rebuilt with that layer.
- Shell: Theme.shortcutText now Mac order ⌃⌥⇧⌘ (was ⌘⇧N for Shift+Cmd+N; Mac shows ⇧⌘N) + shell appmenu check.
- integ (fresh login, all new code): autostarted KWrite + Mousepad (started with/before the shell) export menus;
  Mousepad menus in our bar, German, ⇧⌘N order, Neu activates (new tab), ⌘N (physical Alt) reaches Mousepad,
  Ctrl+F2 + arrows + Return opens "Datei öffnen" from our bar. Fallback: stop shell → KWrite+Mousepad own German bars
  (04a), start shell → hidden, menus in bar (04b). KWin kill -9: KWrite reconnects, re-announced /MenuBar/4, menus OK.
  Mousepad (GTK3) dies with the compositor (no Wayland reconnect in GTK3; upstream).
- LibreOffice 26.8 (installed in container): kf6 VCL (default under Plasma) → German menus in bar (05a), fallback
  in-window + back OK. gtk3 VCL (SAL_USE_VCLPLUGIN=gtk3) → NO menus at all on Wayland (LO hides its bar when the
  registrar exists, announces via X11 props / gtk_shell only). NOT FIXED, documented (needs libreoffice-kf6).
- Blender 5.2.1 RPM + wine-core installed in container: Blender menu=None, own UI fine, bar "Blender Ablage Fenster".
  Wine notepad: menu=None, own Win32 menu drawn in window; bar named it "Exe" (appId notepad.exe) → shell fix
  Apps.displayName strips .exe ("Notepad", "RobloxStudioBeta") + shell core check.
- u.sh did not import GTK_*/GDK_* env → GTK apps started via u.sh lacked GTK_MODULES (tool bug; fixed in my copy).
- after shots saved: 01b kwrite, 02b mousepad, 03b systemsettings; fallback 04a/04b.
- devenv: Dockerfile layer gtk3-devel only (mousepad dropped to avoid side effects); local devenv matches.
- suites running in background: kwin/bridge, shell (logs scratch/menus/suite-*.log).
- Verified in integ: exported top-level menus (German) — KWrite, Kate (+Sitzungen), Konsole, Dolphin, Mousepad;
  System Settings exports an empty bar. ⌘N (physical Alt+N) reaches KWrite and Mousepad with hidden bars.
- Docs updated: bridge.md (menus topic + deviations), bridge README "Global menus", shell.md app-menus paragraph,
  theme.md "Menus to the menu bar". integration/tools/u.sh GTK env fix. Tools copy in menus/tools.
- SUITES (local, kristall-devenv + gtk3-devel layer, --network none): kwin/bridge 46/46 passed; shell exit 0
  (173 PASS, 0 FAIL); theme exit 0 (107 PASS, 7 SKIP) after gating its GTK 3 checks on adw-gtk3 (gtk3-devel brings
  gtk3-widget-factory/gtk3-demo into the plain devenv, where adw-gtk3 is absent → they used to be skipped).
- integ container removed (kristall-integ:latest kept). Next: publish, watch CI.
