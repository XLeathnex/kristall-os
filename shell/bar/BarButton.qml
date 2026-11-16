// SPDX-License-Identifier: GPL-3.0-or-later
// One menu-bar item: a title (text), a symbol or custom content, with the 20-px rounded highlight
// while its menu is open or it is pressed. Items with a menu take part in menu tracking
// (press-and-drag across items, ←/→ between open menus).
import QtQuick
import qs.core
import qs.services

Item {
    id: btn
    property var bar                       // the Bar window (tracker, screen)
    property string owner: ""              // unique per bar, e.g. "title:2", "status:wifi"
    property string text: ""
    property bool bold: false
    property string icon: ""
    property real padding: Theme.size.barTitlePadding
    property var menuSource: null          // function () -> menu source, or null (plain button)
    property bool rightClickMenu: false     // tray items: left click activates, right click opens the menu
    property string menuAlign: "left"
    property real menuMinWidth: 0
    property string scheme: bar ? bar.scheme : Theme.scheme
    property bool active: false            // highlighted by something other than its menu (open panel)
    property string tooltip: ""
    property string accessibleName: text
    default property alias content: custom.data
    signal clicked()
    signal activated(int button)            // a click that did not open a menu

    readonly property string fullOwner: (bar ? bar.screenName : "") + "/" + owner
    readonly property bool menuOpen: Menus.isOpen(fullOwner)
    readonly property bool hasMenu: menuSource !== null
    readonly property bool trackable: hasMenu && visible && width > 0 && (bar ? bar.isVisibleInBar(btn) : true)

    implicitHeight: Theme.size.bar
    implicitWidth: (text !== "" ? label.implicitWidth : icon !== "" ? glyph.width : custom.childrenRect.width) + 2 * padding
    Accessible.role: hasMenu ? Accessible.MenuItem : Accessible.Button
    Accessible.name: accessibleName

    function openMenu(keyboard) {
        if (!hasMenu || !bar)
            return;
        Tooltips.hide();
        const r = Menus.itemRect(btn, 0, 0);
        Menus.open({
            screen: bar.screenName,
            rect: { x: r.x, y: 0, w: r.w, h: Theme.size.bar },
            source: menuSource(),
            owner: fullOwner,
            keyboard: keyboard,
            tracker: bar.tracker,
            align: menuAlign,
            minWidth: menuMinWidth,
            gap: 3
        });
    }

    Component.onCompleted: if (bar) bar.registerButton(btn)
    Component.onDestruction: if (bar) bar.unregisterButton(btn)

    Rectangle {
        anchors.centerIn: parent
        width: parent.width
        height: Theme.size.barItemHeight
        radius: Theme.radius.barItem
        color: Theme.color(btn.scheme, "barHighlight")
        visible: btn.menuOpen || btn.active || mouse.pressed
    }
    KText {
        id: label
        visible: btn.text !== ""
        anchors.centerIn: parent
        text: btn.text
        textStyle: "menuBar"
        emphasized: btn.bold
        scheme: btn.scheme
        tabular: btn.owner === "status:clock"
    }
    KIcon {
        id: glyph
        visible: btn.icon !== ""
        anchors.centerIn: parent
        name: btn.icon
        size: Theme.size.barIcon
        scheme: btn.scheme
        color: Theme.color(btn.scheme, "label")
    }
    Item {
        id: custom
        anchors.centerIn: parent
        width: childrenRect.width
        height: childrenRect.height
    }
    KTooltip { text: btn.tooltip; visible: !btn.menuOpen }

    MouseArea {
        id: mouse
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        property bool menuPress: false
        onPressed: mouse => {
            menuPress = btn.hasMenu && (!btn.rightClickMenu || mouse.button === Qt.RightButton);
            if (menuPress) {
                if (btn.menuOpen)
                    Menus.close("toggle");
                else
                    btn.openMenu(false);
            }
        }
        onPositionChanged: mouse => {
            if (!pressed || !menuPress || !btn.bar)
                return;
            const p = mapToItem(null, mouse.x, mouse.y);
            Menus.dragMove(btn.bar.screenName, p.x, p.y);
        }
        onReleased: mouse => {
            if (menuPress && btn.bar) {
                const p = mapToItem(null, mouse.x, mouse.y);
                Menus.dragRelease(btn.bar.screenName, p.x, p.y);
            } else if (containsMouse) {
                btn.activated(mouse.button);
                if (mouse.button === Qt.LeftButton)
                    btn.clicked();
            }
        }
    }
}
