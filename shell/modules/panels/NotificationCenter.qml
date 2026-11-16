// SPDX-License-Identifier: GPL-3.0-or-later
// Notification Centre on one output (opened from the clock): slides in from the right edge. The
// history grouped by app, newest first; a group shows as a stack and opens on click, with "Show
// Less" and clear; "Clear All" on top. Below, widgets that need no account or network: today's
// month, battery, now playing. Closes on Escape, a click outside, another popover.
// Surface: namespace "kristall-notifications", Overlay, full output, keyboard exclusive while open
// (inline replies).
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services

PanelWindow {
    id: ncWindow

    property bool open: false
    signal finished()
    signal closeRequested()
    readonly property string screenName: screen ? screen.name : ""
    property var expanded: ({})          // appKey -> true
    property int layoutRevision: 0

    Component.onDestruction: PanelsRegistry.remove("nc:" + ncWindow.screenName, ncWindow)
    onScreenNameChanged: PanelsRegistry.add("nc:" + screenName, ncWindow)
    Item { Component.onCompleted: PanelsRegistry.add("nc:" + ncWindow.screenName, ncWindow) }

    WlrLayershell.namespace: "kristall-notifications"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"

    property real t: 0
    property real fade: 0
    Behavior on t { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
    Behavior on fade { NumberAnimation { duration: Theme.duration("short", true); easing.type: Easing.InOutQuad } }
    Component.onCompleted: _apply()
    onOpenChanged: _apply()
    function _apply() {
        t = open ? 1 : 0;
        fade = open ? 1 : 0;
        if (open)
            Qt.callLater(() => keys.forceActiveFocus());
    }
    onTChanged: _maybeDone()
    onFadeChanged: _maybeDone()
    function _maybeDone() {
        if (!open && t <= 0.001 && fade <= 0.001)
            finished();
    }

    function toggleGroup(key) {
        const e = Object.assign({}, expanded);
        if (e[key])
            delete e[key];
        else
            e[key] = true;
        expanded = e;
        Qt.callLater(() => ncWindow.layoutRevision++);
    }

    GlassSurface {
        id: glassSurface
        key: "notifications-" + ncWindow.screenName
        layerNamespace: "kristall-notifications"
        output: ncWindow.screenName
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onPressed: ncWindow.closeRequested()
    }

    FocusScope {
        id: keys
        focus: true
        readonly property real offset: (1 - ncWindow.t) * (PanelMetrics.cardWidth + PanelMetrics.bannerEdge + 20)
        x: ncWindow.width - PanelMetrics.cardWidth - PanelMetrics.bannerEdge + offset
        y: Theme.size.bar + PanelMetrics.bannerTop
        width: PanelMetrics.cardWidth
        height: ncWindow.height - y - PanelMetrics.bannerTop
        Keys.onEscapePressed: ev => { ncWindow.closeRequested(); ev.accepted = true; }

        // clicks between the cards close too, like outside
        KScrollArea {
            id: scroll
            anchors.fill: parent
            contentHeight: list.implicitHeight
            scheme: Theme.scheme
            Connections {
                target: scroll.flickable
                function onContentYChanged() { ncWindow.layoutRevision++; }
                function onHeightChanged() { ncWindow.layoutRevision++; }
            }

            Column {
                id: list
                width: PanelMetrics.cardWidth
                spacing: PanelMetrics.cardGap
                onImplicitHeightChanged: Qt.callLater(() => ncWindow.layoutRevision++)
                move: Transition {
                    NumberAnimation { properties: "y"; duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") }
                }

                // ---- "Clear All" -----------------------------------------------------------------
                Item {
                    visible: Notifs.count > 0
                    width: parent.width
                    height: Theme.size.controlSmall
                    NcPill {
                        objectName: "nc.clearAll"
                        anchors.right: parent.right
                        surface: glassSurface
                        shapeId: "clear-all"
                        text: Strings.t("panels.notifications.clearAll")
                        icon: "bold/x"
                        clipItem: scroll
                        layoutRevision: ncWindow.layoutRevision
                        fade: ncWindow.fade
                        onClicked: Notifs.clearAll()
                    }
                }

                // ---- groups ----------------------------------------------------------------------
                Repeater {
                    model: ScriptModel { values: Notifs.groups.map(g => g.key) }
                    Column {
                        id: groupBox
                        required property string modelData           // the group's key
                        readonly property var group: Notifs.group(modelData)
                        readonly property bool isOpen: ncWindow.expanded[modelData] === true && group.entries.length > 1
                        width: PanelMetrics.cardWidth
                        spacing: PanelMetrics.cardGap

                        Item {
                            visible: groupBox.isOpen
                            width: parent.width
                            height: Theme.size.controlSmall
                            NcPill {
                                surface: glassSurface
                                shapeId: "group-name-" + groupBox.modelData
                                text: groupBox.group.name
                                clipItem: scroll
                                layoutRevision: ncWindow.layoutRevision
                                fade: ncWindow.fade
                                onClicked: ncWindow.toggleGroup(groupBox.modelData)
                            }
                            Row {
                                anchors.right: parent.right
                                spacing: 6
                                NcPill {
                                    objectName: "nc.group.less:" + groupBox.modelData
                                    surface: glassSurface
                                    shapeId: "group-less-" + groupBox.modelData
                                    text: Strings.t("panels.notifications.showLess")
                                    clipItem: scroll
                                    layoutRevision: ncWindow.layoutRevision
                                    fade: ncWindow.fade
                                    onClicked: ncWindow.toggleGroup(groupBox.modelData)
                                }
                                NcPill {
                                    objectName: "nc.group.clear:" + groupBox.modelData
                                    surface: glassSurface
                                    shapeId: "group-clear-" + groupBox.modelData
                                    icon: "bold/x"
                                    clipItem: scroll
                                    layoutRevision: ncWindow.layoutRevision
                                    fade: ncWindow.fade
                                    Accessible.name: Strings.t("panels.notifications.clear")
                                    onClicked: Notifs.clearGroup(groupBox.modelData)
                                }
                            }
                        }
                        Repeater {
                            model: ScriptModel { values: groupBox.isOpen ? groupBox.group.entries : groupBox.group.entries.slice(0, 1) }
                            NotifCard {
                                id: ncCard
                                required property var modelData
                                entry: modelData
                                objectName: "nc:" + modelData.key
                                surface: glassSurface
                                shapeKey: "nc-" + modelData.key
                                stacked: groupBox.isOpen ? 0 : Math.min(2, groupBox.group.entries.length - 1)
                                clipItem: scroll
                                layoutRevision: ncWindow.layoutRevision
                                expandedBody: groupBox.isOpen || groupBox.group.entries.length === 1
                                originX: 0
                                originY: 0
                                opacity: ncWindow.fade
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: (modelData.summary || "") + ", " + (modelData.body || "")
                                Keys.onReturnPressed: activated()
                                Keys.onDeletePressed: closed()
                                KFocusRing { targetRadius: Theme.radius.panel; scheme: ncCard.scheme }
                                onActivated: {
                                    if (!groupBox.isOpen && groupBox.group.entries.length > 1)
                                        ncWindow.toggleGroup(groupBox.modelData);
                                    else {
                                        Notifs.activate(modelData);
                                        if (!modelData.resident)
                                            ncWindow.closeRequested();
                                    }
                                }
                                onClosed: {
                                    if (!groupBox.isOpen && groupBox.group.entries.length > 1)
                                        Notifs.clearGroup(groupBox.modelData);
                                    else
                                        Notifs.remove(modelData);
                                }
                                onSwiped: Notifs.remove(modelData)
                                onMenuRequested: PanelsMenus.cardMenu(ncCard, ncWindow.screenName)
                            }
                        }
                    }
                }

                // ---- widgets -------------------------------------------------------------------
                Item { width: 1; height: Notifs.count > 0 ? 6 : 0 }
                Row {
                    spacing: PanelMetrics.cardWidth - 2 * PanelMetrics.widgetSmall
                    CalendarWidget {
                        surface: glassSurface
                        clipItem: scroll
                        layoutRevision: ncWindow.layoutRevision
                        opacity: ncWindow.fade
                    }
                    BatteryWidget {
                        visible: Power.hasBattery
                        surface: glassSurface
                        clipItem: scroll
                        layoutRevision: ncWindow.layoutRevision
                        opacity: ncWindow.fade
                    }
                }
                MediaWidget {
                    visible: Media.available
                    surface: glassSurface
                    clipItem: scroll
                    layoutRevision: ncWindow.layoutRevision
                    opacity: ncWindow.fade
                }
            }
        }
    }
}
