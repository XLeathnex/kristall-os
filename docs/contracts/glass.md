# Contract: `glass` — Liquid Glass compositor effect

Owner: `kwin/glass/`. Consumers: shell-core, shell-apps, assistant-ui, setup, power.
Status: protocol version **1**. This document is normative; the implementation follows it.

## 1. What it is

`kristall_glass` is a KWin 6.8 effect (Wayland only). It draws the Liquid Glass material
*behind* client surfaces, inside the compositor, from the live screen content:

* for **explicit shapes** that a client declares over `glass.sock` for one of its own surfaces
  (the shell uses this for every glass element), and
* for **every surface that requests background blur** through `ext-background-effect-v1`
  (the only blur protocol KWin 6.8 implements; the old `org_kde_kwin_blur` is gone from KWin),
  KWin internal windows (`kwin_blur` property) and translucent window decorations. These get one
  rounded-rect shape over the requested region with default parameters (§5.4). KWin's stock
  `blur` effect is disabled system-wide; the glass effect advertises the blur capability instead.

The client draws its own content and shadows; the effect draws only the glass, underneath the
client's pixels. Where a glass shape is, the client surface must be transparent (or carry only
the content that sits on the glass).

## 2. Files, programs, settings

| What | Where |
|---|---|
| Plugin | `/usr/lib64/qt6/plugins/kwin/effects/plugins/kristall_glass.so` (plugin id `kristall_glass`) |
| Enabled for all users | `/etc/xdg/kwinrc`: `[Plugins] kristall_glassEnabled=true`, `blurEnabled=false` (other keys in that file are preserved; other components must also merge, never overwrite) |
| Socket | `$XDG_RUNTIME_DIR/kristall/glass.sock`, mode 0600, directory 0700. Override for tests: env `KRISTALL_GLASS_SOCKET` (read by server and the reference clients) |
| Crash guard | `$XDG_RUNTIME_DIR/kristall/glass.guard` (§7: whole-session record, 2 crashes in 10 min) |
| CLI | `/usr/bin/kristall-glass-ctl` (`check`, `status`, `watch`, `apply`, `pipe`, `quality`, `debug`) |
| Reference QML client | `/usr/share/kristall/glass/demo/{GlassClient,GlassSurface,GlassShape}.qml` (+ demo `shell.qml`) |
| Logs | KWin's journal stream, category `kristall.glass` (`journalctl --user -b | grep kristall.glass`) |

Settings read from the shared settings file (ARCHITECTURE.md §3), key `appearance`; changes apply
live (file watch on the atomic rename):

| Key | Type / values | Default | Meaning |
|---|---|---|---|
| `appearance.glass` | number 0.0 … 1.0 | `0.3` | 0 ultra-clear … 1 fully tinted (tint strength and blur radius) |
| `appearance.theme` | `"light"` \| `"dark"` \| `"auto"` | `"auto"` | `auto` follows the Plasma colour scheme (`kdeglobals` `[Colors:Window] BackgroundNormal` lightness < 0.5 ⇒ dark) |
| `appearance.glassQuality` | `"auto"` \| `"high"` \| `"efficient"` | `"auto"` | §6. `auto` = the latest `qualityHint` from a client (power component), else `efficient` on battery (UPower `OnBattery`), else `high` |
| `appearance.reduceTransparency` | boolean | `false` | Accessibility: shapes are drawn opaque-tinted, no background sampling at all |

Out-of-range numbers are clamped; unknown values fall back to the default.

## 3. Transport

* Unix stream socket; **UTF-8, newline-delimited JSON, one object per line**, both directions.
* Only peers with the session user's uid are accepted (`SO_PEERCRED`); others are closed.
* The server sends `hello` immediately after accepting a connection.
* Messages from one connection are processed strictly in order. Everything a connection sends
  before the compositor paints again is applied before that paint (bursts coalesce: only the last
  state of a surface is drawn).
* Every state a connection created (bindings, shapes, quality hint, timing subscription) is
  removed when the connection closes, for any reason (exit, crash, kill).
* Limits: 32 connections (the 33rd gets `error`/`limit` and is closed); 64 bound surfaces per
  connection; 64 shapes per surface; a line may be at most 1 MiB (longer lines are rejected with
  `too-long`; > 1 MiB without any newline closes the connection); a client that leaves more than
  4 MiB of replies unread is disconnected.
* Unknown fields are ignored (forward compatibility). Unknown `op` → `error`/`unknown-op`.

## 4. Client → server messages

