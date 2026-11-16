// SPDX-License-Identifier: GPL-3.0-or-later
// Regular slider: 6-px capsule track, accent fill, white capsule knob 28×20 with a soft shadow.
// Keyboard: ←/→ (or ↓/↑) by `step`, Home/End.
// Binding-safe like KCapsuleSlider: bind `value`, act on `moved(v)`; never writes `value`.
import QtQuick

Item {
    id: s
    property real value: 0.5          // from..to
    property real from: 0
    property real to: 1
    property real step: 0.05
    property string scheme: Theme.scheme
    property string label: ""
    property string showState: ""     // gallery: "focus" | "pressed"
    signal moved(real value)          // user changes only

    property bool _interacting: false
    property real _drag: 0
    readonly property real shown: _interacting ? _drag : value
    readonly property real frac: to > from ? Math.max(0, Math.min(1, (shown - from) / (to - from))) : 0
    implicitWidth: 200
    implicitHeight: Theme.size.sliderKnobH + 4
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.Slider
    Accessible.name: label

    function setFrac(f) {
        const v = Math.round((from + Math.max(0, Math.min(1, f)) * (to - from)) * 1000) / 1000;
        if (v !== shown) {
            _drag = v;
            _interacting = true;
            sliderSettle.restart();
            moved(v);
        }
    }
    Timer {
        id: sliderSettle
        interval: 600
        onTriggered: if (!drag.active) s._interacting = false
    }
    Keys.onLeftPressed: setFrac(frac - step)
    Keys.onDownPressed: setFrac(frac - step)
    Keys.onRightPressed: setFrac(frac + step)
    Keys.onUpPressed: setFrac(frac + step)
    Keys.onPressed: e => {
        if (e.key === Qt.Key_Home) { setFrac(0); e.accepted = true; }
        else if (e.key === Qt.Key_End) { setFrac(1); e.accepted = true; }
    }

    readonly property real kw: Theme.size.sliderKnobW
    Rectangle {
        id: track
        x: s.kw / 2 - 3
        width: s.width - s.kw + 6
        height: Theme.size.sliderTrack
        anchors.verticalCenter: parent.verticalCenter
        radius: height / 2
        color: Theme.color(s.scheme, "trackOff")
        Rectangle {
            width: 6 + (track.width - 6) * s.frac
            height: parent.height
            radius: height / 2
            color: Theme.accentFor(s.scheme)
        }
    }
    Item {
        id: knob
        width: drag.active || s.showState === "pressed" ? s.kw + 4 : s.kw
        height: Theme.size.sliderKnobH
        anchors.verticalCenter: parent.verticalCenter
        x: (s.width - s.kw) * s.frac - (width - s.kw) / 2
        Behavior on width { NumberAnimation { duration: Theme.duration("micro") } }
        KShadow { kind: "knob"; radius: 10; target: knob }
        Rectangle { anchors.fill: parent; radius: height / 2; color: Theme.color(s.scheme, "knob") }
        KFocusRing { target: knob; targetRadius: knob.height / 2; visible: s.activeFocus || s.showState === "focus"; scheme: s.scheme }
    }
    DragHandler {
        id: drag
        target: null
        xAxis.enabled: true
        yAxis.enabled: false
        property real startFrac: 0
        onActiveChanged: if (active) { startFrac = s.frac; s.forceActiveFocus(Qt.MouseFocusReason); } else sliderSettle.restart()
        onTranslationChanged: s.setFrac(startFrac + translation.x / Math.max(1, s.width - s.kw))
    }
    TapHandler {
        onTapped: (ev) => { s.forceActiveFocus(Qt.MouseFocusReason); s.setFrac((ev.position.x - s.kw / 2) / Math.max(1, s.width - s.kw)); }
    }
    WheelHandler {
        onWheel: ev => s.setFrac(s.frac + (ev.angleDelta.y > 0 ? s.step : -s.step))
    }
}
