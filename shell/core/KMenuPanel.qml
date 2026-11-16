// SPDX-License-Identifier: GPL-3.0-or-later
// One level of a glass menu: resolves its source (static entries, a DBusMenu node, or a
// Quickshell menu handle for tray items) into rows and draws them on a "menu" glass shape.
import QtQuick
import Quickshell
import qs.services

Item {
    id: menuPanel
    required property var src
    required property int level
    property var host
    property GlassSurface surface
    property int currentIndex: -1
    property int flashIndex: -1
    property bool flashOff: false
    property bool wantFirst: false       // opened from the keyboard: select the first item once loaded

    onEntriesChanged: if (wantFirst) selectFirst()
    function selectFirst() {
        if (currentIndex < 0)
            step(1);
        if (currentIndex >= 0)
            wantFirst = false;
        else
            wantFirst = true;
    }

    readonly property string scheme: shape.scheme

    // ---- source -> entries ----------------------------------------------------------------------
    QsMenuOpener {
        id: opener
        menu: menuPanel.src && menuPanel.src.kind === "qs" ? menuPanel.src.handle : null
    }
    function _fromDbus(key, node) {
        if (!node)
            return [];
        const out = [];
        for (const c of node.children || []) {
            if (c.type === "separator") {
                out.push({ type: "separator" });
                continue;
            }
            const id = c.id;
            out.push({
                label: c.label, enabled: c.enabled !== false, toggle: c.toggle || "", checked: !!c.checked,
                shortcut: Theme.shortcutText(c.shortcut),
                sub: c.children ? { kind: "dbus", key: key, item: id } : null,
                action: function () { AppMenus.activate(key, id); }
            });
        }
        return out;
    }
    function _fromQs(list) {
        const out = [];
        for (const e of list) {
            if (e.isSeparator) {
                out.push({ type: "separator" });
                continue;
            }
            out.push({
                label: e.text, enabled: e.enabled,
                toggle: e.buttonType === QsMenuButtonType.CheckBox ? "checkmark" : e.buttonType === QsMenuButtonType.RadioButton ? "radio" : "",
                checked: e.checkState === Qt.Checked,
                sub: e.hasChildren ? { kind: "qs", handle: e } : null,
                action: function () { e.triggered(); }
            });
        }
        return out;
    }
    readonly property var entries: {
        const s = menuPanel.src;
        if (!s)
            return [];
        let list;
        if (s.kind === "dbus") {
            AppMenus.revision;
            list = _fromDbus(s.key, AppMenus.node(s.key, s.item));
        } else if (s.kind === "qs") {
            list = opener.children ? _fromQs(opener.children.values) : [];
        } else {
            list = (s.entries || []).filter(e => e && e.visible !== false);
        }
        // no leading/trailing/double separators
        const clean = [];
        for (const e of list) {
            if ((e.type === "separator") && (clean.length === 0 || clean[clean.length - 1].type === "separator"))
                continue;
            clean.push(e);
        }
        while (clean.length && clean[clean.length - 1].type === "separator")
            clean.pop();
        if (clean.length === 0)
            clean.push({ label: Strings.t("menu.empty"), enabled: false });
        return clean;
    }

    function selectable(i) {
        const e = entries[i];
        return e && (e.type || "item") === "item" && e.enabled !== false;
    }
    function step(dir) {
        const n = entries.length;
        let i = currentIndex;
        for (let k = 0; k < n; ++k) {
            i = i < 0 ? (dir > 0 ? 0 : n - 1) : (i + dir + n) % n;
            if (selectable(i)) {
                currentIndex = i;
                return;
            }
        }
    }
    function rowHovered(i) {
        if (host)
            host.hoverRow(level, i);
    }
    function rowActivated(i, keyboard) {
        if (host)
            host.activateRow(level, i, keyboard);
    }
    function rowRect(i) {
        const r = rows.itemAt(i);
        return r ? { y: menuPanel.y + column.y + r.y, h: r.height } : { y: menuPanel.y, h: 0 };
    }
    function rowAt(px, py) {     // host coordinates -> row index or -1
        const lx = px - menuPanel.x, ly = py - menuPanel.y - column.y;
        if (lx < 0 || lx > menuPanel.width || ly < 0 || ly > column.height)
            return -1;
        for (let i = 0; i < rows.count; ++i) {
            const r = rows.itemAt(i);
            if (r && ly >= r.y && ly < r.y + r.height)
                return i;
        }
        return -1;
    }

    implicitWidth: {
        let w = 0;
        for (let i = 0; i < rows.count; ++i)
            if (rows.itemAt(i))
                w = Math.max(w, rows.itemAt(i).implicitWidth);
        return Math.ceil(Math.min(Theme.size.menuMaxWidth, Math.max(Theme.size.menuMinWidth, host && level === 0 ? host.minWidth : 0, w)));
    }
    implicitHeight: column.height + 2 * Theme.size.menuPaddingV
    width: implicitWidth
    height: implicitHeight

    GlassShape {
        id: shape
        anchors.fill: parent
        shapeId: "level" + menuPanel.level
        surface: menuPanel.surface
        role: "menu"
    }
    Column {
        id: column
        y: Theme.size.menuPaddingV
        width: menuPanel.width
        Repeater {
            id: rows
            model: menuPanel.entries
            KMenuRow {
                required property var modelData
                entry: modelData
                panel: menuPanel
                scheme: menuPanel.scheme
                selected: index === menuPanel.currentIndex
                flashOff: menuPanel.flashOff && index === menuPanel.flashIndex
            }
        }
    }
}
