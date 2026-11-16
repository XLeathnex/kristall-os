// SPDX-License-Identifier: GPL-3.0-or-later
// Test helper: a known picture on the background layer of every output (the "wallpaper").
// The image is chosen with KRISTALL_TEST_BG=<path>; touching the file reloads it.
import QtQuick
import Quickshell
import Quickshell.Wayland

ShellRoot {
    Variants {
        model: Quickshell.screens
        delegate: Component {
            PanelWindow {
                required property var modelData
                screen: modelData
                WlrLayershell.layer: WlrLayer.Background
                WlrLayershell.namespace: "kristall-test-background"
                anchors { top: true; bottom: true; left: true; right: true }
                exclusionMode: ExclusionMode.Ignore
                color: "black"
                Image {
                    id: img
                    anchors.fill: parent
                    source: "file://" + Quickshell.env("KRISTALL_TEST_BG")
                    fillMode: Image.Stretch
                    smooth: false
                    cache: false
                    sourceSize: Qt.size(width * (parent.Window.window ? parent.Window.window.devicePixelRatio : 1), height * (parent.Window.window ? parent.Window.window.devicePixelRatio : 1))
                }
            }
        }
    }
}
