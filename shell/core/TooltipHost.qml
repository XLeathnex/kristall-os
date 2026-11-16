// SPDX-License-Identifier: GPL-3.0-or-later
// Per-output tooltip surface: Overlay layer, namespace "kristall-tooltip", no input, glass role
// "tooltip". Exists only while a tooltip is shown on this output.
import QtQuick
import Quickshell
import Quickshell.Wayland

Scope {
    id: host
    required property var screen
    readonly property var tip: Tooltips.current && Tooltips.current.screen === screen.name ? Tooltips.current : null

    LazyLoader {
        active: host.tip !== null
        PanelWindow {
            id: win
            screen: host.screen
            WlrLayershell.namespace: "kristall-tooltip"
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            exclusionMode: ExclusionMode.Ignore
            anchors { top: true; left: true }
            readonly property var r: host.tip ? host.tip.rect : ({ x: 0, y: 0, w: 0, h: 0 })
            readonly property real pad: 24   // room for the shadow
            implicitWidth: label.implicitWidth + 2 * Theme.size.tooltipPadH + 2 * pad
            implicitHeight: label.implicitHeight + 2 * Theme.size.tooltipPadV + 2 * pad
            margins {
                left: Math.max(0, Math.min(host.screen.width - implicitWidth, r.x + r.w / 2 - implicitWidth / 2))
                top: (r.y + r.h + 6 + implicitHeight - 2 * pad > host.screen.height) ? r.y - implicitHeight + pad - 6 : r.y + r.h + 6 - pad
            }
            color: "transparent"
            mask: Region {}

            GlassSurface {
                id: gs
                key: "tooltip-" + host.screen.name
                layerNamespace: "kristall-tooltip"
                output: host.screen.name
            }
            GlassShape {
                id: shape
                shapeId: "tooltip"
                surface: gs
                role: "tooltip"
                x: win.pad; y: win.pad
                width: win.implicitWidth - 2 * win.pad
                height: win.implicitHeight - 2 * win.pad
                KText {
                    id: label
                    anchors.centerIn: parent
                    text: host.tip ? host.tip.text : ""
                    textStyle: "callout"
                    scheme: shape.scheme
                }
            }
        }
    }
}
