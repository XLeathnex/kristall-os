// SPDX-License-Identifier: GPL-3.0-or-later
// A full-width Control Center module with a title and the thick slider (Display, Sound, Keyboard).
// The title opens the expanded module when there is one.
import QtQuick
import qs.core
import qs.services

CcTile {
    id: sm
    property string title: ""
    property string icon: ""
    property real value: 0
    property bool expandable: true
    property string sliderName: ""
    property alias slider: theSlider
    default property alias extra: extraBox.data
    signal moved(real v)
    signal opened()

    width: PanelMetrics.ccInner
    height: PanelMetrics.ccCell

    Item {
        id: titleRow
        objectName: sm.sliderName + ".open"
        x: 12
        y: 6
        width: parent.width - 24
        height: 20
        activeFocusOnTab: sm.expandable
        Accessible.role: Accessible.Button
        Accessible.name: sm.title
        Keys.onReturnPressed: if (sm.expandable) sm.opened()
        Keys.onSpacePressed: if (sm.expandable) sm.opened()
        function activate() { if (sm.expandable) sm.opened(); }
        KText {
            anchors.verticalCenter: parent.verticalCenter
            text: sm.title
            textStyle: "subheadline"
            emphasized: true
            scheme: sm.scheme
        }
        KIcon {
            visible: sm.expandable
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            size: 12
            name: "bold/caret-right"
            color: Theme.color(sm.scheme, "secondaryLabel")
        }
        KFocusRing { targetRadius: 6; scheme: sm.scheme }
        TapHandler { enabled: sm.expandable; onTapped: sm.opened() }
        HoverHandler { enabled: sm.expandable; cursorShape: Qt.PointingHandCursor }
    }
    KCapsuleSlider {
        id: theSlider
        objectName: sm.sliderName
        x: 12
        y: 30
        width: parent.width - 24
        icon: sm.icon
        value: sm.value
        label: sm.title
        scheme: sm.scheme
        onMoved: v => sm.moved(v)
    }
    Item {
        id: extraBox
        anchors.fill: theSlider
    }
}
