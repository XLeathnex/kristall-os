// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall design tokens. Every number here is specified (and justified) in
// docs/contracts/design.md; change both together. All lengths are logical pixels.
//
// Usage: `import qs.core` then Theme.type.body.size, Theme.radius.menu, Theme.color(scheme, "label"),
// Theme.glassRole("menu"), Theme.duration("short"), Theme.curve("smooth").
// `scheme` is the appearance of the surface the content sits on: "light" (light glass/material,
// draw dark content) or "dark". On glass it comes from the legibility signal (GlassShape.scheme).
pragma Singleton
import QtQuick
import Quickshell
import qs.services

Singleton {
    id: root

    // ---- owner settings ---------------------------------------------------------------------
    property bool plasmaDark: false
    readonly property string themeSetting: Settings.get("appearance.theme", "auto")
    readonly property bool dark: themeSetting === "dark" || (themeSetting === "auto" && (GlassClient.active ? GlassClient.theme === "dark" : plasmaDark))
    readonly property string scheme: dark ? "dark" : "light"          // scheme of opaque materials
    readonly property real glassLevel: Math.max(0, Math.min(1, Number(Settings.get("appearance.glass", 0.3))))
    readonly property bool reduceTransparency: Settings.get("appearance.reduceTransparency", false) === true
    readonly property bool reduceMotion: Settings.get("accessibility.reduceMotion", false) === true
    readonly property bool increaseContrast: Settings.get("accessibility.increaseContrast", false) === true
    readonly property string accentName: Settings.get("appearance.accent", "blue")

    Connections {
        target: Helper
        function onEvent(ev) {
            if (ev.event === "plasma")
                root.plasmaDark = ev.dark;
        }
    }
    Component.onCompleted: if (Helper.last.plasma) plasmaDark = Helper.last.plasma.dark

    // ---- typography -------------------------------------------------------------------------
    // macOS text styles (HIG, "macOS built-in text styles"), Inter standing in for the system
    // font. Inter's x-height is ~4 % larger than the system font's at the same size, so sizes stay
    // on Apple's grid and tracking is tightened slightly (design.md §3). "Inter Display" (the
    // optical size for large text) from 20 px up, like the system font switches to its display cut.
    readonly property string fontFamily: "Inter"
    readonly property string displayFamily: "Inter Display"
    readonly property var type: ({
        largeTitle:  { size: 26, line: 32, weight: 400, emphasized: 700, tracking: -0.40, family: displayFamily },
        title1:      { size: 22, line: 26, weight: 400, emphasized: 700, tracking: -0.30, family: displayFamily },
        title2:      { size: 17, line: 22, weight: 400, emphasized: 700, tracking: -0.25, family: fontFamily },
        title3:      { size: 15, line: 20, weight: 400, emphasized: 600, tracking: -0.20, family: fontFamily },
        headline:    { size: 13, line: 16, weight: 700, emphasized: 800, tracking: -0.10, family: fontFamily },
        body:        { size: 13, line: 16, weight: 400, emphasized: 600, tracking: -0.10, family: fontFamily },
        callout:     { size: 12, line: 15, weight: 400, emphasized: 600, tracking: -0.05, family: fontFamily },
        subheadline: { size: 11, line: 14, weight: 400, emphasized: 600, tracking: 0.00, family: fontFamily },
        footnote:    { size: 10, line: 13, weight: 400, emphasized: 600, tracking: 0.05, family: fontFamily },
        caption1:    { size: 10, line: 13, weight: 400, emphasized: 500, tracking: 0.05, family: fontFamily },
        caption2:    { size: 10, line: 13, weight: 500, emphasized: 600, tracking: 0.05, family: fontFamily },
        // UI-specific roles built on the scale
        menuBar:     { size: 13, line: 16, weight: 400, emphasized: 700, tracking: -0.10, family: fontFamily },
        menu:        { size: 13, line: 16, weight: 400, emphasized: 600, tracking: -0.10, family: fontFamily },
        control:     { size: 13, line: 16, weight: 400, emphasized: 600, tracking: -0.10, family: fontFamily },
        controlSmall:{ size: 11, line: 14, weight: 400, emphasized: 600, tracking: 0.00, family: fontFamily },
        sectionHeader:{ size: 11, line: 14, weight: 600, emphasized: 700, tracking: 0.10, family: fontFamily },
        hudValue:    { size: 15, line: 20, weight: 600, emphasized: 700, tracking: -0.20, family: fontFamily },
        clockLarge:  { size: 96, line: 104, weight: 600, emphasized: 700, tracking: -2.0, family: displayFamily }
    })
    // Font weights in Qt's 1..1000 scale are CSS weights: 400 regular, 500 medium, 600 semibold, 700 bold.

    // ---- spacing (4-px grid with 2-px half steps) ---------------------------------------------
    readonly property var space: ({ xxs: 2, xs: 4, s: 6, m: 8, l: 12, xl: 16, xxl: 20, xxxl: 24, huge: 32 })

    // ---- sizes --------------------------------------------------------------------------------
    readonly property var size: ({
        bar: 24,                 // menu bar height (Mac without a notch)
        barItemHeight: 20,       // highlight behind an open title / status item
        barTitlePadding: 9,      // text to highlight edge, each side
        barTitleSpacing: 2,      // between title highlights (text gap = 2*9+2 = 20)
        barEdge: 8,              // screen edge to first/last highlight
        barMarkPadding: 11,      // the mark's highlight padding
        barStatusPadding: 7,     // status icon to highlight edge, each side
        barIcon: 16,             // status symbols (battery is 25×12)
        menuItem: 24,            // menu row
        menuSeparator: 11,
        menuPaddingV: 5,         // menu top/bottom padding
        menuInset: 5,            // highlight inset from the menu edge (concentric with radius.menu)
        menuTextLeft: 22,        // menu edge to label start (check column 8..22)
        menuTextRight: 16,       // label/shortcut end to menu edge
        menuMinWidth: 180,
        menuMaxWidth: 420,
        menuShortcutGap: 28,     // label to shortcut column
        submenuGap: 3,           // gap between a menu and its submenu (glass does not refract glass, so no overlap)
        controlSmall: 22,        // capsule controls
        control: 28,
        controlLarge: 36,
        toggleWidth: 42, toggleHeight: 24, toggleKnobInset: 2,
        sliderTrack: 6, sliderKnobW: 28, sliderKnobH: 20,
        capsuleSlider: 28,       // thick Control-Center style slider
        segmented: 28, segmentInset: 2,
        field: 28,
        listRow: 32, listRowCompact: 24,
        tooltipPadH: 8, tooltipPadV: 4,
        hairline: 1              // logical; components divide by devicePixelRatio for 1 device px
    })

    // ---- corner radii (concentric: inner = outer − inset) --------------------------------------
    readonly property var radius: ({
        barItem: 6,
        menu: 12,
        menuItem: 7,            // 12 − 5
        tooltip: 8,
        panel: 26,              // Control Center, notification centre, Search
        panelTile: 16,          // 26 − 10 padding
        hud: 22,
        field: 8,
        control: 8,             // rounded-rect controls (non-capsule), list highlight
        listRow: 8,
        card: 14,
        dock: 24,
        windowSmall: 16,        // titlebar-only windows (theme component)
        window: 20,             // windows with a toolbar (macOS 27: 20, was 26 in 26)
        appIcon: 0.2237          // fraction of the icon size (continuous-curvature squircle)
    })
    readonly property real smoothing: 0.6   // continuous-curvature corners (glass contract field)

    // ---- colours -----------------------------------------------------------------------------
    readonly property var accents: ({
        blue:     { light: "#007AFF", dark: "#0A84FF" },
        purple:   { light: "#AF52DE", dark: "#BF5AF2" },
        pink:     { light: "#FF2D55", dark: "#FF375F" },
        red:      { light: "#FF3B30", dark: "#FF453A" },
        orange:   { light: "#FF9500", dark: "#FF9F0A" },
        yellow:   { light: "#FFCC00", dark: "#FFD60A" },
        green:    { light: "#28CD41", dark: "#32D74B" },
        graphite: { light: "#8E8E93", dark: "#98989D" }
    })
    function accentFor(scheme) {
        const a = accents[accentName] || accents.blue;
        return scheme === "dark" ? a.dark : a.light;
    }
    readonly property color accent: accentFor(scheme)
    readonly property color accentContent: "#FFFFFF"   // text and symbols on accent fills

    // semantic colours by scheme of the surface. Values are macOS's label/fill/separator opacities.
    function color(scheme, role) {
        const d = scheme === "dark";
        const hc = increaseContrast;
        const v = d ? 1 : 0;                       // ink: white on dark, black on light
        const a = function (x) { return Qt.rgba(v, v, v, x); };
        switch (role) {
        case "label": return d ? (hc ? "#FFFFFF" : "#F2F2F7") : (hc ? "#000000" : "#1D1D1F");
        case "secondaryLabel": return a(hc ? 0.75 : (d ? 0.55 : 0.50));
        case "tertiaryLabel": return a(hc ? 0.55 : 0.25);
        case "quaternaryLabel": return a(hc ? 0.40 : 0.10);
        case "disabledLabel": return a(hc ? 0.45 : 0.25);
        case "separator": return a(hc ? 0.35 : (d ? 0.20 : 0.14));
        case "fill": return a(hc ? 0.20 : (d ? 0.12 : 0.08));        // control backgrounds on glass
        case "fillStrong": return a(hc ? 0.30 : (d ? 0.20 : 0.14));
        case "hover": return a(d ? 0.10 : 0.06);
        case "pressed": return a(d ? 0.18 : 0.12);
        case "barHighlight": return d ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(0, 0, 0, 0.12);
        case "border": return a(hc ? 0.45 : (d ? 0.14 : 0.10));
        case "rim": return a(hc ? 0.5 : (d ? 0.24 : 0.16));       // hairline outline of solid glass objects (KGlassRim)
        case "shadow": return Qt.rgba(0, 0, 0, d ? 0.45 : 0.22);
        case "knob": return "#FFFFFF";
        case "trackOff": return a(d ? 0.18 : 0.12);
        case "window": return d ? "#262628" : "#ECECEE";       // opaque material behind content
        case "barSolid": return d ? "#1F1F21" : "#F4F4F6";     // dimmed (solid) menu bar
        case "fieldBackground": return d ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(1, 1, 1, 0.70);
        case "fallback": return d ? "#1E1E20" : "#F6F6F8";     // translucent fill without glass
        case "focusRing": return Qt.alpha(accentFor(scheme), 0.55);
        case "destructive": return d ? "#FF453A" : "#FF3B30";
        case "success": return d ? "#32D74B" : "#28CD41";
        case "warning": return d ? "#FFD60A" : "#FFCC00";
        case "micOrange": return d ? "#FF9F0A" : "#FF9500";     // the microphone-in-use sign (privacy dot, mic badge)
        }
        console.warn("Theme.color: unknown role", role);
        return "magenta";
    }

    // ---- glass material by role (parameters of docs/contracts/glass.md) -------------------------
    // tint: [ultra-clear, fully tinted] tint amounts interpolated by the owner's slider (null =
    // the effect's own slider mapping). fallback: [clear, tinted] opacity of the plain fill used
    // when the effect is absent (glass contract §7).
    readonly property var glassRoles: ({
        bar:     { kind: "rect", radius: 0, smoothing: 0, bezel: 5, depth: 3, variant: "regular", tint: null, fallback: [0.80, 0.94] },
        menu:    { kind: "rect", radius: 12, smoothing: 0.6, bezel: 10, depth: 6, variant: "regular", tint: [0.78, 0.94], fallback: [0.90, 0.97] },
        panel:   { kind: "rect", radius: 26, smoothing: 0.6, bezel: 18, depth: 10, variant: "regular", tint: [0.70, 0.92], fallback: [0.86, 0.96] },
        control: { kind: "capsule", radius: 14, smoothing: 0.6, bezel: -1, depth: -1, variant: "regular", tint: null, fallback: [0.80, 0.92] },
        hud:     { kind: "rect", radius: 22, smoothing: 0.6, bezel: 14, depth: 8, variant: "regular", tint: [0.50, 0.88], fallback: [0.88, 0.96] },
        tooltip: { kind: "rect", radius: 8, smoothing: 0.6, bezel: 4, depth: 2, variant: "regular", tint: [0.82, 0.94], fallback: [0.95, 0.98] },
        media:   { kind: "rect", radius: 16, smoothing: 0.6, bezel: 10, depth: 6, variant: "clear", tint: null, fallback: [0.55, 0.80] },
        dock:    { kind: "rect", radius: 24, smoothing: 0.6, bezel: -1, depth: -1, variant: "regular", tint: [0.52, 0.9], fallback: [0.84, 0.95] },
        platter: { kind: "rect", radius: 16, smoothing: 0.6, bezel: 8, depth: 3, variant: "regular", tint: [0.58, 0.86], fallback: [0.0, 0.0] }
    })
    function glassRole(role) {
        return glassRoles[role] || glassRoles.panel;
    }
    // tint amount for a role at the current slider; -1 = leave it to the effect
    function glassTint(role) {
        const r = glassRole(role);
        if (!r.tint)
            return increaseContrast ? Math.min(1, (dark ? 0.16 + 0.68 * glassLevel : 0.10 + 0.72 * glassLevel) + 0.15) : -1;
        const t = r.tint[0] + (r.tint[1] - r.tint[0]) * glassLevel;
        return Math.min(1, t + (increaseContrast ? 0.12 : 0));
    }
    function fallbackOpacity(role) {
        if (reduceTransparency)
            return 1;
        const f = glassRole(role).fallback;
        return Math.min(1, f[0] + (f[1] - f[0]) * glassLevel + (increaseContrast ? 0.05 : 0));
    }

    // ---- shadows (drawn by the client around glass; the glass interior stays clear) ------------
    // blur = Gaussian radius (≈ 2σ), y = offset, opacity at light theme (dark × 1.6, capped .6).
    readonly property var shadows: ({
        menu:    { blur: 24, y: 8, opacity: 0.22 },
        panel:   { blur: 40, y: 14, opacity: 0.20 },
        control: { blur: 8, y: 2, opacity: 0.14 },
        knob:    { blur: 6, y: 1, opacity: 0.22 },
        hud:     { blur: 30, y: 10, opacity: 0.18 },
        tooltip: { blur: 12, y: 4, opacity: 0.18 },
        window:  { blur: 48, y: 16, opacity: 0.32 },
        ambient: { blur: 24, y: 3, opacity: 0.30 }      // soft shadow under floating chrome (Dock)
    })
    function shadowOpacity(kind) {
        const s = shadows[kind] || shadows.menu;
        return dark ? Math.min(0.6, s.opacity * 1.6) : s.opacity;
    }

    // ---- motion -----------------------------------------------------------------------------
    // Durations in ms. Reduce Motion: movement/scale become 0 ms, fades stay (cross-fade).
    readonly property var durations: ({
        instant: 0,
        micro: 100,     // hover, press
        short: 150,     // menu/tooltip appear, highlight moves
        medium: 250,    // popovers, panels open
        long: 350,      // large transitions (overview, sheets)
        legibility: 300,// text colour follows the glass (contract §5.3)
        barDim: 400,    // menu bar glass <-> solid
        menuFlash: 70,  // selected item blinks once before a menu closes
        menuFade: 150   // menu fades out after a selection
    })
    function duration(kind, isFade) {
        const d = durations[kind] !== undefined ? durations[kind] : 250;
        return reduceMotion && !isFade ? 0 : d;
    }
    // Cubic Béziers (x1,y1,x2,y2) for Easing.BezierSpline. Springs are approximated by curves with
    // the same settle time; "bouncy" overshoots ~6 %.
    readonly property var curves: ({
        standard: [0.25, 0.1, 0.25, 1.0, 1, 1],    // CAMediaTimingFunction default
        easeOut:  [0.0, 0.0, 0.2, 1.0, 1, 1],      // things appearing
        easeIn:   [0.4, 0.0, 1.0, 1.0, 1, 1],      // things leaving
        easeInOut:[0.42, 0.0, 0.58, 1.0, 1, 1],
        smooth:   [0.2, 0.9, 0.25, 1.0, 1, 1],     // spring, response .5 s, damping 1.0
        snappy:   [0.2, 1.0, 0.3, 1.02, 1, 1],     // spring, response .4 s, damping .9
        bouncy:   [0.3, 1.35, 0.5, 1.0, 1, 1]      // spring, response .5 s, damping .7 (Dock bounce, toggles)
    })
    function curve(kind) {
        return curves[kind] || curves.standard;
    }

    // ---- keyboard shortcut display (menus) -------------------------------------------------------
    // Mac order and glyphs. With keyboard.commandKey = "ctrl" (the key next to the space bar sends
    // Control, set up by the keyboard component) Control shows as ⌘.
    readonly property bool ctrlIsCommand: Settings.get("keyboard.commandKey", "") === "ctrl"
    function shortcutText(chords) {
        if (!chords || chords.length === 0)
            return "";
        const order = ["Control", "Alt", "Shift", "Super"];
        const glyph = { Control: ctrlIsCommand ? "⌘" : "⌃", Alt: "⌥", Shift: "⇧", Super: ctrlIsCommand ? "⌃" : "⌘" };
        const keys = { Return: "↩", Enter: "⌤", Escape: "⎋", BackSpace: "⌫", Delete: "⌦", Tab: "⇥", space: "Space",
                       Left: "←", Right: "→", Up: "↑", Down: "↓", Home: "↖", End: "↘", Prior: "⇞", Next: "⇟",
                       plus: "+", minus: "-", equal: "=", comma: ",", period: ".", slash: "/" };
        return chords.map(function (chord) {
            const mods = chord.filter(function (k) { return order.indexOf(k) >= 0; });
            mods.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); });
            const rest = chord.filter(function (k) { return order.indexOf(k) < 0; }).map(function (k) {
                return keys[k] || (k.length === 1 ? k.toUpperCase() : k);
            });
            return mods.map(function (m) { return glyph[m]; }).join("") + rest.join("");
        }).join(" ");
    }
}
