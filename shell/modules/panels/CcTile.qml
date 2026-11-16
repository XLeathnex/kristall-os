// SPDX-License-Identifier: GPL-3.0-or-later
// A Control Center module's platter: a rounded fill on the panel's glass (radius 16 = panel 26 −
// padding 10, concentric). Glass does not refract glass, so modules are fills, not glass shapes.
import QtQuick
import qs.core

Rectangle {
    property string scheme: Theme.scheme
    radius: Theme.radius.panelTile
    color: Theme.color(scheme, "fill")
}
