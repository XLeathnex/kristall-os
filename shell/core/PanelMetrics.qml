// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell


// Layout numbers of Control Center, notifications and the HUD that docs/contracts/design.md does
// not have yet. Everything else comes from Theme. These belong in Theme.qml/design.md §4 once
// shell-core takes them over (listed in README.md). All logical pixels; estimates from macOS 26/27
// screenshots at known scale, like the bar metrics in design.md §2.
Singleton {
    // Control Center: 4-column grid of 68-px cells with 10-px gaps inside a 10-px panel padding
    // (concentric: panel radius 26 − 10 = tile radius 16) → 322 px wide, like the Mac's ≈ 320 pt.
    readonly property int ccPadding: 10
    readonly property int ccGap: 10
    readonly property int ccCell: 68
    readonly property int ccInner: 4 * ccCell + 3 * ccGap          // 302
    readonly property int ccWidth: ccInner + 2 * ccPadding         // 322
    readonly property int ccHalf: 2 * ccCell + ccGap               // 146
    readonly property int ccTop: 6                                 // gap below the menu bar
    readonly property int ccEdge: 8                                 // gap to the screen's right edge
    readonly property int ccRound: 36                               // round toggle (= controlLarge)
    readonly property int ccListMax: 300                            // tallest list in an expanded module before it scrolls

    // notification banners and Notification Centre (macOS ≈ 344 pt cards, 10-pt margins)
    readonly property int cardWidth: 344
    readonly property int cardPadding: 12
    readonly property int cardIcon: 32
    readonly property int cardImage: 40
    readonly property int cardGap: 8
    readonly property int stackPeek: 8                              // how far a grouped card shows below the one in front
    readonly property int bannerTop: 6
    readonly property int bannerEdge: 10
    readonly property int bannerMax: 3                              // banners on screen at once
    readonly property int bannerTimeout: 5000                       // ms, normal urgency (Mac ≈ 5 s)
    readonly property int bannerTimeoutLow: 3500
    readonly property int widgetSmall: 168                          // square widget (Mac small widget ≈ 170 pt)

    // HUD (macOS 26/27: a small glass module at the top right, under the menu bar)
    readonly property int hudWidth: 300
    readonly property int hudHeight: 72
    readonly property int hudTimeout: 1500                          // ms after the last change
    readonly property int shadowPad: 48                             // room for panel shadows around glass
}
