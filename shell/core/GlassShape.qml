// SPDX-License-Identifier: GPL-3.0-or-later
// One glass shape (docs/contracts/glass.md §4) styled by a material role from the design
// tokens (bar, menu, panel, control, hud, tooltip, media). Adopted from
// kwin/glass/demo/GlassShape.qml. While the glass is drawn this item paints nothing itself
// (except the optional shadow outside the shape); otherwise it paints the mandatory fallback:
// a plain fill in the theme colour (opaque with Reduce Transparency) with a hairline border.
// `scheme` follows the effect's legibility signal; use `textColor`/Theme.color(scheme, …).
import QtQuick
import qs.services

Item {
    id: shape

    required property string shapeId
    property GlassSurface surface
    property string role: "panel"
    readonly property var material: Theme.glassRole(role)

    property string kind: material.kind
    property real radius: kind === "capsule" ? Math.min(width, height) / 2 : material.radius
    property real smoothing: material.smoothing
    property string variant: material.variant
    property color tint: "transparent"     // transparent = theme tint
    property real tintAmount: Theme.glassTint(role)   // < 0 = the effect's slider mapping
    property real depth: material.depth      // < 0 = default
    property real bezel: material.bezel      // < 0 = default
    property bool pointerActive: false
    property point pointer                  // in this item's coordinates
    property bool pressed: false
    property string group: ""
    property real merge: 12
    property real glassOpacity: 1           // fades the glass (and the fallback) together
    property bool glassEnabled: true        // false: no glass and no fallback (e.g. solid bar)
    property bool shadow: role === "menu" || role === "panel" || role === "hud" || role === "tooltip"
    property string shadowKind: role

    // legibility: "light" glass wants dark content, "dark" glass wants light content
    readonly property bool glassDrawn: surface !== null && surface.glassDrawn && !Theme.reduceTransparency
    property string _signalled: ""
    readonly property string scheme: glassDrawn && _signalled !== "" ? _signalled : Theme.scheme
    readonly property color textColor: Theme.color(scheme, "label")
    readonly property color secondaryTextColor: Theme.color(scheme, "secondaryLabel")

    function toGlass() {
        const p = mapToItem(null, 0, 0);
        const o = { id: shapeId, kind: kind, x: p.x, y: p.y, w: width, h: height, variant: variant, opacity: glassOpacity };
        if (kind === "rect") {
            o.radius = radius;
            o.smoothing = smoothing;
        }
        if (tint.a > 0)
            o.tint = [tint.r, tint.g, tint.b, tint.a];
        if (tintAmount >= 0)
            o.tintAmount = tintAmount;
        if (depth >= 0)
            o.depth = depth;
        if (bezel >= 0)
            o.bezel = Math.min(bezel, Math.min(width, height) / 2);
        if (pointerActive)
            o.pointer = [p.x + pointer.x, p.y + pointer.y];
        if (pressed)
            o.pressed = true;
        if (group !== "") {
            o.group = group;
            o.merge = merge;
        }
        return o;
    }

    function _changed() {
        if (surface)
            surface.requestUpdate();
    }
    onXChanged: _changed()
    onYChanged: _changed()
    onWidthChanged: _changed()
    onHeightChanged: _changed()
    onPointerChanged: _changed()
    onPressedChanged: _changed()
    onVisibleChanged: _changed()
    onGlassOpacityChanged: _changed()
    onGlassEnabledChanged: _changed()
    onTintAmountChanged: _changed()
    onRadiusChanged: _changed()
    onSurfaceChanged: if (surface) surface.register(shape)
    Component.onCompleted: if (surface) surface.register(shape)
    Component.onDestruction: if (surface) surface.unregister(shape)

    Connections {
        target: GlassClient
        function onLegibility(key, shapeId, scheme, luminance) {
            if (shape.surface && key === shape.surface.key && shapeId === shape.shapeId)
                shape._signalled = scheme;
        }
    }

    KShadow {
        visible: shape.shadow && shape.glassEnabled
        kind: shape.shadowKind
        target: shape
        radius: shape.radius
        strength: shape.glassOpacity
    }

    // fallback material when the glass is not drawn
    Rectangle {
        anchors.fill: parent
        visible: shape.glassEnabled && !shape.glassDrawn
        radius: shape.radius
        color: Qt.alpha(Theme.color(Theme.scheme, shape.role === "bar" ? "fallback" : "fallback"), Theme.fallbackOpacity(shape.role) * shape.glassOpacity)
        border.width: shape.role === "bar" ? 0 : 1 / Math.max(1, shape.Window.window ? shape.Window.window.devicePixelRatio : 1)
        border.color: Theme.color(Theme.scheme, "border")
        Rectangle {   // the bar has only a bottom hairline
            visible: shape.role === "bar"
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 1 / Math.max(1, shape.Window.window ? shape.Window.window.devicePixelRatio : 1)
            color: Theme.color(Theme.scheme, "separator")
        }
    }
    // Increase Contrast: a visible edge on glass too
    Rectangle {
        anchors.fill: parent
        visible: shape.glassEnabled && shape.glassDrawn && Theme.increaseContrast && shape.role !== "bar"
        radius: shape.radius
        color: "transparent"
        border.width: 1
        border.color: Theme.color(shape.scheme, "border")
    }
}
