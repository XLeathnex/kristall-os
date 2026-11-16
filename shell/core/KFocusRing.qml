// SPDX-License-Identifier: GPL-3.0-or-later
// Keyboard focus ring: 3 px accent halo outside the control's shape (macOS draws it outside).
import QtQuick

Rectangle {
    property Item target: parent
    property real targetRadius: 8
    property string scheme: Theme.scheme
    visible: target && (target.activeFocus || target.showState === "focus")
    x: -3; y: -3
    width: target ? target.width + 6 : 0
    height: target ? target.height + 6 : 0
    radius: targetRadius + 3
    color: "transparent"
    border.width: 3
    border.color: Theme.color(scheme, "focusRing")
}
