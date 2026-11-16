// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell


// Glass popup menus for the whole shell (docs/contracts/shell.md §4, design.md §9).
// One menu (with its submenus) is open at a time, drawn by the MenuHost of its output.
//
//   Menus.open({
//     screen: "eDP-1",                    // output name
//     rect: {x, y, w, h},                 // anchor in the output's logical coordinates
//     source: Menus.list([...entries]),   // or {kind:"dbus", key, item} or {kind:"qs", handle}
//     owner: "dock:firefox",              // who opened it (for toggling / highlighting)
//     keyboard: false,                    // opened from the keyboard: select the first item
//     tracker: null,                      // menu-bar style tracking (see bar/Bar.qml)
//     align: "left"                       // "left" | "right" | "center" edge of rect to align to
//     onClosed: function(reason) {}
//   })
//
// Entry: {label, enabled, toggle: ""|"checkmark"|"radio", checked, shortcut (text), action(),
//         children: [entries] | sub: <source>}, {type: "separator"}, {type: "header", label},
//        {type: "custom", component, height}   (custom rows get `menuScheme` and `closeMenu()`)
Singleton {
    id: root

    property var current: null
    property int serial: 0
    property var hosts: ({})

    signal opened(string owner)
    signal closed(string owner, string reason)

    function list(entries) {
        return { kind: "static", entries: entries };
    }

    function open(p) {
        if (current && current.onClosed && current.owner !== p.owner)
            current.onClosed("replaced");
        serial++;
        current = Object.assign({ rect: { x: 0, y: 0, w: 0, h: 0 }, owner: "", keyboard: false, tracker: null, align: "left" }, p);
        opened(current.owner);
    }

    function close(reason) {
        if (!current)
            return;
        const c = current;
        current = null;
        if (c.onClosed)
            c.onClosed(reason || "closed");
        closed(c.owner, reason || "closed");
    }

    function isOpen(owner) {
        return current !== null && current.owner === owner;
    }

    function registerHost(screen, host) {
        const h = Object.assign({}, hosts);
        h[screen] = host;
        hosts = h;
    }
    function unregisterHost(screen, host) {
        if (hosts[screen] === host) {
            const h = Object.assign({}, hosts);
            delete h[screen];
            hosts = h;
        }
    }

    // pointer events of a press-and-drag that started on another surface (the bar holds the
    // implicit grab), in the output's logical coordinates
    function dragMove(screen, x, y) {
        const h = hosts[screen];
        if (h)
            h.pointerMove(x, y, true);
    }
    function dragRelease(screen, x, y) {
        const h = hosts[screen];
        return h ? h.pointerRelease(x, y) : false;
    }

    // rectangle of `item` in its output's coordinates, given its surface's offset on the output
    function itemRect(item, originX, originY) {
        const p = item.mapToItem(null, 0, 0);
        return { x: p.x + (originX || 0), y: p.y + (originY || 0), w: item.width, h: item.height };
    }
}
