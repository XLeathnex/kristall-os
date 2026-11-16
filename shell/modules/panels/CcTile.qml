// SPDX-License-Identifier: GPL-3.0-or-later
// A Control Center module's platter (macOS 27): its own piece of glass on top of the panel's
// glass — lighter (a white tint, lower lens strength: bezel 8, depth 3), a specular rim and
// hairline (KGlassRim), radius 16 = panel 26 − padding 10 (concentric). `on`: the platter is
// filled with the accent colour (a module that is switched on as a whole, e.g. Focus).
// Shapes go to the Control Center's GlassSurface only when something changes (the panel's
// idle frame count stays 0). Without glass: a quiet fill, as before.
import QtQuick
import qs.core

Item {
    id: tile
    property string scheme: Theme.scheme
    property bool on: false
    property real radius: Theme.radius.panelTile
    default property alias content: inner.data

    // the Control Center provides its surface and content opacity on an ancestor
    property var _surface: null
    property real _fade: 1
    Component.onCompleted: {
        let host = null;
        for (let p = tile.parent; p && !host; p = p.parent)
            if (p.ccGlassSurface !== undefined)
                host = p;
        if (host) {
            _surface = host.ccGlassSurface;
            _fade = Qt.binding(() => host.ccContentOpacity);
        }
    }
    readonly property string _id: "tile-" + Math.floor(Math.random() * 1e9)

    GlassShape {
        id: platter
        anchors.fill: parent
        shapeId: tile._id
        surface: tile._surface
        role: "platter"
        radius: tile.radius
        shadow: false
        tint: tile.on ? Theme.accentFor(tile.scheme) : (tile.scheme === "dark" ? Qt.rgba(0.40, 0.40, 0.43, 1) : Qt.rgba(1, 1, 1, 1))
        tintAmount: tile.on ? 0.85 : Theme.glassTint("platter")
        glassOpacity: tile._fade
        glassEnabled: tile._surface !== null && tile.visible
    }
    Rectangle {          // no glass (effect absent, Reduce Transparency): a quiet fill
        anchors.fill: parent
        visible: !platter.glassDrawn
        radius: tile.radius
        color: tile.on ? Theme.accentFor(tile.scheme) : Theme.color(tile.scheme, "fill")
    }
    KGlassRim {
        radius: tile.radius
        scheme: tile.scheme
        specular: 0.7
        strength: platter.glassDrawn ? 1 : 0.6
    }
    Item {
        id: inner
        anchors.fill: parent
    }
}
