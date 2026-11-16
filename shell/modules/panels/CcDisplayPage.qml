// SPDX-License-Identifier: GPL-3.0-or-later
// Expanded Display module: brightness, light/dark/automatic appearance, Night Light.
import QtQuick
import qs.core
import qs.services

Column {
    id: dp
    property string scheme: Theme.scheme
    property var cc: null
    width: PanelMetrics.ccInner
    spacing: 8

    CcHeader {
        title: Strings.t("panels.display")
        scheme: dp.scheme
        onBack: dp.cc.back()
    }
    KCapsuleSlider {
        objectName: "cc.display.page.slider"
        visible: Hw.hasBacklight
        x: 6
        width: parent.width - 12
        icon: "fill/sun"
        label: Strings.t("panels.display")
        value: Hw.brightness
        scheme: dp.scheme
        onMoved: v => Hw.setBrightness(v)
    }
    CcSection { text: Strings.t("panels.display.appearance"); scheme: dp.scheme }
    KSegmented {
        objectName: "cc.display.appearance"
        x: 6
        width: parent.width - 12
        scheme: dp.scheme
        model: [Strings.t("panels.appearance.light"), Strings.t("panels.appearance.dark"), Strings.t("panels.appearance.auto")]
        id: appearanceSegments
        currentIndex: ["light", "dark", "auto"].indexOf(Settings.get("appearance.theme", "auto"))
        onActivated: i => Settings.set("appearance.theme", ["light", "dark", "auto"][i])
    }
    CcItemRow {
        visible: Hw.hasNightLight
        objectName: "cc.display.nightlight"
        width: PanelMetrics.ccInner
        icon: "fill/sun-horizon"
        on: Hw.nightLightOn
        title: Strings.t("panels.nightLight")
        subtitle: Strings.t("panels.nightLight.hint")
        scheme: dp.scheme
        onActivated: Hw.setNightLight(!Hw.nightLightOn)
    }
    CcFooter {
        text: Strings.t("panels.display.settings")
        kcm: "kcm_kscreen"
        scheme: dp.scheme
        onActivated: dp.cc.closeRequested()
    }
}
