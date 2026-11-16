// SPDX-License-Identifier: GPL-3.0-or-later
// Test helper: an empty, fully transparent full-screen layer surface. Tests bind glass shapes
// to it over the socket (namespace "kristall-test-glass", any pid) and so control the exact
// geometry. Optional KRISTALL_TEST_LABEL draws a line of text on it (dark/light per env).
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
                WlrLayershell.layer: WlrLayer.Top
                WlrLayershell.namespace: "kristall-test-glass"
                anchors { top: true; bottom: true; left: true; right: true }
                exclusionMode: ExclusionMode.Ignore
                color: "transparent"
                mask: Region {}
            }
        }
    }
}
