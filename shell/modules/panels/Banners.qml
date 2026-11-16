// SPDX-License-Identifier: GPL-3.0-or-later
// Notification banners at the top right of one output: glass cards that slide in from the right
// edge, newest on top, at most three; banners of one app stack into one. A banner stays ~5 s
// (critical ones until handled), the timer pauses while the pointer is on it; a swipe to the right
// or the timeout puts it into Notification Centre, the close button clears it.
// Surface: namespace "kristall-banners", Overlay, input only on the cards, no keyboard (on demand
// while an inline reply is being typed). Exists only while banners are shown.
import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Notifications
import qs.core
import qs.services

PanelWindow {
    id: bannerWindow
    readonly property string screenName: screen ? screen.name : ""
    readonly property int pad: PanelMetrics.shadowPad
    property bool replying: false

    Component.onDestruction: PanelsRegistry.remove("banners:" + bannerWindow.screenName, bannerWindow)
    onScreenNameChanged: PanelsRegistry.add("banners:" + screenName, bannerWindow)
    Item { Component.onCompleted: PanelsRegistry.add("banners:" + bannerWindow.screenName, bannerWindow) }

    WlrLayershell.namespace: "kristall-banners"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: replying ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; right: true }
    implicitWidth: PanelMetrics.cardWidth + PanelMetrics.bannerEdge + pad
    implicitHeight: Math.max(1, Theme.size.bar + PanelMetrics.bannerTop + stack.height + pad)
    color: "transparent"
    mask: Region { item: stack }

    GlassSurface {
        id: glassSurface
        key: "banners-" + bannerWindow.screenName
        layerNamespace: "kristall-banners"
        output: bannerWindow.screenName
    }

    Column {
        id: stack
        x: bannerWindow.pad
        y: Theme.size.bar + PanelMetrics.bannerTop
        width: PanelMetrics.cardWidth
        spacing: PanelMetrics.cardGap
        move: Transition {
            NumberAnimation { properties: "y"; duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") }
        }

        Repeater {
            // ScriptModel keeps each card (and its timer) while the list around it changes
            model: ScriptModel { values: Notifs.banners }
            NotifCard {
                id: bannerCard
                required property var modelData
                required property int index
                entry: modelData
                objectName: "banner:" + modelData.key
                surface: glassSurface
                shapeKey: "banner-" + modelData.key
                stacked: Notifs.stackedBehind(modelData)
                originX: bannerWindow.screen.width - bannerWindow.width
                originY: 0

                // slide in from the right edge, fade out when leaving
                property bool leaving: false
                slideX: PanelMetrics.cardWidth / 3
                opacity: 0
                Component.onCompleted: { slideX = 0; opacity = 1; }
                Behavior on slideX { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
                Behavior on opacity { NumberAnimation { duration: Theme.duration("short", true); easing.type: Easing.InOutQuad } }
                onOpacityChanged: if (leaving && opacity <= 0.01) Notifs.hideBanner(modelData)
                function leave() {
                    if (leaving)
                        return;
                    leaving = true;
                    opacity = 0;
                    if (Theme.duration("short", true) === 0)
                        Notifs.hideBanner(modelData);
                }

                // stays while hovered, while a reply is typed, and for critical notifications
                Timer {
                    id: life
                    interval: bannerCard.modelData.critical ? 0 : bannerCard.modelData.urgency === NotificationUrgency.Low ? PanelMetrics.bannerTimeoutLow
                              : bannerCard.modelData.expireTimeout > 0 ? Math.max(3000, Math.min(30000, bannerCard.modelData.expireTimeout * (bannerCard.modelData.expireTimeout < 100 ? 1000 : 1)))
                              : PanelMetrics.bannerTimeout
                    running: !bannerCard.modelData.critical && !bannerCard.hovered && !bannerCard.replying && !bannerCard.leaving
                    onTriggered: bannerCard.leave()
                }
                Connections {
                    target: Notifs
                    function onBannerUpdated(e) { if (e === bannerCard.modelData) life.restart(); }
                }
                onReplyingChanged: bannerWindow.replying = replying
                onActivated: Notifs.activate(modelData)
                onClosed: Notifs.remove(modelData)
                onSwiped: leave()
                onMenuRequested: PanelsMenus.cardMenu(bannerCard, bannerWindow.screenName)
            }
        }
    }
}
