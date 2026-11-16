// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io


// User-visible strings in German and English (docs/contracts/shell.md §6).
// Tables: shell/strings/strings.json and modules/<name>/strings.json, each
// {"en": {"key": "text"}, "de": {...}}. Keys are namespaced by owner ("bar.", "menu.", "dock.").
// t(key, args) replaces {name} placeholders; tn(key, n, args) picks key + ".one"/".other".
Singleton {
    id: root

    // "de" or "en": the system language (LANG/LC_MESSAGES via Qt), override KRISTALL_LANG
    readonly property string lang: {
        const forced = Quickshell.env("KRISTALL_LANG");
        if (forced)
            return forced.substring(0, 2);
        return Qt.locale().name.substring(0, 2) === "de" ? "de" : "en";
    }
    readonly property var locale: Qt.locale(Quickshell.env("KRISTALL_LANG") || Qt.locale().name)

    property var _tables: ({})
    property int revision: 0
    property var files: [Quickshell.shellDir + "/strings/strings.json"]

    function addFile(path) {
        if (files.indexOf(path) < 0)
            files = files.concat([path]);
    }

    function t(key, args) {
        revision; // binding dependency: re-evaluates when tables load
        const tl = _tables[lang];
        let s = tl && tl[key] !== undefined ? tl[key] : undefined;
        if (s === undefined && _tables.en)
            s = _tables.en[key];
        if (s === undefined)
            return key;
        if (args)
            s = s.replace(/\{(\w+)\}/g, (m, k) => args[k] !== undefined ? String(args[k]) : m);
        return s;
    }

    function tn(key, n, args) {
        return t(key + (n === 1 ? ".one" : ".other"), Object.assign({ n: n }, args || {}));
    }

    // display name from a {"de": …, "en": …} object (manifest, assistant, update)
    function pick(obj) {
        if (!obj)
            return "";
        if (typeof obj === "string")
            return obj;
        return obj[lang] || obj.en || "";
    }

    function _merge(text) {
        let doc;
        try {
            doc = JSON.parse(text);
        } catch (e) {
            console.warn("strings: invalid JSON", e);
            return;
        }
        for (const l in doc) {
            if (!_tables[l])
                _tables[l] = {};
            Object.assign(_tables[l], doc[l]);
        }
        revision++;
    }

    Variants {
        model: root.files
        delegate: FileView {
            required property string modelData
            path: modelData
            blockLoading: true      // read at once: a module may use its strings in onCompleted
            printErrors: false
            Component.onCompleted: {
                const t = text();
                if (t)
                    root._merge(t);
            }
        }
    }
}
