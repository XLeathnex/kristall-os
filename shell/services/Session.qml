// SPDX-License-Identifier: GPL-3.0-or-later
// Session actions. Restart / shut down / log out show Plasma's confirmation (with countdown);
// lock and sleep act at once. All go through the helper (D-Bus), never a terminal.
pragma Singleton
import QtQuick
import Quickshell

Singleton {
    function lock() { Helper.request("session", { action: "lock" }); }
    function sleep() { Helper.request("session", { action: "sleep" }); }
    function restart() { Helper.request("session", { action: "restart" }); }
    function shutDown() { Helper.request("session", { action: "shutdown" }); }
    function logOut() { Helper.request("session", { action: "logout" }); }
    function restartToUpdate() { Helper.request("session", { action: "restart-update" }); }

    // System Settings opens on a Kristall page (setup contract: kcm_kristall_<page>); KDE's
    // landing page is hidden on purpose, so plain `systemsettings` would open blank.
    readonly property string defaultSettingsPage: "kcm_kristall_appearance"
    function openSystemSettings(module) {
        Quickshell.execDetached(["systemsettings", module ? module : defaultSettingsPage]);
    }
    function aboutThisComputer() {
        Quickshell.execDetached(["systemsettings", "kcm_kristall_about"]);
    }

    readonly property string userName: Quickshell.env("USER") || Quickshell.env("LOGNAME") || (Quickshell.env("HOME") || "").split("/").pop()
}
