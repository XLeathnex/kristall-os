# Contract: `design` — the Kristall design system

Owner: **shell-core** (`shell/core/`). Consumers: every shell module (panels, dock, search, apps,
switcher, assistant UI, setup), the `theme` component (window radii, colours, type for apps,
login and lock screen), anyone drawing UI for the owner.
Implementation: `shell/core/Theme.qml` (tokens) and the `K*`/`Glass*` components in `shell/core/`.
The gallery (`kristall-shellctl gallery toggle`, source `shell/gallery/Gallery.qml`) shows every
component in every state; screenshots in `shell/tests/evidence/gallery-*.jpg`.
This document is normative: a number here and in `Theme.qml` must agree.

## 1. Rules

1. **Use the tokens and components, never your own numbers.** If you need a value that is not
   here, add it to `Theme.qml` and this file in the same change (or ask in your report).
2. All lengths are **logical pixels** (Wayland surface coordinates). The panel is 2880×1800 and
   runs at a fractional scale (≈ 1.5–1.75); everything is laid out on whole logical pixels, and
   hairlines are `1 / devicePixelRatio` (exactly one device pixel).
3. Content on glass takes its colours from the **glass legibility signal**:
   `GlassShape.scheme` (`"light"` glass → dark content, `"dark"` glass → light content) and
   `Theme.color(scheme, role)`. Opaque materials use `Theme.scheme`. Never hard-code black/white
   text on glass.
4. Animate only in response to input or events, then stop (ARCHITECTURE §5.3). Durations come
   from `Theme.duration(kind)`, which honours Reduce Motion.
5. Every glass shape has the fallback built in (`GlassShape`); do not draw your own blur.

## 2. How the numbers were obtained

| Source | Used for |
|---|---|
| Apple Human Interface Guidelines, *Typography → macOS built-in text styles* | type scale sizes, line heights, weights |
| HIG *Color → system colors* (published sRGB values, light/dark) | accent palette, label/fill/separator opacities |
| WWDC25 session 310 *Build an AppKit app with the new design* and *Meet Liquid Glass* | control size classes (mini…extra-large, large+ are capsules), concentric corners, menus without icons in macOS 27 |
| Community measurements of macOS 26/27 windows (MacRumors "all the Liquid Glass changes in macOS Golden Gate", lapcatsoftware "macOS Tahoe windows have different corner radiuses") | window radii 26/16 in 26 → ~20/16 in 27 |
| Published third-party token set for macOS 26 (juanlara-aidev "macos-26-design") | cross-check of type ramp, spacing steps, motion durations |
| Measurement of Apple screenshots at known scale (menu bar 24 pt on displays without a notch, menu rows, highlight insets) | bar and menu metrics — **estimates**, marked ≈ below |
| Rendering our own components in the headless compositor at 1.0× and 1.6× | Inter tracking, hairlines, symbol sizes |

What could not be measured here (no Mac, no network access to Apple's design resources from the
build sandbox): exact menu-row heights and highlight radii of macOS 27, exact control heights in
points, the exact springs. These values are best estimates from screenshots and are the first
place to adjust when comparing against a real Mac.

## 3. Typography

Font: **Inter** (SIL OFL, Fedora `rsms-inter-fonts`) for text; **Inter Display** (the optical
size for large text) from 20 px up, the same way the system font switches to its display cut.

| Style | Size / line (px) | Weight (emphasized) | Tracking (px) | Family |
|---|---|---|---|---|
| largeTitle | 26 / 32 | 400 (700) | −0.40 | Inter Display |
| title1 | 22 / 26 | 400 (700) | −0.30 | Inter Display |
| title2 | 17 / 22 | 400 (700) | −0.25 | Inter |
| title3 | 15 / 20 | 400 (600) | −0.20 | Inter |
| headline | 13 / 16 | 700 (800) | −0.10 | Inter |
| body | 13 / 16 | 400 (600) | −0.10 | Inter |
| callout | 12 / 15 | 400 (600) | −0.05 | Inter |
| subheadline | 11 / 14 | 400 (600) | 0 | Inter |
| footnote | 10 / 13 | 400 (600) | +0.05 | Inter |
| caption1 | 10 / 13 | 400 (500) | +0.05 | Inter |
| caption2 | 10 / 13 | 500 (600) | +0.05 | Inter |
| menuBar, menu, control | 13 / 16 | 400 (bar app name 700) | −0.10 | Inter |
| controlSmall | 11 / 14 | 400 | 0 | Inter |
| sectionHeader | 11 / 14 | 600 | +0.10 | Inter |
| hudValue | 15 / 20 | 600 | −0.20 | Inter |
| clockLarge (lock screen) | 96 / 104 | 600 | −2.0 | Inter Display |

