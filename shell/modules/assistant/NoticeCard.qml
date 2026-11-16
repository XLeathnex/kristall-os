// SPDX-License-Identifier: GPL-3.0-or-later
// A calm, human sentence for every non-happy state — the daemon's own bilingual message for its
// errors, ours for states it does not word (daemon unreachable, account not ready, restart) —
// with what to do next as buttons. Never a code.
import QtQuick
import qs.core
import qs.services

FocusScope {
    id: notice
    property string icon: "warning-circle"
    property color iconColor: Theme.color(scheme, "secondaryLabel")
    property string message: ""
    property string hint: ""
    property string scheme: Theme.scheme
    property var actions: []                // [{label, primary, run: function}]
    property bool quiet: false               // a light-weight line (e.g. "nothing heard")
    implicitHeight: col.implicitHeight + (quiet ? 0 : 24)
    Accessible.role: Accessible.AlertMessage
    Accessible.name: message

    function focusDefault() {
        if (buttons.children.length > 0 && actions.length > 0)
            buttons.children[0].forceActiveFocus(Qt.OtherFocusReason);
    }

    Rectangle {
        visible: !notice.quiet
        anchors.fill: parent
        radius: Theme.radius.card
        color: Theme.color(notice.scheme, "fill")
        border.width: 1
        border.color: Theme.color(notice.scheme, "border")
    }
    Column {
        id: col
        x: notice.quiet ? 0 : 12
        y: notice.quiet ? 0 : 12
        width: notice.width - 2 * x
        spacing: 10
        Row {
            width: parent.width
            spacing: 10
            KIcon {
                id: ic
                size: 20
                name: notice.icon
                color: notice.iconColor
            }
            Column {
                width: parent.width - 30
                spacing: 4
                KText {
                    width: parent.width
                    text: notice.message
                    textStyle: notice.quiet ? "body" : "title3"
                    scheme: notice.scheme
                    wrapMode: Text.Wrap
                    lineHeightMode: Text.ProportionalHeight
                    lineHeight: 1.08
                }
                KText {
                    visible: notice.hint !== ""
                    width: parent.width
                    text: notice.hint
                    textStyle: "callout"
                    level: "secondaryLabel"
                    scheme: notice.scheme
                    wrapMode: Text.Wrap
                    lineHeightMode: Text.ProportionalHeight
                    lineHeight: 1.15
                }
            }
        }
        Row {
            id: buttons
            visible: notice.actions.length > 0
            anchors.right: parent.right
            spacing: 8
            layoutDirection: Qt.RightToLeft
            Repeater {
                model: notice.actions
                KButton {
                    required property var modelData
                    required property int index
                    text: modelData.label
                    variant: modelData.primary ? "accent" : "fill"
                    scheme: notice.scheme
                    onClicked: modelData.run()
                    Keys.onLeftPressed: { const n = buttons.children[index + 1]; if (n && n.forceActiveFocus) n.forceActiveFocus(Qt.TabFocusReason); }
                    Keys.onRightPressed: { if (index > 0) buttons.children[index - 1].forceActiveFocus(Qt.TabFocusReason); }
                }
            }
        }
    }
}
