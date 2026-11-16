// SPDX-License-Identifier: GPL-3.0-or-later
// One edge of the crystal light: a thin layer surface along one side of an output (the top and
// bottom strips span the full width and carry the corners; the side strips fill in between).
// Only these strips are surfaces, so only they are re-rendered and damaged while the light moves;
// the rest of the screen is untouched. Click-through (empty input region), no keyboard, Overlay
// layer, namespace kristall-assistant-light-<edge> (excluded from the assistant's screenshots).
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.services

PanelWindow {
    id: strip
    required property var light            // EdgeLight (shared uniforms)
    required property string edge          // top | bottom | left | right
    readonly property real depth: light.depth
    readonly property bool horizontal: edge === "top" || edge === "bottom"

    screen: light.screen
    visible: light.mapped
    color: "transparent"
    WlrLayershell.namespace: "kristall-assistant-light-" + edge
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    mask: Region {}
    anchors {
        top: edge !== "bottom"
        bottom: edge !== "top"
        left: edge !== "right"
        right: edge !== "left"
    }
    margins {
        top: horizontal ? 0 : depth
        bottom: horizontal ? 0 : depth
    }
    implicitHeight: depth
    implicitWidth: depth

    // strip origin in output coordinates (the shader works in output space so the pieces join)
    readonly property point origin: Qt.point(edge === "right" ? light.screenW - width : 0,
                                             edge === "bottom" ? light.screenH - height : (edge === "top" ? 0 : depth))

    readonly property int api: content.GraphicsInfo.api
    readonly property bool gpu: api !== GraphicsInfo.Unknown && api !== GraphicsInfo.Software

    Item {
        id: content
        anchors.fill: parent

        Loader {
            id: shaderLoader
            anchors.fill: parent
            active: strip.gpu && !strip.light.forceFallback
            sourceComponent: ShaderEffect {
                property size stripSize: Qt.size(width, height)
                property point stripOrigin: strip.origin
                property size screenSize: Qt.size(strip.light.screenW, strip.light.screenH)
                property real radius: strip.light.cornerRadius
                property real time: strip.light.time
                property real phase: strip.light.hueTime
                property real level: strip.light.level
                property real intensity: strip.light.intensity
                property real rimWidth: strip.light.rimWidth
                property real reach: strip.light.reach * strip.light.reachScale
                property real shimmer: strip.light.shimmer
                property real pulse: strip.light.pulse
                property real onLight: strip.light.onLight
                property real sweep: strip.light.sweep
                property real bloom: strip.light.bloom
                property real accent: strip.light.accent
                property real holeRadius: strip.light.holeRadius
                property rect hole: strip.light.hole
                property color colA: strip.light.colA
                property color colB: strip.light.colB
                property color colC: strip.light.colC
                property color colD: strip.light.colD
                fragmentShader: Qt.resolvedUrl("shaders/edgelight.frag.qsb")
                onStatusChanged: if (status === ShaderEffect.Error) { console.info("kristall-assistant: light shader unavailable, using the plain glow"); strip.light.forceFallback = true; }
            }
        }

        // Plain glow without a GPU path (Qt Quick software renderer, shader failure): a still
        // gradient from the edge inward; its opacity follows the voice level.
        Rectangle {
            id: plain
            visible: !shaderLoader.active
            anchors.fill: parent
            opacity: Math.min(1, strip.light.intensity * Math.min(1, strip.light.sweep) * (0.8 + 0.4 * strip.light.level + 0.3 * strip.light.pulse))
            // fade to the same colour at zero alpha (fading to "transparent" would pass through grey)
            readonly property bool fromStart: strip.edge === "top" || strip.edge === "left"
            gradient: Gradient {
                orientation: strip.horizontal ? Gradient.Vertical : Gradient.Horizontal
                GradientStop { position: 0.0; color: plain.fromStart ? Qt.alpha(strip.light.colA, 0.9) : Qt.alpha(strip.light.colC, 0) }
                GradientStop { position: plain.fromStart ? 0.06 : 0.55; color: plain.fromStart ? Qt.alpha(strip.light.colB, 0.5) : Qt.alpha(strip.light.colC, 0.10) }
                GradientStop { position: plain.fromStart ? 0.45 : 0.94; color: plain.fromStart ? Qt.alpha(strip.light.colC, 0.10) : Qt.alpha(strip.light.colB, 0.5) }
                GradientStop { position: 1.0; color: plain.fromStart ? Qt.alpha(strip.light.colC, 0) : Qt.alpha(strip.light.colA, 0.9) }
            }
        }
    }
}
