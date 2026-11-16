// SPDX-License-Identifier: GPL-3.0-or-later
// Energy: the automatic mode in one line (`power.automatic`), and a charge limit if the hardware
// has one (`power.chargeLimit`; the power component applies it, docs/contracts/power.md §8).
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    icon: "battery-charging"
    title: Strings.t("setup.energy.title")
    subtitle: Strings.t("setup.energy.subtitle")
    cardWidth: 600
    implicitHeight: col.implicitHeight

    readonly property var status: ctl ? ctl.helper.power : null
    readonly property bool hasBattery: Power.hasBattery || (status !== null && status.battery !== null && status.battery !== undefined)
    readonly property var limit: status && status.charge_limit ? status.charge_limit : null
    readonly property bool canLimit: limit !== null && limit.supported === true
    readonly property bool firmwareOnly: canLimit && (limit.methods || []).every(m => m.method === "long-life")
    readonly property bool automatic: ctl ? ctl.value("power.automatic", true) === true : true
    readonly property int chargeLimit: ctl ? Number(ctl.value("power.chargeLimit", 100)) : 100

    function primary() {
        if (!automatic)
            ctl.put("power.automatic", true);   // Continue = the recommended automatic mode
        ctl.next();
    }

    component Card: Rectangle {
        id: cardItem
        property string scheme: Theme.scheme
        property alias title: t.text
        property alias note: n.text
        default property alias trailing: holder.data
        width: parent ? parent.width : 0
        height: Math.max(64, textCol.implicitHeight + 28)
        radius: 14
        color: Theme.color(cardItem.scheme, "fill")
        Column {
            id: textCol
            x: 16
            width: parent.width - 32 - 64
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            KText { id: t; emphasized: true; scheme: cardItem.scheme }
            KText { id: n; width: parent.width; wrapMode: Text.WordWrap; textStyle: "caption1"; level: "secondaryLabel"; scheme: cardItem.scheme }
        }
        Item { id: holder; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; width: childrenRect.width; height: childrenRect.height }
    }

    Column {
        id: col
        width: parent.width
        spacing: 12
        Card {
            scheme: st.scheme
            title: Strings.t("setup.energy.automatic")
            note: Strings.t("setup.energy.automaticNote")
            KToggle {
                objectName: "setup.energy.automatic"
                checked: st.automatic
                label: Strings.t("setup.energy.automatic")
                scheme: st.scheme
                onToggled: v => st.ctl.put("power.automatic", v)
            }
        }
        Card {
            scheme: st.scheme
            visible: st.canLimit
            title: Strings.t("setup.energy.limit")
            note: st.firmwareOnly ? Strings.t("setup.energy.limitFirmware") : Strings.t("setup.energy.limitNote")
            KToggle {
                objectName: "setup.energy.limit"
                checked: st.chargeLimit < 100
                label: Strings.t("setup.energy.limit")
                scheme: st.scheme
                onToggled: v => st.ctl.put("power.chargeLimit", v ? 80 : 100)
            }
        }
        KText {
            visible: !st.hasBattery
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: Strings.t("setup.energy.noBattery")
            textStyle: "callout"
            level: "secondaryLabel"
            scheme: st.scheme
        }
    }
}
