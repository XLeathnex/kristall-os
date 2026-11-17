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
    readonly property var typeStyle: Theme.type[textStyle] || Theme.type.body

    font.family: typeStyle.family
    font.pixelSize: typeStyle.size
    font.weight: emphasized ? typeStyle.emphasized : typeStyle.weight
    font.letterSpacing: typeStyle.tracking
    font.features: tabular ? { "tnum": 1, "calt": 1 } : { "calt": 1 }
    font.hintingPreference: Font.PreferNoHinting
    lineHeightMode: Text.FixedHeight
    lineHeight: typeStyle.line
    verticalAlignment: Text.AlignVCenter
    renderType: Text.NativeRendering
    color: Theme.color(scheme, level)
    Behavior on color {
        ColorAnimation { duration: Theme.duration("legibility", true); easing.type: Easing.InOutQuad }
    }
}
