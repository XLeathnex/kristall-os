// SPDX-License-Identifier: GPL-3.0-or-later
// Segmented control: capsule track (fill), the selected segment is a raised white capsule
// (inset 2, concentric) that glides between segments. Keyboard ←/→.
// Binding-safe: bind `currentIndex` and act on `activated(i)`; the control never writes
// `currentIndex`. The chosen segment shows at once until `currentIndex` follows (≤ 1.5 s).
import QtQuick

Item {
    id: seg
    property var model: []            // strings
    property int currentIndex: 0      // the selection shown (bind it); never written by the control
    readonly property int shownIndex: _pending >= 0 ? _pending : currentIndex
    property int _pending: -1
    property string scheme: Theme.scheme
    property string showState: ""
    signal activated(int index)

    readonly property real inset: Theme.size.segmentInset
    readonly property real segW: model.length > 0 ? (width - 2 * inset) / model.length : 0
    implicitHeight: Theme.size.segmented
    implicitWidth: {
        let w = 0;
        for (let i = 0; i < labels.count; ++i)
            w = Math.max(w, labels.itemAt(i) ? labels.itemAt(i).implicitWidth : 0);
        return (w + 28) * Math.max(1, model.length) + 2 * inset;
    }
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.PageTabList

    function select(i) {
        if (i < 0 || i >= model.length || i === shownIndex)
            return;
        _pending = i;
        settle.restart();
        activated(i);
    }
    onCurrentIndexChanged: { _pending = -1; settle.stop(); }
    Timer {
        id: settle
        interval: 1500
        onTriggered: seg._pending = -1
    }
    Keys.onLeftPressed: select(shownIndex - 1)
    Keys.onRightPressed: select(shownIndex + 1)

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Theme.color(seg.scheme, "fill")
    }
    Item {
        id: thumb
        visible: seg.shownIndex >= 0          // −1: nothing chosen
        x: seg.inset + seg.segW * Math.max(0, seg.shownIndex)
        y: seg.inset
        width: seg.segW
        height: seg.height - 2 * seg.inset
        Behavior on x { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
        KShadow { kind: "control"; radius: 11; target: thumb; strength: 0.8 }
        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: seg.scheme === "dark" ? Qt.rgba(1, 1, 1, 0.24) : "#FFFFFF"
        }
    }
    Repeater {
        id: labels
        model: seg.model
        KText {
            required property string modelData
            required property int index
            x: seg.inset + seg.segW * index
            width: seg.segW
            height: seg.height
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: modelData
            textStyle: "control"
            emphasized: index === seg.shownIndex
            scheme: seg.scheme
            elide: Text.ElideRight
            TapHandler { onTapped: { seg.forceActiveFocus(Qt.MouseFocusReason); seg.select(index); } }
        }
    }
    KFocusRing { targetRadius: seg.height / 2; scheme: seg.scheme }
}
