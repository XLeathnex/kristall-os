// SPDX-License-Identifier: GPL-3.0-or-later
// Scrolling area with the Mac's overlay scroller: a thin capsule that appears while scrolling
// and fades out 0.8 s later (no timer runs while nothing scrolls).
import QtQuick

Item {
    id: area
    default property alias content: flick.flickableData
    property alias contentHeight: flick.contentHeight
    property alias contentWidth: flick.contentWidth
    property alias flickable: flick
    property string scheme: Theme.scheme
    clip: true

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        boundsBehavior: Flickable.StopAtBounds
        maximumFlickVelocity: 4000
        onContentYChanged: { bar.opacity = 1; hide.restart(); }
    }
    Rectangle {
        id: bar
        readonly property real ratio: flick.height / Math.max(1, flick.contentHeight)
        visible: ratio < 1
        anchors.right: parent.right
        anchors.rightMargin: 3
        width: barHover.hovered ? 9 : 6
        radius: width / 2
        height: Math.max(24, flick.height * ratio)
        y: (flick.height - height) * (flick.contentY / Math.max(1, flick.contentHeight - flick.height))
        color: Theme.color(area.scheme, "tertiaryLabel")
        opacity: 0
        Behavior on opacity { NumberAnimation { duration: Theme.duration("medium", true) } }
        HoverHandler { id: barHover; onHoveredChanged: if (hovered) { bar.opacity = 1; hide.stop(); } else hide.restart() }
    }
    Timer {
        id: hide
        interval: 800
        onTriggered: bar.opacity = 0
    }
}
