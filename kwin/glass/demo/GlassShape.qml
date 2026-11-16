// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall glass: one glass shape. While the effect is active this item draws nothing (the
// compositor draws the glass behind the window); when the effect is absent it draws a plain
// translucent fill so the shell still looks finished.
import QtQuick

Item {
    id: shape

    required property string shapeId
    property GlassSurface surface
    property string kind: "rect"           // "rect" | "capsule"
    property real radius: 16
    property real smoothing: 0.6
    property string variant: "regular"     // "regular" | "clear"
    property color tint: "transparent"     // transparent = theme tint
    property real tintAmount: -1           // < 0 = from the owner's slider
    property real depth: -1                // < 0 = default
    property real bezel: -1                // < 0 = default
    property bool pointerActive: false
    property point pointer                 // in this item's coordinates
    property bool pressed: false
    property string group: ""
    property real merge: 12
    property real glassOpacity: 1

    // legibility: "light" glass wants dark text, "dark" glass wants light text
    property string scheme: GlassClient.theme === "dark" ? "dark" : "light"
    readonly property color textColor: scheme === "light" ? "#1d1d1f" : "#f5f5f7"

    function toGlass() {
        const p = mapToItem(null, 0, 0);
        const o = { id: shapeId, kind: kind, x: p.x, y: p.y, w: width, h: height, variant: variant, opacity: glassOpacity };
        if (kind === "rect") {
            o.radius = radius;
            o.smoothing = smoothing;
        }
        if (tint.a > 0) o.tint = [tint.r, tint.g, tint.b, tint.a];
        if (tintAmount >= 0) o.tintAmount = tintAmount;
        if (depth >= 0) o.depth = depth;
        if (bezel >= 0) o.bezel = bezel;
        if (pointerActive) o.pointer = [p.x + pointer.x, p.y + pointer.y];
        if (pressed) o.pressed = true;
        if (group !== "") { o.group = group; o.merge = merge; }
        return o;
    }

    onXChanged: if (surface) surface.requestUpdate()
    onYChanged: if (surface) surface.requestUpdate()
    onWidthChanged: if (surface) surface.requestUpdate()
    onHeightChanged: if (surface) surface.requestUpdate()
    onPointerChanged: if (surface) surface.requestUpdate()
    onPressedChanged: if (surface) surface.requestUpdate()
    onVisibleChanged: if (surface) surface.requestUpdate()

    // fallback material when there is no glass effect
    Rectangle {
        anchors.fill: parent
        visible: !GlassClient.active
        radius: shape.kind === "capsule" ? Math.min(width, height) / 2 : shape.radius
        color: GlassClient.theme === "dark" ? Qt.rgba(0.12, 0.12, 0.14, 0.82) : Qt.rgba(0.97, 0.97, 0.98, 0.82)
        border.width: 1
        border.color: GlassClient.theme === "dark" ? Qt.rgba(1, 1, 1, 0.12) : Qt.rgba(0, 0, 0, 0.10)
    }
}
