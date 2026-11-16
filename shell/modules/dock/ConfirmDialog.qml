// SPDX-License-Identifier: GPL-3.0-or-later
// A Mac-style alert (icon, bold title, message, Cancel + action) for "Empty Trash". Overlay
// surface over the whole output (a click outside cancels), exclusive keyboard while open:
// Return runs the action (it is the default button, as on the Mac), Escape cancels.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services
import "common"

PanelWindow {
    id: dialog
    property string title: ""
    property string message: ""
    property string actionText: ""
    property string iconSource: ""
    signal accepted()
    signal rejected()

    WlrLayershell.namespace: "kristall-dock-alert"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"

    property real shown: 0
    Component.onCompleted: { shown = 1; Qt.callLater(() => keys.forceActiveFocus()); }
    Behavior on shown { NumberAnimation { duration: Theme.duration("short", true); easing.type: Easing.OutQuad } }

    GlassSurface {
        id: gs
        key: "dock-alert-" + (dialog.screen ? dialog.screen.name : "")
        layerNamespace: "kristall-dock-alert"
        output: dialog.screen ? dialog.screen.name : ""
    }
    MouseArea {
        anchors.fill: parent
        onPressed: dialog.rejected()
    }
    GlassShape {
        id: panel
        shapeId: "alert"
        surface: gs
        role: "panel"
        width: 280
        height: col.implicitHeight + 2 * Theme.space.xxl
        anchors.horizontalCenter: parent.horizontalCenter
        y: Math.round(parent.height * 0.3)
        glassOpacity: dialog.shown
        opacity: dialog.shown
        scale: 0.96 + 0.04 * dialog.shown
        MouseArea { anchors.fill: parent }     // clicks on the panel stay here
        Column {
            id: col
            anchors.centerIn: parent
            width: parent.width - 2 * Theme.space.xxl
            spacing: Theme.space.m
            AppIcon {
                anchors.horizontalCenter: parent.horizontalCenter
                size: 64
                plain: true
                source: dialog.iconSource
                scheme: panel.scheme
            }
            KText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: dialog.title
                textStyle: "headline"
                scheme: panel.scheme
            }
            KText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                lineHeightMode: Text.ProportionalHeight
                lineHeight: 1.1
                text: dialog.message
                textStyle: "callout"
                scheme: panel.scheme
            }
            Item { width: 1; height: Theme.space.xs }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: Theme.space.m
                KButton {
                    text: Strings.t("common.cancel")
                    scheme: panel.scheme
                    minWidth: 104
                    onClicked: dialog.rejected()
                }
                KButton {
                    text: dialog.actionText
                    variant: "accent"
                    scheme: panel.scheme
                    minWidth: 104
                    onClicked: dialog.accepted()
                }
            }
        }
    }
    Item {
        id: keys
        focus: true
        Keys.onReturnPressed: dialog.accepted()
        Keys.onEnterPressed: dialog.accepted()
        Keys.onEscapePressed: dialog.rejected()
    }
}
