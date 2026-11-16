// SPDX-License-Identifier: GPL-3.0-or-later
// A widget's glass platter in Notification Centre (cut to the visible part of the scroll area).
import QtQuick
import qs.core

Item {
    id: w
    property GlassSurface surface: null
    property string shapeId: "widget"
    property Item clipItem: null
    property int layoutRevision: 0
    readonly property string scheme: shape.scheme
    default property alias content: inner.data

    readonly property real visTop: {
        layoutRevision;
        if (!clipItem)
            return 0;
        const scrolled = clipItem.flickable ? clipItem.flickable.contentY : 0;   // dependency
        return Math.max(0, -mapToItem(clipItem, 0, 0).y + scrolled * 0);
    }
    readonly property real visBottom: {
        layoutRevision;
        if (!clipItem)
            return height;
        const scrolled = clipItem.flickable ? clipItem.flickable.contentY : 0;
        return Math.min(height, clipItem.height - mapToItem(clipItem, 0, 0).y + scrolled * 0);
    }

    GlassShape {
        id: shape
        shapeId: w.shapeId
        surface: w.surface
        role: "panel"
        y: w.visTop
        width: w.width
        height: Math.max(0, w.visBottom - w.visTop)
        radius: Math.min(Theme.radius.panel, height / 2)
        glassEnabled: height > 1
        glassOpacity: w.opacity
        shadow: false
    }
    Item {
        id: inner
        anchors.fill: parent
    }
}
