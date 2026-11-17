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
  Meta+W; Plasma's Meta+Tab "walk through activities" is unbound.
* `kglobalaccel/org.kristall.switcher.desktop` → `/usr/share/kglobalaccel/`: Ctrl+↑ (the Mac's
  Mission Control key) → the Overview action "Kristall Overview" (KWin ignores extra keys for its
  own actions from `/etc/xdg/kglobalshortcutsrc`; found in the integrated session).
* `kwin/effects/kristall_overview/` → `/usr/share/kwin/effects/`: **Overview** — *2026-11-17*:
  Kristall's own declarative KWin effect replaces KWin's Overview (`kwinrc`: `overviewEnabled=false`,
  `kristall_overviewEnabled=true`; KWin's "Overview" action unbound, "Kristall Overview" on Meta+W).
  It uses KWin's window layout (`org.kde.kwin.private.effects` WindowHeap, as KWin's Overview and
  Window View do): the current desktop's windows side by side over the wallpaper dimmed 28 %, no
  desktop bar, no search field (Search is ⌘Space), no captions (KWin's read "Home — Dolphin"), the
  Dock left in place (a live thumbnail of the shell's bottom surface), the menu bar hidden. Escape, a click
  on the wallpaper or Ctrl+↑ again close it (checked in the integrated session); a click on a window
  brings it forward (KWin's WindowHeap behaviour, not checked separately); four fingers up/down on the
  touchpad open/close it (not tested: no touchpad here). Different from Mission Control:
  no Spaces bar (one desktop; with several desktops there is no way to switch here), windows are not
  grouped by app, no title on hover, the layout is KWin's (top-aligned rows), and the Dock thumbnail
  shows the Dock without its glass material (thumbnails do not run the glass effect).
* `tools/gen-names.py` → `kwin/tabbox/…/names.js` (committed; the test checks it is current): our
  app names for the switcher's label ("Dateien", not "Dolphin" from the window title).
* `Module.qml`: ShellBus target `switcher` for programs: `next` (= a quick Command-Tab), `previous`.


Tests: `shell/modules/switcher/tests/run.sh` (real key sequences through fake input).
Material: real Liquid Glass. The TabBox `Window` declares `kristallGlass` (its panel: x/y/w/h,
radius 22), which the glass effect reads from KWin-internal windows (`docs/contracts/glass.md`
§1.1); while the effect draws it, it sets `kristallGlassActive` and the panel keeps only a light
veil; without the effect (or after its crash guard) the panel falls back to the opaque material.
(Earlier blocker: a plain QML `Window` cannot set `kwin_blur`, a KWin `RegionF`, and
`PlasmaCore.Dialog` brings Plasma's opaque frame.) Limits: icons are the apps' own, without the
Dock's plates; KWin activates the app's most recent window only (macOS raises all its windows).
Overview (ours) runs in the dev container (`tests/run.sh` section `overview`) and was checked in
the integrated session (`docs/evidence/polish/`).
