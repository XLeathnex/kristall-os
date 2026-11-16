// SPDX-License-Identifier: GPL-3.0-or-later
// Everything inside the assistant's glass: the compact listening capsule and the expanded
// conversation (see Panel.qml). Sizes it wants are `targetW`/`targetH`; the glass morphs to them.
import QtQuick
import Quickshell
import qs.core
import qs.services
import "../../core/Markdown.js" as Md

FocusScope {
    id: body
    required property var ctl
    property string scheme: Theme.scheme
    property real wideW: 440
    property real compactH: 52
    property real maxH: 600
    property real originX: 0
    readonly property var c: ctl.client
    readonly property bool compact: ctl.compact
    readonly property string name: c.assistantName || "Kristall"

    // ---- sizes ------------------------------------------------------------------------------
    readonly property real textX: 54
    readonly property real compactReserve: (ctl.micLive ? 28 + 8 : 0) + 22 + 14 + 8
    readonly property string compactText: c.transcript !== "" ? c.transcript : (ctl.typedQuestion !== "" ? ctl.typedQuestion : "")
    readonly property real compactW: Math.max(300, Math.min(wideW, textX + Math.max(measure.implicitWidth, placeholderMeasure.implicitWidth) + compactReserve + 8))
    readonly property real compactTargetH: Math.max(compactH, compactLabel.implicitHeight + 32)
    readonly property real footerH: Theme.size.field + 24
    readonly property real bodyMaxH: maxH - 12 - footerH
    readonly property real bodyH: Math.max(32, Math.min(bodyMaxH, column.implicitHeight))
    readonly property real expandedH: 14 + bodyH + footerH
    readonly property real targetW: compact ? compactW : wideW
    readonly property real targetH: compact ? compactTargetH : expandedH

    KText { id: measure; visible: false; text: body.compactText; textStyle: "title3" }
    KText { id: placeholderMeasure; visible: false; text: Strings.t("assistant.listening"); textStyle: "title3" }

    function takeFocus() {
        if (perms.count > 0 && perms.itemAt(0)) {
            perms.itemAt(0).focusDefault();
        } else if (!body.compact && field.visible) {
            field.input.forceActiveFocus(Qt.OtherFocusReason);
        } else {
            body.forceActiveFocus(Qt.OtherFocusReason);
        }
    }
    onCompactChanged: Qt.callLater(takeFocus)
    Connections {
        target: body.c
        function onPermissionsChanged() { Qt.callLater(body.takeFocus); }
    }

    // keys: Escape dismisses (and stops); typing anywhere switches to text
    Keys.onPressed: ev => {
        if (ev.key === Qt.Key_Escape) {
            body.ctl.dismiss("escape");
            ev.accepted = true;
            return;
        }
        const printable = ev.text && ev.text.length === 1 && ev.text.charCodeAt(0) >= 32 && ev.text.charCodeAt(0) !== 127
                          && !(ev.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier));
        if (printable && !field.input.activeFocus) {
            body.ctl.typingStarted();
            field.text = field.text + ev.text;
            Qt.callLater(() => { field.input.forceActiveFocus(Qt.OtherFocusReason); field.input.cursorPosition = field.text.length; });
            ev.accepted = true;
        }
    }

    // ---- the crystal (the assistant's face), same place in both layouts -----------------------
    Orb {
        id: orb
        x: 10
        y: 10
        size: 32
        mode: body.ctl.orbMode
        level: body.c.level
        scheme: body.scheme
    }

    // ---- close (both layouts) and the live microphone (compact) ---------------------------------
    KButton {
        id: closeBtn
        objectName: "closeBtn"
        icon: "bold/x"
        variant: "plain"
        size: "small"
        scheme: body.scheme
        x: body.width - width - 13
        y: body.compact ? (Math.min(body.height, body.compactH) - height) / 2 : 13
        Accessible.name: Strings.t("assistant.close")
        activeFocusOnTab: false
        onClicked: body.ctl.dismiss("close")
        KTooltip { text: Strings.t("assistant.close"); originX: body.originX + body.x; originY: body.y }
    }
    MicBadge {
        id: compactMic
        objectName: "compactMic"
        visible: body.compact && body.ctl.micLive
        x: closeBtn.x - width - 8
        y: (Math.min(body.height, body.compactH) - height) / 2
        level: body.c.levelSource === "mic" ? body.c.level : 0
        scheme: body.scheme
        tipOriginX: body.originX + body.x
        tipOriginY: body.y
        onClicked: body.ctl.endListening()
    }

    // ---- compact: the words as they are spoken -------------------------------------------------
    Item {
        id: compactLayer
        anchors.fill: parent
        opacity: body.compact ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.duration("short", true) } }
        KText {
            id: compactLabel
            x: body.textX
            y: 16
            width: body.targetW - body.textX - body.compactReserve
            text: body.compactText !== "" ? body.compactText : Strings.t("assistant.listening")
            textStyle: "title3"
            level: body.compactText !== "" ? "label" : "secondaryLabel"
            scheme: body.scheme
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignTop
        }
    }

    // ---- expanded: the conversation ----------------------------------------------------------
    Item {
        id: expandedLayer
        anchors.fill: parent
        opacity: body.compact ? 0 : 1
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.duration("medium", true) } }

        KScrollArea {
            id: scroll
            x: body.textX
            y: 14
            width: body.width - body.textX - 44
            height: body.bodyH
            contentHeight: column.implicitHeight
            scheme: body.scheme
            property bool follow: true
            Connections {
                target: scroll.flickable
                function onMovementStarted() { scroll.follow = false; }
                function onContentYChanged() {
                    const f = scroll.flickable;
                    if (f.contentY >= f.contentHeight - f.height - 6)
                        scroll.follow = true;
                }
            }
            function toEnd() {
                if (follow)
                    flickable.contentY = Math.max(0, column.implicitHeight - height);
            }
            Connections {
                target: body.c
                function onTurnStarted() { scroll.follow = true; Qt.callLater(scroll.toEnd); }
            }

            Column {
                id: column
                width: scroll.width - 6
                spacing: 10
                onImplicitHeightChanged: Qt.callLater(scroll.toEnd)

                // earlier turns of this conversation
                Repeater {
                    model: body.ctl.history
                    delegate: Column {
                        required property var modelData
                        width: column.width
                        spacing: 4
                        KText {
                            width: parent.width
                            visible: text !== ""
                            text: modelData.question
                            textStyle: "callout"
                            level: "secondaryLabel"
                            scheme: body.scheme
                            wrapMode: Text.Wrap
                        }
                        ReplyText {
                            width: parent.width
                            visible: modelData.reply !== ""
                            segments: [modelData.reply]
                            scheme: body.scheme
                            opacity: 0.82
                        }
                    }
                }
                KSeparator {
                    visible: body.ctl.history.length > 0
                    width: column.width
                    scheme: body.scheme
                }

                // the current question: live words, then settled
                KText {
                    id: questionText
                    width: column.width
                    visible: text !== ""
                    text: body.c.transcript !== "" && !body.c.transcriptFinal ? body.c.transcript : (body.c.question !== "" ? body.c.question : body.ctl.typedQuestion)
                    textStyle: "title3"
                    level: body.ctl.listening ? "label" : "secondaryLabel"
                    scheme: body.scheme
                    wrapMode: Text.Wrap
                    verticalAlignment: Text.AlignTop
                }
                KText {
                    width: column.width
                    visible: body.ctl.listening && questionText.text === ""
                    text: Strings.t("assistant.listening")
                    textStyle: "title3"
                    level: "secondaryLabel"
                    scheme: body.scheme
                }

                ReplyText {
                    id: reply
                    objectName: "reply"
                    width: column.width
                    visible: body.c.reply.trim() !== ""
                    segments: body.c.segments
                    streaming: !body.c.replyDone && body.c.busy
                    large: body.ctl.largeReply
                    scheme: body.scheme
                }

                // thinking, before anything else is there
                KText {
                    id: thinkingText
                    width: column.width
                    visible: body.ctl.showThinking
                    text: Strings.t("assistant.thinking")
                    textStyle: "callout"
                    level: "secondaryLabel"
                    scheme: body.scheme
                    property real breath: 0
                    opacity: 0.55 + 0.45 * breath
                    SequentialAnimation on breath {
                        running: thinkingText.visible && !Theme.reduceMotion
                        loops: Animation.Infinite
                        NumberAnimation { from: 0; to: 1; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { from: 1; to: 0; duration: 700; easing.type: Easing.InOutSine }
                    }
                }

                ActivityLine {
                    width: column.width
                    visible: body.ctl.showActivity
                    activity: body.c.activity
                    fallbackText: Strings.t("assistant.working")
                    scheme: body.scheme
                }

                Repeater {
                    id: perms
                    model: body.c.permissions
                    delegate: PermissionCard {
                        required property var modelData
                        width: column.width
                        request: modelData
                        scheme: body.scheme
                        shownText: body.c.reply
                        onDecided: decision => body.ctl.decide(modelData.request_id, decision)
                    }
                }

                NoticeCard {
                    id: noticeCard
                    width: column.width
                    visible: body.ctl.notice !== null
                    icon: body.ctl.notice ? body.ctl.notice.icon : ""
                    iconColor: body.ctl.notice && body.ctl.notice.tone === "warning" ? Theme.color(body.scheme, "warning")
                             : body.ctl.notice && body.ctl.notice.tone === "accent" ? Theme.accentFor(body.scheme)
                             : Theme.color(body.scheme, "secondaryLabel")
                    message: body.ctl.notice ? body.ctl.notice.message : ""
                    hint: body.ctl.notice ? (body.ctl.notice.hint || "") : ""
                    actions: body.ctl.notice ? (body.ctl.notice.actions || []) : []
                    quiet: body.ctl.notice ? body.ctl.notice.quiet === true : false
                    scheme: body.scheme
                }

                // copy the answer
                Item {
                    width: column.width
                    height: copyBtn.height
                    visible: body.c.replyDone && body.c.reply.trim() !== "" && !body.c.busy
                    KButton {
                        id: copyBtn
                        objectName: "copyBtn"
                        property bool done: false
                        text: done ? Strings.t("assistant.copied") : Strings.t("assistant.copy")
                        icon: done ? "bold/check" : "copy"
                        variant: "plain"
                        size: "small"
                        scheme: body.scheme
                        activeFocusOnTab: true
                        onClicked: {
                            clip.text = Md.toPlain(body.c.reply);
                            clip.selectAll();
                            clip.copy();
                            clip.text = "";
                            done = true;
                        }
                        Connections {
                            target: body.c
                            function onTurnStarted() { copyBtn.done = false; }
                        }
                    }
                }
            }
        }

        // footer: type a follow-up, or speak / stop
        KTextField {
            id: field
            objectName: "field"
            x: 12
            y: body.height - Theme.size.field - 12
            width: body.width - 24 - (footerAction.visible ? footerAction.width + 8 : 0)
            scheme: body.scheme
            placeholder: (body.ctl.history.length > 0 || body.c.reply !== "") ? Strings.t("assistant.followUpPlaceholder")
                                                                               : Strings.t("assistant.askPlaceholder", { name: body.name })
            enabled: body.c.connected
            onAccepted: {
                const t = text.trim();
                if (t !== "") {
                    body.ctl.ask(t, "panel");
                    text = "";
                }
            }
            onEscaped: body.ctl.dismiss("escape")
            Connections {
                target: field.input
                function onTextEdited() { body.ctl.typingStarted(); }
            }
        }
        Item {
            id: footerAction
            width: Theme.size.field
            height: Theme.size.field
            x: body.width - 12 - width
            y: field.y
            visible: body.ctl.micLive || body.c.busy || body.ctl.canSpeak
            MicBadge {
                anchors.fill: parent
                visible: body.ctl.micLive
                level: body.c.levelSource === "mic" ? body.c.level : 0
                scheme: body.scheme
                tipOriginX: body.originX + body.x
                tipOriginY: body.y
                onClicked: body.ctl.endListening()
            }
            KButton {
                objectName: "stopBtn"
                anchors.fill: parent
                visible: !body.ctl.micLive && body.c.busy
                icon: "fill/stop"
                variant: "fill"
                scheme: body.scheme
                Accessible.name: Strings.t("assistant.stop")
                onClicked: body.ctl.stop()
                KTooltip { text: Strings.t("assistant.stop"); originX: body.originX + body.x; originY: body.y }
            }
            KButton {
                objectName: "micBtn"
                anchors.fill: parent
                visible: !body.ctl.micLive && !body.c.busy && body.ctl.canSpeak
                icon: "microphone"
                variant: "fill"
                scheme: body.scheme
                Accessible.name: Strings.t("assistant.speak")
                onClicked: body.ctl.listen("panel")
                KTooltip { text: Strings.t("assistant.speak"); originX: body.originX + body.x; originY: body.y }
            }
        }
    }

    // invisible helper for the clipboard
    TextEdit {
        id: clip
        visible: false
        textFormat: TextEdit.PlainText
    }
}
