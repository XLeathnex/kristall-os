// SPDX-License-Identifier: GPL-3.0-or-later
// Base of one Setup Assistant step: what the card around it shows (symbol, title, one sentence)
// and what its buttons do. The default for Continue is to go on; a step overrides `primary()`
// to apply its choice first. Children are the step's own content, laid out by the card.
import QtQuick
import qs.core
import qs.services

Item {
    id: base
    property var ctl: null
    property string scheme: Theme.scheme
    property var surface: null                // the window's GlassSurface (for glass buttons)
    property string icon: ""
    property string title: ""
    property string subtitle: ""
    property string primaryText: Strings.t("setup.continue")
    property bool primaryEnabled: true
    property string secondaryText: ""
    property bool showBack: true
    property string side: "center"            // "left": the card moves aside to show the desktop
    property real cardWidth: 600
    property bool busy: false
    property bool yieldToApps: false          // true: the owner works in another app now (SetupWindow.yielding)
    signal primaryRequested()
    signal secondaryRequested()

    function primary() { ctl.next(); }
    function secondary() { ctl.next(); }
    // the window forwards keys it does not use itself (the keyboard step's "try it")
    function keyPressed(ev) { return false; }

    width: cardWidth - 2 * 40
    implicitHeight: childrenRect.height
}
