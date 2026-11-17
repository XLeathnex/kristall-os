# kwin/bridge — kristall-bridge

A KWin 6.8 plugin (runs inside the compositor) that serves `$XDG_RUNTIME_DIR/kristall/bridge.sock`:

* **windows** — the window list with deltas (coalesced to one batch per frame), the active window,
  stacking, outputs with their work area (what the menu bar and Dock leave free), desktops,
  application-menu service/path (global menu bar), minimise targets;
* **agent input** — pointer, keyboard and text for the assistant, delivered to applications
  without moving or disturbing the owner's pointer;
* **screenshots** — silent, fast, optionally without the assistant's own overlays.

The interface is [`docs/contracts/bridge.md`](../../docs/contracts/bridge.md). This file explains
how it works, how to build and test it, and its limits.

| Path | What |
| --- | --- |
| `src/` | the plugin (C++23, Qt 6.11, KWin 6.8 internal API) |
| `protocols/wlr-layer-shell-unstable-v1.xml` | protocol for the in-process helper client (MIT, wlr-protocols) |
| `python/kristall_bridge.py` | dependency-free client module (installed to `/usr/lib/kristall/bridge/python/`) |
| `tools/kristall-bridgectl` | CLI for tests and debugging (`/usr/bin/kristall-bridgectl`) |
| `image/install.sh` | image build: builds against the image's KWin, installs, enables in `/etc/xdg/kwinrc` |
| `tests/` | headless test suite (`run.sh`), test clients (`clients/`), harness (`support/`) |

## How agent pointer input works (and why)

Wayland gives a seat one pointer. Two ways to click "somewhere else" from inside the compositor:

1. *move-act-move back within one event-loop turn* through KWin's normal input pipeline;
2. *deliver enter/motion/button/axis/frame to the target surface through the seat* while the global
   cursor position is never touched, then hand the seat's pointer focus back.

The bridge uses **(2)**. Evidence from KWin 6.8.3's source and from the tests:

* (1) cannot express the contract's separate `down`/`move`/`up` calls: between calls the button is
  held, so moving the cursor back to the owner would drag whatever was pressed to the owner's spot.
  It also moves real state that has side effects: `updatePosition()` changes the active output,
  pointer constraints/locks and edge barriers can refuse the move (a game holding a pointer lock
  would make the agent click in the wrong place), screen edges, zoom, shake-to-find-cursor and
  effects see the motion, and the shell's own hover (Dock magnification) would flicker.
* (2) never calls `Cursor::setPos`: the cursor cannot be drawn elsewhere, on any frame, by
  construction. The tests verify this from inside KWin (a `framePresented` trace of the cursor and
  the rendered cursor item, plus a `Cursor::posChanged` counter: zero changes during agent input).

What (2) has to do itself, because it bypasses KWin's input filters — each with a test:

* **click to focus**: the same `Window::getMousePressCommand`/`performMousePressCommand` KWin runs
  on press (activate) and the release command (KWin 6.8 raises *on release* by default);
* **popup grabs**: a press outside an open grabbing popup closes the popups and is swallowed
  (`PopupInputFilter` semantics); inside, it is delivered. Menus open with one call and are used
  with the next;
* **server-side decorations**: hover/press/release go to the `KDecoration3::Decoration` object, as
  `DecorationEventFilter` does; title-bar press runs KWin's title-bar command, a double-click the
  title-bar double-click operation, a drag moves the window by the drag's delta;
* **client-side moves/resizes**: when a client answers the agent's press with `xdg_toplevel.move`
  (GTK, CSD), KWin would bind the move to the *owner's* pointer; the bridge cancels that interactive
  move and moves/resizes the window itself along the agent's drag;
* **implicit grab**: while the agent holds a button, motion goes to the pressed surface;
* **drag-and-drop** started by the agent is driven through the seat (best effort, see limits);
* **hover restoration**: after every call the seat's pointer focus is re-entered on the surface
  KWin's pointer redirection has under the owner's pointer, at the owner's position, in the same
  batch of events. The hovered client sees leave/enter/motion pairs but ends where it started;
* **modifiers** (ctrl-click …) are sent as `wl_keyboard.modifiers` to the target client only;
* **timestamps** strictly increase by ≥ 1 ms (Qt only recognises multi-clicks then);
* **owner priority**: owner button held/dragging/moving a window → wait ≤ 1 s, then `busy`; owner
  pointer activity during an agent-held gesture ends it (release where the agent is); owner Escape
  ends the session;
