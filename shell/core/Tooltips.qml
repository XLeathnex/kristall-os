// SPDX-License-Identifier: GPL-3.0-or-later
// Tooltips: shown by the TooltipHost of an output (a small glass surface that takes no input).
// Use KTooltip inside the control; this is the shared state behind it.
pragma Singleton
import QtQuick
import Quickshell

Singleton {
    id: root
    property var current: null      // {screen, rect, text}
    property real lastHidden: 0

    function show(screen, rect, text) {
        current = { screen: screen, rect: rect, text: text };
    }
    function hide() {
        if (current) {
            current = null;
            lastHidden = Date.now();
        }
    }
    // a tooltip was visible a moment ago: the next one appears without the delay (like macOS)
    function warm() {
        return current !== null || Date.now() - lastHidden < 600;
    }
}
