// SPDX-License-Identifier: GPL-3.0-or-later
// The Dock on one output: a centred, floating glass capsule at the bottom (layer Top, namespace
// "kristall-dock", reserves its height unless it hides automatically).
//
// Layout is computed in one pass per frame (computeLayout): every tile's size from the pointer
// (magnification: a raised-cosine falloff around the pointer, neighbours spread so the point under
// the pointer stays under it — the row grows away from the pointer's side, like the Mac), slot
// presence while tiles appear/leave (others make room), and the capsule around them. Nothing runs
// while the pointer is still or away: the surface presents no frames.
// The capsule's glass is sent with sync "commit" (GlassSurface's default) so it moves in step with
// the icons. The input region covers only the capsule and the magnified icons.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services

PanelWindow {
    id: dockWindow

    required property var dockModel
    required property var places
    required property var launcher
    signal emptyTrashRequested()
    readonly property string screenName: screen ? screen.name : ""

    // ---- settings (dock.*), live --------------------------------------------------------------
    readonly property real tileSize: Math.round(Math.max(24, Math.min(128, Number(Settings.get("dock.size", 48)))))
    readonly property bool magnifyOn: Settings.get("dock.magnification", true) === true
    readonly property real magSize: magnifyOn ? Math.round(Math.max(tileSize, Math.min(160, Number(Settings.get("dock.magnifiedSize", 76))))) : tileSize
    readonly property bool autoHide: Settings.get("dock.autoHide", false) === true

    // ---- metrics (scale with the icon size, 48 px ≈ the Mac's default tile size) ----------------
    readonly property real pad: Math.round(tileSize * 0.125)          // capsule padding around the icons
    readonly property real gap: Math.max(1, Math.round(tileSize * 0.04))
    readonly property real capH: tileSize + 2 * pad
    readonly property real sepW: Math.round(tileSize * 0.24)
    readonly property real bottomGap: Theme.space.s           // the capsule floats above the edge
    readonly property real labelRoom: 44
    // (fixed while dragging: resizing the surface under a pointer grab cancels the drag)
    readonly property real surfaceH: Math.ceil(bottomGap + capH + (magSize - tileSize) + tileSize * 0.45 + labelRoom)
    readonly property real radius: Math.min(capH / 2, Math.round(Theme.radius.dock * tileSize / 48))

    WlrLayershell.namespace: "kristall-dock"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    anchors { bottom: true; left: true; right: true }
    implicitHeight: surfaceH
    exclusiveZone: autoHide ? 0 : Math.round(capH + bottomGap)
    color: "transparent"
    mask: Region { item: inputArea }

    // ---- show / hide (auto-hide) -----------------------------------------------------------------
    property bool revealed: !autoHide
    readonly property real hideOffset: revealed ? 0 : capH + bottomGap + 4
    property real offset: hideOffset
    Behavior on offset { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
    onAutoHideChanged: revealed = !autoHide
    function reveal() { revealed = true; concealTimer.stop(); }
    function conceal() {
        if (autoHide && !hovering && !menuOpen && !dragging && !alertOpen)
            revealed = false;
    }
    Timer { id: concealTimer; interval: 450; onTriggered: dockWindow.conceal() }
    Timer { id: revealTimer; interval: 120; onTriggered: dockWindow.reveal() }
    property bool alertOpen: false

    // ---- slots: entries with presence animations ---------------------------------------------------
    // slot: {id, entry, p0, p1} ; presence = p0 + (p1 - p0) * tt while slotAnim runs
    property var slots: []
    property real tt: 1
    property string handoffFrom: ""      // a drag gap that becomes the dropped item without animating
    property string handoffTo: ""
    NumberAnimation {
        id: slotAnim
        target: dockWindow
        property: "tt"
        from: 0
        to: 1
        duration: Theme.duration("medium")
        easing.type: Easing.BezierSpline
        easing.bezierCurve: Theme.curve("smooth")
        onFinished: dockWindow._settle()
    }
    function presenceOf(s) {
        return s.p0 + (s.p1 - s.p0) * tt;
    }
    function _settle() {
        const kept = slots.filter(s => s.p1 > 0).map(s => ({ id: s.id, entry: s.entry, p0: 1, p1: 1 }));
        tt = 1;
        slots = kept;
        _syncModel();
    }

    // the entries to show: the model's, or the drag preview
    readonly property var shownEntries: dragging ? dragPreview : dockModel.entries
    onShownEntriesChanged: Qt.callLater(_sync)
    Component.onCompleted: _sync()

    function _sync() {
        const target = shownEntries;
        const ids = target.map(e => e.id);
        const cur = slots;
        const same = cur.length === target.length && cur.every((s, i) => s.id === ids[i] && s.p1 === 1);
        if (same) {
            // membership unchanged: refresh the entries (running state, titles) without animating
            slots = cur.map((s, i) => ({ id: s.id, entry: target[i], p0: s.p0, p1: s.p1 }));
            return;
        }
        const pres = {};
        for (const s of cur)
            pres[s.id] = presenceOf(s);
        const animate = Theme.duration("medium") > 0;
        const out = target.map(e => ({ id: e.id, entry: e, p0: pres[e.id] !== undefined ? pres[e.id] : (animate ? 0 : 1), p1: 1 }));
        // a drag gap handing over to the dropped item: no shrink/grow, it simply becomes it
        if (handoffTo !== "") {
            const t = out.find(s => s.id === handoffTo);
            if (t && pres[handoffFrom] !== undefined)
                t.p0 = Math.max(t.p0, pres[handoffFrom]);
        }
        // leaving slots stay where they were while they shrink
        for (let i = 0; i < cur.length; ++i) {
            const s = cur[i];
            if (ids.indexOf(s.id) >= 0 || (handoffTo !== "" && s.id === handoffFrom))
                continue;
            if (pres[s.id] <= 0.001 || !animate)
                continue;
            let at = 0;
            for (let j = i - 1; j >= 0; --j) {
                const k = out.findIndex(o => o.id === cur[j].id);
                if (k >= 0) {
                    at = k + 1;
                    break;
                }
            }
            out.splice(at, 0, { id: s.id, entry: s.entry, p0: pres[s.id], p1: 0 });
        }
        handoffFrom = "";
        handoffTo = "";
        slotAnim.stop();
        tt = animate ? 0 : 1;
        slots = out;
        _syncModel();
        if (animate)
            slotAnim.start();
        else
            _settle();
    }
    // keep the delegates stable (bounce state, decoded icons) across inserts, removals and moves
    ListModel { id: slotModel }
    function _syncModel() {
        const ids = slots.map(s => s.id);
        for (let i = 0; i < ids.length; ++i) {
            if (i < slotModel.count && slotModel.get(i).sid === ids[i])
                continue;
            let j = -1;
            for (let k = i + 1; k < slotModel.count; ++k)
                if (slotModel.get(k).sid === ids[i]) {
                    j = k;
                    break;
                }
            if (j >= 0)
                slotModel.move(j, i, 1);
            else
                slotModel.insert(i, { sid: ids[i] });
        }
        while (slotModel.count > ids.length)
            slotModel.remove(slotModel.count - 1);
    }

    // ---- pointer state ----------------------------------------------------------------------------
    property real pointerX: -1
    property real pointerY: -1
    property bool hovering: false
    readonly property bool menuOpen: Menus.current !== null && String(Menus.current.owner).startsWith("dock:")
    property real hoverAmt: 0
    Behavior on hoverAmt { NumberAnimation { duration: Theme.duration("short"); easing.type: Easing.OutQuad } }
    readonly property bool magnifying: (hovering || menuOpen || dragging) && revealed && magSize > tileSize
    onMagnifyingChanged: hoverAmt = magnifying ? 1 : 0

    // ---- layout (one pass, per frame while something moves) ------------------------------------------
    readonly property real capBottom: surfaceH - bottomGap + offset
    readonly property real capTop: capBottom - capH
    readonly property real iconBottom: capBottom - pad
    property real layoutCostMs: 0
    readonly property var layout: computeLayout(slots, tt, pointerX, hoverAmt, tileSize, magSize, width)
    function computeLayout(sl, t, px0, amt, s, m, w) {
        const n = sl.length;
        const ws = new Array(n), ga = new Array(n), left = new Array(n), isIcon = new Array(n), pres = new Array(n);
        let rowW = 0;
        for (let i = 0; i < n; ++i) {
            const p = sl[i].p0 + (sl[i].p1 - sl[i].p0) * t;
            pres[i] = p;
            const kind = sl[i].entry.kind;
            isIcon[i] = kind !== "sep";
            ws[i] = (kind === "sep" ? sepW : s) * p;
            ga[i] = i < n - 1 ? gap * p : 0;
            rowW += ws[i] + ga[i];
        }
        const rowLeft = Math.round((w - rowW) / 2);
        let acc = rowLeft;
        for (let i = 0; i < n; ++i) {
            left[i] = acc;
            acc += ws[i] + ga[i];
        }
        const W = ws.slice();
        let L = rowLeft;
        if (amt > 0.001 && m > s && n > 0) {
            const px = Math.max(rowLeft, Math.min(rowLeft + rowW, px0));
            const R = Math.max(s * 2.6, m * 1.5);
            let P = 0;
            for (let i = 0; i < n; ++i) {
                if (isIcon[i]) {
                    const d = Math.abs(px - (left[i] + ws[i] / 2)) / R;
                    const f = d < 1 ? (1 + Math.cos(Math.PI * d)) / 2 : 0;
                    W[i] = ws[i] * (1 + (m / s - 1) * amt * f);
                }
                const base = ws[i] + ga[i];
                const cov = base > 0 ? Math.max(0, Math.min(1, (px - left[i]) / base)) : 0;
                P += (W[i] + ga[i]) * cov;
            }
            L = px - P;
        }
        const x = new Array(n);
        acc = L;
        let maxW = 0;
        for (let i = 0; i < n; ++i) {
            x[i] = acc;
            acc += W[i] + ga[i];
            if (isIcon[i] && W[i] > maxW)
                maxW = W[i];
        }
        return { x: x, w: W, p: pres, capL: L - pad, capR: acc + pad, maxW: maxW, baseLeft: left, baseW: ws, rowLeft: rowLeft, rowW: rowW };
    }

    // ---- material -----------------------------------------------------------------------------
    GlassSurface {
        id: glassSurface
        key: "dock-" + dockWindow.screenName
        layerNamespace: "kristall-dock"
        output: dockWindow.screenName
    }
    GlassShape {
        id: capsule
        shapeId: "capsule"
        surface: glassSurface
        // the Dock reads as a solid object of glass on any wallpaper: its own (stronger) tint, a
        // crisp specular rim and hairline (KGlassRim) and a soft ambient shadow underneath
        role: "dock"
        kind: "rect"
        radius: dockWindow.radius
        bezel: Math.round(dockWindow.capH * 0.22)
        depth: Math.round(dockWindow.capH * 0.12)
        shadow: true
        shadowKind: "ambient"
        x: dockWindow.layout.capL
        y: dockWindow.capTop
        width: Math.max(0, dockWindow.layout.capR - dockWindow.layout.capL)
        height: dockWindow.capH
        KGlassRim {
            radius: capsule.radius
            scheme: capsule.scheme
        }
    }
    readonly property string scheme: capsule.scheme

    // ---- tiles --------------------------------------------------------------------------------------
    property int hoverIndex: -1
    property int pressIndex: -1
    Repeater {
        id: tiles
        model: slotModel
        delegate: Item {
            id: slotItem
            required property int index
            required property string sid
            readonly property var slot: dockWindow.slots[index] || null
            readonly property var entry: slot ? slot.entry : null
            readonly property string key: entry ? entry.key : ""
            readonly property real tw: dockWindow.layout.w[index] || 0
            readonly property bool isRunning: entry !== null && entry.kind === "app" && AppCatalog.isRunning(key)
            readonly property var attention: {
                if (!entry || entry.kind !== "app")
                    return false;
                return AppCatalog.windowsOf(key).some(w => w.demandsAttention && !w.active && !dockWindow.attended[w.id]);
            }
            x: dockWindow.layout.x[index] || 0
            y: dockWindow.iconBottom - tw
            width: tw
            height: tw
            z: entry && entry.kind === "sep" ? 0 : 1

            DockItem {
                anchors.fill: parent
                entry: slotItem.entry
                size: slotItem.tw
                baseSize: dockWindow.tileSize
                renderSize: dockWindow.magSize
                presence: dockWindow.layout.p[slotItem.index] || 0
                scheme: dockWindow.scheme
                pressed: dockWindow.pressIndex === slotItem.index && !dockWindow.dragging
                dragging: dockWindow.dragging && dockWindow.dragGapId === slotItem.sid
                badge: slotItem.key !== "" ? (dockWindow.launcher.byKey[slotItem.key] || null) : null
                iconSource: dockWindow.iconFor(slotItem.entry)
                bouncing: slotItem.entry !== null && slotItem.entry.kind === "app" && (dockWindow.dockModel.launching[slotItem.key] !== undefined || slotItem.attention === true)
                separatorHeight: dockWindow.tileSize * 0.72
            }
            // running indicator: stays put while the icon bounces
            Rectangle {
                visible: slotItem.isRunning
                width: Math.max(4, Math.round(dockWindow.tileSize * 0.08))
                height: width
                radius: width / 2
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height + (dockWindow.pad - height) / 2 + 0.5
                color: Theme.color(dockWindow.scheme, "label")
                opacity: 0.8
            }
        }
    }
    function iconFor(entry) {
        if (!entry)
            return "";
        switch (entry.kind) {
        case "app":
        case "window":
            return AppCatalog.iconForKey(entry.key);
        case "downloads":
            return AppCatalog.iconUrl("folder-download");
        case "trash":
            return AppCatalog.iconUrl(places.trashFull ? "user-trash-full" : "user-trash");
        }
        return "";
    }

    // attention bounces stop after a few seconds (the badge/urgent state stays)
    property var attended: ({})
    Timer {
        id: attentionTimer
        interval: 3000
        onTriggered: {
            const a = Object.assign({}, dockWindow.attended);
            for (const id in Bridge.windows)
                if (Bridge.windows[id].demandsAttention)
                    a[id] = true;
            dockWindow.attended = a;
        }
    }
    Connections {
        target: Bridge
        function onWindowChanged(id, changes) {
            if (changes.demandsAttention === true)
                attentionTimer.restart();
            else if (changes.demandsAttention === false && dockWindow.attended[id]) {
                const a = Object.assign({}, dockWindow.attended);
                delete a[id];
                dockWindow.attended = a;
            }
        }
    }

    // ---- hover label (glass, above the icon under the pointer) ----------------------------------------
    readonly property string labelText: {
        if (hoverIndex < 0 || pressIndex >= 0 || menuOpen || hoverAmt < 0.01 && !hovering)
            return dragging && dragRemove ? Strings.t("dock.remove") : "";
        const e = slots[hoverIndex] ? slots[hoverIndex].entry : null;
        return e ? labelFor(e) : "";
    }
    function labelFor(e) {
        switch (e.kind) {
        case "app": return AppCatalog.displayName(e.key);
        case "apps": return Strings.t("dock.apps");
        case "downloads": return Strings.t("dock.downloads");
        case "trash": return Strings.t("dock.trash");
        case "window": {
            const w = Bridge.windows[e.windowId];
            return w ? (w.title || AppCatalog.displayName(e.key)) : "";
        }
        }
        return "";
    }
    readonly property real labelCenter: {
        if (dragging)
            return dragX;
        if (hoverIndex < 0 || !layout.x[hoverIndex])
            return width / 2;
        return layout.x[hoverIndex] + layout.w[hoverIndex] / 2;
    }
    readonly property real labelBottom: dragging ? dragY - tileSize * 0.62 : iconBottom - (layout.w[hoverIndex] || tileSize) - 10
    GlassShape {
        id: label
        shapeId: "label"
        surface: glassSurface
        role: "tooltip"
        visible: dockWindow.labelText !== ""
        width: Math.round(labelTextItem.implicitWidth + 2 * 10)
        height: 24
        x: Math.round(Math.max(4, Math.min(dockWindow.width - width - 4, dockWindow.labelCenter - width / 2)))
        y: Math.round(Math.max(0, dockWindow.labelBottom - height))
        shadow: true
        KText {
            id: labelTextItem
            anchors.centerIn: parent
            text: dockWindow.labelText
            textStyle: "body"
            scheme: label.scheme
            elide: Text.ElideRight
            width: Math.min(implicitWidth, 420)
        }
    }

    // ---- input ------------------------------------------------------------------------------------
    Item {
        id: inputArea
        readonly property bool full: dockWindow.dragging
        readonly property real topY: dockWindow.revealed ? Math.min(dockWindow.capTop, dockWindow.iconBottom - dockWindow.layout.maxW) : dockWindow.surfaceH - 1
        x: full ? 0 : dockWindow.layout.capL
        width: full ? dockWindow.width : Math.max(1, dockWindow.layout.capR - dockWindow.layout.capL)
        y: full ? 0 : topY
        height: dockWindow.surfaceH - y
    }
    function hit(mx, my) {
        if (my < Math.min(capTop, iconBottom - layout.maxW) || my > capBottom)
            return -1;
        for (let i = 0; i < slots.length; ++i) {
            const k = slots[i].entry.kind;
            if (k === "sep" || slots[i].p1 === 0)
                continue;
            const x0 = layout.x[i] - gap / 2, x1 = layout.x[i] + layout.w[i] + gap / 2;
            if (mx >= x0 && mx < x1)
                return my >= iconBottom - layout.w[i] - gap || my >= capTop ? i : -1;
        }
        return -1;
    }

    // ---- drag to reorder / off to remove --------------------------------------------------------------
    property bool dragging: false
    property var dragEntry: null
    property string dragGapId: ""
    property int _gapSerial: 0
    property real dragX: 0
    property real dragY: 0
    property int dragIndex: 0              // insertion index among the kept items
    readonly property bool dragRemove: dragging && dragY < capTop - tileSize * 0.8
    readonly property var dragPreview: {
        if (!dragging)
            return [];
        const base = dockModel.entries.filter(e => e.id !== dragEntry.id);
        if (dragRemove)
            return base;
        let pinnedCount = 0;
        for (const e of base)
            if (e.pinned)
                pinnedCount++;
        const out = base.slice();
        out.splice(Math.min(dragIndex, pinnedCount), 0, { id: dragGapId, kind: "gap", key: "", pinned: true });
        return out;
    }
    function startDrag(i, mx, my) {
        const e = slots[i].entry;
        if (!(e.kind === "app" || e.kind === "apps"))
            return false;
        Tooltips.hide();
        dragEntry = e;
        _gapSerial++;
        dragGapId = "gap:" + _gapSerial;
        dragX = mx;
        dragY = my;
        dragIndex = pinnedIndexAt(mx, e.id);
        dragging = true;
        return true;
    }
    // where among the kept items (without the dragged one) the pointer is
    function pinnedIndexAt(mx, skipId) {
        let idx = 0;
        for (let i = 0; i < slots.length; ++i) {
            const e = slots[i].entry;
            if (!e.pinned || e.id === skipId || e.kind === "gap")
                continue;
            if (mx > layout.x[i] + layout.w[i] / 2)
                idx++;
        }
        return idx;
    }
    function moveDrag(mx, my) {
        dragX = mx;
        dragY = my;
        const idx = pinnedIndexAt(mx, dragEntry.id);
        if (idx !== dragIndex) {
            dragIndex = idx;
            _gapSerial++;
            dragGapId = "gap:" + _gapSerial;     // old gap closes while the new one opens
        }
    }
    function endDrag() {
        const e = dragEntry;
        const remove = dragRemove;
        const index = dragIndex;
        if (!remove) {
            handoffFrom = dragGapId;
            handoffTo = e.id;
        }
        dragging = false;
        dragEntry = null;
        if (remove) {
            if (e.kind === "apps")
                dockModel.unpinId(e.pinId);
            else if (e.pinned)
                dockModel.unpin(e.key);
        } else if (e.kind === "apps") {
            dockModel.moveTo(e.pinId, index);
        } else {
            dockModel.pin(e.key, index);
        }
    }
    // the dragged icon follows the pointer
    Item {
        visible: dockWindow.dragging
        x: dockWindow.dragX - dockWindow.tileSize / 2
        y: Math.max(0, dockWindow.dragY - dockWindow.tileSize / 2)
        width: dockWindow.tileSize
        height: dockWindow.tileSize
        opacity: dockWindow.dragRemove ? 0.55 : 1
        AppIcon {
            visible: dockWindow.dragEntry !== null && dockWindow.dragEntry.kind === "app"
            anchors.fill: parent
            size: dockWindow.tileSize
            renderSize: dockWindow.magSize
            scheme: dockWindow.scheme
            source: visible ? AppCatalog.iconForKey(dockWindow.dragEntry.key) : ""
        }
        AppsGlyph {
            visible: dockWindow.dragEntry !== null && dockWindow.dragEntry.kind === "apps"
            anchors.fill: parent
            size: dockWindow.tileSize
            scheme: dockWindow.scheme
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        property real pressX: 0
        property real pressY: 0
        property int button: 0
        onEntered: {
            dockWindow.hovering = true;
            if (!dockWindow.revealed)
                revealTimer.restart();
            concealTimer.stop();
        }
        onExited: {
            dockWindow.hovering = false;
            dockWindow.hoverIndex = -1;
            revealTimer.stop();
            if (dockWindow.autoHide)
                concealTimer.restart();
        }
        onPositionChanged: m => {
            dockWindow.pointerX = m.x;
            dockWindow.pointerY = m.y;
            if (dockWindow.dragging) {
                dockWindow.moveDrag(m.x, m.y);
                return;
            }
            if (pressed && dockWindow.pressIndex >= 0 && button === Qt.LeftButton
                    && Math.hypot(m.x - pressX, m.y - pressY) > 6) {
                longPress.stop();
                if (dockWindow.startDrag(dockWindow.pressIndex, m.x, m.y))
                    dockWindow.pressIndex = -1;
                return;
            }
            dockWindow.hoverIndex = dockWindow.hit(m.x, m.y);
        }
        onPressed: m => {
            button = m.button;
            pressX = m.x;
            pressY = m.y;
            const i = dockWindow.hit(m.x, m.y);
            dockWindow.pressIndex = i;
            if (i < 0) {
                if (m.button === Qt.RightButton && m.y >= dockWindow.capTop)
                    dockWindow.openDockMenu();
                return;
            }
            if (m.button === Qt.RightButton) {
                dockWindow.openMenu(i);
                dockWindow.pressIndex = -1;
            } else {
                longPress.restart();
            }
        }
        onReleased: m => {
            longPress.stop();
            if (dockWindow.dragging) {
                dockWindow.endDrag();
                return;
            }
            const i = dockWindow.pressIndex;
            dockWindow.pressIndex = -1;
            if (i >= 0 && m.button === Qt.LeftButton && dockWindow.hit(m.x, m.y) === i)
                dockWindow.click(i);
        }
        onCanceled: {
            longPress.stop();
            dockWindow.pressIndex = -1;
            if (dockWindow.dragging)
                dockWindow.endDrag();
        }
        Timer {
            id: longPress
            interval: 600
            onTriggered: {
                const i = dockWindow.pressIndex;
                dockWindow.pressIndex = -1;
                if (i >= 0)
                    dockWindow.openMenu(i);
            }
        }
    }

    // ---- actions -----------------------------------------------------------------------------------
    function click(i) {
        const e = slots[i] ? slots[i].entry : null;
        if (!e)
            return;
        switch (e.kind) {
        case "app":
            AppCatalog.activate(e.key);
            break;
        case "apps":
            ShellBus.request("apps", "toggle", "", screenName);
            break;
        case "window":
            AppCatalog.activateWindow(e.windowId);
            break;
        case "downloads":
            places.open(places.downloads);
            break;
        case "trash":
            places.openTrash();
            break;
        }
    }
    readonly property real originY: (screen ? screen.height : 0) - surfaceH
    function tileRect(i) {
        const w = layout.w[i] || tileSize;
        return { x: layout.x[i], y: originY + iconBottom - w, w: w, h: w };
    }
    function openMenu(i) {
        const e = slots[i] ? slots[i].entry : null;
        if (!e)
            return;
        const items = DockMenus.forEntry(e, dockWindow);
        if (!items || items.length === 0)
            return;
        Menus.open({
            screen: screenName, rect: tileRect(i), align: "center", owner: "dock:" + e.id, gap: 8,
            source: Menus.list(items),
            onClosed: reason => { if (!dockWindow.hovering && dockWindow.autoHide) concealTimer.restart(); }
        });
    }
    function openDockMenu() {
        Menus.open({
            screen: screenName, rect: { x: pointerX, y: originY + capTop, w: 1, h: capH }, align: "center", owner: "dock:dock", gap: 8,
            source: Menus.list(DockMenus.dockOptions(dockWindow))
        });
    }

    // ---- where minimised windows flow to (bridge window.setIconGeometry) --------------------------------
    // Per window, in global logical coordinates, from the resting layout (no magnification):
    // its own tile while minimised; else the slot a new minimised tile will take (or the app's icon
    // with dock.minimizeToApp, and for windows hidden with Hide).
    property var _sentGeom: ({})
    readonly property var outputOrigin: {
        for (const o of Bridge.outputs)
            if (o.name === screenName)
                return { x: o.x, y: o.y };
        return { x: 0, y: 0 };
    }
    function restingRects() {
        const n = slots.length;
        const ws = [];
        let rowW = 0;
        for (let i = 0; i < n; ++i) {
            if (slots[i].p1 === 0) {
                ws.push(0);
                continue;
            }
            const w = slots[i].entry.kind === "sep" ? sepW : tileSize;
            ws.push(w);
            rowW += w + gap;
        }
        rowW -= gap;
        const out = {};
        let x = Math.round((width - rowW) / 2);
        let downloadsRel = rowW;
        for (let i = 0; i < n; ++i) {
            if (ws[i] === 0)
                continue;
            out[slots[i].id] = x;
            if (slots[i].id === "downloads")
                downloadsRel = x - Math.round((width - rowW) / 2);
            x += ws[i] + gap;
        }
        // a new minimised tile goes before Downloads; the row grows by one tile and re-centres
        const grown = rowW + tileSize + gap;
        out["new-window"] = Math.round((width - grown) / 2) + downloadsRel;
        return out;
    }
    function updateIconGeometry() {
        if (!Bridge.connected || width <= 0)
            return;
        const xs = restingRects();
        const o = outputOrigin;
        const y = o.y + originY + (surfaceH - bottomGap - pad - tileSize) + (revealed ? 0 : hideOffset);
        const sent = Object.assign({}, _sentGeom);
        const live = {};
        const rects = {};
        for (const key in AppCatalog.running) {
            const appX = xs["app:" + key];
            if (appX !== undefined)
                rects[key] = { x: o.x + appX, y: y, w: tileSize, h: tileSize };
            for (const w of AppCatalog.running[key]) {
                let x;
                if (AppCatalog.hiddenIds[w.id] || dockModel.minimizeToApp)
                    x = appX;
                else if (w.minimized && xs["win:" + w.id] !== undefined)
                    x = xs["win:" + w.id];
                else
                    x = xs["new-window"];
                if (x === undefined)
                    continue;
                const r = { id: w.id, x: o.x + x, y: y, w: tileSize, h: tileSize };
                const sig = [r.x, r.y, r.w, r.h].map(v => Math.round(v)).join(",");
                live[w.id] = sig;
                if (sent[w.id] === sig)
                    continue;
                Bridge.call("window.setIconGeometry", r);
            }
        }
        _sentGeom = live;
        AppCatalog.dockRects = rects;
    }
    onSlotsChanged: Qt.callLater(updateIconGeometry)
    onWidthChanged: Qt.callLater(updateIconGeometry)
    onTileSizeChanged: Qt.callLater(updateIconGeometry)
    onRevealedChanged: Qt.callLater(updateIconGeometry)
    Connections {
        target: Bridge
        function onConnectedChanged() { dockWindow._sentGeom = {}; Qt.callLater(dockWindow.updateIconGeometry); }
        function onWindowAdded(w) { Qt.callLater(dockWindow.updateIconGeometry); }
    }

    // measures app icons for every shell-apps module (one long-lived probe)
    IconProbe {}

    // ---- frame statistics for the tests (counters only; no timers) --------------------------------------
    property int frames: 0
    property var frameTimes: []
    property bool recordFrames: false
    Connections {
        target: capsule.Window.window
        function onFrameSwapped() {
            dockWindow.frames++;
            if (dockWindow.recordFrames && dockWindow.frameTimes.length < 4000)
                dockWindow.frameTimes.push(Date.now());
        }
    }
}
