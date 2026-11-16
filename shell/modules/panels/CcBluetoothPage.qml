// SPDX-License-Identifier: GPL-3.0-or-later
// Expanded Bluetooth module: switch, paired devices (connected first) with their battery where the
// device reports it; a click connects or disconnects.
import QtQuick
import Quickshell
import Quickshell.Bluetooth
import qs.core
import qs.services

Column {
    id: bp
    property string scheme: Theme.scheme
    property var cc: null
    width: PanelMetrics.ccInner
    spacing: 4

    CcHeader {
        title: Strings.t("panels.bt")
        scheme: bp.scheme
        hasToggle: true
        toggleName: "cc.bt.switch"
        checked: BluetoothStatus.enabled
        onToggled: on => BluetoothStatus.setEnabled(on)
        onBack: bp.cc.back()
    }
    CcNote {
        visible: !BluetoothStatus.enabled
        text: Strings.t("panels.bt.isOff")
        scheme: bp.scheme
    }
    CcSection {
        visible: BluetoothStatus.enabled
        text: Strings.t("panels.bt.devices")
        scheme: bp.scheme
    }
    CcNote {
        visible: BluetoothStatus.enabled && Hw.btDevices.length === 0
        text: Strings.t("panels.bt.none")
        scheme: bp.scheme
    }
    KScrollArea {
        visible: BluetoothStatus.enabled && Hw.btDevices.length > 0
        width: parent.width
        height: Math.min(devColumn.implicitHeight, PanelMetrics.ccListMax)
        contentHeight: devColumn.implicitHeight
        scheme: bp.scheme
        Column {
            id: devColumn
            width: PanelMetrics.ccInner
            Repeater {
                model: ScriptModel { values: Hw.btDevices }
                CcItemRow {
                    required property var modelData
                    readonly property bool busy: modelData.state === BluetoothDeviceState.Connecting || modelData.state === BluetoothDeviceState.Disconnecting
                    objectName: "cc.bt.dev:" + (modelData.name || modelData.deviceName)
                    width: PanelMetrics.ccInner
                    icon: Hw.btIcon(modelData)
                    on: modelData.connected
                    title: modelData.name || modelData.deviceName
                    subtitle: busy ? Strings.t("panels.bt.connecting")
                              : modelData.connected && modelData.batteryAvailable ? Strings.t("panels.bt.battery", { n: Math.round(modelData.battery * 100) })
                              : modelData.connected ? Strings.t("panels.bt.connected") : ""
                    scheme: bp.scheme
                    onActivated: {
                        if (busy)
                            return;
                        if (modelData.connected)
                            modelData.disconnect();
                        else
                            modelData.connect();
                    }
                }
            }
        }
    }
    CcFooter {
        text: Strings.t("panels.bt.settings")
        kcm: "kcm_bluetooth"
        scheme: bp.scheme
        onActivated: bp.cc.closeRequested()
    }
}
