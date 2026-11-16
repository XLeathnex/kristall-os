// SPDX-License-Identifier: GPL-3.0-or-later
// Battery, power source and the three owner-facing power modes.
// Leise / Ausgewogen / Leistung map one-to-one onto the power-profiles D-Bus API
// (power-saver / balanced / performance) that tuned-ppd provides; the `power` component decides
// what each profile means. Uses Quickshell's native UPower and PowerProfiles services.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Services.UPower

Singleton {
    id: root

    readonly property var device: UPower.displayDevice
    // a laptop battery is present (UPower's display device is a battery and is present)
    readonly property bool hasBattery: device !== null && device.ready && device.isLaptopBattery && device.isPresent
    readonly property real percent: hasBattery ? Math.round(device.percentage * (device.percentage <= 1 ? 100 : 1)) : 0
    readonly property bool onBattery: UPower.onBattery
    readonly property bool charging: hasBattery && (device.state === UPowerDeviceState.Charging || device.state === UPowerDeviceState.PendingCharge)
    readonly property bool full: hasBattery && device.state === UPowerDeviceState.FullyCharged
    readonly property real timeToEmpty: hasBattery ? device.timeToEmpty : 0   // seconds, 0 = unknown
    readonly property real timeToFull: hasBattery ? device.timeToFull : 0

    // "quiet" | "balanced" | "performance"
    readonly property var modes: ["quiet", "balanced", "performance"]
    readonly property string mode: {
        switch (PowerProfiles.profile) {
        case PowerProfile.PowerSaver: return "quiet";
        case PowerProfile.Performance: return "performance";
        default: return "balanced";
        }
    }
    readonly property bool hasPerformance: PowerProfiles.hasPerformanceProfile

    function setMode(m) {
        PowerProfiles.profile = m === "quiet" ? PowerProfile.PowerSaver : m === "performance" ? PowerProfile.Performance : PowerProfile.Balanced;
    }

    function modeName(m) {
        return Strings.t("power.mode." + m);
    }
}
