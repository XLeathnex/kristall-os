# Contract: kristall-bridge (compositor bridge)

Owner: `kwin/bridge/`. Consumers: the shell (window list, active app, app menus, minimise targets),
`assistant/hands` (agent input, screenshots, window control).

This file was written by the planner before either side existed so that both can be built in
parallel. The bridge implements it; consumers code against it. If the KWin API makes something here
impossible, the bridge owner keeps the message shape, returns `unsupported`, omits the capability
from `hello`, and records the reason at the bottom of this file.

Items marked *(addition)* were added by the bridge owner; everything else is unchanged in shape.
Clients must ignore fields and events they do not know.

## Transport

- Unix stream socket `$XDG_RUNTIME_DIR/kristall/bridge.sock`, mode 0600, created by a KWin plugin
  running inside the compositor process.
- Newline-delimited JSON, UTF-8, one object per line, no line longer than 1 MiB.
- Request: `{"id": <number|string>, "method": "<name>", "params": {…}}`
- Reply: `{"id": <same>, "result": {…}}` or `{"id": <same>, "error": {"code": "<code>", "message": "<text>"}}`
- Event (unsolicited, only after `subscribe`): `{"event": "<name>", "data": {…}}`
- Error codes: `invalid` (bad request), `not_found`, `busy`, `unsupported`, `denied`, `internal`.
- Replies to one connection are sent in request order. The plugin never blocks the compositor on a
  client: slow or dead clients are dropped; a client's unread backlog is capped.
- All coordinates are **logical pixels in the global compositor space** (the space in which
  outputs are laid out), floats allowed. Sizes likewise.