All coordinates and lengths are **logical pixels** (Wayland surface coordinates = QML window
coordinates; the effect multiplies by the output scale). Colours are `"#RRGGBB"`,
`"#RRGGBBAA"` or `[r, g, b]` / `[r, g, b, a]` with components 0…1.

### `hello` (optional)
`{"op":"hello","client":"kristall-shell"}` — names the client in logs (≤ 64 chars). Reply: `hello`.

### `bind` — declare one of your surfaces
```json
{"op":"bind","surface":"dock-eDP-1","match":{"namespace":"kristall-dock","output":"eDP-1"}}
```
* `surface` (string, 1–128 chars): the client's own key for this surface, unique per connection.
* `match` (object) selects windows; **all given fields must match**:
  * `namespace` — wlr-layer-shell namespace (Quickshell `WlrLayershell.namespace`), exact, case-sensitive.
  * `appId` — xdg-toplevel app id (case-insensitive); for normal windows instead of `namespace`.
  * `title` — exact window title (toplevels; evaluated when the window appears and on `bind`).
  * `output` — output connector name (`QScreen.name`, e.g. `eDP-1`, `DP-2`).
  * `pid` — owner process: absent ⇒ the connecting process's pid (normal case: the shell process
    owns both the socket and the surfaces); `0` ⇒ any process (tools/tests); n ⇒ that pid.
  * At least one of `namespace` or `appId` is required.
* Re-sending `bind` with an existing key replaces its `match`; shapes are kept.
* A binding matches every current **and future** window satisfying `match`: if the shell
  re-creates the surface (screen change, reload), the last shapes apply to the new window
  automatically. Reply: `bound` (now and whenever the count changes).

**Why namespace + pid (+ output):** an effect cannot observe client-side object ids, QML objects
or wl_surface ids; what KWin exposes about a layer surface is its owning client (pid via the
Wayland credentials), its output and — through the layer-shell interface — its namespace.
Namespace + pid is stable across surface re-creation and needs no handshake on the Wayland
connection. **Rule for the shell: every glass-carrying layer surface gets a namespace that is
unique within the shell process per output** (e.g. `kristall-bar`, `kristall-dock`,
`kristall-cc`, `kristall-notifications`), and per-output instances bind with `output` set.
If several windows still match, every one of them gets the same shapes.

Note: KWin derives a layer surface's *window type* from the namespace for the reserved names
`desktop`, `dock`, `notification`, `critical-notification`, `tooltip`, `on-screen-display`,
`dialog`, `splash`, `utility`; any other namespace (all `kristall-*` ones) is type "normal" for
KWin. Glass matching does not care either way.

### `shapes` — replace the whole shape list of a surface (atomic)
```json
{"op":"shapes","surface":"dock-eDP-1","sync":"commit","shapes":[ {shape}, … ]}
```
* The list replaces the previous one entirely. If any shape is invalid, the whole message is
  rejected (`error`, `bad-request`) and the previous list stays.
* `sync` (optional): `"immediate"` (default) — applied for the next compositor frame;
  `"commit"` — held until the bound surface's next `wl_surface.commit`, then applied with that
  frame (use when content and shapes animate together, e.g. Dock magnification), but at most
  **100 ms** later if no commit comes. While no window is bound, `commit` acts like `immediate`.
  A later `shapes`/`patch` replaces a held one.
* Order of the array = paint order (later shapes are drawn over earlier ones).

### `patch` — change some fields of existing shapes
`{"op":"patch","surface":"dock-eDP-1","shapes":[{"id":"dock","pointer":[312,40]}]}` — each entry
needs an existing `id`; the given fields are applied (same validation, same atomicity, same
`sync`). Fields cannot be removed except the nullable ones (`tint`, `tintAmount`, `depth`,
`bezel`, `pointer`, `group` accept `null` = back to default).

### `unbind`
`{"op":"unbind","surface":"dock-eDP-1"}` — removes the binding and its shapes.

### `config`
`{"op":"config","qualityHint":"efficient"}` — `"high"`, `"efficient"` or `null` (clear).
Used by the power component. Only effective while `appearance.glassQuality` is `auto`. The most
recent hint from any connection wins; it is dropped when that connection closes. Reply: a
`state` event if the effective quality changed.

### `status`, `ping`, `debug`
* `{"op":"status"}` → `status` event (diagnostics, §5.3).
* `{"op":"ping","token":<any>}` → `{"event":"pong","token":<same>}`.
* `{"op":"debug","timing":true|false,"isolate":"none"|"refraction"}` → `debug` event.
  `timing` subscribes this connection to `timing` events (≤ 1 per second while frames are
  painted; **this brackets passes with `glFinish` and costs performance — diagnostics only**).
  `isolate:"refraction"` (global, for measurements) draws only the refracted background without
  blur, tint, light or dither. Env `KRISTALL_GLASS_TIMING=1` logs timings without a client.

