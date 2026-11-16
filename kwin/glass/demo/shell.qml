// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall glass demo: run with `quickshell -p kwin/glass/demo` inside a Kristall/KWin session.
// A menu-bar strip, a Dock capsule (magnifies under the pointer), a panel and a group of shapes
// that merge — all drawn by the compositor's Liquid Glass via glass.sock, exactly as the shell
// will use it. Without the effect every shape falls back to a plain translucent fill.
import QtQuick
import Quickshell

ShellRoot {
    Variants {
        model: Quickshell.screens
        delegate: Component {
            Scope {
                id: perScreen
                required property var modelData
                DemoBar { screen: perScreen.modelData }
                DemoDock { screen: perScreen.modelData }
            }
        }
    }
    DemoPanel { screen: Quickshell.screens[0] }
    DemoBlobs { screen: Quickshell.screens[0] }
}
