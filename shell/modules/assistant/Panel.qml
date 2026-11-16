// SPDX-License-Identifier: GPL-3.0-or-later
// The assistant panel on one output: a glass capsule under the menu bar at the right (where a Mac
// owner finds the assistant and notifications) that grows — the glass shape itself morphs, it
// never pops — from a listening capsule into a conversation:
//   compact   [crystal] Ich höre zu … / the live words            (mic live) (×)
//   expanded  [crystal] earlier turns · the question · the answer, streaming · what it is doing ·
//                       permission questions · calm notices                     (×)
//             [ Frag weiter …                                         ] (mic/stop)
// Two surfaces: the panel (Overlay layer, exclusive keyboard while open, input only on the glass)
// and a transparent click catcher under it (Top layer, full output): a click anywhere else
// dismisses, as with the Mac's assistant and our menus. Both exist only while the panel is open.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services

Scope {
    id: panel
    required property var screen
    required property var ctl                  // the module (Module.qml)
    readonly property var client: ctl.client
    readonly property string screenName: screen ? screen.name : ""
    readonly property bool open: ctl.open && ctl.output === screenName
    property bool closing: false
    readonly property bool mapped: open || closing

    readonly property real wideW: 440
    readonly property real compactH: 52
    readonly property real topY: Theme.size.bar + Theme.space.m
    readonly property real rightM: Theme.space.m
    readonly property real pad: 52                // room for the shadow around the glass
    readonly property real maxH: Math.max(200, Math.min(660, (screen ? screen.height : 800) - topY - 90))
    readonly property string scheme: shape.scheme
    readonly property bool fullscreenHere: Bridge.frontWindow !== null && Bridge.frontWindow.fullscreen === true && Bridge.frontWindow.output === screenName
    // the glass in output coordinates (the light passes under it)
    readonly property rect glassRect: open ? Qt.rect((screen ? screen.width : 0) - win.width + shape.x, shape.y, shape.width, shape.height) : Qt.rect(0, 0, 0, 0)

    // the glass morphs only once the panel is on screen: it opens at its first size, then grows
    property bool settled: false
    Timer {
        id: settle
        interval: 80
        onTriggered: panel.settled = true
    }
    onOpenChanged: {
        settled = false;
        if (open) {
            settle.restart();
            closeAnim.stop();
            closing = false;
            win.contentOpacity = 1;
        } else if (win.visible) {
            closing = true;
            closeAnim.restart();
        }
    }
    SequentialAnimation {
        id: closeAnim
        NumberAnimation { target: win; property: "contentOpacity"; to: 0; duration: Theme.duration("short", true); easing.type: Easing.InQuad }
        ScriptAction { script: panel.closing = false }
    }

    // ---- click catcher (under the panel) ---------------------------------------------------------
    PanelWindow {
        id: catcher
        screen: panel.screen
        visible: panel.open
        color: "transparent"
        WlrLayershell.namespace: "kristall-assistant-catcher"
        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; bottom: true; left: true; right: true }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
            onPressed: panel.ctl.dismiss("outside")
        }
    }

    // ---- the panel surface ------------------------------------------------------------------------
    PanelWindow {
        id: win
        screen: panel.screen
        visible: panel.mapped
        color: "transparent"
        property real contentOpacity: 1
        WlrLayershell.namespace: "kristall-assistant-panel"
        // Top layer, so the assistant's cursor and light (Overlay) stay above the panel even after
        // KWin raises the panel on activation; Overlay only over a full-screen window, which
        // covers the Top layer
        WlrLayershell.layer: panel.fullscreenHere ? WlrLayer.Overlay : WlrLayer.Top
        WlrLayershell.keyboardFocus: panel.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; right: true }
        implicitWidth: panel.wideW + panel.rightM + panel.pad
        // grows at once to the target size, shrinks only after the morph has finished: the surface
        // is resized at most twice per morph, never every frame
        property real winH: panel.compactH
        implicitHeight: Math.ceil(panel.topY + winH + panel.pad)
        function fit() {
            if (body.targetH > winH || !panel.mapped)
                winH = body.targetH;
            else if (Math.abs(shape.height - body.targetH) < 0.5)
                winH = body.targetH;
        }
        mask: Region { item: shape }

        GlassSurface {
            id: gs
            key: "assistant-panel-" + panel.screenName
            layerNamespace: "kristall-assistant-panel"
            output: panel.screenName
        }

        GlassShape {
            id: shape
            shapeId: "panel"
            surface: gs
            role: "panel"
            radius: Math.min(height / 2, Theme.radius.panel)
            glassOpacity: win.contentOpacity
            width: body.targetW
            height: body.targetH
            x: win.width - panel.rightM - width
            y: panel.topY
            onHeightChanged: win.fit()
            Behavior on width { enabled: panel.open && panel.settled && !Theme.reduceMotion; NumberAnimation { duration: 380; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
            Behavior on height { enabled: panel.open && panel.settled && !Theme.reduceMotion; NumberAnimation { duration: 380; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
        }

        PanelBody {
            id: body
            ctl: panel.ctl
            scheme: panel.scheme
            wideW: panel.wideW
            compactH: panel.compactH
            maxH: panel.maxH
            x: shape.x
            y: shape.y
            width: shape.width
            height: shape.height
            opacity: win.contentOpacity
            originX: (panel.screen ? panel.screen.width : 0) - win.width
            focus: true
            onTargetHChanged: win.fit()
        }
    }

    // keyboard focus to the panel when it opens
    Connections {
        target: panel.ctl
        function onFocusRequested() {
            if (panel.open)
                body.takeFocus();
        }
    }
    function bodyItem() { return body; }
}
