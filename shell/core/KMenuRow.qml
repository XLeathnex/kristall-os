// SPDX-License-Identifier: GPL-3.0-or-later
// One row of a glass menu (used by KMenuPanel). Layout per design.md §9: check column 8–22,
// label from 22, shortcut right-aligned in the secondary colour, chevron for submenus,
// highlight inset 5 with radius 7 (concentric with the 12-px menu).
import QtQuick

Item {
    id: row
    required property var entry
    required property int index
    property var panel
    property string scheme: "light"
    property bool selected: false
    property bool flashOff: false

    readonly property string type: entry.type || "item"
    readonly property bool selectable: type === "item" && entry.enabled !== false
    readonly property bool hasSub: !!(entry.sub || entry.children)
    readonly property bool lit: selected && selectable && !flashOff
    readonly property string contentScheme: lit ? "dark" : scheme
    readonly property string shortcut: entry.shortcut || ""

    width: parent ? parent.width : 0
    height: type === "separator" ? Theme.size.menuSeparator : type === "custom" ? (entry.height || Theme.size.menuItem) : type === "header" ? 22 : Theme.size.menuItem
    implicitWidth: type === "custom" ? (entry.width || 0) : type === "separator" ? 0
        : Theme.size.menuTextLeft + label.implicitWidth + (shortcut !== "" ? Theme.size.menuShortcutGap + sc.implicitWidth : 0) + (hasSub ? 24 : 0) + Theme.size.menuTextRight

    Accessible.role: type === "separator" ? Accessible.Separator : Accessible.MenuItem
    Accessible.name: entry.label || ""
    Accessible.checkable: !!entry.toggle
    Accessible.checked: !!entry.checked

    Rectangle {
        visible: row.lit
        x: Theme.size.menuInset
        width: row.width - 2 * Theme.size.menuInset
        height: row.height
        radius: Theme.radius.menuItem
        color: Theme.accentFor(row.scheme)
    }
    KSeparator {
        visible: row.type === "separator"
        x: 12
        width: row.width - 24
        anchors.verticalCenter: parent.verticalCenter
        scheme: row.scheme
    }
    KText {
        visible: row.type === "header"
        x: 14
        anchors.verticalCenter: parent.verticalCenter
        text: row.entry.label || ""
        textStyle: "subheadline"
        emphasized: true
        level: "secondaryLabel"
        scheme: row.scheme
    }
    KIcon {
        visible: row.type === "item" && !!row.entry.toggle && row.entry.checked === true
        x: 8
        anchors.verticalCenter: parent.verticalCenter
        size: 11
        name: row.entry.toggle === "radio" ? "fill/circle" : "bold/check"
        scale: row.entry.toggle === "radio" ? 0.55 : 1
        color: Theme.color(row.contentScheme, row.selectable ? "label" : "disabledLabel")
    }
    KText {
        id: label
        visible: row.type === "item"
        x: Theme.size.menuTextLeft
        width: Math.max(0, row.width - x - (row.shortcut !== "" ? sc.implicitWidth + Theme.size.menuShortcutGap : 0) - (row.hasSub ? 24 : 0) - Theme.size.menuTextRight)
        anchors.verticalCenter: parent.verticalCenter
        text: row.entry.label || ""
        textStyle: "menu"
        elide: Text.ElideRight
        scheme: row.contentScheme
        level: row.selectable ? "label" : "disabledLabel"
        Behavior on color { enabled: false; ColorAnimation {} }
    }
    KText {
        id: sc
        visible: row.type === "item" && row.shortcut !== ""
        anchors.right: parent.right
        anchors.rightMargin: Theme.size.menuTextRight + (row.hasSub ? 24 : 0)
        anchors.verticalCenter: parent.verticalCenter
        text: row.shortcut
        textStyle: "menu"
        scheme: row.contentScheme
        level: row.lit ? "label" : row.selectable ? "secondaryLabel" : "disabledLabel"
        Behavior on color { enabled: false; ColorAnimation {} }
    }
    KIcon {
        visible: row.type === "item" && row.hasSub
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        size: 10
        name: "bold/caret-right"
        color: Theme.color(row.contentScheme, row.selectable ? "label" : "disabledLabel")
    }
    Loader {
        active: row.type === "custom"
        anchors.fill: parent
        sourceComponent: row.entry.component || null
        property string menuScheme: row.scheme
        function closeMenu() { Menus.close("custom"); }
    }
}
