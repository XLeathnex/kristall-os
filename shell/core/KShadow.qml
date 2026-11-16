// SPDX-License-Identifier: GPL-3.0-or-later
// Soft shadow around a rounded shape, from the pre-rendered nine-patches in assets/
// (tools/gen-shadows.py; the shape's interior is cut out so glass stays clear).
// Available: menu 12, panel 26/16, tooltip 8, hud 22, control 11/14/18, knob 10/12,
// ambient 12/16/20/24/28/32/40/48 (any radius: the nearest asset is used — the shadow is soft enough).
import QtQuick

BorderImage {
    id: sh
    property string kind: "menu"
    property Item target: parent
    property real radius: 12
    readonly property var recipe: Theme.shadows[kind] || Theme.shadows.menu
    readonly property int margin: Math.ceil(recipe.blur * 1.25) + Math.abs(recipe.y)
    readonly property var available: ({ menu: [12], panel: [26, 16], tooltip: [8], hud: [22], control: [11, 14, 18], knob: [10, 12],
                                        ambient: [12, 16, 20, 24, 28, 32, 40, 48] })
    readonly property bool nearest: kind === "ambient"
    readonly property int r: {
        const want = Math.round(radius);
        if (!nearest)
            return want;
        let best = -1;
        for (const a of available[kind])
            if (best < 0 || Math.abs(a - want) < Math.abs(best - want))
                best = a;
        return best;
    }
    readonly property bool exists: (available[kind] || []).indexOf(r) >= 0

    visible: exists
    source: exists ? Qt.resolvedUrl("assets/shadow-" + kind + "-" + r + ".png") : ""
    x: target ? (target === parent ? 0 : target.x) - margin : 0
    y: target ? (target === parent ? 0 : target.y) - margin : 0
    width: target ? target.width + 2 * margin : 0
    height: target ? target.height + 2 * margin : 0
    border { left: margin + r; right: margin + r; top: margin + r; bottom: margin + r }
    horizontalTileMode: BorderImage.Stretch
    verticalTileMode: BorderImage.Stretch
    smooth: true
    property real strength: 1
    // the asset is black at full alpha; the recipe's opacity per theme
    opacity: Theme.shadowOpacity(kind) * strength
    z: -1
}
