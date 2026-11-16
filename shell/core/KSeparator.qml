// SPDX-License-Identifier: GPL-3.0-or-later
// A one-device-pixel separator line (horizontal by default) in the separator colour.
import QtQuick

Rectangle {
    property string scheme: Theme.scheme
    property bool vertical: false
    readonly property real px: 1 / Math.max(1, Window.window ? Window.window.devicePixelRatio : 1)
    implicitWidth: vertical ? px : 100
    implicitHeight: vertical ? 100 : px
    width: vertical ? px : implicitWidth
    height: vertical ? implicitHeight : px
    color: Theme.color(scheme, "separator")
}
