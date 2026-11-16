// SPDX-License-Identifier: GPL-3.0-or-later
// Text in one of the design system's styles (Theme.type). `scheme` = appearance of the surface
// underneath ("light" → dark text); `level`: label | secondaryLabel | tertiaryLabel | disabledLabel.
// Colour changes from the glass legibility signal cross-fade over 300 ms (glass contract §5.3).
import QtQuick

Text {
    id: t
    property string textStyle: "body"
    property bool emphasized: false
    property string scheme: Theme.scheme
    property string level: "label"
    property bool tabular: false           // tabular figures (clock, percentages)
    readonly property var st: Theme.type[textStyle] || Theme.type.body

    font.family: st.family
    font.pixelSize: st.size
    font.weight: emphasized ? st.emphasized : st.weight
    font.letterSpacing: st.tracking
    font.features: tabular ? { "tnum": 1, "calt": 1 } : { "calt": 1 }
    font.hintingPreference: Font.PreferNoHinting
    lineHeightMode: Text.FixedHeight
    lineHeight: st.line
    verticalAlignment: Text.AlignVCenter
    renderType: Text.NativeRendering
    color: Theme.color(scheme, level)
    Behavior on color {
        ColorAnimation { duration: Theme.duration("legibility", true); easing.type: Easing.InOutQuad }
    }
}
