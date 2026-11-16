// SPDX-License-Identifier: GPL-3.0-or-later
// Control Center's Now Playing module (2×2): art, title, artist, previous / play-pause / next.
// The art or the title opens the expanded player.
import QtQuick
import qs.core
import qs.services

CcTile {
    id: np
    signal opened()
    width: PanelMetrics.ccHalf
    height: PanelMetrics.ccHalf

    Item {
        id: head
        objectName: "cc.media.open"
        x: 12; y: 12
        width: parent.width - 24
        height: 88
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: Media.title + ", " + Media.artist
        Keys.onReturnPressed: np.opened()
        Keys.onSpacePressed: np.opened()
        function activate() { np.opened(); }
        Artwork {
            width: 48; height: 48
            source: Media.art
            scheme: np.scheme
        }
        Column {
            y: 54
            width: parent.width
            KText { width: parent.width; text: Media.title; textStyle: "callout"; emphasized: true; elide: Text.ElideRight; scheme: np.scheme }
            KText { width: parent.width; text: Media.artist || Media.appName; textStyle: "subheadline"; level: "secondaryLabel"; elide: Text.ElideRight; scheme: np.scheme }
        }
        KFocusRing { targetRadius: 8; scheme: np.scheme }
        TapHandler { onTapped: np.opened() }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - 38
        spacing: 6
        KButton {
            objectName: "cc.media.previous"
            icon: "fill/skip-back"; variant: "plain"; scheme: np.scheme
            enabled: Media.player !== null && Media.player.canGoPrevious
            Accessible.name: Strings.t("panels.media.previous")
            onClicked: Media.previous()
        }
        KButton {
            objectName: "cc.media.toggle"
            icon: Media.playing ? "fill/pause" : "fill/play"; variant: "plain"; scheme: np.scheme
            enabled: Media.player !== null && Media.player.canTogglePlaying
            Accessible.name: Media.playing ? Strings.t("panels.media.pause") : Strings.t("panels.media.play")
            onClicked: Media.toggle()
        }
        KButton {
            objectName: "cc.media.next"
            icon: "fill/skip-forward"; variant: "plain"; scheme: np.scheme
            enabled: Media.player !== null && Media.player.canGoNext
            Accessible.name: Strings.t("panels.media.next")
            onClicked: Media.next()
        }
    }
}
