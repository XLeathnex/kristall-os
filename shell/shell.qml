// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall Shell — entry point. Run: quickshell -p /usr/share/kristall/shell (kristall-shell.service).
// Owns: per-output menu bar, menu and tooltip hosts, the module loader, the IPC entry point.
// Spec: docs/contracts/shell.md.
//@ pragma Env QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough
import QtQuick
import Quickshell
import Quickshell.Io
import qs.core
import qs.services
import qs.bar
import qs.gallery

ShellRoot {
    id: shell

    readonly property bool safeMode: Quickshell.env("KRISTALL_SHELL_SAFE") === "1"
    readonly property bool testMode: Quickshell.env("KRISTALL_SHELL_TEST") === "1"
    property bool galleryOpen: Quickshell.env("KRISTALL_SHELL_GALLERY") === "1"
    property var loadedModules: ({})     // name -> "loaded" | "failed" | "absent"

    Component.onCompleted: {
        console.info("kristall-shell: starting", safeMode ? "(safe mode: modules off)" : "", "on", Quickshell.screens.length, "output(s)");
        Helper.request("fallback.cleanup", { delay: 20 });
    }
    // a restarted helper forgets the pending cleanup: ask again whenever it (re)starts
    Connections {
        target: Helper
        function onEvent(ev) {
            if (ev && ev.event === "ready")
                Helper.request("fallback.cleanup", { delay: 20 });
        }
    }

    // ---- per output: bar, menu host, tooltip host -------------------------------------------------
    Variants {
        model: Quickshell.screens
        delegate: Component {
            Scope {
                id: perScreen
                required property var modelData
                Bar { modelData: perScreen.modelData }
                MenuHost { screen: perScreen.modelData }
                TooltipHost { screen: perScreen.modelData }
            }
        }
    }

    // ---- modules (modules.list) -------------------------------------------------------------------
    FileView {
        id: registry
        path: Quickshell.shellDir + "/modules.list"
        blockLoading: true
        printErrors: false
        readonly property var names: {
            const t = text();
            return t.split("\n").map(l => l.replace(/#.*/, "").trim()).filter(l => /^[a-z][a-z0-9-]*$/.test(l));
        }
    }
    Variants {
        model: shell.safeMode ? [] : registry.names
        delegate: Component {
            Scope {
                id: mod
                required property string modelData
                readonly property string dir: Quickshell.shellDir + "/modules/" + modelData
                FileView {
                    // existence check without warnings (a module file is never empty)
                    id: moduleFile
                    path: mod.dir + "/Module.qml"
                    blockLoading: true
                    printErrors: false
                }
                FileView {
                    // every module directory carries a qmldir listing its types (shell.md §2):
                    // Quickshell 0.2.1 resolves same-directory types of a module loaded by URL only with it
                    id: qmldirFile
                    path: mod.dir + "/qmldir"
                    blockLoading: true
                    printErrors: false
                }
                readonly property bool present: moduleFile.text().length > 0
                onPresentChanged: if (present) Strings.addFile(mod.dir + "/strings.json")
                Component.onCompleted: {
                    if (present) {
                        Strings.addFile(mod.dir + "/strings.json");
                        if (qmldirFile.text().length === 0)
                            console.warn("kristall-shell: module", mod.modelData, "has no qmldir (required, docs/contracts/shell.md §2): its own types may not resolve");
                    } else {
                        shell._setModule(mod.modelData, "absent");
                    }
                }
                LazyLoader {
                    active: mod.present
                    source: mod.present ? Qt.resolvedUrl("modules/" + mod.modelData + "/Module.qml") : ""
                    onItemChanged: {
                        if (item) {
                            console.info("kristall-shell: module", mod.modelData, "loaded");
                            shell._setModule(mod.modelData, "loaded");
                        }
                    }
                    // a module that does not compile (or whose root throws while being created) ends
                    // with no item: log it once and carry on without it
                    function check() {
                        if (mod.present && !loading && !item && shell.loadedModules[mod.modelData] !== "failed") {
                            console.warn("kristall-shell: module", mod.modelData, "failed to load and is skipped");
                            shell._setModule(mod.modelData, "failed");
                        }
                    }
                    onActiveChanged: Qt.callLater(check)
                    onLoadingChanged: Qt.callLater(check)
                    Component.onCompleted: Qt.callLater(check)
                }
            }
        }
    }
    function _setModule(name, state) {
        const m = Object.assign({}, loadedModules);
        m[name] = state;
        loadedModules = m;
    }

    // ---- gallery (kristall-shellctl gallery toggle) ----------------------------------------------
    LazyLoader {
        active: shell.galleryOpen
        Gallery { screen: Quickshell.screens[0] }
    }

    // ---- global shortcuts the helper owns (press and release: push-to-talk) --------------------------
    // The assistant's key (Alt+Space, the Copilot key) is a kglobalaccel D-Bus action of the helper:
    // press → "assistant invoke shortcut", release → "assistant release <held ms>" (the assistant
    // ends the utterance when the key was held, a tap keeps tap-to-talk). docs/contracts/shell.md §6.
    Connections {
        target: Helper
        function onEvent(ev) {
            if (ev.event !== "shortcut" || ev.action !== "assistant-talk")
                return;
            if (ev.state === "pressed")
                ShellBus.request("assistant", "invoke", "shortcut", "");
            else if (ev.state === "released")
                ShellBus.request("assistant", "release", String(ev.heldMs || 0), "");
        }
    }

    // ---- the glass effect switched itself off after crashes (glass.md §7): tell the owner once ------
    // One gentle notification per login session (a marker in the runtime directory, which the
    // next boot clears together with the effect's own record).
    FileView {
        id: glassNotified
        path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/kristall/glass-guard-notified"
        blockLoading: true
        printErrors: false
    }
    readonly property bool glassGuardTripped: GlassClient.state === "disabled" && GlassClient.reason === "crash-guard"
    onGlassGuardTrippedChanged: if (glassGuardTripped) Qt.callLater(_notifyGlassGuard)
    function _notifyGlassGuard() {
        if (!glassGuardTripped || glassNotified.text().length > 0)
            return;
        glassNotified.setText(String(Date.now()));
        Quickshell.execDetached(["notify-send", "--app-name=" + Strings.t("glass.guard.app"), "--icon=dialog-information",
                                 "--urgency=low", Strings.t("glass.guard.title"), Strings.t("glass.guard.body")]);
    }

    // ---- requests the shell itself handles ----------------------------------------------------------
    Connections {
        target: ShellBus
        function onRequested(target, action, arg, output) {
            if (target === "gallery")
                shell.galleryOpen = action === "toggle" ? !shell.galleryOpen : action === "show";
            else if (target === "bar" && (action === "focus" || action === "open-menu"))
                shell._focusBar(output, parseInt(arg || "0"));
            else if (target === "shell" && action === "close-menus")
                Menus.close("ipc");
        }
    }
    function _focusBar(output, index) {
        // the bar of the requested output, else of the front window's output, else the first
        const want = output || (Bridge.frontWindow ? Bridge.frontWindow.output : "") || (Quickshell.screens.length ? Quickshell.screens[0].name : "");
        BarRegistry.focus(want, index);
    }

    // ---- IPC: kristall-shellctl <target> <action> [arg] [output] ----------------------------------
    IpcHandler {
        target: "shell"
        function request(target: string, action: string, arg: string, output: string): string {
            ShellBus.request(target, action, arg, output);
            return "ok";
        }
        // what kristall-shellctl uses: arg and output as "v" + percent-encoded UTF-8, because
        // quickshell's command line parser reads some arguments itself ("[1, 2]" as a list, "-x" as
        // an option) and mishandles empty ones
        function requestEncoded(target: string, action: string, arg: string, output: string): string {
            let a, o;
            if (!arg.startsWith("v") || !output.startsWith("v"))
                return "bad encoding";
            try {
                a = decodeURIComponent(arg.substring(1));
                o = decodeURIComponent(output.substring(1));
            } catch (e) {
                return "bad encoding";
            }
            ShellBus.request(target, action, a, o);
            return "ok";
        }
        function status(): string {
            return JSON.stringify({
                safeMode: shell.safeMode, modules: shell.loadedModules, outputs: Quickshell.screens.map(s => s.name),
                glass: GlassClient.state, bridge: Bridge.connected, helper: Helper.ready, menuOpen: Menus.current !== null,
                handled: ShellBus.handled
            });
        }
    }

    // ---- test hooks (KRISTALL_SHELL_TEST=1 only) ---------------------------------------------------
    LazyLoader {
        active: shell.testMode
        TestHooks {}
    }
}
