# shell/modules/search — Search or Ask (shell-apps)

Meta+Space (the Mac's Command-Space; `kglobalaccel/org.kristall.search.desktop`) or
`kristall-shellctl search toggle`. Full-output Overlay surface `kristall-search`, exclusive
keyboard while open; a glass capsule that grows into the results list.

Results: Ask (first when the text reads as a question/request) · Top Hit · Apps (German and
English names, keywords, typos, learned picks) · Calculator / unit conversion (`calc.js`, local) ·
System Settings pages by everyday words (`catalog.js`) · Actions (lock, sleep, restart, shut
down, log out, dark mode, Do Not Disturb, Overview, show desktop) · Files & Folders · Ask · Web.
Keys: ↑↓/Tab, ↩ open, Ctrl/Meta+↩ show a file in Files, ⎋ clears then closes.

* Apps, settings, actions and calculations are computed synchronously per keystroke; the list
  model is updated in place (delegates reused). Files arrive asynchronously and never take the
  selection away.
* **Files**: Baloo — the index Plasma already runs (`baloo_file`: inotify, idle IO priority, no
  polling). We configure it system-wide to index **file names only** (`/etc/xdg/baloofilerc`
  `only basic indexing=true`): content extraction is what costs CPU and battery after large
  changes; file-name indexing is a one-off low-priority pass, then inotify events only. Queried
  with `baloosearch6 -l 40 <text>` 120 ms after typing stops (override: `KRISTALL_SEARCH_FILES_CMD`).
  No indexer or watcher of our own. With Baloo switched off by the owner there are no file results.
* **Ask** sends `ShellBus.request("assistant", "ask", text, output)`; the row exists only while
  the `assistant` module has claimed its target.
* Dark mode writes `appearance.theme`, Do Not Disturb writes `panels.focus.until` (the panels
  module's key) — both are the owner's own choices, made from Search.
* Web: Firefox's own default engine (`firefox --search`), else DuckDuckGo via `xdg-open`.

Tests: `shell/modules/search/tests/run.sh [static behaviour looks]` (real Meta+Space through
KWin's kglobalaccel, real typing; a stand-in for `baloosearch6` over a 50 000-file list because the
dev container has Baloo's libraries but not `baloo_file`).

Limits: no menu-bar Search item (the bar belongs to shell-core); no currency conversion; no
Quick Look preview, no recent/suggested items when empty; a window that maps while Search is open
takes keyboard focus from it (KWin 6.8, observed in the tests).
