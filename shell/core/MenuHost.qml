// SPDX-License-Identifier: GPL-3.0-or-later
// Per-output surface that draws the open menu (see Menus.qml). A full-output layer surface on the
// Overlay layer (namespace "kristall-menu"), mapped only while a menu is open, with exclusive
// keyboard focus; a press outside the menus closes them (and is not passed on, as on the Mac).
// Implements: hover/press-drag-release selection, submenus, keyboard navigation (↑↓ ←→ ↩ ⎋,
// type to select), menu-bar tracking (moving over another title switches menus), the selection
// blink and fade-out, and the submenu "safe triangle": while the pointer moves from a row towards
// its open submenu (inside the triangle between its previous position and the submenu's near
// corners), rows it crosses on the way do not take over; if it rests there for 300 ms, they do.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.services

Scope {
    id: menuHost
    required property var screen
    readonly property string screenName: screen ? screen.name : ""
    readonly property var menu: Menus.current && Menus.current.screen === screenName ? Menus.current : null
    readonly property bool open: menu !== null
    readonly property real minWidth: menu && menu.minWidth ? menu.minWidth : 0

    property var _levels: []           // [{src, anchorLevel, anchorRow}]
    property int activeLevel: 0
    property bool _dragged: false
    property int _openedSerial: -1
    property var _pendingAction: null
    property string _typed: ""

    Component.onCompleted: Menus.registerHost(screenName, menuHost)
    Component.onDestruction: Menus.unregisterHost(screenName, menuHost)

    onMenuChanged: {
        if (menu) {
            closeAnim.stop();
            win.contentOpacity = 1;
            if (_openedSerial !== Menus.serial)
                rebuild();
        } else if (win.visible) {
            closeAnim.restart();
        }
    }

    function rebuild() {
        _openedSerial = Menus.serial;
        levelModel.clear();
        _levels = [{ src: menu.source, anchorLevel: -1, anchorRow: -1 }];
        levelModel.append({ lvl: 0 });
        activeLevel = 0;
        _dragged = false;
        _typed = "";
        _lastPointer = Qt.point(-1, -1);
        safeTimer.stop();
        Qt.callLater(function () {
            const p = panelAt(0);
            if (p && menuHost.menu && menuHost.menu.keyboard)
                p.selectFirst();
            keys.forceActiveFocus();
        });
    }

    function panelAt(i) {
        return levelRepeater.itemAt(i);
    }

    function closeFrom(level) {
        while (levelModel.count > level) {
            const i = levelModel.count - 1;
            const lv = _levels[i];
            if (lv && lv.src && lv.src.kind === "dbus")
                AppMenus.hidden(lv.src.key, lv.src.item);
            levelModel.remove(i);
        }
        _levels = _levels.slice(0, level);
        if (activeLevel >= level)
            activeLevel = Math.max(0, level - 1);
    }

    function entryAt(level, row) {
        const p = panelAt(level);
        return p ? p.entries[row] : null;
    }

    function openSub(level, row, keyboard) {
        const e = entryAt(level, row);
        if (!e || e.enabled === false)
            return;
        const src = e.sub || (e.children ? Menus.list(e.children) : null);
        if (!src)
            return;
        if (levelModel.count > level + 1 && _levels[level + 1].anchorRow === row) {
            if (keyboard) {
                activeLevel = level + 1;
                panelAt(level + 1).selectFirst();
            }
            return;
        }
        closeFrom(level + 1);
        if (src.kind === "dbus")
            AppMenus.aboutToShow(src.key, src.item);
        _levels = _levels.concat([{ src: src, anchorLevel: level, anchorRow: row }]);
        levelModel.append({ lvl: level + 1 });
        if (keyboard) {
            activeLevel = level + 1;
            Qt.callLater(function () { const p = panelAt(level + 1); if (p) p.selectFirst(); });
        }
    }

    function hoverRow(level, row) {
        const p = panelAt(level);
        if (!p || flash.running)
            return;
        activeLevel = level;
        p.currentIndex = p.selectable(row) || (p.entries[row] && (p.entries[row].sub || p.entries[row].children)) ? row : -1;
        // parents keep the row that leads here highlighted
        for (let l = level; l > 0; --l) {
            const parentPanel = panelAt(l - 1);
            if (parentPanel)
                parentPanel.currentIndex = _levels[l].anchorRow;
        }
        subTimer.level = level;
        subTimer.row = row;
        subTimer.restart();
    }

    function activateRow(level, row, keyboard) {
        const e = entryAt(level, row);
        if (!e || (e.type || "item") !== "item" || e.enabled === false)
            return;
        if (e.sub || e.children) {
            openSub(level, row, true);
            return;
        }
        const p = panelAt(level);
        p.currentIndex = row;
        p.flashIndex = row;
        _pendingAction = e.action || null;
        flash.panel = p;
        flash.restart();
    }

    // ---- pointer (own events and drags forwarded from the bar) ------------------------------------
    function hit(x, y) {
        for (let l = levelModel.count - 1; l >= 0; --l) {
            const p = panelAt(l);
            if (!p || !p.placed)    // not placed yet: its x/y are not where it will be drawn
                continue;
            if (x >= p.x && x < p.x + p.width && y >= p.y && y < p.y + p.height)
                return { level: l, row: p.rowAt(x, y) };
        }
        return null;
    }
    property point _lastPointer: Qt.point(-1, -1)
    function _inTriangle(px, py, ax, ay, bx, by, cx, cy) {
        const s1 = (px - bx) * (ay - by) - (ax - bx) * (py - by);
        const s2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy);
        const s3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay);
        const neg = s1 < 0 || s2 < 0 || s3 < 0, pos = s1 > 0 || s2 > 0 || s3 > 0;
        return !(neg && pos);
    }
    // true while (x, y) moves from the previous pointer position towards the submenu open from `level`
    function inSafeTriangle(level, x, y) {
        if (levelModel.count <= level + 1 || _lastPointer.x < 0)
            return false;
        const sub = panelAt(level + 1), par = panelAt(level);
        if (!sub || !par)
            return false;
        const right = sub.x >= par.x + par.width / 2;
        const ex = right ? sub.x : sub.x + sub.width;          // the submenu's near edge
        const slack = 4;
        return _inTriangle(x, y, _lastPointer.x + (right ? -slack : slack), _lastPointer.y,
                           ex, sub.y - slack, ex, sub.y + sub.height + slack);
    }
    function pointerMove(x, y, dragging) {
        if (!open)
            return;
        const h = hit(x, y);
        const prev = _lastPointer;
        _lastPointer = Qt.point(x, y);
        if (h) {
            if (dragging)
                _dragged = true;
            if (h.row >= 0) {
                const subOpen = levelModel.count > h.level + 1 && _levels[h.level + 1].anchorRow !== h.row;
                if (subOpen && prev.x >= 0) {
                    _lastPointer = prev;
                    const safe = inSafeTriangle(h.level, x, y);
                    _lastPointer = Qt.point(x, y);
                    if (safe) {
                        safeTimer.level = h.level;
                        safeTimer.row = h.row;
                        safeTimer.restart();
                        subTimer.stop();
                        return;
                    }
                }
                safeTimer.stop();
                hoverRow(h.level, h.row);
            }
            return;
        }
        safeTimer.stop();
        // outside the menus: deselect the deepest level's row (not the ones leading to submenus)
        const p = panelAt(activeLevel);
        if (p && levelModel.count - 1 === activeLevel)
            p.currentIndex = -1;
        const t = menu.tracker;
        if (t) {
            const idx = t.hitTest(x, y);
            if (idx >= 0 && idx !== t.openIndex)
                t.openAt(idx, false);
        }
    }
    // returns true when the release selected an item. fromTitle: the button went down on a menu
    // title (press-drag-release from the bar); then only a drag that reached the menus selects —
    // a click or touchpad tap on a title (press and release at once) just opens the menu.
    function pointerRelease(x, y, fromTitle) {
        if (!open)
            return false;
        if (fromTitle && !_dragged) {
            const t0 = menu.tracker;
            if (!t0 || t0.hitTest(x, y) < 0)
                Menus.close("released");
            return false;
        }
        const h = hit(x, y);
        if (h && h.row >= 0) {
            const e = entryAt(h.level, h.row);
            if (e && (e.type || "item") === "item" && !(e.sub || e.children)) {
                activateRow(h.level, h.row, false);
                return true;
            }
            return false;
        }
        if (h)
            return false;
        const t = menu.tracker;
        if (t && t.hitTest(x, y) >= 0)
            return false;        // released on a title: the menu stays open (click to open)
        if (_dragged)
            Menus.close("released");
        return false;
    }

    // ---- keyboard --------------------------------------------------------------------------------
    function key(ev) {
        const p = panelAt(activeLevel);
        if (!p)
            return;
        switch (ev.key) {
        case Qt.Key_Down: p.step(1); break;
        case Qt.Key_Up: p.step(-1); break;
        case Qt.Key_Right: {
            const e = p.entries[p.currentIndex];
            if (e && (e.sub || e.children) && e.enabled !== false)
                openSub(activeLevel, p.currentIndex, true);
            else if (menu.tracker)
                menu.tracker.step(1);
            break;
        }
        case Qt.Key_Left:
            if (activeLevel > 0)
                closeFrom(activeLevel);
            else if (menu.tracker)
                menu.tracker.step(-1);
            break;
        case Qt.Key_Return:
        case Qt.Key_Enter:
        case Qt.Key_Space:
            if (p.currentIndex >= 0)
                activateRow(activeLevel, p.currentIndex, true);
            break;
        case Qt.Key_Escape:
            if (activeLevel > 0)
                closeFrom(activeLevel);
            else
                Menus.close("escape");
            break;
        case Qt.Key_Home: p.currentIndex = -1; p.step(1); break;
        case Qt.Key_End: p.currentIndex = -1; p.step(-1); break;
        default:
            if (ev.text && ev.text.length === 1 && ev.text.trim() !== "") {
                // type to select: first item whose label starts with what was typed
                _typed += ev.text.toLowerCase();
                typeReset.restart();
                for (let i = 0; i < p.entries.length; ++i) {
                    const lab = (p.entries[i].label || "").toLowerCase();
                    if (p.selectable(i) && lab.startsWith(_typed)) {
                        p.currentIndex = i;
                        break;
                    }
                }
            } else {
                return;
            }
        }
        ev.accepted = true;
    }

    Timer {
        id: subTimer
        property int level: 0
        property int row: -1
        interval: 120
        onTriggered: {
            const e = menuHost.entryAt(level, row);
            if (e && (e.sub || e.children) && e.enabled !== false)
                menuHost.openSub(level, row, false);
            else if (menuHost.levelModel.count > level + 1)
                menuHost.closeFrom(level + 1);
        }
    }
    Timer {
        // the pointer stopped inside the safe triangle over another row: that row takes over
        id: safeTimer
        property int level: 0
        property int row: -1
        interval: 300
        onTriggered: menuHost.hoverRow(level, row)
    }
    Timer {
        id: typeReset
        interval: 1000
        onTriggered: menuHost._typed = ""
    }
    property alias levelModel: levelModel
    ListModel { id: levelModel }

    // the item blinks once, then the menu fades and the action runs
    SequentialAnimation {
        id: flash
        property var panel: null
        PropertyAction { target: flash.panel; property: "flashOff"; value: true }
        PauseAnimation { duration: Theme.durations.menuFlash }
        PropertyAction { target: flash.panel; property: "flashOff"; value: false }
        PauseAnimation { duration: Theme.durations.menuFlash }
        ScriptAction {
            script: {
                const act = menuHost._pendingAction;
                menuHost._pendingAction = null;
                Menus.close("activated");
                if (act) {
                    try {
                        act();
                    } catch (e) {
                        console.warn("menu action failed:", e);
                    }
                }
            }
        }
    }
    SequentialAnimation {
        id: closeAnim
        NumberAnimation { target: win; property: "contentOpacity"; to: 0; duration: Theme.duration("menuFade", true); easing.type: Easing.InQuad }
        ScriptAction {
            script: {
                if (!menuHost.open) {
                    menuHost.closeFrom(0);
                    menuHost._openedSerial = -1;
                }
            }
        }
    }

    PanelWindow {
        id: win
        screen: menuHost.screen
        visible: menuHost.open || closeAnim.running
        property real contentOpacity: 1
        WlrLayershell.namespace: "kristall-menu"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: menuHost.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"

        GlassSurface {
            id: gs
            key: "menu-" + menuHost.screenName
            layerNamespace: "kristall-menu"
            output: menuHost.screenName
        }

        MouseArea {
            id: outside
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
            onPositionChanged: mouse => menuHost.pointerMove(mouse.x, mouse.y, pressed)
            onPressed: mouse => {
                const h = menuHost.hit(mouse.x, mouse.y);
                if (h)
                    return;
                const t = menuHost.menu ? menuHost.menu.tracker : null;
                const idx = t ? t.hitTest(mouse.x, mouse.y) : -1;
                if (idx >= 0) {
                    if (idx === t.openIndex)
                        Menus.close("toggle");
                    else
                        t.openAt(idx, false);
                    return;
                }
                Menus.close("outside");
            }
            onReleased: mouse => menuHost.pointerRelease(mouse.x, mouse.y)
        }

        FocusScope {
            id: keys
            anchors.fill: parent
            focus: true
            Keys.onPressed: ev => menuHost.key(ev)
            opacity: win.contentOpacity

            Repeater {
                id: levelRepeater
                model: levelModel
                KMenuPanel {
                    id: lp
                    required property int index
                    required property int lvl
                    readonly property var info: menuHost._levels[lvl] || ({ src: null, anchorLevel: -1, anchorRow: -1 })
                    src: info.src
                    level: lvl
                    host: menuHost
                    surface: gs
                    // false until the layer surface has its size: a panel placed against a
                    // 0×0 window would sit at the top left, under a quick click on a title
                    property bool placed: false
                    function place() {
                        const W = win.width, H = win.height, m = 6;
                        if (W <= 0 || H <= 0) {
                            placed = false;
                            return;
                        }
                        let nx, ny;
                        if (info.anchorLevel < 0) {
                            const r = menuHost.menu ? menuHost.menu.rect : { x: 0, y: 0, w: 0, h: 0 };
                            const align = menuHost.menu ? menuHost.menu.align : "left";
                            nx = align === "right" ? r.x + r.w - width : align === "center" ? r.x + r.w / 2 - width / 2 : r.x;
                            ny = r.y + r.h + (menuHost.menu && menuHost.menu.gap !== undefined ? menuHost.menu.gap : 2);
                            if (ny + height > H - m && r.y - height - 2 > m)
                                ny = r.y - height - 2;      // no room below: open above
                        } else {
                            const parentPanel = menuHost.panelAt(info.anchorLevel);
                            if (!parentPanel)
                                return;
                            const rr = parentPanel.rowRect(info.anchorRow);
                            nx = parentPanel.x + parentPanel.width + Theme.size.submenuGap;
                            if (nx + width > W - m)
                                nx = parentPanel.x - width - Theme.size.submenuGap;
                            ny = rr.y - Theme.size.menuPaddingV;
                        }
                        x = Math.round(Math.max(m, Math.min(W - m - width, nx)));
                        y = Math.round(Math.max(m, Math.min(H - m - height, ny)));
                        placed = true;
                    }
                    onWidthChanged: place()
                    onHeightChanged: place()
                    Component.onCompleted: place()
                    Connections {
                        target: win
                        function onWidthChanged() { lp.place(); }
                        function onHeightChanged() { lp.place(); }
                    }
                }
            }
        }
    }
}