- Limits and malformed input *(addition, precise)*: `id` must be a finite number or a string of at
  most 256 characters, `params` an object or absent. A line that is not such a request gets an
  `invalid` reply with `"id": null` (or the request's id if it was readable); the connection stays
  open. Blank lines are ignored. A line longer than 1 MiB gets an `invalid` reply and the connection
  is closed. Unknown methods → `invalid`. At most 32 requests per connection are in flight; further
  lines wait in the socket. A client with more than 8 MiB of unread output is disconnected. At most
  32 connections. Parameters are type- and range-checked; extra parameters are ignored.

## Access control

- Peer must be the same uid (SO_PEERCRED), otherwise the connection is closed.
- Methods under `agent.*` and `screenshot` are **privileged**: allowed only if the peer's
  executable (`/proc/<pid>/exe`) is under `/usr/lib/kristall/` or matches `/usr/bin/kristall-*`,
  or KWin was started with `KRISTALL_BRIDGE_DEV=1` (development and tests only). Otherwise `denied`.
  - *(addition)* Python programs: when the executable is a system interpreter
    (`/usr/bin/python3`, `/usr/bin/python3.N`), the first non-option argument (the script) must be
    an absolute path under `/usr/lib/kristall/` or match `/usr/bin/kristall-*`. Interpreter options
    without argument (`-I -s -S -E -B -P -O -OO -u -b -bb -q -R`) and `-W x`/`-X x` are skipped;
    `-c`, `-m` and `-` are never privileged. So `/usr/bin/kristall-hands` with a
    `#!/usr/bin/python3 -I` shebang, or `python3 /usr/lib/kristall/hands/main.py`, are privileged.
  - *(addition, 2026-11-16)* A Python interpreter *under* the trusted prefix (a virtual
    environment's `bin/python`, `python3`, `python3.N` copied to `/usr/lib/kristall/…`) gets the
    same script rule — `-c`/`-m` are not trusted there either; other general interpreters there
    (shells, perl, node, ruby, lua, …) are never trusted. (A venv's usual symlinked interpreter
    resolves to `/usr/bin/python3.N` anyway; the assistant daemon runs `-m` and is unprivileged.)
  - The decision is made once, at connect; `hello` reports it (`privileged`).
- Everything else is available to any same-user peer.
- While the screen is locked, every privileged method returns `denied` and an active agent session
  is ended: the assistant can never operate or see the lock screen.
- Our own shell surfaces use layer-shell namespaces starting with `kristall-` (`kristall-bar`,
  `kristall-dock`, `kristall-assistant-…`). They are reported with `"normal": false`, and surfaces
  whose namespace starts with `kristall-assistant` are the ones `excludeShell` removes.
  *(addition)* `kristall-assistant*` surfaces are also transparent to agent pointer input (the
  agent never clicks its own cursor, glow or panel); other `kristall-*` surfaces (bar, Dock) receive
  agent clicks like any window. Namespaces starting with `kristall-bridge-` are the bridge's own
  helper surfaces and are never reported.

## Session

### `hello`
params `{"client": "<name>", "version": 1}` → result
`{"version": 1, "kwin": "6.8.2", "capabilities": ["windows","menus","iconGeometry","agentInput","agentText","screenshot", …]}`.
A capability missing from the list means the corresponding methods return `unsupported`.
*(addition)* Two capabilities are informational (they name a guarantee, not methods):
`orderedText` — `agent.text` keeps the text's order across every mix of paths (see `agent.text`);
`workArea` — output objects carry `workArea`. A client that meets a bridge without them falls back
(for example restricts multi-line `agent.text` to the key paths, or uses the output geometry).
*(addition)* The result also has `"privileged": bool` (may this connection use privileged methods)
and `"locked": bool` (screen locked now).

### `subscribe`
params `{"events": ["windows","active","stacking","outputs","desktops","agent"]}` → result `{}`.
Immediately followed by a snapshot event for each subscribed topic, then deltas.
The snapshot is taken when the reply is written, so no delta precedes its snapshot.
Unknown topic → `invalid`. *(addition)* Topic `"menus"`: has no events; it declares "this client
displays application menus". While at least one connection is subscribed to `menus`, the bridge
owns the D-Bus name `org.kde.kappmenuview`, which makes kded's appmenu module publish
`com.canonical.AppMenu.Registrar`; only then do applications export their menus (and hide their
in-window menu bars). When the last such client disconnects, apps show their own menu bars again.
The shell's menu bar must subscribe to `menus`.

## Windows

Window object:

```
{ "id": "<stable string for the window's lifetime>",
  "appId": "<desktop file id without .desktop, or resource class>",
  "title": "…", "pid": 1234,
  "x": 0, "y": 0, "w": 0, "h": 0,            // frame geometry
  "output": "<output name>", "desktops": [1], "allDesktops": false,
  "active": false, "minimized": false, "maximized": false, "fullscreen": false,
  "keepAbove": false, "demandsAttention": false,
  "normal": true,            // a regular app window (not dock/panel/popup/OSD/our shell)
  "skipTaskbar": false, "skipSwitcher": false,
  "closeable": true, "minimizable": true, "maximizable": true,
  "icon": "<themed icon name or empty>",
  "menu": {"service": "<dbus name>", "path": "<object path>"} | null,  // DBusMenu app menu
  // additions:
  "type": "normal"|"dialog"|"utility"|"popup"|"menu"|"tooltip"|"notification"|"osd"|"dock"|"desktop"|"splash"|"layer"|"other",
  "parentId": "<id>"|null,   // transient parent (dialogs)
  "xwayland": false,         // an X11 client
  "pointerLocked": false,    // the client holds a pointer lock (zwp_locked_pointer_v1) on the window, active or not
  "pointerConstrained": false, // the client holds a pointer confinement (zwp_confined_pointer_v1), active or not
  "content": {"x","y","w","h"},  // client area inside the frame (frame minus server-side decoration)
  "namespace": "kristall-dock"   // only for layer-shell surfaces
}
```

Notes: `id` is KWin's window UUID without braces. Geometry is rounded to 1/100 px. Popups (open
menus) are listed with `"type": "popup"` (or `"menu"`) and `"normal": false`; the window list is in
stacking order, bottom to top. `menu` is the window's DBusMenu (`com.canonical.dbusmenu` at
`service`/`path`) — see `menus` above for when apps export one, and the notes below for which apps
can. `icon` is often a generic name (`wayland`) for apps without a themed icon; use `appId` to find
the desktop file. `pointerLocked`/`pointerConstrained` are what games and 3D tools request while they
run (relative mouse look, a pointer kept inside the window); they change live (`window.changed`) when
the client creates or destroys the constraint. They report the *request*: KWin activates a lock only
while the window has pointer focus. XWayland games that grab the pointer through X11 instead are
not covered (the shell treats every full-screen XWayland window as a game anyway).