Optical adjustments and how they were judged:

* Inter's x-height (≈ 0.546 em) is about 4 % taller than the system font's (≈ 0.52–0.53 em)
  and its letters are slightly wider. Sizes stay on Apple's points (layouts line up with real Mac
  measurements) and tracking is tightened a little more than Inter's own "dynamic metrics" formula
  gives (≈ −0.04 px at 13 px) so a line of 13-px Inter takes about the width of the system font's.
  Judged by rendering the menu bar strings ("Dateien Ablage Bearbeiten Darstellung Fenster
  Hilfe", "So. 15. Nov. 22:02") at 1.0× and 1.6× next to the measured title spacing of a Mac menu
  bar (20 px text-to-text) and checking that nothing reads as letter-spaced or cramped.
* Small sizes (10–11 px) get slightly *positive* tracking, as the system font does at small sizes.
* `font.features: tnum` (tabular figures) for the clock, percentages and other changing numbers;
  contextual alternates on. No hinting (`PreferNoHinting`), `Text.NativeRendering` (glyphs
  rasterised at device resolution — crisp at fractional scales; distance-field text is softer at
  13 px).
* Weights are CSS weights (Qt 6): 400 regular, 500 medium, 600 semibold, 700 bold.

Use `KText { textStyle: "body"; emphasized: false; level: "label"; scheme: … }`.

## 4. Spacing, sizes

Spacing grid (4 px with 2-px half steps): `xxs 2, xs 4, s 6, m 8, l 12, xl 16, xxl 20, xxxl 24, huge 32`.

| Token (`Theme.size.*`) | Value | Notes |
|---|---|---|
| bar | 24 | menu bar height (Mac without a notch; the panel has none) |
| barItemHeight / radius.barItem | 20 / 6 | highlight behind an open title or status item (≈) |
| barTitlePadding / barTitleSpacing | 9 / 2 | text-to-text gap between titles = 20 |
| barEdge | 8 | screen edge to the first/last highlight |
| barMarkPadding | 11 | around the 15-px mark |
| barStatusPadding | 7 | around 16-px status symbols (status items sit edge to edge) |
| barIcon | 16 | status symbols; the battery glyph is 27×12 |
| menuItem / menuSeparator / header | 24 / 11 / 22 | menu rows (≈) |
| menuPaddingV / menuInset | 5 / 5 | top/bottom padding; highlight inset from the menu edge |
| menuTextLeft / menuTextRight | 22 / 16 | check column 8–22, then the label |
| menuShortcutGap / menuMinWidth / menuMaxWidth | 28 / 180 / 420 | |
| submenuGap | 3 | glass does not refract glass, so submenus do not overlap their parent |
| controlSmall / control / controlLarge | 22 / 28 / 36 | capsule controls |
| toggleWidth × toggleHeight, knob inset | 42 × 24, 2 | knob 20 |
| sliderTrack, sliderKnob | 6, 28 × 20 | |
| capsuleSlider | 28 | Control-Center style slider |
| segmented / segmentInset | 28 / 2 | |
| field | 28 | text and search fields |
| listRow / listRowCompact | 32 / 24 | 44 with a subtitle |
| tooltip padding | 8 × 4 | |

## 5. Corner radii and concentricity

Rule: a shape inside another shape with padding *p* has radius `outer − p` (never less than
the inner element's own minimum). Corners use **continuous curvature** (`smoothing 0.6` in the
glass contract; QML `Rectangle` corners are circular — acceptable below 10 px).

| Element | Radius |
|---|---|
| bar title highlight | 6 |
| menu / menu item highlight | 12 / 7 (= 12 − 5) |
| tooltip | 8 |
| panel (Control Center, notification centre, Search) / tile inside | 26 / 16 (= 26 − 10) |
| HUD | 22 |
| text field / rounded-rect control / list row highlight / card | 8 / 8 / 8 / 14 |
| capsule controls, toggles, sliders, segments, search field | height / 2 |
| Dock | 24 |
| windows (theme): titlebar-only / with toolbar | 16 / 20 (macOS 27; macOS 26 used 26) |
| window title bar / buttons (theme, ≈) | 28 high; buttons 12 Ø circles, 8 apart, first 12 from the window edge (`theme.md` §3) |
| app icons | 22.37 % of the size, continuous curvature |

## 6. Colour

`Theme.color(scheme, role)` (scheme = surface appearance). Light / dark values:

| Role | Light | Dark |
|---|---|---|
| label | #1D1D1F | #F2F2F7 |
| secondaryLabel | black 50 % | white 55 % |
| tertiaryLabel / disabledLabel | black 25 % | white 25 % |
| quaternaryLabel | black 10 % | white 10 % |
| separator | black 14 % | white 20 % |
| fill / fillStrong (controls on glass) | black 8 % / 14 % | white 12 % / 20 % |
| hover / pressed veil | black 6 % / 12 % | white 10 % / 18 % |
| barHighlight | black 12 % | white 22 % |
| border (hairlines) | black 10 % | white 14 % |
| trackOff | black 12 % | white 18 % |
| knob | #FFFFFF | #FFFFFF |
| window (opaque material) | #ECECEE | #262628 |
| barSolid (dimmed bar) | #F4F4F6 | #1F1F21 |
| fieldBackground | white 70 % | white 8 % |
| fallback (no glass) | #F6F6F8 | #1E1E20 |
| destructive / success / warning | #FF3B30 / #28CD41 / #FFCC00 | #FF453A / #32D74B / #FFD60A |
| focusRing | accent 55 % | accent 55 % |

Accent (`appearance.accent`, default `blue`): blue #007AFF/#0A84FF, purple #AF52DE/#BF5AF2,
pink #FF2D55/#FF375F, red #FF3B30/#FF453A, orange #FF9500/#FF9F0A, yellow #FFCC00/#FFD60A,
green #28CD41/#32D74B, graphite #8E8E93/#98989D (light/dark). Content on accent fills is white.

## 7. Shadows

Drawn by the client *outside* glass shapes (the effect draws only the glass) from pre-rendered
nine-patches with the shape cut out (`shell/tools/gen-shadows.py` → `shell/core/assets/`; use
`KShadow`, or `GlassShape.shadow`). Gaussian blur radius (≈ 2σ), y offset, opacity in the light
theme (dark: × 1.6, ≤ 0.6):

| Kind | blur | y | opacity | Radii available |
|---|---|---|---|---|
| menu | 24 | 8 | 0.22 | 12 |
| panel | 40 | 14 | 0.20 | 26, 16 |
| hud | 30 | 10 | 0.18 | 22 |
| tooltip | 12 | 4 | 0.18 | 8 |
| control | 8 | 2 | 0.14 | 11, 14, 18 |
| knob | 6 | 1 | 0.22 | 10, 12 |
| window (theme) | 48 | 16 | 0.32 | — |

A new radius: add it to `SHAPES` in the generator and to `KShadow.available`.

## 8. Motion

`Theme.duration(kind, isFade)` in ms — Reduce Motion turns movement into 0 ms while fades stay:

| Kind | ms | Use |
|---|---|---|
| micro | 100 | hover, press, knob stretch |
| short | 150 | menus/tooltips appear, highlight moves |
| medium | 250 | popovers and panels open, toggles, segments |
| long | 350 | large transitions (overview, sheets) |
| legibility | 300 | text colour follows the glass (glass contract §5.3) |
| barDim | 400 | menu bar glass ↔ solid |
| menuFlash | 70 (× 2) | the chosen menu item blinks off/on once |
| menuFade | 150 | menu fades out after a selection |

`Theme.curve(kind)` → `Easing.BezierSpline` control points: `standard` (0.25, 0.1, 0.25, 1)
CAMediaTimingFunction default · `easeOut` (0, 0, 0.2, 1) appearing · `easeIn` (0.4, 0, 1, 1)
leaving · `easeInOut` (0.42, 0, 0.58, 1) · `smooth` (0.2, 0.9, 0.25, 1) ≈ spring response 0.5 s,
damping 1.0 · `snappy` (0.2, 1.0, 0.3, 1.02) ≈ spring 0.4 s, damping 0.9 · `bouncy`
(0.3, 1.35, 0.5, 1) ≈ spring 0.5 s, damping 0.7, ~6 % overshoot (Dock bounce, toggle knob).
Menus open without movement (macOS shows them at once); they fade out.

## 9. Glass material by role

Parameters of `docs/contracts/glass.md` §4 per role (`Theme.glassRole(role)`). `tint` is the
`tintAmount` at the owner's slider ends (ultra-clear 0.0 → fully tinted 1.0), interpolated
linearly; `effect` = the effect's own slider mapping (light 0.10 + 0.72·s, dark 0.16 + 0.68·s).
`fallback` = opacity of the plain fill when the effect is absent (Reduce Transparency: 1.0).
Increase Contrast adds +0.12 tint (+0.15 for `effect` roles) and +0.05 fallback opacity.

| Role | kind | radius | smoothing | bezel | depth | variant | tint clear → tinted | fallback clear → tinted |
|---|---|---|---|---|---|---|---|---|
| bar | rect | 0 | 0 | 5 | 3 | regular | effect | 0.80 → 0.94 |
| menu | rect | 12 | 0.6 | 10 | 6 | regular | 0.78 → 0.94 | 0.90 → 0.97 |
| panel | rect | 26 | 0.6 | 18 | 10 | regular | 0.70 → 0.92 | 0.86 → 0.96 |
| control | capsule | h/2 | 0.6 | default | default | regular | effect | 0.80 → 0.92 |
| hud | rect | 22 | 0.6 | 14 | 8 | regular | 0.50 → 0.88 | 0.88 → 0.96 |
| tooltip | rect | 8 | 0.6 | 4 | 2 | regular | 0.82 → 0.94 | 0.95 → 0.98 |
| media | rect | 16 | 0.6 | 10 | 6 | clear | effect | 0.55 → 0.80 |

Why menus and panels carry more tint than the bar: they hold many lines of small text over
arbitrary content; at the effect's light blur (2–10 px) only tint keeps them legible. The bar
follows the slider fully (it carries little text and its colour follows the legibility signal).

The bar strip is edge to edge (radius 0, small bezel so the lens shows along its lower edge). When
the front window on that output is maximised or full screen the bar **dims**: the glass fades out
(`glassOpacity` → 0 over 400 ms) and an opaque `barSolid` fill fades in; content opacity 0.88.

## 10. Accessibility

Settings (shell-core owns `accessibility`; `appearance.reduceTransparency` is the glass
contract's key): **Reduce Transparency** — glass is drawn opaque by the effect; fallbacks are
opaque. **Reduce Motion** — `Theme.duration()` returns 0 for movement, fades remain.
**Increase Contrast** — labels pure black/white, secondary labels 75 %, separators 35 %, borders
on glass shapes, more tint. Every control has `Accessible.role/name`, is reachable with Tab, has
a focus ring (3 px, accent 55 %, outside the shape) and works with Space/Return/arrows.

## 11. Components (`import qs.core`)

| Component | Key properties | Notes |
|---|---|---|
| `GlassSurface` | `key`, `layerNamespace`, `output`, `glassDrawn` | one per layer window; shapes register themselves |
| `GlassShape` | `shapeId`, `surface`, `role`, `scheme`, `textColor`, `glassOpacity`, `glassEnabled`, `pressed`, `pointer*`, `group`/`merge`, `shadow` | fallback, shadow, increase-contrast border built in |
| `KText` | `textStyle`, `emphasized`, `scheme`, `level`, `tabular` | colour cross-fades 300 ms |
| `KIcon` | `name` (`"wifi-high"`, `"fill/…"`, `"bold/…"`, `"kristall/…"`), `size`, `color`, `scheme` | SVG at device resolution, any colour |
| `KButton` | `text`, `icon`, `variant` fill/accent/plain/destructive/glass, `size` small/regular/large, `checkable`/`checked`, `showState` | icon-only = circle |
| `KToggle` | `checked`, `toggled(bool)` | |
| `KSlider` | `value`, `from`, `to`, `step`, `moved(v)` | |
| `KCapsuleSlider` | `value` 0..1, `icon`, `moved(v)` | Control Center style |
| `KSegmented` | `model`, `currentIndex`, `activated(i)` | |
| `KTextField` | `text`, `placeholder`, `search`, `password`, `accepted()`, `escaped()` | needs keyboard focus on the surface |
| `KListRow` | `title`, `subtitle`, `icon`, `detail`, `chevron`, `selected`, trailing children | |
| `KSeparator` | `vertical`, `scheme` | one device pixel |
| `KScrollArea` | children = content, `contentHeight` | overlay scroller |
| `KTooltip` | `text`, `originX/Y` | 0.7 s delay, warm-up like macOS |
| `KFocusRing`, `KShadow` | | building blocks |
| `Menus` (singleton), `KMenuPanel`, `KMenuRow`, `MenuHost` | see §12 | |
| `Theme` (singleton) | tokens, `color()`, `glassRole()`, `glassTint()`, `duration()`, `curve()`, `shortcutText()` | |

`showState` ("hover", "pressed", "focus") exists for the gallery only.

## 12. Menus

Glass popup menus replace toolkit menus everywhere (app menus, tray menus, Dock and desktop
context menus). API in `docs/contracts/shell.md` §4. Look and behaviour:

* Rows 24 px, label at 22 px, shortcut right-aligned in the secondary colour (Mac glyph order
  ⌃⌥⇧⌘; with `keyboard.commandKey: "ctrl"` Control is shown as ⌘), chevron for submenus, check
  mark for checked items (a dot for radio items), headers (11 px semibold, secondary), separators
  (one device pixel, inset 12). **No icons** (macOS 27 removed them).
* Highlight: accent fill inset 5 px, radius 7; content on it is white. Disabled items are not
  highlighted and use the disabled colour.
* Open: no motion. Choose: the item blinks once (70 ms off, 70 ms on), the menu fades out in
  150 ms, then the action runs. Submenus open after 120 ms of hover, at once from the keyboard.
* Keyboard: ↑↓ move (skipping separators/disabled), → opens a submenu or the next menu-bar menu,
  ← closes a submenu or opens the previous menu-bar menu, ↩/Space choose, ⎋ closes one level,
  Home/End, typing selects by label prefix.
* Pointer: press-drag-release across titles and items; a click outside closes (and is not passed
  on); moving over another menu-bar title while a menu is open switches menus.

## 13. Symbols and the mark

Symbols: **Phosphor Icons 2.1.1** (MIT), weights regular, bold and fill, bundled in
`shell/icons/phosphor/` (source and licence in `shell/ASSETS.md`). Status symbols use bold (Wi-Fi)
or fill (speaker) at 16 px to match the visual weight of 13-px text. Our own symbols are in
`shell/icons/kristall/`: `mark` (the Kristall crystal — a quartz point cut into four facets that
differ only in opacity; monochrome; drawn by `shell/tools/gen-mark.py`), `control-center`,
`assistant`. Never use an Apple symbol or logo.

## 14. Known differences from macOS 27 (see also shell/README.md)

* Typeface: Inter is not the system font; letterforms (a, g, t, digits) differ visibly.
* The refraction and blur are the glass effect's model, not Apple's; menus need more tint than
  Apple's to stay legible over busy content because the effect's blur is lighter.
* Menus do not reproduce Apple's "safe triangle" for diagonal moves into submenus (120-ms delay
  instead) and have no scroll arrows for menus taller than the screen.
* Exact menu metrics and springs are estimates (§2).
