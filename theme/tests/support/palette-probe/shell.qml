// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only: a running Qt Quick process under the KDE platform theme (as the shell and every Qt
// app are) that reports the palette's highlight colour, so a test can see what a process that is
// not restarted draws after an accent change. `quickshell ipc -p <dir> call probe highlight`.
import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
    SystemPalette {
        id: pal
        colorGroup: SystemPalette.Active
        onPaletteChanged: probe.changes++
    }
    QtObject {
        id: probe
        property int changes: 0
    }
    IpcHandler {
        target: "probe"
        function highlight(): string { return JSON.stringify({ highlight: String(pal.highlight), changes: probe.changes }); }
    }
}
