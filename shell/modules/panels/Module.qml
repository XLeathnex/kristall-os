// SPDX-License-Identifier: GPL-3.0-or-later
// The `panels` module (docs/contracts/shell.md §2): Control Center, notifications (banners and
// Notification Centre) and the heads-up displays for volume, brightness and keyboard backlight.
// Requests (ShellBus target "panels"): toggle-control-center, show-control-center,
// hide-control-center, toggle-notifications, show-notifications, hide-notifications,
// show-hud (volume|mute|brightness|kbd|mic), focus (on|off|<minutes>), close.
// Surfaces exist only while something is shown (idle costs nothing); see README.md.
import QtQuick
import Quickshell
import qs.core
import qs.services

Scope {
    id: panels

    readonly property bool testMode: Quickshell.env("KRISTALL_SHELL_TEST") === "1"

    // what is open where ("" = closed)
    property string ccOutput: ""
    property var ccAnchor: null
    property string ncOutput: ""
    property var hud: null              // {kind, value (0..1), text, icon, output, serial}
    property int _hudSerial: 0

    readonly property string firstScreen: Quickshell.screens.length ? Quickshell.screens[0].name : ""
    // banners and HUDs appear where the owner is working: the front window's output, else the first
    readonly property string mainOutput: {
        const f = Bridge.frontWindow;
        if (f && f.output && Quickshell.screens.some(s => s.name === f.output))
            return f.output;
        return firstScreen;
    }
    onMainOutputChanged: Notifs.bannerOutput = mainOutput
    Component.onCompleted: {
        ShellBus.claim("panels");
        Notifs.bannerOutput = mainOutput;
        // read the symbols once now, so the first opening of Control Center has no empty frames
        for (const n of ["bold/bluetooth", "bold/caret-left", "bold/caret-right", "bold/check", "bold/network", "bold/wifi-high", "bold/wifi-low", "bold/wifi-medium", "bold/wifi-none", "bold/wifi-slash", "bold/x", "fill/battery-charging", "fill/battery-full", "fill/battery-high", "fill/battery-low", "fill/battery-medium", "fill/battery-warning", "fill/bell", "fill/circle-half", "fill/info", "fill/keyboard", "fill/lightning", "fill/lock-simple", "fill/microphone", "fill/microphone-slash", "fill/moon", "fill/paper-plane-tilt", "fill/pause", "fill/play", "fill/skip-back", "fill/skip-forward", "fill/speaker-simple-high", "fill/speaker-simple-low", "fill/speaker-simple-none", "fill/speaker-simple-slash", "fill/sun", "fill/sun-horizon"])
            Icons.url(n, "#000000");
        console.info("kristall-panels: ready (notifications, Control Center, HUD)");
    }

    function _out(output) {
        return output && Quickshell.screens.some(s => s.name === output) ? output : (mainOutput || firstScreen);
    }

    function showControlCenter(output, arg) {
        const o = _out(output);
        closeNotifications();
        Menus.close("replaced");
        let a = null;
        try {
            a = arg ? JSON.parse(arg) : null;
        } catch (e) {
            a = null;
        }
        ccAnchor = a && a.w !== undefined ? a : null;
        ccOutput = o;
    }
    function closeControlCenter() {
        ccOutput = "";
    }
    function showNotifications(output) {
        const o = _out(output);
        closeControlCenter();
        Menus.close("replaced");
        Notifs.hideAllBanners();
        ncOutput = o;
    }
    function closeNotifications() {
        ncOutput = "";
    }

    onCcOutputChanged: {
        const o = Object.assign({}, ShellBus.open);
        for (const s of Quickshell.screens)
            if (ShellBus.isOpen("control-center", s.name) && s.name !== ccOutput)
                ShellBus.setOpen("control-center", s.name, false);
        if (ccOutput !== "")
            ShellBus.setOpen("control-center", ccOutput, true);
        else if (o["control-center"] !== undefined)
            ShellBus.setOpen("control-center", "", false);
    }
    onNcOutputChanged: {
        Notifs.centerOpen = ncOutput !== "";
        if (ncOutput !== "")
            ShellBus.setOpen("notifications", ncOutput, true);
        else
            ShellBus.setOpen("notifications", "", false);
    }

    function showHud(kind, value, text, icon) {
        _hudSerial++;
        hud = { kind: kind, value: value, text: text || "", icon: icon || "", output: mainOutput, serial: _hudSerial };
    }

    Connections {
        target: ShellBus
        function onRequested(target, action, arg, output) {
            if (target === "shell" && action === "close-menus") {
                panels.closeControlCenter();
                panels.closeNotifications();
                return;
            }
            if (target !== "panels")
                return;
            switch (action) {
            case "toggle-control-center":
                if (panels.ccOutput !== "" && (output === "" || output === panels.ccOutput))
                    panels.closeControlCenter();
                else
                    panels.showControlCenter(output, arg);
                break;
            case "show-control-center": panels.showControlCenter(output, arg); break;
            case "hide-control-center": panels.closeControlCenter(); break;
            case "toggle-notifications":
                if (panels.ncOutput !== "" && (output === "" || output === panels.ncOutput))
                    panels.closeNotifications();
                else
                    panels.showNotifications(output);
                break;
            case "show-notifications": panels.showNotifications(output); break;
            case "hide-notifications": panels.closeNotifications(); break;
            case "close":
                panels.closeControlCenter();
                panels.closeNotifications();
                break;
            case "focus":
                // Do Not Disturb: arg "on" (until switched off), "off", or a number of minutes.
                // The state itself is the setting panels.focus.until (README), so this is a shortcut.
                if (arg === "off")
                    Notifs.setDnd(0);
                else if (arg === "" || arg === "on")
                    Notifs.setDnd(-1);
                else if (parseInt(arg) > 0)
                    Notifs.setDnd(Date.now() + parseInt(arg) * 60000);
                break;
            case "show-hud":
                panels.hudFor(arg || "volume", -1, "", "");
                break;
            }
        }
        // another popover of the shell opened (search, apps, assistant …): ours close
        function onOpenChanged() {
            for (const k of ["search", "apps", "assistant", "switcher"]) {
                if (ShellBus.open[k] !== undefined) {
                    panels.closeControlCenter();
                    panels.closeNotifications();
                }
            }
        }
    }
    Connections {
        target: Menus
        function onOpened(owner) {
            // a menu (bar, Dock, tray …) replaces our panels, as a Mac menu replaces Control Center
            if (!String(owner).startsWith("panels:")) {
                panels.closeControlCenter();
                panels.closeNotifications();
            }
        }
    }

    // ---- HUD from the on-screen displays plasmashell announces (keys) ------------------------------
    function hudFor(kind, percent, text, icon) {
        // live values from our services; the announced percentage only where we have none
        switch (kind) {
        case "volume":
        case "mute":
            showHud("volume", Audio.available ? (Audio.muted ? 0 : Audio.volume) : Math.max(0, percent) / 100, text, icon);
            break;
        case "brightness":
            showHud("brightness", Hw.hasBacklight ? Hw.brightness : Math.max(0, percent) / 100, text, icon);
            break;
        case "kbd":
            showHud("kbd", Hw.hasKbdLight ? Hw.kbdLevel : Math.max(0, percent) / 100, text, icon);
            break;
        case "mic":
            showHud("mic", Math.max(0, percent) / 100, text, icon);
            break;
        default:
            showHud("text", -1, text, icon);
        }
    }
    Connections {
        target: PanelsHelper
        function onOsd(ev) {
            const icon = ev.icon || "";
            let kind = "text";
            if (icon.startsWith("audio-volume"))
                kind = ev.progress ? "volume" : "mute";
            else if (icon.startsWith("microphone"))
                kind = "mic";
            else if (icon.indexOf("keyboard-brightness") >= 0 || icon === "input-keyboard-brightness")
                kind = "kbd";
            else if (icon.indexOf("brightness") >= 0)
                kind = "brightness";
            panels.hudFor(kind, ev.progress ? Math.round(100 * ev.percent / Math.max(1, ev.max)) : -1, ev.text || "", icon);
        }
    }

    // ---- surfaces, per output --------------------------------------------------------------------
    Variants {
        model: Quickshell.screens
        delegate: Component {
            Scope {
                id: perScreen
                required property var modelData
                readonly property string screenName: modelData.name

                property bool ccShown: false
                readonly property bool ccWanted: panels.ccOutput === screenName
                onCcWantedChanged: if (ccWanted) ccShown = true
                LazyLoader {
                    active: perScreen.ccShown
                    ControlCenter {
                        screen: perScreen.modelData
                        open: perScreen.ccWanted
                        anchorRect: panels.ccAnchor
                        onFinished: perScreen.ccShown = false
                        onCloseRequested: panels.closeControlCenter()
                    }
                }

                property bool ncShown: false
                readonly property bool ncWanted: panels.ncOutput === screenName
                onNcWantedChanged: if (ncWanted) ncShown = true
                LazyLoader {
                    active: perScreen.ncShown
                    NotificationCenter {
                        screen: perScreen.modelData
                        open: perScreen.ncWanted
                        onFinished: perScreen.ncShown = false
                        onCloseRequested: panels.closeNotifications()
                    }
                }

                LazyLoader {
                    active: Notifs.banners.length > 0 && panels.mainOutput === perScreen.screenName
                    Banners {
                        screen: perScreen.modelData
                    }
                }

                property bool hudShown: false
                readonly property bool hudWanted: panels.hud !== null && panels.hud.output === screenName
                onHudWantedChanged: if (hudWanted) hudShown = true
                LazyLoader {
                    active: perScreen.hudShown
                    Hud {
                        screen: perScreen.modelData
                        hud: panels.hud
                        onFinished: {
                            perScreen.hudShown = false;
                            if (panels.hud && panels.hud.output === perScreen.screenName)
                                panels.hud = null;
                        }
                    }
                }
            }
        }
    }

    // ---- test hooks (KRISTALL_SHELL_TEST=1 only) ----------------------------------------------------
    LazyLoader {
        active: panels.testMode
        PanelsTestHooks {
            module: panels
        }
    }
}
