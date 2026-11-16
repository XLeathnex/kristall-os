// SPDX-License-Identifier: GPL-3.0-or-later
// Control Center on one output (macOS 26/27 arrangement): a glass panel under the menu bar's
// Control Center button that grows out of the button, with rounded module platters and thick
// capsule sliders. A module's name opens its expanded view in the same panel, which morphs to
// the new size. Closes on Escape (in an expanded view: back first), a click outside, another
// shell popover or menu opening, and the toggle request.
// Surface: namespace "kristall-cc", Overlay, full output (the transparent rest catches the click
// outside), keyboard exclusive while open (the Wi-Fi password field needs it).
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services

PanelWindow {
    id: ccWindow

    property bool open: false
    property var anchorRect: null
    signal finished()
    signal closeRequested()

    readonly property string screenName: screen ? screen.name : ""
    property string page: "main"
    property var passwordNetwork: null
    readonly property string scheme: panel.scheme

    Component.onDestruction: PanelsRegistry.remove("cc:" + ccWindow.screenName, ccWindow)
    onScreenNameChanged: PanelsRegistry.add("cc:" + screenName, ccWindow)
    Item { Component.onCompleted: PanelsRegistry.add("cc:" + ccWindow.screenName, ccWindow) }

    WlrLayershell.namespace: "kristall-cc"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"

    // ---- open / close: the glass grows out of the button (t: 0 → 1), content fades in ------------
    property real t: 0
    property real fade: 0
    Behavior on t { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
    Behavior on fade { NumberAnimation { duration: Theme.duration("short", true); easing.type: Easing.InOutQuad } }
    Component.onCompleted: _apply()
    onOpenChanged: _apply()
    function _apply() {
        if (open) {
            page = "main";
            t = 1;
            fade = 1;
            Qt.callLater(() => keys.forceActiveFocus());
        } else {
            t = 0;
            fade = 0;
            Hw.wifiScanning = false;
        }
    }
    onTChanged: _maybeDone()
    onFadeChanged: _maybeDone()
    function _maybeDone() {
        if (!open && t <= 0.001 && fade <= 0.001)
            finished();
    }

    function lerp(a, b, k) { return a + (b - a) * k; }
    readonly property real contentHeight: (page === "main" ? mainPage.implicitHeight : (detail.item ? detail.item.implicitHeight : 100)) + 2 * PanelMetrics.ccPadding
    property real animatedHeight: contentHeight
    Behavior on animatedHeight { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
    readonly property rect target: Qt.rect(width - PanelMetrics.ccEdge - PanelMetrics.ccWidth, Theme.size.bar + PanelMetrics.ccTop, PanelMetrics.ccWidth, animatedHeight)
    // where it grows from: the button's rectangle when the bar sends it, else the top right corner
    readonly property rect origin: anchorRect ? Qt.rect(anchorRect.x, anchorRect.y, anchorRect.w, anchorRect.h)
                                              : Qt.rect(width - PanelMetrics.ccEdge - 120, 2, 28, Theme.size.bar - 4)

    function back() {
        if (page === "password")
            page = "wifi";
        else
            page = "main";
        Qt.callLater(() => keys.forceActiveFocus());
    }
    function openPage(p) {
        page = p;
        Qt.callLater(() => keys.forceActiveFocus());
    }

    GlassSurface {
        id: glassSurface
        key: "cc-" + ccWindow.screenName
        layerNamespace: "kristall-cc"
        output: ccWindow.screenName
    }

    // the click outside closes (and is not passed on)
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onPressed: ccWindow.closeRequested()
    }

    GlassShape {
        id: panel
        shapeId: "panel"
        surface: glassSurface
        role: "panel"
        x: ccWindow.lerp(ccWindow.origin.x, ccWindow.target.x, ccWindow.t)
        y: ccWindow.lerp(ccWindow.origin.y, ccWindow.target.y, ccWindow.t)
        width: ccWindow.lerp(ccWindow.origin.width, ccWindow.target.width, ccWindow.t)
        height: ccWindow.lerp(ccWindow.origin.height, ccWindow.target.height, ccWindow.t)
        radius: Math.min(Theme.radius.panel, height / 2)
        glassOpacity: ccWindow.fade
        shadow: ccWindow.t > 0.98
        clip: true

        // presses inside the panel never reach the "outside" area
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        }

        FocusScope {
            id: keys
            x: panel.width - PanelMetrics.ccPadding - PanelMetrics.ccInner   // grows leftwards out of the button
            y: PanelMetrics.ccPadding
            width: PanelMetrics.ccInner
            height: ccWindow.target.height - 2 * PanelMetrics.ccPadding
            focus: true
            opacity: Math.max(0, Math.min(1, (ccWindow.t - 0.35) / 0.65)) * ccWindow.fade
            scale: 0.97 + 0.03 * ccWindow.t
            transformOrigin: Item.TopRight
            Keys.onEscapePressed: ev => {
                if (ccWindow.page !== "main")
                    ccWindow.back();
                else
                    ccWindow.closeRequested();
                ev.accepted = true;
            }

            CcMainPage {
                id: mainPage
                width: PanelMetrics.ccInner
                visible: ccWindow.page === "main"
                scheme: ccWindow.scheme
                onOpenPage: p => ccWindow.openPage(p)
                onCloseRequested: ccWindow.closeRequested()
            }

            Loader {
                id: detail
                width: PanelMetrics.ccInner
                active: ccWindow.page !== "main"
                visible: active
                opacity: 0
                property string shownPage: ""
                source: {
                    switch (ccWindow.page) {
                    case "wifi": return "CcWifiPage.qml";
                    case "password": return "CcPasswordPage.qml";
                    case "bluetooth": return "CcBluetoothPage.qml";
                    case "focus": return "CcFocusPage.qml";
                    case "display": return "CcDisplayPage.qml";
                    case "sound": return "CcSoundPage.qml";
                    case "energy": return "CcEnergyPage.qml";
                    case "media": return "CcMediaPage.qml";
                    }
                    return "";
                }
                onLoaded: {
                    item.scheme = Qt.binding(() => ccWindow.scheme);
                    item.cc = ccWindow;
                    opacity = 0;
                    fadeIn.restart();
                }
                NumberAnimation on opacity {
                    id: fadeIn
                    running: false
                    to: 1
                    duration: Theme.duration("short", true)
                    easing.type: Easing.OutQuad
                }
            }
        }
    }
}
