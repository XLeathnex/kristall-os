// SPDX-License-Identifier: GPL-3.0-or-later
// The thick capsule slider of Control Center (volume, brightness): 28-px capsule, white fill
// from the left, symbol inside on the left. Dragging anywhere moves the value relatively.
// Binding-safe: bind `value` to the live value and act on `moved(v)`; the control never writes
// `value`. While the owner drags (and 600 ms after) it shows the dragged position, so a service
// that reports back late never makes the fill jitter; then it follows `value` again.
import QtQuick

Item {
    id: s
    property real value: 0.5          // 0..1, the live value (bind it); never written by the control
    readonly property real shown: interacting ? _drag : Math.max(0, Math.min(1, value))
    readonly property bool interacting: _interacting
    property bool _interacting: false
    property real _drag: 0
    property string icon: ""
    property string scheme: Theme.scheme
    property string label: ""
    property string showState: ""
    property real step: 0.0625         // 16 steps, like the Mac's volume keys
    signal moved(real value)

    implicitWidth: 240
    implicitHeight: Theme.size.capsuleSlider
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.Slider
    Accessible.name: label

    function setValue(v) {             // as if the owner dragged there (keyboard, wheel, tests)
        v = Math.max(0, Math.min(1, v));
        if (v === shown)
            return;
        _drag = v;
        _interacting = true;
        settle.restart();
        moved(v);
    }
    Timer {
        id: settle
        interval: 600
        onTriggered: if (!drag.active) s._interacting = false
    }
    Keys.onLeftPressed: setValue(shown - step)
    Keys.onRightPressed: setValue(shown + step)
    Keys.onDownPressed: setValue(shown - step)
    Keys.onUpPressed: setValue(shown + step)

    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: Theme.color(s.scheme, "fillStrong")
        clip: true
        Rectangle {
            // the fill is never narrower than the capsule's height (the round end holds the symbol)
            width: s.height + (s.width - s.height) * s.shown
            height: parent.height
            radius: height / 2
            color: "#FFFFFF"
            opacity: s.scheme === "dark" ? 0.92 : 1.0
        }
    }
    KIcon {
        x: (s.height - size) / 2
        anchors.verticalCenter: parent.verticalCenter
        size: 14
        name: s.icon
        visible: s.icon !== ""
        color: "#3A3A3C"
    }
    KFocusRing { targetRadius: s.height / 2; scheme: s.scheme }
    DragHandler {
        id: drag
        target: null
        yAxis.enabled: false
        property real start: 0
        onActiveChanged: if (active) { start = s.shown; s.forceActiveFocus(Qt.MouseFocusReason); } else settle.restart()
        onTranslationChanged: s.setValue(start + translation.x / Math.max(1, s.width - s.height))
    }
    TapHandler {
        onTapped: ev => s.setValue((ev.position.x - s.height / 2) / Math.max(1, s.width - s.height))
    }
    WheelHandler {
        onWheel: ev => s.setValue(s.shown + (ev.angleDelta.y > 0 ? s.step : -s.step))
    }
}