### Shape object

| Field | Type | Default | Meaning |
|---|---|---|---|
| `id` | string 1–128 | **required** | Stable identity; keep it across updates so animations and legibility state continue |
| `x`,`y`,`w`,`h` | number | **required** (in `shapes`) | Surface-local logical rect. `w`/`h` ≥ 0; empty shapes are ignored |
| `kind` | `"rect"` \| `"capsule"` | `"rect"` | `capsule` = fully rounded ends (radius = min(w,h)/2, circular) |
| `radius` | number ≥ 0 | `16` | Corner radius of a `rect` (clamped to min(w,h)/2) |
| `smoothing` | 0…1 | `0.6` | Continuous-curvature corners: 0 = circular arc; s > 0 = superellipse-like corner that starts (1+s)·radius before the corner and passes the 45° point where a circular corner of `radius` would (curvature-continuous with the edges) |
| `variant` | `"regular"` \| `"clear"` | `"regular"` | `clear`: ~40 % of the tint, much lighter blur, mostly sharp background, weaker legibility correction (media overlays) |
| `tint` | colour \| null | null | Tint colour replacing the theme tint (accent-tinted controls); its alpha multiplies `tintAmount` |
| `tintAmount` | 0…1 \| null | from slider | Tint strength. With `tint` and no `tintAmount`: max(0.35, slider tint) |
| `bezel` | number \| null | clamp(0.22·min(w,h), 4, 24) | Width of the curved rim (where refraction happens); ≤ min(w,h)/2 |
| `depth` | number \| null | 0.55·bezel | Lens strength: displacement at the very rim, logical px (≤ 64) |
| `pointer` | `[x, y]` \| null | null | Surface-local pointer position for the soft follow highlight and brighter rim near it |
| `pressed` | bool | false | Pressed look: lens 35 % deeper, brighter; the effect animates it (120 ms) |
| `group` | string \| null | null | Shapes with the same group whose rects come within `merge` of each other melt into one body (smooth union, ≤ 8 shapes per body) |
| `merge` | number 0…200 | `12` | Smooth-union distance for its group, logical px |
| `opacity` | 0…1 | `1` | Multiplies the whole glass of this shape (client-side fades) |

## 5. Server → client events

### 5.1 `hello` and `state`
```json
{"event":"hello","server":"kristall-glass","protocol":1,"state":"active","quality":"high",
 "qualitySetting":"auto","theme":"light","glass":0.3,"reduceTransparency":false,"legibility":true}
```
`state`: `"active"` (glass is drawn), `"disabled"` (`reason`:`"crash-guard"`), `"failed"`
(`reason`: e.g. a shader compile error). `legibility`: whether automatic legibility events are
available (needs GL ≥ 3.2 / GLES ≥ 3.0). An event `"state"` with the same fields is sent to
every client whenever any of them changes (settings, quality, failure).

### 5.2 `bound`
`{"event":"bound","surface":"dock-eDP-1","windows":1}` — number of windows the binding currently
applies to; sent after `bind` and on every change. `windows: 0` = your surface is not (or no
longer) there; shapes are kept and re-apply when it appears.

### 5.3 `legibility`
```json
{"event":"legibility","surface":"bar-eDP-1","shape":"strip","scheme":"dark","luminance":0.31}
```
* `scheme`: `"light"` = light glass → draw **dark** text/symbols; `"dark"` = dark glass → draw
  **light** text/symbols.
* `luminance`: estimated glass luminance 0…1 before the legibility band (diagnostic).
* Sent once after a shape first appears (when the first sample is available, ~1 frame) and then
  only when the scheme flips. The decision uses the average background under the inner 80 % of
  the shape, mixed with the tint, with theme-biased hysteresis (light theme flips to `dark` below
  0.40, back above 0.50; dark theme flips to `light` above 0.62, back below 0.52) and at least
  600 ms between flips. Sampling runs only when the background behind the glass changed, at most
  10 Hz (3.3 Hz in the efficient tier).
* The glass itself starts its 300 ms cross-fade when the event is sent; clients should animate
  their text colour over ~300 ms at the same moment. Before the first event, assume the theme:
  light theme ⇒ `"light"`, dark theme ⇒ `"dark"`.
* The rendered glass is held inside a luminance band for its scheme (light: 0.52–0.95, dark:
  0.05–0.45, sRGB-encoded) so text stays legible even over mixed content.
