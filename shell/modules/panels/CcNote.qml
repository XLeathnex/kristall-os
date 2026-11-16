// SPDX-License-Identifier: GPL-3.0-or-later
// A calm sentence in an expanded module ("Wi-Fi is turned off.", "No paired devices").
import QtQuick
import qs.core

KText {
    width: PanelMetrics.ccInner
    leftPadding: 10
    rightPadding: 10
    topPadding: 6
    bottomPadding: 6
    textStyle: "callout"
    level: "secondaryLabel"
    wrapMode: Text.WordWrap
    lineHeightMode: Text.ProportionalHeight
    lineHeight: 1.0
}