Events (topic `windows`): `windows.snapshot {"windows":[…]}`, `window.added {"window":{…}}`,
`window.changed {"id":"…","changes":{<changed fields only>}}`, `window.removed {"id":"…"}`.
Geometry changes during interactive move/resize are coalesced to at most one event per frame.
(All `window.changed` deltas are coalesced per frame of the fastest output; a burst of 300 moves
produced one event in the tests.) A new window's `window.added` always precedes the
`active.changed` that names it.
Topic `active`: `active.changed {"id": "<id>"|null}`. Topic `stacking`:
`stacking.changed {"order": ["<bottom id>", …, "<top id>"]}`.

Methods (all return `{}` on success): `window.activate {id}`, `window.close {id}`,
`window.setMinimized {id, value}`, `window.setMaximized {id, value}`, `window.setFullscreen {id, value}`,
`window.setGeometry {id, x, y, w, h}`, `window.toDesktop {id, desktop}`, `window.toOutput {id, output}`,
`window.setIconGeometry {id, x, y, w, h}` (where the minimise animation should flow to; pass the
Dock icon's rectangle), `window.list {}` → `{"windows":[…]}`.
Details: unknown `id` → `not_found`; an operation the window does not allow (close a non-closeable
window, maximise a non-maximisable one, move a fullscreen one) → `invalid`. `window.activate`
also un-minimises and switches to the window's desktop. `window.setGeometry` restores a maximised
window first; non-resizable windows are only moved. `window.setIconGeometry` with `w` or `h` 0
clears the rectangle; the rectangle is kept for the window's lifetime and survives output changes;
it becomes KWin's `Window::iconGeometry()` (used by the minimise animations).

## Outputs, desktops, effects, cursor

- Topic `outputs`: `outputs.changed {"outputs":[{"name","x","y","w","h","scale","refresh","internal":bool,"primary":bool,"workArea":{"x","y","w","h"}}]}`.
  (`refresh` in Hz; `primary` = first in KWin's output order.)
  *(addition, capability `workArea`)* `workArea` is the part of the output left after the space
  reserved by layer-shell exclusive zones (our menu bar and Dock) and other struts: KWin's maximise
  area, i.e. exactly where a maximised window goes, in global logical pixels like `x`/`y`/`w`/`h`.
  Window arrangements ("left half", "right half", centre) are computed inside it. It is kept
  current: an `outputs.changed` follows whenever a reservation changes (the Dock appears, hides
  automatically or changes size; the bar goes away). `outputs.changed` is only sent when some field
  of some output actually changed.
- Topic `desktops`: `desktops.changed {"current":1,"count":1,"names":["…"]}`; method `desktop.set {index}`.
- `workspace.showDesktop {value}`; `effect.toggle {"name": "overview"|"windowview"|"desktopgrid"}`.
  (`desktopgrid` is the overview effect's grid mode in KWin 6; an effect that is not loaded →
  `unsupported`.)
- `cursor.get {}` → `{"x","y"}` — the owner's pointer position.

## Agent input (privileged, capability `agentInput` / `agentText`)

Purpose: let the assistant operate applications **without taking the owner's pointer**. The
assistant's visible cursor is drawn by the shell; the bridge only delivers input.

Guarantee the bridge must provide: after any `agent.*` call returns, the owner's pointer is where
the owner left it; no presented frame shows the owner's pointer anywhere else; hover state under the
owner's pointer is restored. Keyboard input necessarily goes to one window at a time: the bridge
may move keyboard focus to the target for the duration of the call and restores the previously
active window afterwards when `restoreFocus` is true (default true).

How the bridge provides it: the global cursor position is never changed; events go to the target
surface through the Wayland seat and the seat's pointer focus is handed back to the surface under
the owner's pointer before control returns to the event loop. Consequence for clients under the
owner's pointer: they may see a `leave`/`enter` pair around agent input, and while an agent
gesture is held across calls (`down` … `up`, a running `agent.drag`, a `move` with `hoverMs`) they
do not have pointer focus.

- `agent.begin {"label": "<what it is doing>"}` → `{"session": "<token>"}`; `agent.end {"session"}`.
  One session at a time (`busy` otherwise). A session ends automatically if its connection closes
  or after 120 s without calls. Topic `agent`: `agent.state {"active": bool, "label": "…"}`.
  When a session ends, `label` says why: `"ended"` (agent.end), `"cancelled"` (owner pressed
  Escape), `"timeout"`, `"disconnected"`, `"locked"`. A wrong or expired token → `denied`.
  *(addition)* Topic `agent` also carries `agent.pointer {"x","y","type","button"}` for every agent
  pointer action, emitted just before it is delivered (`type`: move/click/down/up/scroll), so the
  shell can draw the agent cursor and click feedback where the agent acts.
- `agent.pointer {"session", "x", "y", "type": "move"|"click"|"down"|"up"|"scroll",
   "button": "left"|"right"|"middle", "count": 1, "dx": 0, "dy": 0, "modifiers": ["ctrl","shift","alt","meta"]}`
  → `{"target": {"windowId": "<id>"|null, "appId": "…"}}`. `scroll` uses `dx`/`dy` in notches.
  Semantics in detail:
  - The target is the topmost window that accepts input at (x, y) — what a screenshot shows there
    (`kristall-assistant*` overlays excluded). A click on an inactive or partly covered window
    behaves like a real click: it activates it (on press) and raises it (on release, KWin's
    default). A press outside an open menu/popup closes the popup and is **not** delivered
    (`"dismissedPopups": true` in the result); a press inside it is delivered, so "open menu" and
    "choose item" are two separate calls. A click on a server-side title bar runs KWin's title-bar
    action; `count: 2` there runs the double-click action (maximise by default).
  - `count` 1–3: multi-clicks with strictly increasing event times (toolkits see a double-click).
  - `down` presses and keeps the button held; `move` while held moves within that gesture (the
    pressed surface keeps receiving motion even outside itself); `up` releases (x/y optional,
    default: the last position). Only one button can be held; other calls → `busy`.
  - `scroll`: one notch = 15 in `wl_pointer.axis` units and 120 in `axis_value120`; `dy > 0`
    scrolls down, `dx > 0` right. Range ±100.
  - `modifiers` are delivered to the target client only, for the duration of the action.
  - *(addition)* `"windowId": "<id>"`: the window the action is meant for. If the point is covered
    by another window, the target is activated and raised first; if the point is not inside it
    (or its popups/dialogs) → `not_found` and nothing is delivered.
  - *(addition)* `"hoverMs": 0–5000` with `type: "move"`: keep hovering there that long (tooltips,
    hover menus); the call returns when the hover ends (or early if the owner moves the pointer).
  - *(addition)* `"button"` also accepts `"back"` and `"forward"`.
  - Result additions: `target.namespace` (layer surfaces), `target.decoration: true` (server-side
    decoration hit), `dismissedPopups`.
  - Compositor-internal windows (KWin's own menus/OSDs) → `unsupported`. While a full-screen effect
    such as the overview has the pointer → `busy`.
- `agent.drag {"session", "from": {"x","y"}, "to": {"x","y"}, "button": "left", "durationMs": 300}`.
  → `{"target": {…}}` when released. Motion is interpolated at ~60 Hz over `durationMs` (0–10000;
  0 = in one step). A drag starting on a title bar (server-side, or a client-side one that asks for
  an interactive move) moves the window by `to - from` (a client-side resize request is taken over
  the same way; not covered by a test yet); the owner's pointer is never involved. *(addition)* `"modifiers"` as above.
- `agent.key {"session", "keys": "ctrl+shift+t", "windowId": "<id>"?, "restoreFocus": true}` — a chord;
  key names follow XKB keysym names in lower case (`return`, `escape`, `tab`, `backspace`, `delete`,
  `left`, `f5`, `a` …) with modifiers `ctrl`, `shift`, `alt`, `meta`.
  Any single character is accepted as a key (`"ctrl+ü"`, `"ctrl+plus"` or `"ctrl++"`); aliases
  `enter`, `esc`, `del`, `pageup`/`pgup`, `pagedown`/`pgdn`, `ins`, `space`, modifier aliases
  `control`, `super`/`cmd`/`win` (= meta), `option` (= alt); a lone modifier (`"meta"`) presses
  that key. Keys are looked up on the active layout (on German QWERTZ `ctrl+z` presses the key
  labelled Z). Without `windowId` the active window is the target. → `{"target": {…}}`. Unknown key
  or modifier → `invalid`; a key that is not on the layout → `unsupported`.
  Agent key events bypass KWin's global shortcuts (they go straight to the target application).
- `agent.text {"session", "text": "…", "windowId": "<id>"?, "restoreFocus": true}` — types arbitrary
  Unicode correctly regardless of the active keyboard layout (German QWERTZ is the owner's layout:
  ä ö ü ß @ € and emoji must arrive intact).
  → *(addition)* `{"target": {…}, "paths": ["keymap", …], "path": "<the only path, if one>",
  "segments": [{"path": "…", "length": <characters>}, …]}`. Paths, chosen per target and per
  character: `textInput` (the focused client has text-input-v3/v2 enabled: one `commit_string`),
  `keymap` (character on the active layout: its key with that level's modifiers), `temporaryKeymap`
  (native Wayland client, character not on the layout, e.g. emoji: a one-key keymap is sent to that
  client only, the key typed, the real keymap sent back), `clipboard` (XWayland client, character
  not on the layout: the clipboard is saved, set to the text, Ctrl+V — Ctrl+Shift+V in terminals —
  sent, and the saved clipboard restored). `\n` and `\t` are typed as Return and Tab; `\r` is
  dropped. At most 20 000 characters; typing is paced (~4000 characters/s).
  *(addition)* `"paths": [...]` restricts the paths that may be used (diagnostics, tests); a
  character no allowed path can produce → `unsupported`.
  *(addition, capability `orderedText`)* **Order.** Characters arrive in the order of `text` on
  every path and every mix of paths. Toolkits (Qt, GTK) apply a text-input commit while reading it
  but queue key events, so where the text switches between `textInput` and a key path (`keymap`,
  `temporaryKeymap`, `clipboard`) the bridge first waits until the client has dispatched what it
  was sent (an `xdg_wm_base` ping answered; a 50 ms pause for surfaces without one), then a short
  settle time. Each such switch costs a client round trip plus ~10 ms. Bridges without the
  `orderedText` capability (before 2026-11-16) could deliver Return/Tab after the text-input text in
  Qt and GTK apps; clients of those restrict multi-line text to `["keymap", "temporaryKeymap",
  "clipboard"]`.
  Keyboard focus: native Wayland targets get the seat's keyboard focus for the call without being
  activated or raised (the active window stays active); XWayland targets are activated (X11 input
  focus follows activation) and the previous window is re-activated afterwards. For XWayland
  targets `agent.key` and `agent.text` send no key before an X round trip (`GetInputFocus` on
  KWin's X11 connection) confirms that the window has X input focus (≤ 500 ms), and hand focus back
  only after a second round trip has shown that Xwayland routed every key sent: X focus and keys
  travel on different connections, and without this a key right after a previous call (e.g. Return
  after a `clipboard` paste) could reach whichever X window had focus by then (fixed 2026-11-17,
  `test_x11_keys_after_clipboard_text`). Cost: one or two X round trips (< 1 ms) per call. With
  `restoreFocus: false` the target ends up active. If the owner presses a key during `agent.key` or
  `agent.text`, focus returns to the owner's window before that key is delivered (it is typed
  normally) and the call returns `busy`.
- Owner priority: if the owner is holding a pointer button or dragging, pointer injection waits up
  to 1 s and then returns `busy`. Any owner key press of Escape while a session is active ends the
  session and emits `agent.state {"active": false, "label": "cancelled"}`.
  Also: owner dragging/resizing a window counts as busy; keyboard calls wait (≤ 1 s, then `busy`)
  while the owner holds a key. Owner pointer activity during an agent-held gesture ends that
  gesture at the agent's position (the pending `agent.drag` returns `busy`; a later `up` →
  `invalid`). The owner's Escape also reaches the focused application.

## Screenshots (privileged, capability `screenshot`)

`screenshot {"target": "desktop" | {"output": "<name>"} | {"window": "<id>"} | {"region": {"x","y","w","h"}},
 "maxWidth": 0, "maxHeight": 0, "includeCursor": false, "excludeShell": false}`
→ `{"path": "<file>", "width": <px>, "height": <px>, "originX": <logical>, "originY": <logical>,
    "scaleX": <image px per logical px>, "scaleY": <…>}`.

PNG written with mode 0600 under `$XDG_RUNTIME_DIR/kristall/shots/`; the caller deletes it. With
`maxWidth`/`maxHeight` > 0 the image is scaled down to fit (aspect preserved) — callers map image
coordinates back with `originX + px / scaleX`. `excludeShell: true` omits the assistant's own overlay
surfaces (agent cursor, edge glow, assistant panel) so the model does not see itself.
Details: `target` defaults to `"desktop"` (all outputs; native resolution of the highest output
scale). `scaleX` is exactly `width / logicalWidth`. A `window` shot is the frame including a
server-side decoration, without the shadow; its origin is the frame's position. Windows the owner
excluded from screenshots (KWin's per-window setting) are never captured; a `window` shot of one →
`denied`. Maximum 16384 px per side at native scale → `invalid` beyond. At most 4 requests are
queued (`busy` beyond) and renders are paced to one per 100 ms. Files left for more than 30 minutes
are deleted. *(addition)* Result also has `"logicalWidth"`, `"logicalHeight"` and `"renderMs"`.

## Development mode only

With `KRISTALL_BRIDGE_DEV=1`: `debug.trace {"enable": bool}` → counters (cursor moves during agent
input, presented frames with the cursor and cursor-item positions, event-loop lateness). Tests only;
not available otherwise.

## Deviations and notes from the implementation

(the bridge owner fills this in)

- **No capability had to be dropped.** Built and tested against KWin 6.8.3 / Qt 6.11.2 in
  `kristall-devenv`; the image builds it against its own KWin (KWin refuses a plugin built for a
  different version, so `kwin` in `hello` is also the running version).
- **Agent pointer input** is delivered through the seat, never by moving the cursor (rationale and
  evidence in `kwin/bridge/README.md`). What KWin does for real clicks (click-to-focus, popup
  dismissal, decoration handling, client move requests) is replicated by the bridge.
- **`window.setIconGeometry`**: KWin 6.8 computes `Window::iconGeometry()` only from
  `org_kde_plasma_window.set_minimized_geometry` requests relative to a panel surface and has no
  server-side setter. The bridge runs an in-process Wayland client that maps an invisible 1×1
  layer surface per output (namespace `kristall-bridge-anchor`) and uses plasma-window-management.
  Minimise animations (squash, magic lamp) read that geometry.
- **Global menus**: with Plasma's panels removed nobody owns `org.kde.kappmenuview`, so apps would
  not export menus; hence the `menus` topic. Requirements on the system: kded6 with its `appmenu`
  module (Plasma's `plasma-kded6.service`), Qt apps using the KDE platform theme. GTK 3 apps export
  only when running under XWayland with `GTK_MODULES=unity-gtk-module` and `gmenudbusmenuproxy`
  running on the xcb platform; GTK on native Wayland, GTK 4/libadwaita and Flatpak GTK apps cannot
  export menus (their `menu` is `null`). Apps started while no `menus` subscriber existed may keep
  their in-window menu bars until restarted.
- **`effect.toggle`** triggers the effect's own toggle action; if the effect is not loaded (the
  overview needs `org.kde.milou`) → `unsupported`.
- **Not supported** (`unsupported` / documented): agent input to compositor-internal windows;
  agent drags on server-side resize borders (use `window.setGeometry`). Agent drag-and-drop between
  windows is best effort (KWin draws the drag icon at the owner's pointer while it lasts).
