// SPDX-License-Identifier: GPL-3.0-or-later
// An image cropped to fill and clipped to a rounded rectangle. Drawn with Canvas, which works on
// every Qt Quick backend (shape fills and shader masks do not exist in the software renderer the
// fallback and the tests use); it paints only when the image or the size changes.
import QtQuick

Item {
    id: ri
    property string source: ""
    property real radius: 8
    property int status: Image.Null

    Canvas {
        id: canvas
        anchors.fill: parent
        property string loaded: ""
        function load() {
            ri.status = ri.source === "" ? Image.Null : Image.Loading;
            if (ri.source === "")
                return requestPaint();
            if (isImageLoaded(ri.source)) {
                ri.status = Image.Ready;
                requestPaint();
            } else {
                loadImage(ri.source);
            }
        }
        Component.onCompleted: load()
        Connections {
            target: ri
            function onSourceChanged() { canvas.load(); }
        }
        onImageLoaded: {
            ri.status = isImageError(ri.source) ? Image.Error : Image.Ready;
            requestPaint();
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            if (ri.source === "" || !isImageLoaded(ri.source) || width <= 0 || height <= 0)
                return;
            const r = Math.min(ri.radius, width / 2, height / 2);
            ctx.beginPath();
            ctx.moveTo(r, 0);
            ctx.arcTo(width, 0, width, height, r);
            ctx.arcTo(width, height, 0, height, r);
            ctx.arcTo(0, height, 0, 0, r);
            ctx.arcTo(0, 0, width, 0, r);
            ctx.closePath();
            ctx.clip();
            // cover: crop the longer side
            const img = ctx.createImageData(ri.source);
            const iw = img ? img.width : width, ih = img ? img.height : height;
            const s = Math.max(width / iw, height / ih);
            const dw = iw * s, dh = ih * s;
            ctx.drawImage(ri.source, (width - dw) / 2, (height - dh) / 2, dw, dh);
        }
    }
}
