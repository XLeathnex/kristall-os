// SPDX-License-Identifier: GPL-3.0-or-later
// A reply, typeset. Short spoken-style answers (one paragraph, no markup) are set large and calm
// (title2, 17/22); longer or formatted ones in body size with the Markdown subset of Markdown.js.
// Selectable with the pointer and the keyboard, Ctrl+C copies; links (http/https/mailto only) open
// in the default app. Earlier segments of a reply (the model's "what I'm doing" preamble) are set
// in the secondary colour.
import QtQuick
import Quickshell
import qs.core
import "../../core/Markdown.js" as Md

TextEdit {
    id: rt
    property var segments: []               // strings; the last one is the answer
    property bool streaming: false
    property string scheme: Theme.scheme
    property bool large: false               // decided by the caller
    readonly property string plain: segments.join("")
    readonly property var st: Theme.type[large ? "title2" : "body"]

    readOnly: true
    selectByMouse: true
    selectByKeyboard: true
    persistentSelection: false
    activeFocusOnTab: false
    wrapMode: TextEdit.Wrap
    textFormat: TextEdit.RichText
    font.family: large ? Theme.displayFamily : Theme.fontFamily
    font.pixelSize: st.size
    font.letterSpacing: st.tracking
    font.hintingPreference: Font.PreferNoHinting
    renderType: Text.NativeRendering
    color: Theme.color(scheme, "label")
    selectionColor: Qt.alpha(Theme.accentFor(scheme), 0.35)
    selectedTextColor: Theme.color(scheme, "label")
    Behavior on color { ColorAnimation { duration: Theme.duration("legibility", true) } }

    function _colors() {
        const d = scheme === "dark";
        return {
            color: Theme.color(scheme, "label").toString(),
            secondary: d ? "#A9A9B2" : "#6E6E73",
            link: Theme.accentFor(scheme).toString(),
            codeBg: d ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.06)",
            mono: "monospace",
            size: st.size,
            lineHeight: large ? 128 : 138,
            gap: large ? 6 : 8
        };
    }
    function render() {
        const o = _colors();
        const n = segments.length;
        let html = "";
        for (let i = 0; i < n; ++i) {
            const seg = segments[i];
            if (!seg || !seg.trim())
                continue;
            const last = i === n - 1;
            let h = Md.toHtml(seg.trim(), o, streaming && last);
            if (!last)
                h = '<div style="color:' + o.secondary + '">' + h + "</div>";
            if (html !== "")
                html += '<p style="margin:0;font-size:4px">&nbsp;</p>';
            html += h;
        }
        if (text !== html)
            text = html;
    }
    onSegmentsChanged: Qt.callLater(render)
    onStreamingChanged: Qt.callLater(render)
    onSchemeChanged: Qt.callLater(render)
    onLargeChanged: Qt.callLater(render)
    Component.onCompleted: render()

    onLinkActivated: link => {
        if (/^(https?:|mailto:)/i.test(link))
            Qt.openUrlExternally(link);
    }
    HoverHandler {
        cursorShape: rt.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.IBeamCursor
    }
    Keys.onPressed: ev => {
        if ((ev.modifiers & Qt.ControlModifier) && ev.key === Qt.Key_A) {
            rt.selectAll();
            ev.accepted = true;
        }
    }
}
