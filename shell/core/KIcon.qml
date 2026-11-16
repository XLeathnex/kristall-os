// SPDX-License-Identifier: GPL-3.0-or-later
// A symbol from the bundled set (Phosphor, MIT; plus our own "kristall/…"), any colour, crisp at
// fractional scales (rendered from SVG at device resolution). name: "wifi-high", "fill/speaker-high",
// "bold/check", "kristall/control-center".
import QtQuick
import qs.services

Image {
    id: icon
    property string name: ""
    property color color: Theme.color(scheme, "label")
    property string scheme: Theme.scheme
    property real size: Theme.size.barIcon

    width: size
    height: size
    sourceSize: Qt.size(size, size)
    source: name !== "" ? Icons.url(name, color.toString()) : ""
    fillMode: Image.PreserveAspectFit
    smooth: true
    asynchronous: false
    cache: true
}
