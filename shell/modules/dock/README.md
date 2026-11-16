# shell/modules/dock — the Dock (shell-apps)

Floating glass capsule at the bottom of the main display (bridge primary output, else the first
screen). Layer-shell namespace `kristall-dock`, layer Top, reserves `capsule + 6 px` unless
`dock.autoHide`. Also hosts `common/`, the code all four shell-apps modules share.

```
Module.qml          screen choice, ShellBus target "dock" (show, hide, bounce <app id>), Empty Trash alert
Dock.qml            the window: one-pass layout (magnification, presence animations), input region,
                    hover label, drag to reorder / off to remove, menus, minimise targets
DockModel.qml       what is shown: kept apps, running apps, separator, minimised windows, Downloads, Trash
DockItem.qml        one tile (icon, badge, progress, bounce, minimised-window card, separator)
DockMenus.qml       context menus (apps, Apps tile, windows, Downloads, Trash, the Dock's own options)
Places.qml          Downloads (XDG user dir) and Trash state via FolderListModel (inotify)
LauncherEntries.qml + helper/kristall-dock-launcher-entries   badges/progress (Unity LauncherEntry, D-Bus)
ConfirmDialog.qml   "Empty Trash" alert (namespace kristall-dock-alert)
common/             AppCatalog (apps + manifest, window→app, Mac click semantics, hide/quit,
                    kept apps, learned ranking), fuzzy.js, AppIcon + IconShapes + IconProbe (icon
                    plates), AppsGlyph, SyncedGlassSurface
kwin/kwinrc         merged into /etc/xdg/kwinrc: Magic Lamp on, Squash off
image/              install.sh, settings.json (→ settings.d/50-dock.json), merge-ini
tests/              run.sh, test_dock.py, support/appsession.py (shared by all four), evidence/
```

## Behaviour decisions

* **Click** (Mac): not running → launch and bounce until its first window appears (15 s cap);
  running → all its windows come forward, top one active; hidden (Hide) → shown again; only
  minimised windows → the most recently minimised one is restored; front app → nothing new.
* **Magnification**: raised-cosine falloff over ±max(2.6·size, 1.5·magnified) around the pointer;
  every tile's width follows; the point under the pointer stays under it (the row grows away from
  the pointer side). Enter/leave ease over 150 ms; nothing runs while the pointer is still.
  Glass shapes go out with `sync:"commit"` (SyncedGlassSurface) so the capsule moves with the icons.
* **Icon plates**: each icon's alpha is measured once (48×48, cached in
  `~/.cache/kristall/shell-apps/icon-shapes.json`). Filled rounded squares are drawn as they are;
  everything else sits on a light/dark rounded plate (superellipse) like macOS 26 does. Both are
  normalised by their visible bounding box (82 % body), never stretched.
* **Minimise into the Dock**: every app window gets `window.setIconGeometry` = the slot its
  minimised tile will take (before Downloads), its own tile once minimised, or the app icon with
  `dock.minimizeToApp` and for Hide. KWin's Magic Lamp draws the flow.
* Drag a kept app (or the Apps tile) to reorder; drag it ≈ 0.8 tile above the Dock and release to
  remove it ("Entfernen" label). Dropping a running app among the kept ones keeps it.
* Settings (`dock`, live): `size` 48, `magnification` true, `magnifiedSize` 76, `autoHide` false,
  `minimizeToApp` false, `pinned` null (= manifest order). The Dock's background menu changes them.

## Tests

`docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest shell/modules/dock/tests/run.sh [static kwinconfig behaviour perf autohide looks]`

Numbers of the last run: `tests/evidence/results.json`.

## Known limits / differences from macOS 27

* No live thumbnails of minimised windows (KWin offers the shell no window capture): a window card
  with the app icon stands in. Downloads opens the folder; no fan/grid stack popover.
* Pressed icons dim by opacity (no tint without shaders in the software renderer); no "poof" when
  dragged off; Show All Windows opens KWin's window view for all apps, not just this one.
* The Dock stays on the Top layer: under a full-screen window it is covered (no edge reveal there).
* Not verified here: real touchpad/pointer feel, 120 Hz on Iris Xe, the owner's real app set.
