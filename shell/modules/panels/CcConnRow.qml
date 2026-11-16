// SPDX-License-Identifier: GPL-3.0-or-later
// One connectivity row in Control Center: round toggle, name and state. The round button
// switches; the name opens the module's list (as on the Mac).
import QtQuick
import qs.core

Item {
    id: row
    property string icon: ""
    property string title: ""
    property string subtitle: ""
    property bool on: false
    property bool switchable: true
    property string scheme: Theme.scheme
    property string objectBase: ""
    signal toggled()
    signal opened()

    implicitWidth: PanelMetrics.ccHalf - 20
    implicitHeight: PanelMetrics.ccRound + 4

    CcRound {
        id: round
        objectName: row.objectBase
        anchors.verticalCenter: parent.verticalCenter
        icon: row.icon
        on: row.on
        name: row.title
        scheme: row.scheme
        enabled: row.switchable
        opacity: 1
        onClicked: row.toggled()
    }
    Item {
        id: label
        objectName: row.objectBase + ".open"
        x: round.width + 8
        width: row.width - x
        height: parent.height
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: row.title + ", " + row.subtitle
        Keys.onReturnPressed: row.opened()
        Keys.onSpacePressed: row.opened()
        function activate() { row.opened(); }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            KText { width: parent.width; text: row.title; textStyle: "callout"; emphasized: true; elide: Text.ElideRight; scheme: row.scheme }
            KText { width: parent.width; text: row.subtitle; textStyle: "subheadline"; level: "secondaryLabel"; elide: Text.ElideRight; scheme: row.scheme }
        }
        KFocusRing { targetRadius: 6; scheme: row.scheme }
        TapHandler { onTapped: row.opened() }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }
}
