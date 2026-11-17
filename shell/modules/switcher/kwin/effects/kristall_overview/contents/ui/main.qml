// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall Overview — the Mac's Mission Control on KWin: every window of the current desktop laid
// out side by side over the dimmed wallpaper, the Dock left where it is. No desktop bar (Kristall
// uses one desktop), no search field (Search is ⌘Space), no captions under the windows (the Mac
// shows none; KWin's would read "Home — Dolphin"). A small declarative KWin effect built on KWin's
// own window layout (org.kde.kwin.private.effects: WindowHeap, the layout of KWin's Overview), so
// arranging, the open/close animation and keyboard selection are KWin's. Replaces KWin's Overview
// effect (kwinrc: overviewEnabled=false), keeps its keys: Meta+W, Control+↑ (kglobalaccel file),
// four fingers up on the touchpad. Click a window to bring it forward; Escape or a click on the
// wallpaper closes. Idle: nothing runs while it is closed.
import QtQuick
import org.kde.kwin as KWinComponents
import org.kde.kwin.private.effects

KWinComponents.SceneEffect {
    id: effect

    readonly property int animationDuration: 250
    property bool closing: false
    // what KWin's WindowHeapDelegate reads from its effect
    property bool gestureInProgress: false
    property real partialActivationFactor: 0
    function checkItemDraggedOutOfScreen(item) {}
    function checkItemDroppedOutOfScreen(pos, item) {}

    function open() {
        closeTimer.stop();
        closing = false;
        visible = true;
    }
    function close() {
        if (!visible || closing)
            return;
        closing = true;
        closeTimer.restart();
    }
    function toggle() {
        if (visible && !closing)
            close();
        else
            open();
    }
    Timer {
        id: closeTimer
        interval: effect.animationDuration
        onTriggered: {
            effect.visible = false;
            effect.closing = false;
        }
    }

    delegate: Item {
        id: container
        readonly property QtObject effect: KWinComponents.SceneView.effect
        readonly property QtObject targetScreen: KWinComponents.SceneView.screen
        property bool organized: false
        // the Dock's height on this screen (kept visible, windows are laid out above it)
        property real dockTop: height

        focus: true
        Keys.onEscapePressed: effect.close()
        Component.onCompleted: organized = true
        Connections {
            target: effect
            function onClosingChanged() {
                if (effect.closing)
                    container.organized = false;
            }
        }

        KWinComponents.DesktopBackground {
            activity: KWinComponents.Workspace.currentActivity
            desktop: KWinComponents.Workspace.currentDesktop
            outputName: container.targetScreen.name
        }
        // Kristall's overlay dim (as behind Apps and the Setup Assistant): the wallpaper stays
        // recognisable, the windows stand out
        Rectangle {
            anchors.fill: parent
            color: "black"
            opacity: container.organized ? 0.28 : 0
            Behavior on opacity {
                NumberAnimation { duration: effect.animationDuration; easing.type: Easing.OutCubic }
            }
            TapHandler {
                onTapped: effect.close()
            }
        }

        WindowHeap {
            id: heap
            x: 0
            y: 0
            width: parent.width
            height: Math.max(parent.height / 2, container.dockTop)
            focus: true
            padding: 48
            animationDuration: effect.animationDuration
            animationEnabled: true
            organized: container.organized
            model: KWinComponents.WindowFilterModel {
                activity: KWinComponents.Workspace.currentActivity
                desktop: KWinComponents.Workspace.currentDesktop
                screenName: container.targetScreen.name
                windowModel: stackModel
                minimizedWindows: false
                windowType: ~KWinComponents.WindowFilterModel.Dock & ~KWinComponents.WindowFilterModel.Desktop
                            & ~KWinComponents.WindowFilterModel.Notification & ~KWinComponents.WindowFilterModel.CriticalNotification
            }
            delegate: WindowHeapDelegate {
                id: thumb
                windowHeap: heap
                windowTitleVisible: false
                closeButtonVisible: false
                contentItemParent: container
                partialActivationFactor: container.organized ? 1 : 0
                Behavior on partialActivationFactor {
                    SequentialAnimation {
                        PropertyAction { target: thumb; property: "gestureInProgress"; value: true }
                        NumberAnimation { duration: effect.animationDuration; easing.type: Easing.OutCubic }
                        PropertyAction { target: thumb; property: "gestureInProgress"; value: false }
                    }
                }
            }
            onActivated: effect.close()
        }

        // the Dock (and only the Dock: the menu bar steps aside, as on the Mac) stays on screen.
        // The shell's surfaces are layer-shell windows KWin lists as normal windows that skip the
        // switcher; the Dock is the one along the bottom edge, less than a third of the height.
        Instantiator {
            model: KWinComponents.WindowFilterModel {
                desktop: KWinComponents.Workspace.currentDesktop
                screenName: container.targetScreen.name
                windowModel: stackModel
            }
            KWinComponents.WindowThumbnail {
                readonly property var g: container.targetScreen.geometry
                readonly property bool isDock: model.window.skipSwitcher && model.window.resourceName === "quickshell"
                                               && model.window.y + model.window.height >= g.y + g.height - 1
                                               && model.window.height < g.height / 3
                wId: model.window.internalId
                x: model.window.x - g.x
                y: model.window.y - g.y
                width: model.window.width
                height: model.window.height
                z: 10 + model.window.stackingOrder
                visible: isDock && !model.window.hidden
                onIsDockChanged: if (isDock) container.dockTop = Math.min(container.dockTop, y)
                Component.onCompleted: if (isDock) container.dockTop = Math.min(container.dockTop, y)
            }
            onObjectAdded: (index, object) => object.parent = container
        }

        KWinComponents.WindowModel {
            id: stackModel
        }
    }

    KWinComponents.ShortcutHandler {
        name: "Kristall Overview"
        text: Qt.locale().name.substring(0, 2) === "de" ? "Übersicht" : "Overview"
        sequence: "Meta+W"
        onActivated: effect.toggle()
    }
    KWinComponents.SwipeGestureHandler {
        direction: KWinComponents.SwipeGestureHandler.Direction.Up
        fingerCount: 4
        onActivated: effect.open()
    }
    KWinComponents.SwipeGestureHandler {
        direction: KWinComponents.SwipeGestureHandler.Direction.Down
        fingerCount: 4
        onActivated: effect.close()
    }
}
