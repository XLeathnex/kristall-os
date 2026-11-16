// SPDX-License-Identifier: GPL-3.0-or-later
// The `dock` module (docs/contracts/shell.md §2): the Dock on the main display (the bridge's
// primary output, else the first screen), its context menus, the Empty Trash alert.
// Requests (ShellBus target "dock"): show, hide (auto-hide reveal/conceal), bounce <app id>.
// Settings: `dock` (size, magnification, magnifiedSize, autoHide, minimizeToApp, pinned) — live.
import QtQuick
import Quickshell
import qs.core
import qs.services

Scope {
    id: dockModule

    readonly property var mainScreen: {
        const screens = Quickshell.screens;
        if (!screens.length)
            return null;
        for (const o of Bridge.outputs)
            if (o.primary)
                for (const s of screens)
                    if (s.name === o.name)
                        return s;
        return screens[0];
    }

    DockModel { id: dockEntries }
    Places { id: dockPlaces }
    LauncherEntries { id: dockLauncher }

    LazyLoader {
        id: dockLoader
        active: dockModule.mainScreen !== null
        Dock {
            screen: dockModule.mainScreen
            dockModel: dockEntries
            places: dockPlaces
            launcher: dockLauncher
            onEmptyTrashRequested: dockModule.alertOpen = true
        }
    }

    property bool alertOpen: false
    onAlertOpenChanged: if (dockLoader.item) dockLoader.item.alertOpen = alertOpen
    LazyLoader {
        active: dockModule.alertOpen
        ConfirmDialog {
            screen: dockModule.mainScreen
            title: Strings.t("dock.emptyTrashTitle")
            message: Strings.t("dock.emptyTrashMessage")
            actionText: Strings.t("dock.emptyTrash")
            iconSource: AppCatalog.iconUrl("user-trash-full")
            onAccepted: { dockPlaces.emptyTrash(); dockModule.alertOpen = false; }
            onRejected: dockModule.alertOpen = false
        }
    }

    Connections {
        target: ShellBus
        function onRequested(target, action, arg, output) {
            if (target !== "dock")
                return;
            const d = dockLoader.item;
            if (action === "show" && d)
                d.reveal();
            else if (action === "hide" && d) {
                d.revealed = !d.autoHide;
            } else if (action === "bounce" && arg)
                dockEntries.noteLaunch(AppCatalog.keyForAppId(arg));
        }
    }
    Component.onCompleted: ShellBus.claim("dock")

    // test hooks (KRISTALL_SHELL_TEST=1 only)
    LazyLoader {
        active: Quickshell.env("KRISTALL_SHELL_TEST") === "1"
        DockTestHooks { dock: dockLoader.item; model: dockEntries; places: dockPlaces }
    }
}
