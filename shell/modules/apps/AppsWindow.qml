// SPDX-License-Identifier: GPL-3.0-or-later
// Apps: every installed app in a large glass panel (macOS 26/27 "Apps", the Launchpad successor):
// a search field, category buttons and the icon grid. Full-output Overlay surface (namespace
// "kristall-apps"; a click outside closes), exclusive keyboard while open: typing filters, arrows
// move, ↩ opens, ⎋ clears, then closes. Right click: Open, Keep in Dock, Uninstall … (Flatpak apps:
// handed to the app store). The list follows installs and removals live (AppCatalog).
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services
import "../dock/common"

PanelWindow {
    id: appsWindow
    signal closeRequested()
    signal launched(string key)
    readonly property string screenName: screen ? screen.name : ""

    WlrLayershell.namespace: "kristall-apps"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: menuOpen ? WlrKeyboardFocus.None : WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    readonly property bool menuOpen: Menus.current !== null && String(Menus.current.owner).startsWith("apps:")

    // ---- metrics -----------------------------------------------------------------------------
    readonly property real panelW: Math.min(1040, width - 2 * 64)
    readonly property real panelH: Math.min(740, height - Theme.size.bar - 2 * 56)
    readonly property real cellW: 128
    readonly property real cellH: 118
    readonly property real iconSize: 72

    property real shown: 0
    Behavior on shown { NumberAnimation { duration: Theme.duration("medium", true); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
    Component.onCompleted: {
        shown = 1;
        Qt.callLater(() => field.input.forceActiveFocus());
    }
    onMenuOpenChanged: if (!menuOpen) Qt.callLater(() => field.input.forceActiveFocus())

    // ---- content ------------------------------------------------------------------------------
    readonly property var categoryOrder: ["productivity", "internet", "media", "graphics", "games", "developer", "utilities", "system"]
    readonly property var categories: {
        AppCatalog.revision;
        const present = {};
        for (const r of AppCatalog.apps)
            present[r.category] = true;
        return ["all"].concat(categoryOrder.filter(c => present[c]));
    }
    property string category: "all"
    readonly property string filterText: field.text.trim()
    readonly property var shownApps: {
        AppCatalog.revision;
        if (filterText !== "")
            return AppCatalog.search(filterText, 0).map(x => x.rec);
        return AppCatalog.apps.filter(r => category === "all" || r.category === category);
    }
    property int current: 0
    onShownAppsChanged: current = Math.min(current, Math.max(0, shownApps.length - 1))
    onFilterTextChanged: current = 0
    onCategoryChanged: current = 0

    function launch(i) {
        const r = shownApps[i];
        if (!r)
            return;
        if (filterText !== "")
            AppCatalog.notePick(r.key, filterText);
        AppCatalog.activate(r.key);
        launched(r.key);
        closeRequested();
    }
    function moveBy(dx, dy) {
        const cols = Math.max(1, Math.floor(grid.width / cellW));
        let i = current + dx + dy * cols;
        i = Math.max(0, Math.min(shownApps.length - 1, i));
        current = i;
        grid.positionViewAtIndex(i, GridView.Contain);
    }
    function openMenu(i, item) {
        const r = shownApps[i];
        if (!r)
            return;
        current = i;
        const p = item.mapToItem(null, 0, 0);
        const items = [{ label: Strings.t("apps.open"), action: () => appsWindow.launch(i) }];
        const kept = AppCatalog.isPinned(r.key);
        items.push({ label: kept ? Strings.t("apps.removeFromDock") : Strings.t("apps.addToDock"),
                     action: () => kept ? AppCatalog.unpin(r.key) : AppCatalog.pin(r.key) });
        if (r.flatpak !== "") {
            items.push({ type: "separator" });
            items.push({ label: Strings.t("apps.uninstall") + Strings.t("common.ellipsis"), action: () => appsWindow.uninstall(r) });
        }
        Menus.open({ screen: screenName, rect: { x: p.x, y: p.y, w: item.width, h: item.height * 0.7 }, align: "center", owner: "apps:" + r.key,
                     source: Menus.list(items) });
    }
    // removal is the app store's job: open the app's page there (appstream:// → Bazaar/Discover)
    function uninstall(r) {
        Quickshell.execDetached(["xdg-open", "appstream://" + r.flatpak]);
        lastHandOff = "appstream://" + r.flatpak;
        closeRequested();
    }
    property string lastHandOff: ""
    function openMenuForKey(key) {
        const i = shownApps.findIndex(r => r.key === key);
        if (i < 0)
            return false;
        grid.positionViewAtIndex(i, GridView.Contain);
        const item = grid.cellItem(i);
        if (item)
            openMenu(i, item);
        return !!item;
    }

    // ---- surface ------------------------------------------------------------------------------
    GlassSurface {
        id: gs
        key: "apps-" + appsWindow.screenName
        layerNamespace: "kristall-apps"
        output: appsWindow.screenName
    }
    Rectangle {      // a faint veil, like the Mac dims the desktop behind Apps
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, Theme.dark ? 0.22 : 0.12)
        opacity: appsWindow.shown
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPressed: appsWindow.closeRequested()
    }
    GlassShape {
        id: panel
        shapeId: "apps"
        surface: gs
        role: "panel"
        width: appsWindow.panelW
        height: appsWindow.panelH
        x: Math.round((appsWindow.width - width) / 2)
        y: Math.round(Theme.size.bar + (appsWindow.height - Theme.size.bar - height) / 2)
        glassOpacity: appsWindow.shown
        opacity: appsWindow.shown
        scale: 0.96 + 0.04 * appsWindow.shown
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton }

        KTextField {
            id: field
            search: true
            scheme: panel.scheme
            width: 300
            anchors.horizontalCenter: parent.horizontalCenter
            y: Theme.space.xxl
            placeholder: Strings.t("apps.search")
            // the text input keeps ←/→ while it can move the cursor; the rest reaches us
            Keys.onPressed: ev => {
                switch (ev.key) {
                case Qt.Key_Left: appsWindow.moveBy(-1, 0); break;
                case Qt.Key_Right: appsWindow.moveBy(1, 0); break;
                case Qt.Key_Up: appsWindow.moveBy(0, -1); break;
                case Qt.Key_Down: appsWindow.moveBy(0, 1); break;
                default: return;
                }
                ev.accepted = true;
            }
            onAccepted: appsWindow.launch(appsWindow.current)
            onEscaped: {
                if (field.text !== "")
                    field.text = "";
                else
                    appsWindow.closeRequested();
            }
        }

        // categories: capsule buttons (binding-safe: the selection lives here, not in the control)
        Row {
            id: cats
            anchors.horizontalCenter: parent.horizontalCenter
            y: field.y + field.height + Theme.space.l
            spacing: Theme.space.xs
            visible: appsWindow.filterText === ""
            Repeater {
                model: appsWindow.categories
                Rectangle {
                    id: catButton
                    required property string modelData
                    readonly property bool on: appsWindow.category === modelData
                    height: Theme.size.controlSmall
                    width: catLabel.implicitWidth + 2 * Theme.space.l
                    radius: height / 2
                    color: on ? Theme.color(panel.scheme, "fillStrong") : (catHover.hovered ? Theme.color(panel.scheme, "hover") : "transparent")
                    Accessible.role: Accessible.RadioButton
                    Accessible.name: catLabel.text
                    KText {
                        id: catLabel
                        anchors.centerIn: parent
                        text: Strings.t("apps.category." + catButton.modelData)
                        textStyle: "controlSmall"
                        emphasized: catButton.on
                        scheme: panel.scheme
                    }
                    HoverHandler { id: catHover }
                    TapHandler { onTapped: { appsWindow.category = catButton.modelData; field.input.forceActiveFocus(); } }
                }
            }
        }

        GridView {
            id: grid
            function cellItem(i) { return itemAtIndex(i); }
            readonly property real gridTop: cats.y + cats.height + Theme.space.xl
            y: gridTop
            width: Math.floor((parent.width - 2 * Theme.space.xxxl) / appsWindow.cellW) * appsWindow.cellW
            x: Math.round((parent.width - width) / 2)
            height: parent.height - gridTop - Theme.space.l
            clip: true
            cellWidth: appsWindow.cellW
            cellHeight: appsWindow.cellH
            boundsBehavior: Flickable.StopAtBounds
            model: appsWindow.shownApps
            currentIndex: appsWindow.current
            delegate: Item {
                id: cell
                required property var modelData
                required property int index
                readonly property bool selected: appsWindow.current === index
                width: appsWindow.cellW
                height: appsWindow.cellH
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 4
                    radius: Theme.radius.card
                    color: cell.selected ? Theme.color(panel.scheme, "fill") : (cellHover.hovered ? Theme.color(panel.scheme, "hover") : "transparent")
                }
                AppIcon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 8
                    size: appsWindow.iconSize
                    scheme: panel.scheme
                    source: AppCatalog.iconUrl(cell.modelData.iconName)
                    dimmed: cellTap.pressed
                }
                KText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 8 + appsWindow.iconSize + 4
                    width: parent.width - 12
                    horizontalAlignment: Text.AlignHCenter
                    text: cell.modelData.name
                    textStyle: "callout"
                    maximumLineCount: 2
                    wrapMode: Text.WordWrap
                    lineHeightMode: Text.ProportionalHeight
                    lineHeight: 1.0
                    elide: Text.ElideRight
                    scheme: panel.scheme
                }
                HoverHandler { id: cellHover }
                TapHandler {
                    id: cellTap
                    acceptedButtons: Qt.LeftButton
                    onTapped: appsWindow.launch(cell.index)
                    onLongPressed: appsWindow.openMenu(cell.index, cell)
                }
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onPressedChanged: if (pressed) appsWindow.openMenu(cell.index, cell)
                }
                Accessible.role: Accessible.Button
                Accessible.name: cell.modelData.name
            }
        }
        KText {
            visible: appsWindow.shownApps.length === 0
            anchors.centerIn: grid
            text: Strings.t("apps.noResults")
            textStyle: "title3"
            level: "secondaryLabel"
            scheme: panel.scheme
        }
    }
}
