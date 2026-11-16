// SPDX-License-Identifier: GPL-3.0-or-later
// An app icon that sits in the family: icons that are already filled rounded squares are drawn as
// they are, everything else (circles, folders, glyphs, sharp squares) is placed on a rounded
// plate, as macOS 26 does for icons that do not follow its grid. Both are normalised by the
// icon's visible bounding box (measured once, IconShapes), never stretched.
//   size        slot size (logical px); the visible body is 82 % of it, like the Mac's icon grid
//   renderSize  the largest size this icon is ever drawn at (Dock magnification): decoded once at
//               that size, so changing `size` per frame only scales a texture
//   plain       folders and the Trash: normalised, never on a plate
import QtQuick
import qs.core
import "squircle.js" as Squircle

Item {
    id: icon
    property string source: ""
    property real size: 48
    property real renderSize: size
    property string scheme: Theme.scheme
    property bool plain: false
    property bool dimmed: false            // pressed look
    readonly property var info: source !== "" ? IconShapes.get(source) : null
    readonly property bool measured: info !== null
    readonly property bool onPlate: !plain && (!measured || info.k === "plate")
    readonly property real body: size * 0.82
    readonly property real dpr: Window.window ? Window.window.devicePixelRatio : 1

    implicitWidth: size
    implicitHeight: size

    // the glyph's visible box (0..1 of its canvas) and how large that box should appear
    readonly property var box: measured ? info.b : [0.08, 0.08, 0.92, 0.92]
    readonly property real boxSide: Math.max(0.05, Math.max(box[2] - box[0], box[3] - box[1]))
    readonly property real target: onPlate ? size * 0.56 : body
    readonly property real drawn: target / boxSide          // size of the whole image canvas

    Image {
        id: plateImage
        visible: icon.onPlate && icon.source !== ""
        anchors.centerIn: parent
        // the SVG's viewBox has a 2 % margin for the rim and the soft shadow below
        width: icon.body * 104 / 100
        height: width
        source: Squircle.plate(icon.scheme === "dark")
        sourceSize: Qt.size(Math.ceil(icon.renderSize * 0.86), Math.ceil(icon.renderSize * 0.86))
        smooth: true
        opacity: icon.dimmed ? 0.62 : 1
    }
    Image {
        id: glyph
        visible: icon.source !== ""
        x: icon.width / 2 - (icon.box[0] + icon.box[2]) / 2 * width
        y: icon.height / 2 - (icon.box[1] + icon.box[3]) / 2 * height
        width: icon.drawn
        height: icon.drawn
        source: icon.source
        // decode once at the largest size it is drawn at
        sourceSize: Qt.size(Math.ceil(icon.renderSize * (icon.onPlate ? 0.56 : 0.82) / icon.boxSide), Math.ceil(icon.renderSize * (icon.onPlate ? 0.56 : 0.82) / icon.boxSide))
        fillMode: Image.PreserveAspectFit
        smooth: true
        asynchronous: false
        cache: true
        opacity: icon.dimmed ? 0.62 : 1
    }

    // unknown shape: ask for a measurement (IconProbe, hosted by the Dock's window, does it once)
    onSourceChanged: if (source !== "" && !measured) IconShapes.request(source)
    Component.onCompleted: if (source !== "" && !measured) IconShapes.request(source)
}
