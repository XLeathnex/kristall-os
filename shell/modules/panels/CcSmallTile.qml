// SPDX-License-Identifier: GPL-3.0-or-later
// A one-cell Control Center control: round button with a short caption under it.
import QtQuick
import qs.core

CcTile {
    id: st
    property string icon: ""
    property string caption: ""
    property bool on: false
    property string buttonName: ""
    signal clicked()

    width: PanelMetrics.ccCell
    height: PanelMetrics.ccCell

    CcRound {
        objectName: st.buttonName
        anchors.horizontalCenter: parent.horizontalCenter
        y: 5
        icon: st.icon
        on: st.on
        name: st.caption
        scheme: st.scheme
        onClicked: st.clicked()
    }
    KText {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 43
        width: parent.width - 4
        horizontalAlignment: Text.AlignHCenter
        text: st.caption
        textStyle: "caption1"
        wrapMode: Text.WordWrap
        maximumLineCount: 2
        lineHeight: 11
        elide: Text.ElideRight
        scheme: st.scheme
    }
}
