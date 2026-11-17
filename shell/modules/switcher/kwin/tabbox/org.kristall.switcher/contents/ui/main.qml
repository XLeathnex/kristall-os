// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall app switcher — a layout for KWin's own window switcher (TabBox), so holding the key,
// tabbing and releasing are handled inside the compositor with no round trip (quick taps switch
// without showing anything). KWin runs it with [TabBox] ApplicationsMode=1 (one entry per app,
// most recently used first) for Meta+Tab, and for Meta+` with the current app's windows.
// While it is shown: Tab/Shift+Tab and ←/→ move, Q quits the highlighted app, H hides it, Escape
// cancels (KWin), releasing the key switches (KWin).
// Look: design tokens of docs/contracts/design.md copied here (KWin's QML cannot import the
// shell's): HUD radius 22, label colours, Inter, durations 100/150 ms. Material: real Liquid Glass
// through the glass effect's kristallGlass property (glass.md); the opaque fallback material only
// while the effect is not drawing it (no effect, crash guard).
import QtQuick
import org.kde.kwin as KWin
import org.kde.kirigami as Kirigami

KWin.TabBoxSwitcher {
    id: tabBox

    // ---- tokens -----------------------------------------------------------------------------
    readonly property bool dark: {
        const c = Kirigami.Theme.textColor;
        return (0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b) > 0.5;
    }
    readonly property color label: dark ? "#F2F2F7" : "#1D1D1F"
    readonly property color secondary: dark ? Qt.rgba(1, 1, 1, 0.55) : Qt.rgba(0, 0, 0, 0.5)
    readonly property color material: dark ? Qt.rgba(0.118, 0.118, 0.125, 0.86) : Qt.rgba(0.965, 0.965, 0.973, 0.86)
    readonly property color border: dark ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(0, 0, 0, 0.10)
    readonly property color highlight: dark ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(0, 0, 0, 0.10)
    readonly property real iconSize: Math.round(Math.min(96, tabBox.screenGeometry.width / 16))
    readonly property real cell: iconSize + 24
    readonly property real pad: 14

    // the app name for an entry: the title's last part ("Report — Kate" → "Kate")
    function appName(caption) {
        const parts = String(caption || "").split(/ [—–-] /);
        return parts.length > 1 ? parts[parts.length - 1] : String(caption || "");
    }
    // every window of the app the entry stands for
    function windowsLike(wid) {
        const out = [];
        let ref = null;
        for (const w of KWin.Workspace.windows)
            if (String(w.internalId) === String(wid))
                ref = w;
        if (!ref)
            return out;
        const key = ref.desktopFileName || ref.resourceClass;
        for (const w of KWin.Workspace.windows)
            if ((w.desktopFileName || w.resourceClass) === key && w.normalWindow)
                out.push(w);
        return out;
    }

    Instantiator {
        active: tabBox.visible
        delegate: Window {
            id: win
            flags: Qt.BypassWindowManagerHint | Qt.FramelessWindowHint | Qt.ToolTip
            color: "transparent"
            visible: true
            width: Math.min(tabBox.screenGeometry.width - 80, row.count * tabBox.cell + 2 * tabBox.pad) + 2 * shadowPad
            height: tabBox.cell + 30 + 2 * tabBox.pad + 2 * shadowPad
            x: tabBox.screenGeometry.x + (tabBox.screenGeometry.width - width) / 2
            y: tabBox.screenGeometry.y + (tabBox.screenGeometry.height - height) / 2
            readonly property real shadowPad: 30
            // Liquid Glass: the glass effect (kwin/glass, glass.md "Internal windows") reads this
            // shape from KWin-internal windows and draws real glass under the panel; it sets
            // kristallGlassActive while it does, and the panel then drops its opaque fallback fill.
            property var kristallGlass: ({ id: "switcher", x: shadowPad, y: shadowPad, w: width - 2 * shadowPad,
                                           h: height - 2 * shadowPad, radius: 22 })
            property bool kristallGlassActive: false

            // soft layered shadow outside the panel (design.md §7, hud: blur 30, y 10)
            Repeater {
                model: 6
                Rectangle {
                    required property int index
                    readonly property real grow: (index + 1) * 4
                    x: win.shadowPad - grow
                    y: win.shadowPad - grow + 10
                    width: panel.width + 2 * grow
                    height: panel.height + 2 * grow
                    radius: 22 + grow
                    color: "transparent"
                    border.width: 4
                    border.color: Qt.rgba(0, 0, 0, (tabBox.dark ? 0.06 : 0.035) * (6 - index) / 6)
                }
            }
            Rectangle {
                id: panel
                x: win.shadowPad
                y: win.shadowPad
                width: win.width - 2 * win.shadowPad
                height: win.height - 2 * win.shadowPad
                radius: 22
                // on glass: only a light veil for legibility (the glass brings tint and blur)
                color: win.kristallGlassActive ? Qt.rgba(tabBox.material.r, tabBox.material.g, tabBox.material.b, 0.18) : tabBox.material
                border.width: 1
                border.color: tabBox.border

                ListView {
                    id: row
                    x: tabBox.pad
                    y: tabBox.pad
                    width: parent.width - 2 * tabBox.pad
                    height: tabBox.cell
                    orientation: ListView.Horizontal
                    model: tabBox.model
                    interactive: false
                    currentIndex: tabBox.currentIndex
                    clip: true
                    highlightMoveDuration: 100
                    highlight: Rectangle {
                        radius: 16
                        color: tabBox.highlight
                    }
                    delegate: Item {
                        id: entry
                        required property int index
                        required property var model
                        width: tabBox.cell
                        height: tabBox.cell
                        Kirigami.Icon {
                            anchors.centerIn: parent
                            width: tabBox.iconSize
                            height: tabBox.iconSize
                            source: entry.model.icon
                            opacity: entry.model.minimized ? 0.6 : 1
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: tabBox.model.activate(entry.index)
                        }
                        Accessible.role: Accessible.ListItem
                        Accessible.name: tabBox.appName(entry.model.caption)
                    }
                    onCurrentIndexChanged: tabBox.currentIndex = currentIndex
                    Connections {
                        target: tabBox
                        function onCurrentIndexChanged() { row.currentIndex = tabBox.currentIndex; }
                    }
                }
                Text {        // the chosen app's name, under its icon (as on the Mac)
                    readonly property real centre: row.currentItem ? row.x + row.currentItem.x - row.contentX + tabBox.cell / 2 : parent.width / 2
                    y: tabBox.pad + tabBox.cell + 4
                    width: Math.min(implicitWidth, parent.width - 2 * tabBox.pad)
                    x: Math.max(tabBox.pad, Math.min(parent.width - tabBox.pad - width, centre - width / 2))
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: row.currentItem ? tabBox.appName(row.currentItem.model.caption) : ""
                    color: tabBox.label
                    font.family: "Inter"
                    font.pixelSize: 13
                    font.weight: 600
                    renderType: Text.NativeRendering
                }
            }

            // keys KWin passes on while the switcher holds the keyboard
            Item {
                focus: true
                Keys.onPressed: ev => {
                    const n = row.count;
                    if (ev.key === Qt.Key_Left && n) {
                        row.currentIndex = (row.currentIndex - 1 + n) % n;
                    } else if (ev.key === Qt.Key_Right && n) {
                        row.currentIndex = (row.currentIndex + 1) % n;
                    } else if (ev.key === Qt.Key_Q && row.currentItem) {
                        // quit the highlighted app: ask each of its windows to close
                        for (const w of tabBox.windowsLike(row.currentItem.model.windowId))
                            w.closeWindow();
                    } else if (ev.key === Qt.Key_H && row.currentItem) {
                        // hide it and move on, so releasing the key does not bring it back
                        for (const w of tabBox.windowsLike(row.currentItem.model.windowId))
                            w.minimized = true;
                        if (n > 1)
                            row.currentIndex = (row.currentIndex + 1) % n;
                    } else {
                        return;
                    }
                    ev.accepted = true;
                }
            }
        }
    }
}
