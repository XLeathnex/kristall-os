// SPDX-License-Identifier: GPL-3.0-or-later
// Default audio output: volume and mute (PipeWire through Quickshell's native service).
// Without PipeWire or without an output, `available` is false and the bar shows a muted speaker.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Services.Pipewire

Singleton {
    id: root

    readonly property var sink: Pipewire.ready ? Pipewire.defaultAudioSink : null
    readonly property bool available: sink !== null && sink.audio !== null
    readonly property real volume: available ? sink.audio.volume : 0
    readonly property bool muted: available ? sink.audio.muted : true
    readonly property string deviceName: available ? (sink.description || sink.nickname || sink.name) : ""

    function setVolume(v) {
        if (!available)
            return;
        sink.audio.volume = Math.max(0, Math.min(1, v));
        if (v > 0 && sink.audio.muted)
            sink.audio.muted = false;
    }

    function setMuted(m) {
        if (available)
            sink.audio.muted = m;
    }

    // binds the default sink so its properties are live (no polling: PipeWire pushes changes)
    PwObjectTracker {
        objects: root.sink ? [root.sink] : []
    }
}
