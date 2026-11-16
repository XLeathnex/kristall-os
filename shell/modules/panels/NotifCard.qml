// SPDX-License-Identifier: GPL-3.0-or-later
// One notification on glass (banner or Notification Centre): app icon, title, time, body, image,
// progress, action buttons, inline reply. Hover shows the close button; a click performs the
// default action and brings the app forward; a swipe to the right puts it away; the context menu
// (right click) clears it or mutes the app. Earlier notifications of the same app can be drawn as
// a stack behind it (`stacked` = 0..2).
import QtQuick
import Quickshell
import Quickshell.Widgets
import qs.core
import qs.services

Item {
    id: card

    required property var entry
    property GlassSurface surface: null
    property string shapeKey: "card-" + (entry ? entry.key : 0)
    property int stacked: 0
    property bool expandedBody: false
    property real originX: 0                 // the surface's offset on its output (menus)
    property real originY: 0
    property Item clipItem: null             // scroll area the card may be partly outside of
    property int layoutRevision: 0
    property bool swipeEnabled: true
    readonly property bool hovered: hover.hovered
    readonly property bool replying: replyBox.visible
    readonly property string scheme: shape.scheme
    signal activated()
    signal closed()
    signal swiped()
    signal menuRequested()

    implicitWidth: PanelMetrics.cardWidth
    implicitHeight: content.implicitHeight + 2 * PanelMetrics.cardPadding + stacked * PanelMetrics.stackPeek
    width: implicitWidth
    height: implicitHeight

    // visible part of the card inside clipItem (in card coordinates): glass is drawn by the
    // compositor and is not clipped by the scroll area, so the shapes are cut to it
    readonly property real visTop: {
        layoutRevision;
        if (!clipItem)
            return 0;
        const scrolled = clipItem.flickable ? clipItem.flickable.contentY : 0;   // dependency
        const p = mapToItem(clipItem, 0, 0);
        return Math.max(0, -p.y + scrolled * 0);
    }
    readonly property real visBottom: {
        layoutRevision;
        if (!clipItem)
            return height;
        const scrolled = clipItem.flickable ? clipItem.flickable.contentY : 0;   // dependency
        const p = mapToItem(clipItem, 0, 0);
        return Math.min(height, clipItem.height - p.y + scrolled * 0);
    }
    readonly property bool onScreen: visBottom - visTop > 1

    // ---- the stack behind (two fixed shapes so they always paint before the card) -----------------
    component Peek: GlassShape {
        required property int depth
        shapeId: card.shapeKey + "-peek" + depth
        surface: card.surface
        role: "panel"
        x: 8 * depth
        width: card.width - 16 * depth
        y: Math.max(card.visTop, mainShape.height - 40 + PanelMetrics.stackPeek * depth)
        height: Math.max(0, Math.min(card.visBottom, mainShape.height + PanelMetrics.stackPeek * depth) - y)
        visible: card.stacked >= depth
        glassEnabled: visible && card.onScreen && height > 1 && card.surface !== null
        glassOpacity: card.opacity * (depth === 1 ? 0.9 : 0.75)
        shadow: false
    }
    Peek { depth: 2 }
    Peek { depth: 1 }
    property bool _mainReady: false
    Component.onCompleted: Qt.callLater(() => card._mainReady = true)

    // ---- the card ----------------------------------------------------------------------------------
    Item {
        id: mainShape
        width: card.width
        height: card.height - card.stacked * PanelMetrics.stackPeek
    }
    GlassShape {
        id: shape
        shapeId: card.shapeKey
        surface: card._mainReady ? card.surface : null
        role: "panel"
        x: 0
        y: card.visTop
        width: card.width
        height: Math.max(0, Math.min(card.visBottom, mainShape.height) - card.visTop)
        glassEnabled: card.onScreen && card.surface !== null
        glassOpacity: card.opacity
        shadow: card.visTop <= 0 && card.clipItem === null
        radius: Math.min(Theme.radius.panel, height / 2)
    }

    Column {
        id: content
        x: PanelMetrics.cardPadding
        y: PanelMetrics.cardPadding
        width: card.width - 2 * PanelMetrics.cardPadding
        spacing: 6

        Item {
            width: parent.width
            height: Math.max(PanelMetrics.cardIcon, texts.implicitHeight)
            // app icon
            Item {
                id: iconBox
                width: PanelMetrics.cardIcon
                height: PanelMetrics.cardIcon
                IconImage {
                    id: appIcon
                    anchors.fill: parent
                    source: card.entry ? card.entry.iconSource : ""
                    visible: source !== "" && status === Image.Ready
                    asynchronous: true
                }
                Rectangle {
                    anchors.fill: parent
                    visible: !appIcon.visible
                    radius: 8
                    color: Theme.color(card.scheme, "fillStrong")
                    KIcon { anchors.centerIn: parent; size: 18; name: "fill/bell"; color: Theme.color(card.scheme, "secondaryLabel") }
                }
            }
            Column {
                id: texts
                x: iconBox.width + 10
                width: parent.width - x - (thumb.visible ? thumb.width + 10 : 0)
                spacing: 1
                Item {
                    width: parent.width
                    height: titleText.implicitHeight
                    KText {
                        id: titleText
                        width: parent.width - when.implicitWidth - 8
                        text: card.entry ? (card.entry.summary !== "" ? card.entry.summary : card.entry.displayName) : ""
                        textStyle: "headline"
                        elide: Text.ElideRight
                        scheme: card.scheme
                    }
                    KText {
                        id: when
                        anchors.right: parent.right
                        anchors.verticalCenter: titleText.verticalCenter
                        text: card.entry ? Fmt.ago(card.entry.time, Clock.date) : ""
                        textStyle: "footnote"
                        level: "secondaryLabel"
                        tabular: true
                        scheme: card.scheme
                    }
                }
                KText {
                    width: parent.width
                    visible: text !== ""
                    text: card.entry ? card.entry.body : ""
                    textStyle: "body"
                    wrapMode: Text.Wrap
                    maximumLineCount: card.expandedBody ? 12 : 3
                    elide: Text.ElideRight
                    lineHeightMode: Text.ProportionalHeight
                    lineHeight: 1.0
                    scheme: card.scheme
                }
            }
            Item {
                id: thumb
                visible: card.entry !== null && card.entry.image !== "" && thumbImg.status !== Image.Error
                anchors.right: parent.right
                y: 0
                width: PanelMetrics.cardImage
                height: PanelMetrics.cardImage
                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: Theme.color(card.scheme, "fill")
                    visible: thumbImg.status !== Image.Ready
                }
                RoundedImage {
                    id: thumbImg
                    anchors.fill: parent
                    radius: 8
                    source: card.entry ? card.entry.image : ""
                }
            }
        }

        // progress ("value" hint), updated in place
        Item {
            visible: card.entry !== null && card.entry.progress >= 0
            x: iconBox.width + 10
            width: parent.width - x
            height: 8
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 4
                radius: 2
                color: Theme.color(card.scheme, "trackOff")
                Rectangle {
                    width: parent.width * (card.entry ? Math.max(0, card.entry.progress) / 100 : 0)
                    height: parent.height
                    radius: 2
                    color: Theme.accentFor(card.scheme)
                    Behavior on width { NumberAnimation { duration: Theme.duration("short"); easing.type: Easing.OutQuad } }
                }
            }
        }

        // actions and reply
        Flow {
            visible: card.entry !== null && card.entry.live && (card.entry.actions.length > 0 || card.entry.hasReply) && !replyBox.visible
            x: iconBox.width + 10
            width: parent.width - x
            spacing: 6
            Repeater {
                model: card.entry && card.entry.live ? card.entry.actions.slice(0, 3) : []
                KButton {
                    required property var modelData
                    objectName: "notif.action:" + modelData.id
                    text: modelData.text
                    size: "small"
                    scheme: card.scheme
                    onClicked: Notifs.invokeAction(card.entry, modelData.id)
                }
            }
            KButton {
                visible: card.entry !== null && card.entry.hasReply
                objectName: "notif.reply"
                text: Strings.t("panels.notifications.reply")
                size: "small"
                scheme: card.scheme
                onClicked: {
                    replyBox.visible = true;
                    Qt.callLater(() => replyField.input.forceActiveFocus());
                }
            }
        }
        Row {
            id: replyBox
            visible: false
            x: iconBox.width + 10
            spacing: 6
            KTextField {
                id: replyField
                objectName: "notif.replyField"
                width: content.width - iconBox.width - 10 - sendButton.width - 6
                placeholder: card.entry && card.entry.replyPlaceholder !== "" ? card.entry.replyPlaceholder : Strings.t("panels.notifications.reply")
                scheme: card.scheme
                onAccepted: Notifs.reply(card.entry, text)
                onEscaped: replyBox.visible = false
            }
            KButton {
                id: sendButton
                objectName: "notif.send"
                icon: "fill/paper-plane-tilt"
                variant: "accent"
                size: "regular"
                Accessible.name: Strings.t("panels.notifications.send")
                enabled: replyField.text !== ""
                onClicked: Notifs.reply(card.entry, replyField.text)
            }
        }
    }

    // ---- pointer -------------------------------------------------------------------------------------
    HoverHandler { id: hover }
    TapHandler {
        acceptedButtons: Qt.LeftButton
        onTapped: card.activated()
    }
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: card.menuRequested()
    }
    DragHandler {
        id: swipe
        enabled: card.swipeEnabled
        target: null
        yAxis.enabled: false
        xAxis.minimum: 0
        onTranslationChanged: card.swipeX = Math.max(0, translation.x)
        onActiveChanged: {
            if (!active) {
                if (card.swipeX > 70)
                    card.swiped();
                else
                    card.swipeX = 0;
            }
        }
    }
    property real swipeX: 0
    property real slideX: 0                  // appear / leave animation of the owner
    transform: Translate { x: card.swipeX + card.slideX }
    Behavior on swipeX { enabled: !swipe.active; NumberAnimation { duration: Theme.duration("short"); easing.type: Easing.OutQuad } }

    // close button (hover), top left as on the Mac
    Rectangle {
        id: closeButton
        objectName: "notif.close"
        visible: hover.hovered && !card.replying
        x: -6
        y: -6
        width: 20
        height: 20
        radius: 10
        color: Theme.color(card.scheme, "fallback")
        border.width: 1
        border.color: Theme.color(card.scheme, "border")
        Accessible.role: Accessible.Button
        Accessible.name: Strings.t("panels.notifications.close")
        function activate() { card.closed(); }
        KIcon { anchors.centerIn: parent; size: 10; name: "bold/x"; color: Theme.color(card.scheme, "secondaryLabel") }
        TapHandler { onTapped: card.closed() }
    }
}
