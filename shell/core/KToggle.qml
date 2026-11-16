// SPDX-License-Identifier: GPL-3.0-or-later
// On/off switch: 42×24 capsule track, 20-px knob inset 2 (concentric: 12 − 2 = 10).
// The knob stretches while pressed and settles with the "bouncy" curve.
// Binding-safe: bind `checked` to the real state and act on `toggled(on)`. A click never writes
// `checked`; the switch shows the requested position at once and keeps showing it until `checked`
// follows (or for 1.5 s, then it shows `checked` again — the change was refused or did not happen).
import QtQuick

Item {
    id: tg
    property bool checked: false          // the state shown (bind it); never written by the control
    readonly property bool shownChecked: _pending !== null ? _pending : checked
    property var _pending: null
    property string scheme: Theme.scheme
    property string label: ""
    property string showState: ""     // gallery: "pressed" | "focus"
    signal toggled(bool checked)

    implicitWidth: Theme.size.toggleWidth
    implicitHeight: Theme.size.toggleHeight
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.checked: shownChecked
    Accessible.checkable: true

    function flip() {
        if (!enabled)
            return;
        const want = !shownChecked;
        _pending = want;
        settle.restart();
        toggled(want);
    }
    onCheckedChanged: { _pending = null; settle.stop(); }
    Timer {
        id: settle
        interval: 1500
        onTriggered: tg._pending = null
    }
    Keys.onSpacePressed: flip()

    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: tg.shownChecked ? Theme.accentFor(tg.scheme) : Theme.color(tg.scheme, "trackOff")
        Behavior on color { ColorAnimation { duration: Theme.duration("medium", true) } }
    }
    Item {
        id: knob
        readonly property real inset: Theme.size.toggleKnobInset
        readonly property real d: tg.height - 2 * inset
        width: tap.pressed || tg.showState === "pressed" ? d + 6 : d
        height: d
        y: inset
        x: tg.shownChecked ? tg.width - width - inset : inset
        Behavior on x { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("bouncy") } }
        Behavior on width { NumberAnimation { duration: Theme.duration("micro"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
        KShadow { kind: "knob"; radius: 10; target: knob }
        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: Theme.color(tg.scheme, "knob")
        }
    }
    KFocusRing { targetRadius: tg.height / 2; scheme: tg.scheme }
    TapHandler {
        id: tap
        onTapped: { tg.forceActiveFocus(Qt.MouseFocusReason); tg.flip(); }
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
