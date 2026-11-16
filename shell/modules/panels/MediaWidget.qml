// SPDX-License-Identifier: GPL-3.0-or-later
// Now Playing (medium widget): art, title and artist, play/pause and next.
import QtQuick
import qs.core
import qs.services

NcWidget {
    id: mw
    width: PanelMetrics.cardWidth
    height: 84
    shapeId: "widget-media"

    Artwork {
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        width: 60; height: 60
        radius: 10
        source: Media.art
        scheme: mw.scheme
    }
    Column {
        x: 84
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - x - controls.width - 16
        KText { width: parent.width; text: Media.title; textStyle: "headline"; elide: Text.ElideRight; scheme: mw.scheme }
        KText { width: parent.width; text: Media.artist || Media.appName; textStyle: "callout"; level: "secondaryLabel"; elide: Text.ElideRight; scheme: mw.scheme }
    }
    Row {
        id: controls
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        KButton {
            objectName: "nc.media.toggle"
            icon: Media.playing ? "fill/pause" : "fill/play"; variant: "plain"; scheme: mw.scheme
            enabled: Media.player !== null && Media.player.canTogglePlaying
            Accessible.name: Media.playing ? Strings.t("panels.media.pause") : Strings.t("panels.media.play")
            onClicked: Media.toggle()
        }
        KButton {
            icon: "fill/skip-forward"; variant: "plain"; scheme: mw.scheme
            enabled: Media.player !== null && Media.player.canGoNext
            Accessible.name: Strings.t("panels.media.next")
            onClicked: Media.next()
        }
    }
}
