// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import qs.core
import qs.services


// Context menus of the panels, in the shell's glass menus (shell.md §4).
Singleton {
    function cardMenu(card, screenName) {
        const e = card.entry;
        if (!e)
            return;
        const muted = Notifs.isMuted(e.appKey);
        Menus.open({
            screen: screenName,
            rect: Menus.itemRect(card, card.originX, card.originY),
            align: "right",
            owner: "panels:notification:" + e.key,
            source: Menus.list([
                { label: Strings.t("panels.notifications.clear"), action: () => Notifs.remove(e) },
                { label: Strings.t("panels.notifications.clearApp", { app: e.displayName }), action: () => Notifs.clearGroup(e.appKey) },
                { type: "separator" },
                { label: muted ? Strings.t("panels.notifications.unmute", { app: e.displayName }) : Strings.t("panels.notifications.mute", { app: e.displayName }),
                  action: () => Notifs.setMuted(e.appKey, !muted) }
            ])
        });
    }
}
