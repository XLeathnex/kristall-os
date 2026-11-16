# shell/modules/apps — Apps (shell-apps)

The grid of every installed app (macOS 26/27 "Apps"): opened by the Dock's Apps tile, Meta+A
(`kglobalaccel/org.kristall.apps.desktop`) or `kristall-shellctl apps toggle`. Full-output Overlay
surface `kristall-apps`, exclusive keyboard while open (released while its context menu is open).

* Content: `AppCatalog` (shell-core) — desktop entries joined with the app manifest (our German
  and English names, categories, `show_in_apps: false` hidden). `DesktopEntries.applicationsChanged`
  rebuilds it, so installs and removals show up live.
* Search field (typing filters with the same matching as Search), category buttons, the grid;
  ←→↑↓ move, ↩ opens, ⎋ clears then closes.
* Right click: Open · Keep in Dock / Remove from Dock · Uninstall … for Flatpak apps, which hands
  off to the app store (`xdg-open appstream://<flatpak id>`); no package work here.

Tests: `shell/modules/apps/tests/run.sh [behaviour looks]`.
Limits: no paging/folders (macOS 27 Apps scrolls too, but groups differently), categories come
from desktop-file categories when the manifest has none; which store opens `appstream://` depends
on the image's handler (Bazaar or Discover) — not verified here (neither is in the dev container).
