// SPDX-License-Identifier: GPL-3.0-or-later
// List row: optional leading symbol, title, optional subtitle, optional trailing text and chevron,
// or any trailing item (put it in `trailing`). Hover veil; `selected` = accent highlight with white
// content (inset rounded rect, radius 8). Rows are 32 px (24 compact, 44 with a subtitle).
import QtQuick

Item {
    id: row
    property string title: ""
    property string subtitle: ""
    property string icon: ""
    property string detail: ""
    property bool chevron: false
    property bool selected: false
    property bool compact: false
    property string showState: ""     // gallery: "hover" | "focus"
    property string scheme: Theme.scheme
    default property alias trailing: trailingBox.data
    signal activated()

    readonly property string contentScheme: selected ? "dark" : scheme
    implicitWidth: 280
    implicitHeight: subtitle !== "" ? 44 : compact ? Theme.size.listRowCompact : Theme.size.listRow
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.ListItem
    Accessible.name: title
    Keys.onReturnPressed: activated()
    Keys.onSpacePressed: activated()

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.listRow
        color: row.selected ? Theme.accentFor(row.scheme) : ((hover.hovered || row.showState === "hover") && row.enabled ? Theme.color(row.scheme, "hover") : "transparent")
    }
    KIcon {
        id: lead
        visible: row.icon !== ""
        x: 10
        anchors.verticalCenter: parent.verticalCenter
        size: 16
        name: row.icon
        color: row.selected ? "#FFFFFF" : Theme.accentFor(row.scheme)
    }
    Column {
        anchors.verticalCenter: parent.verticalCenter
        x: row.icon !== "" ? 36 : 10
        width: row.width - x - trailingBox.width - detailText.width - (row.chevron ? 20 : 0) - 14
        KText { width: parent.width; text: row.title; elide: Text.ElideRight; scheme: row.contentScheme }
        KText {
            visible: row.subtitle !== ""
            width: parent.width
            text: row.subtitle
            textStyle: "subheadline"
            level: "secondaryLabel"
            elide: Text.ElideRight
            scheme: row.contentScheme
        }
    }
    KText {
        id: detailText
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: trailingBox.left
        anchors.rightMargin: row.chevron ? 22 : 10
        text: row.detail
        level: "secondaryLabel"
        scheme: row.contentScheme
    }
    KIcon {
        visible: row.chevron
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: parent.right
        anchors.rightMargin: 10
        size: 12
        name: "bold/caret-right"
        color: Theme.color(row.contentScheme, "tertiaryLabel")
    }
    Item {
        id: trailingBox
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: parent.right
        anchors.rightMargin: children.length > 0 ? 8 : 0
        width: childrenRect.width
        height: childrenRect.height
    }
    KFocusRing { targetRadius: Theme.radius.listRow; scheme: row.scheme }
    HoverHandler { id: hover }
    TapHandler { onTapped: { row.forceActiveFocus(Qt.MouseFocusReason); row.activated(); } }
}
