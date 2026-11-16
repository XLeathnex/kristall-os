// SPDX-License-Identifier: GPL-3.0-or-later
// Measures app icons for IconShapes, one at a time, with one long-lived Canvas. Put exactly one
// in a long-lived window (the Dock hosts it): a Canvas must not be destroyed while it is loading
// an image (Quickshell 0.2.1 / Qt 6.11 abort with "pure virtual method called"), which is what
// per-icon probes inside list delegates did. Idle: nothing runs while the queue is empty.
import QtQuick

Canvas {
    id: probe
    readonly property int n: 48
    property string url: ""
    width: n
    height: n
    opacity: 0
    enabled: false
    renderTarget: Canvas.Image
    renderStrategy: Canvas.Immediate

    readonly property int pending: IconShapes.loaded ? IconShapes.queue.length : 0
    onPendingChanged: if (pending > 0 && url === "") Qt.callLater(next)
    Component.onCompleted: if (pending > 0) Qt.callLater(next)

    function next() {
        if (url !== "")
            return;
        url = IconShapes.take();
        if (url === "")
            return;
        if (isImageLoaded(url))
            requestPaint();
        else
            loadImage(url);
    }
    function finish(info) {
        const u = url;
        IconShapes.set(u, info);
        unloadImage(u);
        url = "";
        Qt.callLater(next);
    }
    onImageLoaded: requestPaint()
    onPaint: {
        if (url === "")
            return;
        if (isImageError(url)) {
            finish({ k: "plate", b: [0, 0, 1, 1] });
            return;
        }
        if (!isImageLoaded(url))
            return;
        const ctx = getContext("2d");
        ctx.clearRect(0, 0, n, n);
        ctx.drawImage(url, 0, 0, n, n);
        const d = ctx.getImageData(0, 0, n, n).data;
        const a = new Array(n * n);
        for (let i = 0; i < n * n; ++i)
            a[i] = d[i * 4 + 3];
        finish(IconShapes.classify(a, n));
    }
}
