// SPDX-License-Identifier: GPL-3.0-or-later
// One tile of the Dock, positioned and sized by Dock.qml (magnification): an app (icon, running
// dot, badge, progress, launch/attention bounce), the Apps tile, a minimised window, Downloads,
// the Trash, or the separator. Draws only; input is handled by the Dock.
import QtQuick
import qs.core
import qs.services

Item {
    id: tile
    required property var entry            // DockModel entry
    property real size: 48                 // current (magnified) size
    property real baseSize: 48
    property real renderSize: 48
    property real presence: 1              // 0..1 while appearing / leaving
    property string scheme: Theme.scheme
    property bool pressed: false
    property bool dragging: false          // the dragged item's own slot (drawn elsewhere)
    property var badge: null               // {count, countVisible, progress, progressVisible, urgent}
    property bool trashFull: false
    property string iconSource: ""
    property bool running: false
    property bool bouncing: false
    property real separatorHeight: baseSize * 0.75

    readonly property string kind: entry ? entry.kind : ""
    width: size
    height: size

    // ---- bounce (launch until the first window, attention requests) ---------------------------
    property real lift: 0
    SequentialAnimation {
        id: bounce
        loops: Animation.Infinite
        running: tile.bouncing && Theme.duration("medium") > 0
        NumberAnimation { target: tile; property: "lift"; to: tile.baseSize * 0.45; duration: 300; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("easeOut") }
        NumberAnimation { target: tile; property: "lift"; to: 0; duration: 300; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("easeIn") }
        onRunningChanged: if (!running) settle.restart()
    }
    NumberAnimation { id: settle; target: tile; property: "lift"; to: 0; duration: 150 * tile.lift / Math.max(1, tile.baseSize * 0.45); easing.type: Easing.InQuad }

    Item {
        id: body
        width: tile.width
        height: tile.height
        y: -tile.lift
        visible: !tile.dragging && tile.kind !== "sep"
        opacity: tile.presence
        scale: 0.5 + 0.5 * tile.presence

        // app, Downloads, Trash: an icon (plates for non-conforming app icons)
        AppIcon {
            id: appIcon
            visible: tile.kind === "app" || tile.kind === "downloads" || tile.kind === "trash"
            anchors.fill: parent
            size: tile.size
            renderSize: tile.renderSize
            scheme: tile.scheme
            plain: tile.kind !== "app"
            dimmed: tile.pressed
            source: visible ? tile.iconSource : ""
        }
        // the Apps tile: our own glyph (a plate with a 3×3 grid of colour tiles)
        AppsGlyph {
            visible: tile.kind === "apps"
            anchors.fill: parent
            size: tile.size
            renderSize: tile.renderSize
            scheme: tile.scheme
            opacity: tile.pressed ? 0.62 : 1
        }
        // a minimised window: a small window card with its app's icon
        Item {
            visible: tile.kind === "window"
            anchors.fill: parent
            opacity: tile.pressed ? 0.62 : 1
            Rectangle {
                id: card
                anchors.centerIn: parent
                width: parent.width * 0.84
                height: parent.height * 0.64
                radius: Math.max(3, parent.width * 0.07)
                color: Theme.color(tile.scheme, "window")
                border.width: 1 / Math.max(1, tile.Window.window ? tile.Window.window.devicePixelRatio : 1)
                border.color: Theme.color(tile.scheme, "border")
                Rectangle {     // title bar strip
                    width: parent.width
                    height: parent.height * 0.18
                    radius: parent.radius
                    color: Theme.color(tile.scheme, "fill")
                }
            }
            AppIcon {
                anchors.centerIn: card
                anchors.verticalCenterOffset: card.height * 0.06
                size: card.height * 0.9
                renderSize: tile.renderSize * 0.6
                scheme: tile.scheme
                source: tile.kind === "window" ? tile.iconSource : ""
            }
        }

        // badge (Unity launcher entry count / urgent)
        Rectangle {
            readonly property bool show: tile.badge !== null && ((tile.badge.countVisible && tile.badge.count > 0) || tile.badge.urgent)
            visible: show && tile.kind === "app"
            x: parent.width * 0.91 - width
            y: parent.height * 0.02
            height: Math.round(Math.max(14, tile.size * 0.36))
            width: Math.max(height, badgeText.implicitWidth + height * 0.5)
            radius: height / 2
            color: Theme.color(tile.scheme, "destructive")
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: tile.badge && tile.badge.countVisible && tile.badge.count > 0 ? (tile.badge.count > 999 ? "999+" : String(tile.badge.count)) : "!"
                color: "#FFFFFF"
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(parent.height * 0.62)
                font.weight: 600
                font.features: { "tnum": 1 }
                renderType: Text.NativeRendering
            }
        }
        // progress (downloads, copies): a capsule bar across the icon's lower part
        Rectangle {
            visible: tile.kind === "app" && tile.badge !== null && tile.badge.progressVisible === true
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height * 0.76
            width: parent.width * 0.7
            height: Math.max(4, parent.height * 0.1)
            radius: height / 2
            color: Qt.rgba(0, 0, 0, 0.35)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.6)
            Rectangle {
                x: 1; y: 1
                height: parent.height - 2
                width: Math.max(height, (parent.width - 2) * Math.max(0, Math.min(1, tile.badge ? tile.badge.progress : 0)))
                radius: height / 2
                color: Theme.accentFor(tile.scheme)
            }
        }
    }

    // separator between apps and the right-hand section
    Rectangle {
        visible: tile.kind === "sep"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: (tile.baseSize - tile.separatorHeight) / 2
        width: 1 / Math.max(1, tile.Window.window ? tile.Window.window.devicePixelRatio : 1) * 2
        height: tile.separatorHeight
        color: Theme.color(tile.scheme, "separator")
        opacity: tile.presence
    }
}
