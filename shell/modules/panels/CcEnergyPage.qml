// SPDX-License-Identifier: GPL-3.0-or-later
// Expanded energy module: battery state and the owner-facing power modes
// (Automatisch, Leise, Ausgewogen, Leistung; see PanelsUtil for what "automatic" means).
import QtQuick
import qs.core
import qs.services

Column {
    id: ep
    property string scheme: Theme.scheme
    property var cc: null
    width: PanelMetrics.ccInner
    spacing: 4
    Component.onCompleted: PanelsUtil.refreshStatus()
    Connections {
        target: Power
        function onOnBatteryChanged() { PanelsUtil.refreshStatus(); }
        function onModeChanged() { PanelsUtil.refreshStatus(); }
    }

    CcHeader {
        title: Power.hasBattery ? Strings.t("panels.battery") : Strings.t("panels.energy.mode")
        scheme: ep.scheme
        onBack: ep.cc.back()
    }
    CcItemRow {
        visible: Power.hasBattery
        width: PanelMetrics.ccInner
        icon: PanelsUtil.batteryIcon()
        circle: false
        title: Power.percent + " %"
        subtitle: [PanelsUtil.batteryState(), PanelsUtil.batteryDetail].filter(s => s !== "").join(" · ")
        scheme: ep.scheme
        enabled: false
        opacity: 1
    }
    CcSection { text: Strings.t("panels.energy.mode"); scheme: ep.scheme }
    Repeater {
        model: PanelsUtil.modes
        CcItemRow {
            required property string modelData
            objectName: "cc.energy." + modelData
            width: PanelMetrics.ccInner
            icon: modelData === "auto" ? "sparkle" : modelData === "quiet" ? "leaf" : modelData === "balanced" ? "scales" : "lightning"
            on: PanelsUtil.selectedMode === modelData
            checked: PanelsUtil.selectedMode === modelData
            title: PanelsUtil.modeName(modelData)
            subtitle: modelData === "auto" && PanelsUtil.selectedMode === "auto"
                      ? [Strings.t("panels.energy.now", { mode: PanelsUtil.modeName(Power.mode) }), PanelsUtil.autoReason].filter(s => s !== "").join(" · ")
                      : Strings.t("panels.energy." + modelData + ".hint")
            scheme: ep.scheme
            onActivated: PanelsUtil.chooseMode(modelData)
        }
    }
    CcFooter {
        text: Strings.t("panels.energy.settings")
        kcm: "kcm_powerdevilprofilesconfig"
        scheme: ep.scheme
        onActivated: ep.cc.closeRequested()
    }
}
