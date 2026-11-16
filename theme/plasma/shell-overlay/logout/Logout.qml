// SPDX-License-Identifier: GPL-3.0-or-later
// Logout greeter entry point of the Kristall shell-package overlay (theme.md §6). It loads
// KristallLogout.qml and forwards its signals to Plasma's logout greeter; if that file fails to
// load (e.g. after a Plasma update changed something it relies on) the stock dialog
// Logout.stock.qml, copied from the installed plasma-desktop at image build time, is used instead.
import QtQuick

Item {
    id: root

    signal logoutRequested()
    signal haltRequested()
    signal haltUpdateRequested()
    signal suspendRequested(int spdMethod)
    signal rebootRequested()
    signal rebootRequested2(int opt)
    signal rebootUpdateRequested()
    signal cancelRequested()
    signal lockScreenRequested()
    signal cancelSoftwareUpdateRequested()

    function sleepRequested() { root.suspendRequested(2); }
    function hibernateRequested() { root.suspendRequested(4); }

    Loader {
        id: loader
        anchors.fill: parent
        focus: true
        source: "KristallLogout.qml"
        onStatusChanged: {
            if (status === Loader.Error && source.toString().indexOf("Logout.stock.qml") < 0) {
                console.warn("kristall-theme: KristallLogout.qml failed to load, using the stock dialog");
                source = "Logout.stock.qml";
            }
        }
    }

    Connections {
        target: loader.item
        ignoreUnknownSignals: true
        function onLogoutRequested() { root.logoutRequested(); }
        function onHaltRequested() { root.haltRequested(); }
        function onHaltUpdateRequested() { root.haltUpdateRequested(); }
        function onSuspendRequested(m) { root.suspendRequested(m); }
        function onRebootRequested() { root.rebootRequested(); }
        function onRebootRequested2(o) { root.rebootRequested2(o); }
        function onRebootUpdateRequested() { root.rebootUpdateRequested(); }
        function onCancelRequested() { root.cancelRequested(); }
        function onLockScreenRequested() { root.lockScreenRequested(); }
        function onCancelSoftwareUpdateRequested() { root.cancelSoftwareUpdateRequested(); }
    }
}
