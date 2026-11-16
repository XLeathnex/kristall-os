// SPDX-License-Identifier: GPL-3.0-or-later
// A permission request (assistant-ipc §5 permission_request): the daemon's own question, the
// model's explanation, a Details disclosure with exactly what would run, and the choices
// Erlauben / „<Kategorie> immer erlauben“ (only when offered) / Nicht erlauben. Operable by
// keyboard (Tab, ←/→, ↑/↓, Return/Space) and pointer. The card does not remove itself when
// clicked: it waits (buttons disabled) until the daemon resolves the request.
import QtQuick
import qs.core
import qs.services

FocusScope {
    id: card
    property var request: null
    property string scheme: Theme.scheme
    property string shownText: ""             // reply text already on screen
    signal decided(string decision)
    readonly property bool answered: request && request._answered !== undefined
    readonly property bool canAlways: request && request.can_always === true && (request.options || []).indexOf("allow_always") >= 0
    readonly property string alwaysLabel: {
        const k = "assistant.permission.always." + (request ? request.category : "");
        const s = Strings.t(k);
        return s === k ? Strings.t("assistant.permission.always") : s;
    }
    property bool showDetails: false
    implicitHeight: col.implicitHeight + 24
    Accessible.role: Accessible.AlertMessage
    Accessible.name: request ? Strings.pick(request.question) : ""

    function focusDefault() {
        allowBtn.forceActiveFocus(Qt.OtherFocusReason);
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.card
        color: Theme.color(card.scheme, "fill")
        border.width: 1
        border.color: Theme.color(card.scheme, "border")
    }

    Column {
        id: col
        x: 12
        y: 12
        width: card.width - 24
        spacing: 8

        Row {
            width: parent.width
            spacing: 10
            Rectangle {
                width: 26
                height: 26
                radius: 13
                color: Theme.accentFor(card.scheme)
                KIcon {
                    anchors.centerIn: parent
                    size: 15
                    name: "fill/hand-palm"
                    color: "#FFFFFF"
                }
            }
            KText {
                width: parent.width - 36
                anchors.verticalCenter: parent.verticalCenter
                text: card.request ? Strings.pick(card.request.question) : ""
                textStyle: "title3"
                emphasized: true
                scheme: card.scheme
                wrapMode: Text.Wrap
                lineHeightMode: Text.ProportionalHeight
                lineHeight: 1.0
            }
        }
        KText {
            visible: text !== ""
            width: parent.width
            // the model's own words; left out when the panel already shows them as its preamble
            text: {
                const e = card.request ? (card.request.explanation || "").trim() : "";
                return e !== "" && card.shownText.indexOf(e) >= 0 ? "" : e;
            }
            textStyle: "callout"
            level: "secondaryLabel"
            scheme: card.scheme
            wrapMode: Text.Wrap
            maximumLineCount: 5
            elide: Text.ElideRight
            lineHeightMode: Text.ProportionalHeight
            lineHeight: 1.15
        }
        // Details disclosure
        Item {
            visible: card.request && (card.request.technical || "") !== ""
            width: parent.width
            height: discl.implicitHeight
            Row {
                id: discl
                spacing: 4
                KIcon {
                    anchors.verticalCenter: parent.verticalCenter
                    size: 11
                    name: card.showDetails ? "bold/caret-down" : "bold/caret-right"
                    color: Theme.color(card.scheme, "secondaryLabel")
                }
                KText {
                    text: card.showDetails ? Strings.t("assistant.permission.hideDetails") : Strings.t("assistant.permission.details")
                    textStyle: "callout"
                    level: "secondaryLabel"
                    scheme: card.scheme
                }
                Accessible.role: Accessible.Button
                Accessible.name: Strings.t("assistant.permission.details")
            }
            TapHandler { onTapped: card.showDetails = !card.showDetails }
            HoverHandler { cursorShape: Qt.PointingHandCursor }
        }
        Rectangle {
            visible: card.showDetails
            width: parent.width
            height: tech.implicitHeight + 12
            radius: Theme.radius.control
            color: Theme.color(card.scheme, "fill")
            TextEdit {
                id: tech
                x: 8
                y: 6
                width: parent.width - 16
                readOnly: true
                selectByMouse: true
                activeFocusOnTab: false
                wrapMode: TextEdit.WrapAnywhere
                text: card.request ? (card.request.technical || "") : ""
                font.family: "monospace"
                font.pixelSize: 11
                color: Theme.color(card.scheme, "label")
                selectionColor: Qt.alpha(Theme.accentFor(card.scheme), 0.35)
                renderType: Text.NativeRendering
            }
        }

        // choices: side by side when they fit, stacked full width otherwise (as macOS alerts do)
        Item {
            id: choices
            width: parent.width
            readonly property real gap: 8
            readonly property real need: allowBtn.implicitWidth + denyBtn.implicitWidth + (card.canAlways ? alwaysBtn.implicitWidth + gap : 0) + gap
            readonly property bool stacked: need > width
            height: stacked ? (card.canAlways ? 3 : 2) * Theme.size.control + (card.canAlways ? 2 : 1) * gap : Theme.size.control
            readonly property var order: card.canAlways ? [allowBtn, alwaysBtn, denyBtn] : [allowBtn, denyBtn]
            function move(from, d) {
                const o = order;
                const i = o.indexOf(from);
                o[(i + d + o.length) % o.length].forceActiveFocus(Qt.TabFocusReason);
            }

            KButton {
                id: denyBtn
                objectName: "denyBtn"
                text: Strings.t("assistant.permission.deny")
                scheme: card.scheme
                enabled: !card.answered
                width: choices.stacked ? choices.width : implicitWidth
                x: choices.stacked ? 0 : choices.width - allowBtn.implicitWidth - choices.gap - (card.canAlways ? alwaysBtn.implicitWidth + choices.gap : 0) - implicitWidth
                y: choices.stacked ? choices.height - height : 0
                onClicked: card.decided("deny")
                Keys.onLeftPressed: choices.move(denyBtn, -1)
                Keys.onRightPressed: choices.move(denyBtn, 1)
                Keys.onUpPressed: choices.move(denyBtn, -1)
                Keys.onDownPressed: choices.move(denyBtn, 1)
            }
            KButton {
                id: alwaysBtn
                objectName: "alwaysBtn"
                visible: card.canAlways
                text: card.alwaysLabel
                scheme: card.scheme
                enabled: !card.answered
                width: choices.stacked ? choices.width : implicitWidth
                x: choices.stacked ? 0 : choices.width - allowBtn.implicitWidth - choices.gap - implicitWidth
                y: choices.stacked ? Theme.size.control + choices.gap : 0
                onClicked: card.decided("allow_always")
                Keys.onLeftPressed: choices.move(alwaysBtn, -1)
                Keys.onRightPressed: choices.move(alwaysBtn, 1)
                Keys.onUpPressed: choices.move(alwaysBtn, -1)
                Keys.onDownPressed: choices.move(alwaysBtn, 1)
            }
            KButton {
                id: allowBtn
                objectName: "allowBtn"
                text: Strings.t("assistant.permission.allow")
                variant: "accent"
                scheme: card.scheme
                enabled: !card.answered
                minWidth: 88
                width: choices.stacked ? choices.width : implicitWidth
                x: choices.stacked ? 0 : choices.width - implicitWidth
                y: 0
                focus: true
                onClicked: card.decided("allow_once")
                Keys.onLeftPressed: choices.move(allowBtn, -1)
                Keys.onRightPressed: choices.move(allowBtn, 1)
                Keys.onUpPressed: choices.move(allowBtn, -1)
                Keys.onDownPressed: choices.move(allowBtn, 1)
            }
        }
        KText {
            width: parent.width
            text: card.answered ? Strings.t("assistant.permission.waiting") : card.timeoutText
            textStyle: "footnote"
            level: "tertiaryLabel"
            scheme: card.scheme
            wrapMode: Text.Wrap
            visible: text !== ""
        }
    }
    readonly property string timeoutText: {
        const s = request ? Number(request.expires_in || 0) : 0;
        if (s <= 0)
            return "";
        const t = s >= 90 ? Strings.tn("assistant.time.minutes", Math.round(s / 60)) : Strings.tn("assistant.time.seconds", Math.round(s));
        return Strings.t("assistant.permission.timeout", { time: t });
    }
}
