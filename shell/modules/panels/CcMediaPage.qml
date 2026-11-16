// SPDX-License-Identifier: GPL-3.0-or-later
// Expanded Now Playing: larger art, title, artist and album, position (refreshed once a second
// only while this is on screen and playing), transport, open the player.
import QtQuick
import qs.core
import qs.services

Column {
    id: mpage
    property string scheme: Theme.scheme
    property var cc: null
    width: PanelMetrics.ccInner
    spacing: 8

    CcHeader {
        title: Media.appName || Strings.t("panels.media")
        scheme: mpage.scheme
        onBack: mpage.cc.back()
    }
    CcNote {
        visible: !Media.available
        text: Strings.t("panels.media.none")
        scheme: mpage.scheme
    }
    Row {
        visible: Media.available
        x: 6
        spacing: 12
        Artwork { width: 72; height: 72; radius: 12; source: Media.art; scheme: mpage.scheme }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            width: PanelMetrics.ccInner - 72 - 24
            KText { width: parent.width; text: Media.title; textStyle: "body"; emphasized: true; elide: Text.ElideRight; scheme: mpage.scheme }
            KText { width: parent.width; text: Media.artist; textStyle: "callout"; level: "secondaryLabel"; elide: Text.ElideRight; scheme: mpage.scheme; visible: text !== "" }
            KText { width: parent.width; text: Media.album; textStyle: "subheadline"; level: "tertiaryLabel"; elide: Text.ElideRight; scheme: mpage.scheme; visible: text !== "" }
        }
    }
    Item {
        id: progress
        visible: Media.available && Media.player.lengthSupported && Media.player.length > 0
        x: 6
        width: parent.width - 12
        height: 30
        readonly property real len: Media.player ? Media.player.length : 0
        readonly property real pos: Media.player && Media.player.positionSupported ? Media.player.position : 0
        KSlider {
            id: posSlider
            objectName: "cc.media.position"
            width: parent.width
            from: 0
            to: Math.max(1, progress.len)
            value: progress.pos
            scheme: mpage.scheme
            enabled: Media.player !== null && Media.player.canSeek
            onMoved: v => { if (Media.player) Media.player.position = v; }
        }
        KText { anchors.left: parent.left; anchors.bottom: parent.bottom; text: Fmt.clock(progress.pos); textStyle: "caption1"; level: "secondaryLabel"; tabular: true; scheme: mpage.scheme }
        KText { anchors.right: parent.right; anchors.bottom: parent.bottom; text: "−" + Fmt.clock(Math.max(0, progress.len - progress.pos)); textStyle: "caption1"; level: "secondaryLabel"; tabular: true; scheme: mpage.scheme }
        Timer {
            // the player does not push its position; once a second while it is visible and playing
            running: progress.visible && Media.playing
            interval: 1000
            repeat: true
            onTriggered: if (Media.player) Media.player.positionChanged()
        }
    }
    Row {
        visible: Media.available
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 16
        KButton { icon: "fill/skip-back"; size: "large"; variant: "plain"; scheme: mpage.scheme; enabled: Media.player !== null && Media.player.canGoPrevious; Accessible.name: Strings.t("panels.media.previous"); onClicked: Media.previous() }
        KButton { objectName: "cc.media.page.toggle"; icon: Media.playing ? "fill/pause" : "fill/play"; size: "large"; variant: "plain"; scheme: mpage.scheme; enabled: Media.player !== null && Media.player.canTogglePlaying; Accessible.name: Media.playing ? Strings.t("panels.media.pause") : Strings.t("panels.media.play"); onClicked: Media.toggle() }
        KButton { icon: "fill/skip-forward"; size: "large"; variant: "plain"; scheme: mpage.scheme; enabled: Media.player !== null && Media.player.canGoNext; Accessible.name: Strings.t("panels.media.next"); onClicked: Media.next() }
    }
    CcFooter {
        visible: Media.player !== null && Media.player.canRaise
        text: Strings.t("panels.media.open", { app: Media.appName })
        scheme: mpage.scheme
        onActivated: {
            Media.raise();
            mpage.cc.closeRequested();
        }
    }
}