* **no pointer device** (touch-only machine): the seat advertises a pointer/keyboard for the
  duration of a session, otherwise clients would not create `wl_pointer`.

Windows are looked up per call by `QPointer`, so a window disappearing mid-call is harmless.

## Keyboard and text

Keyboard focus is singular. For the call, the target's surface gets the seat's keyboard focus:
native Wayland targets *only* get keyboard focus (not raised, not activated; the active window
stays active, verified); XWayland targets are activated (X11 input focus is set by the window
manager). Focus goes back afterwards (`restoreFocus`, default true). If the owner presses a key
meanwhile, the bridge's input filter (first in KWin's chain) hands focus back *before* KWin forwards
that key — with the key left out of `wl_keyboard.enter`, so the owner's keystroke is typed normally
— and the agent's call ends with `busy`.

`agent.text` picks a path per target and per character and reports it:

| path | when | how |
| --- | --- | --- |
| `textInput` | the focused client has text-input-v3/v2 enabled (Qt and GTK text fields on Wayland) | one `commit_string` |
| `keymap` | the character is on the active layout (German QWERTZ: ä ö ü ß @ € …) | its key + level modifiers; main-keyboard keys first |
| `temporaryKeymap` | native Wayland client, character not on the layout (emoji) | a one-key keymap sent **to that client only**, key typed, real keymap sent back |
| `clipboard` | XWayland client, character not on the layout | clipboard saved (all types), set, Ctrl+V / Ctrl+Shift+V (terminals), restored |

`\n`, `\t` are typed as Return/Tab. Typing is paced at ~4000 characters/s so a burst cannot overflow
a slow client's 1 MiB Wayland buffer (libwayland would disconnect that client).

**Order across paths.** The events always left the compositor in order, but Qt and GTK apply a
text-input `commit_string` while they read it from the socket and *queue* key events, processing
them afterwards. A commit and a Return that arrive in one read were therefore applied out of order:
`"Liebe Grüße,\nich …"` became `"Liebe Grüße,ich …\n"` in a QTextEdit (reproduced by
`test_multiline_text_in_order` before the fix). Where the text switches between `textInput` and a
key path, the bridge now pings the client (`xdg_wm_base.ping`; the pong means everything before it
has been dispatched), waits ~8 ms for the toolkit to drain its queue, and only then sends the next
segment (layer-shell surfaces, which have no ping: a 50 ms pause; no pong within 1 s: continue).
The test checks raw clients (wire order), Qt and GTK 3 on Wayland (text-input + keys) and Qt under
XWayland (keymap + clipboard) with a multi-line German letter. `hello` advertises `orderedText`.

**X11 targets: focus and keys in order.** KWin sets X input focus over its X11 connection; keys reach
Xwayland over its Wayland connection, and nothing orders the two. A key could therefore arrive before
the activation's `SetInputFocus` was applied, or after the hand-back to the previous window, and land
in another X window (seen as a lost Return right after a `clipboard` paste, and as lost first
characters). The bridge now uses an X round trip as a barrier: after flushing the Wayland events it
sends `GetInputFocus` on KWin's X11 connection and waits for the reply (non-blocking, a 1 ms timer
only while it waits). Xwayland reads every ready socket in one wait and converts input before it runs
requests, so the reply means every key sent before it has been routed; and its `focus` says whether
the target has X focus yet (asked again until it does, ≤ 500 ms). Test:
`test_x11_keys_after_clipboard_text` (six rounds of clipboard text + Return into a Qt/XCB window,
alternating with a native window; failed every time before the fix).

**Work area.** `outputs.changed` carries `workArea` per output: KWin's maximise area
(`Workspace::clientArea(MaximizeArea, output)`), i.e. the output minus layer-shell exclusive zones
and struts. KWin has no "client area changed" signal; the bridge marks the outputs dirty on
`Workspace::aboutToRearrange` (emitted before the recomputation; the coalesced flush runs in a later
event-loop turn) and on desktop switches, and sends `outputs.changed` only when the data differs.

## Screenshots

The scene is rendered into an offscreen texture inside KWin (same technique as KWin's screenshot
plugin; no portal, no flash, no sound) and PNG-encoded on a worker thread. `excludeShell` uses a
per-call scene window filter on `kristall-assistant*` layer namespaces rather than KWin's
per-window *exclude from capture* flag: that flag would also hide the assistant from the owner's own
screenshots and screen recordings. Windows the owner excluded from capture are never captured.
Renders are paced (one per 100 ms, at most 4 queued) because the GPU readback runs on the
compositor thread.

