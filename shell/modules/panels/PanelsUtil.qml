// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import qs.services


// The energy module (Control Center, Notification Centre's battery widget), on the power
// component's contract (docs/contracts/power.md):
//  * the three modes are the power-profiles API (shell Power service: Leise = power-saver,
//    Ausgewogen = balanced, Leistung = performance); picking one by hand is the owner's choice
//    and sticks until they pick Automatisch;
//  * "Automatisch" (the default) = `kristall-power mode auto` (§7.3); it is shown as chosen when
//    the session daemon's $XDG_RUNTIME_DIR/kristall/power.json says automatic && !manual;
//  * battery details beyond UPower (health, present draw, why a mode is active) come from
//    `kristall-power status --json` (§7.2), run only when the expanded module is opened.
// Without the power component (no power.json, no kristall-power) only the three modes are offered.
Singleton {
    id: root

    readonly property string tool: Quickshell.env("KRISTALL_POWER_CMD") || "kristall-power"

    // ---- the session daemon's state (inotify on the file; no polling) -------------------------
    property var daemon: null
    FileView {
        id: stateFile
        path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/kristall/power.json"
        printErrors: false
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                root.daemon = JSON.parse(text());
            } catch (e) {
                root.daemon = null;
            }
        }
        onLoadFailed: root.daemon = null
    }
    // a mode change is also when the daemon rewrites its file: re-read then as well
    Connections {
        target: Power
        function onModeChanged() { stateFile.reload(); }
    }

    readonly property bool hasAutomatic: daemon !== null && daemon.schema === 1
    readonly property bool automatic: hasAutomatic && daemon.automatic === true && !daemon.manual
    readonly property string selectedMode: automatic ? "auto" : Power.mode
    readonly property var modes: (hasAutomatic ? ["auto"] : []).concat(Power.hasPerformance ? ["quiet", "balanced", "performance"] : ["quiet", "balanced"])

    function chooseMode(m) {
        if (m === "auto") {
            Quickshell.execDetached([tool, "mode", "auto"]);
            Qt.callLater(() => stateFile.reload());
        } else {
            Power.setMode(m);
        }
    }
    function modeName(m) {
        return m === "auto" ? Strings.t("panels.energy.auto") : Strings.t("panels.energy." + m);
    }
    // why the effective mode differs from the base, in the owner's words
    readonly property string autoReason: {
        if (!automatic || !daemon)
            return "";
        switch (daemon.reason) {
        case "auto-game": return Strings.t("panels.energy.reason.game");
        case "auto-heavy-app": return Strings.t("panels.energy.reason.heavy");
        case "auto-low-battery": return Strings.t("panels.energy.reason.lowBattery");
        }
        return "";
    }
    // automatic mode holding Leise because the laptop runs on battery (power contract: auto-battery)
    readonly property bool autoBattery: automatic && daemon !== null && daemon !== undefined && daemon.reason === "auto-battery"
    // the line that names the chosen mode: "Automatisch · leise im Akkubetrieb" for auto-battery
    function chosenModeText() {
        return selectedMode === "auto" && autoBattery ? Strings.t("panels.energy.autoBattery") : modeName(selectedMode);
    }

    // ---- kristall-power status --json, on demand ----------------------------------------------
    property var status: null
    function refreshStatus() {
        if (!statusProc.running)
            statusProc.running = true;
    }
    Process {
        id: statusProc
        command: [root.tool, "status", "--json"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.status = JSON.parse(text);
                } catch (e) {
                    root.status = null;
                }
            }
        }
        onExited: code => { if (code !== 0) root.status = null; }
    }
    readonly property string batteryDetail: {
        const s = status;
        if (!s || !s.battery)
            return "";
        const parts = [];
        if (s.battery.health_percent)
            parts.push(Strings.t("panels.battery.health", { n: Math.round(s.battery.health_percent) }));
        if (s.draw && s.draw.watts)
            parts.push(Strings.t("panels.battery.draw", { w: Number(s.draw.watts).toLocaleString(Strings.locale, "f", 1) }));
        return parts.join(" · ");
    }

    function batteryIcon() {
        if (!Power.hasBattery)
            return "fill/lightning";
        if (Power.charging)
            return "fill/battery-charging";
        const p = Power.percent;
        return p >= 88 ? "fill/battery-full" : p >= 60 ? "fill/battery-high" : p >= 35 ? "fill/battery-medium" : p >= 12 ? "fill/battery-low" : "fill/battery-warning";
    }
    function batteryState() {
        if (!Power.hasBattery)
            return "";
        if (Power.full)
            return Strings.t("panels.battery.full");
        if (Power.charging)
            return Power.timeToFull > 0 ? Strings.t("panels.battery.untilFull", { time: Fmt.duration(Power.timeToFull) }) : Strings.t("panels.battery.charging");
        if (!Power.onBattery)
            return Strings.t("panels.battery.onAdapter");
        return Power.timeToEmpty > 0 ? Strings.t("panels.battery.remaining", { time: Fmt.duration(Power.timeToEmpty) }) : Strings.t("panels.battery.onBattery");
    }
    function energySummary() {
        const parts = [chosenModeText()];
        const s = batteryState();
        if (s !== "")
            parts.push(s);
        return parts.join(" · ");
    }
}
