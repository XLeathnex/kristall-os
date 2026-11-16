# shell/modules/switcher — app switcher and Overview wiring (shell-apps)

**Decision:** Command-Tab is KWin's own window switcher (TabBox) with our layout, not a shell
surface. Only the compositor sees a key being held and released without a round trip: a shell
popover would receive each Tab via kglobalaccel → `kristall-shellctl` → IPC (≈100 ms each) and
would miss quick taps. KWin switches on a quick tap without showing anything (`DelayTime=110`),
shows the layout while held, reverses with Shift, cancels with Escape.

* `kwin/tabbox/org.kristall.switcher/` → `/usr/share/kwin/tabbox/` — the layout: one icon per app
  (most recently used first), the chosen app's name under it, design tokens copied from
  design.md (KWin's QML cannot import the shell's). While held: ←/→ move, **Q** quits the
  highlighted app (closes its windows), **H** hides it (minimises, moves on).
* `kwin/kwinrc` → merged into `/etc/xdg/kwinrc`: `[TabBox] LayoutName=org.kristall.switcher`,
  `ApplicationsMode=1`, no window highlighting.
* `kwin/kglobalshortcutsrc` → merged into `/etc/xdg/kglobalshortcutsrc`: Meta+Tab / Meta+Shift+Tab
  (Alt+Tab kept), Meta+` and Meta+< (German keyboards) for the front app's windows, Overview on
  Meta+W and Ctrl+↑ (the Mac's Mission Control key); Plasma's Meta+Tab "walk through activities"
  is unbound.
* `Module.qml`: ShellBus target `switcher` for programs: `next` (= a quick Command-Tab), `previous`.

Overview is KWin's Overview effect; its touchpad gesture is KWin's built-in four-finger swipe up
(not changeable to three fingers in 6.8 as far as we know — unverified, no touchpad here).

Tests: `shell/modules/switcher/tests/run.sh` (real key sequences through fake input).
Limits: the switcher panel uses the design system's opaque fallback material, not Liquid Glass
(KWin-internal QML windows cannot declare glass shapes); icons are the apps' own, without the
Dock's plates; KWin activates the app's most recent window only (macOS raises all its windows).
Overview could not be run here: the dev container lacks `org.kde.milou`, which KWin's Overview
needs — so the Dock/bar during Overview is unverified.