## Minimise targets

`Window::iconGeometry()` (what the minimise animations fly to) is computed only from
`org_kde_plasma_window.set_minimized_geometry` entries, relative to a "panel" surface; KWin has no
server-side setter. The bridge therefore runs an **in-process Wayland client** (socketpair +
`Display::createClient`, fully non-blocking) that maps a 1×1 transparent, input-less layer surface
per output (`kristall-bridge-anchor`, never reported) and sets the geometry relative to it. The same
client provides the clipboard (ext-data-control-v1) for the `clipboard` text path.

## Global menus

Apps export their menus only while a menu *view* owns the D-Bus name `org.kde.kappmenuview`
(kded's appmenu module then publishes `com.canonical.AppMenu.Registrar`). Plasma's panels are
removed in Kristall, so the bridge owns that name while a client subscribes to the `menus` topic,
and releases it when the shell goes away — apps then show their in-window menu bars again.
Verified: Qt/KDE apps (Wayland and XWayland, KDE platform theme), GTK 3 under XWayland
(`unity-gtk-module` + `gmenudbusmenuproxy`). Native-Wayland GTK and GTK 4/libadwaita apps
cannot export menus (no protocol); their `menu` is `null`.

## Safety

* Lines ≤ 1 MiB, ≤ 32 requests in flight per connection, ≤ 8 MiB unread output (then the client is
  dropped), ≤ 32 connections; work per event-loop turn is bounded (64 lines or 1 ms); no blocking
  I/O on the compositor thread (PNG writing on a worker; procfs reads at connect only).
* Access: SO_PEERCRED same uid; privileged = executable under `/usr/lib/kristall/` or
  `/usr/bin/kristall-*`, or a system Python whose script is one of those (`/proc/<pid>/cmdline`,
  pid re-validated through SO_PEERPIDFD), or KWin started with `KRISTALL_BRIDGE_DEV=1`. Locked
  screen: privileged calls denied, session ended, held buttons released.
* Fail soft: unusable socket path, a live bridge already on the path, or init failure → the plugin
  logs once (`journalctl --user -t kristall-bridge`) and KWin runs without it.
* Idle: no timers when nothing happens; deltas are only computed while someone is connected.

## Build and test

```sh
docker run --rm -v /home/user/kristall:/work kristall-devenv:latest /work/kwin/bridge/tests/run.sh
docker run --rm -v /home/user/kristall:/work kristall-devenv:latest /work/kwin/bridge/tests/run.sh popup   # filter
```

The tests start headless KWin instances (virtual backend, llvmpipe) and use purpose-made clients:
`wlprobe` (raw Wayland: logs every pointer/keyboard/text-input event with exact coordinates, popups
with grabs, CSD moves, animation), `qtprobe` (Qt Widgets, native and XWayland), `gtkprobe.py`
(GTK 3), a Quickshell layer-shell scene (Dock + assistant overlay). The *owner* is played through
`org_kde_kwin_fake_input` (`owner`): it drives KWin's real input pipeline, so the cursor really moves
and Escape really reaches KWin. Test-environment facts: `/usr/bin/kwin_wayland` carries file
capabilities a container refuses (a copy is used), llvmpipe needs a `/dev/udmabuf` shim (from
`kwin/glass`), and `--scale` is overridden by KWin's output configuration (scales are set with
`kscreen-doctor`).

## Known limits

* Compositor-internal windows (KWin's own window-operations menu, OSDs) do not receive agent input
  (`unsupported`); a right-click on a title bar opens that menu but the agent cannot use it.
* Drags on window borders (server-side resize) are not supported; use `window.setGeometry`. Taking
  over a client-side *resize* request is implemented like the (tested) client-side move, but no
  test client exercises it.
* Agent drag-and-drop between windows works through the seat but KWin draws the drag icon and drag
  cursor at the owner's pointer during the drag (best effort, not covered by a test).
* While an agent hover (`hoverMs`) or held gesture lasts, the client under the owner's pointer does
  not have pointer focus (the contract's guarantee holds at the end of every call).
* The temporary-keymap path does not work for XWayland clients (verified: nothing arrives), which
  is why they use the clipboard path; that path is seen by clipboard managers.
* Clients that do not enable text-input and whose toolkit ignores keymap changes cannot receive
  characters outside the layout (none found).
* A same-uid process can rewrite its own `cmdline`; the executable check is a speed bump, not a
  security boundary (KWin 6.8 also lets any unsandboxed client use `org_kde_kwin_fake_input`).
