// SPDX-License-Identifier: GPL-3.0-or-later
// Symbol images, recolourable at any colour without shaders. Symbols are SVG files with
// fill="currentColor": Phosphor (icons/phosphor/<weight>/<name>.svg, MIT) and our own
// (icons/kristall/<name>.svg). Each file is read once; url(name, color) returns a data: URL
// that Image renders (and caches) at device resolution.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    property var _svg: ({})            // "weight/name" -> svg text ("" while loading, null missing)
    property var _wanted: []
    property int revision: 0
    property var _pending: []

    function _flushWanted() {
        if (_pending.length === 0)
            return;
        const add = _pending;
        _pending = [];
        _wanted = _wanted.concat(add);
    }

    // name: "wifi-high" (Phosphor regular), "fill/wifi-high", "bold/x", "kristall/mark"
    function _file(name) {
        if (name.startsWith("kristall/"))
            return Quickshell.shellDir + "/icons/" + name + ".svg";
        const i = name.indexOf("/");
        const weight = i > 0 ? name.substring(0, i) : "regular";
        const base = i > 0 ? name.substring(i + 1) : name;
        return Quickshell.shellDir + "/icons/phosphor/" + weight + "/" + base + ".svg";
    }

    function url(name, color) {
        revision;
        const svg = _svg[name];
        if (svg === undefined) {
            _svg[name] = "";
            _pending.push(name);
            Qt.callLater(_flushWanted);
            return "";
        }
        if (!svg)
            return "";
        const c = (typeof color === "string") ? color : String(color);
        const hex = c.length === 9 ? "#" + c.substring(3) : c;   // #AARRGGBB -> #RRGGBB
        const alpha = c.length === 9 ? parseInt(c.substring(1, 3), 16) / 255 : 1;
        const body = svg.replace(/currentColor/g, hex).replace("<svg ", '<svg fill-opacity="' + alpha.toFixed(3) + '" ');
        return "data:image/svg+xml;utf8," + encodeURIComponent(body);
    }

    Variants {
        model: root._wanted
        delegate: FileView {
            required property string modelData
            path: root._file(modelData)
            printErrors: false
            onLoaded: {
                root._svg[modelData] = text();
                root.revision++;
            }
            onLoadFailed: {
                console.warn("icons: missing symbol", modelData);
                root._svg[modelData] = null;
                root.revision++;
            }
        }
    }
}
