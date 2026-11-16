// SPDX-License-Identifier: GPL-3.0-or-later
// Expanded Sound module: volume, mute, the output devices (the default one checked), who is
// using the microphone.
import QtQuick
import Quickshell
import Quickshell.Services.Pipewire
import qs.core
import qs.services

Column {
    id: sp
    property string scheme: Theme.scheme
    property var cc: null
    width: PanelMetrics.ccInner
    spacing: 4

    CcHeader {
        title: Strings.t("panels.sound")
        scheme: sp.scheme
        onBack: sp.cc.back()
    }
    CcNote {
        visible: !Audio.available
        text: Strings.t("panels.sound.none")
        scheme: sp.scheme
    }
    KCapsuleSlider {
        objectName: "cc.sound.page.slider"
        visible: Audio.available
        x: 6
        width: parent.width - 12
        icon: Audio.muted || Audio.volume <= 0 ? "fill/speaker-simple-slash" : "fill/speaker-simple-high"
        label: Strings.t("panels.sound")
        value: Audio.muted ? 0 : Audio.volume
        scheme: sp.scheme
        onMoved: v => Audio.setVolume(v)
    }
    CcItemRow {
        visible: Audio.available
        objectName: "cc.sound.muteRow"
        width: PanelMetrics.ccInner
        icon: "fill/speaker-simple-slash"
        on: Audio.muted
        title: Strings.t("panels.sound.mute")
        scheme: sp.scheme
        onActivated: Audio.setMuted(!Audio.muted)
    }
    CcSection {
        visible: Hw.sinks.length > 0
        text: Strings.t("panels.sound.output")
        scheme: sp.scheme
    }
    Repeater {
        model: ScriptModel { values: Hw.sinks }
        CcItemRow {
            required property var modelData
            objectName: "cc.sound.out:" + Hw.sinkName(modelData)
            width: PanelMetrics.ccInner
            icon: (Hw.sinkName(modelData).toLowerCase().indexOf("kopfh") >= 0 || Hw.sinkName(modelData).toLowerCase().indexOf("head") >= 0) ? "headphones" : "speaker-hifi"
            on: Pipewire.defaultAudioSink === modelData
            checked: Pipewire.defaultAudioSink === modelData
            title: Hw.sinkName(modelData)
            scheme: sp.scheme
            onActivated: Hw.selectSink(modelData)
        }
    }
    CcItemRow {
        visible: Hw.micInUse
        width: PanelMetrics.ccInner
        icon: "fill/microphone"
        circle: false
        title: Hw.micUser !== "" ? Strings.t("panels.mic.inUse", { app: Hw.micUser }) : Strings.t("panels.mic.inUseAnon")
        scheme: sp.scheme
        enabled: false
        opacity: 1
    }
    CcFooter {
        text: Strings.t("panels.sound.settings")
        kcm: "kcm_pulseaudio"
        scheme: sp.scheme
        onActivated: sp.cc.closeRequested()
    }
}
