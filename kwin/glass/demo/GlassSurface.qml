// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall glass: declares the glass shapes of one layer-shell window. Put one inside a
// PanelWindow, list its GlassShape items in `shapes`. Geometry is sent in surface-local
// logical pixels (QML window coordinates), re-evaluated whenever the window animates or
// renders, and only sent when it changed.
import QtQuick
import QtQuick.Window

Item {
    id: surface

    required property string key           // unique per shell process
    required property string layerNamespace // WlrLayershell.namespace of the window
    property string output: ""             // screen.name, when the same namespace exists per output
    property list<Item> shapes

    property string _last: ""

    function requestUpdate() {
        Qt.callLater(update, "immediate");
    }

    // sync "commit": the update was computed for a frame this window is about to commit, so the
    // effect applies it together with that frame (content and glass never drift apart).
    // "immediate": a change outside a frame (nothing else may be committed soon).
    function update(sync) {
        const arr = [];
        for (let i = 0; i < shapes.length; ++i) {
            const s = shapes[i];
            if (s && s.visible && s.width > 0 && s.height > 0)
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
        function onLegibility(key, shapeId, scheme, luminance) {
            if (key !== surface.key)
                return;
            for (let i = 0; i < surface.shapes.length; ++i) {
                if (surface.shapes[i].shapeId === shapeId)
                    surface.shapes[i].scheme = scheme;
            }
        }
        function onActiveChanged() { surface._last = ""; surface.update("immediate"); }
    }
}