* Shapes from automatic blur requests (apps) never adapt and send nothing.

### 5.4 Other events
* `{"event":"error","code":…,"message":…,"op":…,"surface":…}` — codes: `bad-json`,
  `bad-request`, `unknown-op`, `unknown-surface`, `limit`, `too-long`. The connection stays open
  (except as stated in §3).
* `status` — `state`, `guard` (§7), `clients`, `bindings`, counters `frames` (frames the effect saw),
  `glassDraws`, `captures`, `blurs`, `cacheHits`, `composites`, `lumaReads`, `allocations`,
  `quality`, `theme`, `glass`, `reduceTransparency`, `windows` (per glass window: `explicit`,
  `shapes`, `pid`, `namespace`, `geometry`, `shapeStates`), `lastTiming`. Diagnostic: fields may
  be added.
* `timing` — `frames`, `captureMs`, `blurMs`, `compositeMs`, `lumaMs`, `totalMs` (averages per frame).
* `pong`, `debug` — replies.

Defaults for automatic (blur-request) shapes: one `rect` over the bounding box of the requested
region, `radius` = the window's corner radius or inferred from a stair-stepped region,
`smoothing` 0, `bezel` clamp(0.12·min side, 3, 14), `depth` 0.4·bezel, regular variant, tint at
60 % of the slider value. If the region is not close to a rounded rect, the material is clipped
to the region. Apps keep drawing their own (translucent) background on top.

## 6. Quality tiers

| | high | efficient |
|---|---|---|
| background capture | device resolution | device resolution |
| blur | light Dual-Kawase, result at ½ res | one iteration less, result at ¼ res |
| composite samples | sharp + blurred, chromatic split in the rim (≤ 6 taps) | 1 tap, no chroma, single rim light |
| legibility sampling | ≤ 10 Hz | ≤ 3.3 Hz |

Both tiers: nothing is recomputed while the screen is static; the blur is reused while only
shapes change (capture rects snap to a 32-logical-px grid); no per-frame allocations once warm.

## 7. Absence, failure, fallback (clients MUST implement)

Draw a **plain translucent fill** (theme colour, ~82 % opacity, hairline border) for a shape
whenever any of these is true, and the glass otherwise:

1. `glass.sock` does not exist or `connect()` fails (`ENOENT`, `ECONNREFUSED`) — effect not
   loaded, KWin not composited, or KWin restarting. Retry with backoff 0.25 s → 5 s.
2. `hello`/`state` reports `state` ≠ `"active"`.
3. The connection closes (KWin crashed or the effect was unloaded): fall back immediately,
   reconnect with backoff, re-send `hello`, every `bind` and the current `shapes`.
4. `bound` reports `windows: 0` for that surface (the shapes are not drawn anywhere).

The effect protects the session: a plugin that fails to load (e.g. KWin updated without a
rebuild) leaves KWin compositing normally without glass. The **crash guard** covers the whole
login session: the effect keeps `$XDG_RUNTIME_DIR/kristall/glass.guard` (JSON
`{"schema":2,"armed":bool,"disabled":bool,"crashes":[epoch s…]}`, written atomically), `armed`
while it is loaded and drawing; a clean unload clears it. A KWin that starts and finds the record
still armed counts a crash (the previous KWin died with the effect active, at start-up or later).
Two crashes within **10 minutes** and the effect starts disabled (`state:"disabled"`,
`reason:"crash-guard"`) and stays disabled for the rest of the login session, also across
further KWin restarts. The file lives on the runtime tmpfs: the next boot (or login) tries glass
again; deleting the file retries at once. `kristall-glass-ctl status` shows the record under
`guard` (`disabled`, `crashes`, `windowSeconds`); clients see `state`/`reason`, and the shell turns
it into one gentle notification per session (shell.md §8). Tested by killing KWin with SIGSEGV
twice (`tests/test_failsafe.py`).

## 8. Reference client

`GlassClient.qml` (singleton: connection, replay after reconnect, coalescing with
`Qt.callLater`), `GlassSurface.qml` (one per layer window: `key`, `layerNamespace`, `output`,
`shapes:[…]`; sends geometry on every frame the window renders, `sync:"commit"` for frame-bound
updates) and `GlassShape.qml` (an `Item` with the shape fields above, `scheme`/`textColor`
updated from `legibility`, and the fallback fill built in). `demo/shell.qml` shows a menu bar, a
Dock, a panel and merging shapes; run it with `quickshell -p /usr/share/kristall/glass/demo`.
