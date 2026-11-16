// SPDX-License-Identifier: GPL-3.0-or-later
// Declares the glass shapes of one layer-shell window (docs/contracts/glass.md). Adopted from
// kwin/glass/demo/GlassSurface.qml; shell-core owns this copy. Put one inside a PanelWindow;
// GlassShape items register themselves by setting `surface` (or list them in `shapes`).
// Geometry is sent in surface-local logical pixels, re-evaluated whenever the window renders an
// animation frame (sync "commit") or a shape changes (sync "immediate"), and only when it changed.
import QtQuick
import QtQuick.Window
import qs.services

Item {
    id: surface

    required property string key            // unique per shell process, e.g. "bar-eDP-1"
    required property string layerNamespace // WlrLayershell.namespace of the window
    property string output: ""              // screen name when the namespace exists per output
    property list<Item> shapes              // optional static list; GlassShape.surface also registers

    // false when the glass is not drawn for this window: effect absent/not active, or the
    // binding currently matches no window (contract §7). Shapes draw their fallback then.
    readonly property bool glassDrawn: GlassClient.active && (GlassClient.boundWindows[key] || 0) > 0

    property var _registered: []
    property string _last: ""

    function register(shape) {
        if (_registered.indexOf(shape) < 0)
            _registered = _registered.concat([shape]);
        requestUpdate();
    }
    function unregister(shape) {
        const i = _registered.indexOf(shape);
        if (i >= 0) {
            const r = _registered.slice();
            r.splice(i, 1);
            _registered = r;
            requestUpdate();
        }
    }

    function requestUpdate() {
        Qt.callLater(update, "immediate");
    }

    function update(sync) {
        const arr = [];
        const all = [];
        for (let i = 0; i < shapes.length; ++i)
            all.push(shapes[i]);
        for (const s of _registered)
            if (all.indexOf(s) < 0)
                all.push(s);
        for (const s of all) {
            if (s && s.glassEnabled && s.visible && s.width > 0 && s.height > 0 && s.Window.window === surface.Window.window)
                arr.push(s.toGlass());
        }
        const text = JSON.stringify(arr);
        if (text === _last)
            return;
        _last = text;
        GlassClient.setShapes(key, text, sync === "commit" ? "commit" : "immediate");
    }

    Component.onCompleted: {
        const match = { namespace: layerNamespace };
        if (output !== "")
            match.output = output;
        GlassClient.bind(key, match);
        requestUpdate();
    }
    Component.onDestruction: GlassClient.unbind(key)

    // QML animations, anchors and layout changes all end in a frame of this window
    Connections {
        target: surface.Window.window
        function onAfterAnimating() { surface.update("commit"); }
    }
    Connections {
        target: GlassClient
        function onActiveChanged() { surface._last = ""; surface.update("immediate"); }
    }
}
