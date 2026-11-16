// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Services.Mpris
import qs.services


// "Now playing" for Control Center and Notification Centre: the MPRIS player that is playing
// (the one that started most recently wins), else the last one that played, else any player
// that has a track. No player → `player` is null and the tiles give their place to others.
Singleton {
    id: root

    readonly property var players: Mpris.players ? Mpris.players.values : []
    property var _lastPlaying: null
    readonly property var player: {
        let paused = null;
        for (const p of players) {
            if (p.isPlaying)
                return p;
        }
        if (_lastPlaying && players.indexOf(_lastPlaying) >= 0)
            return _lastPlaying;
        for (const p of players)
            if (p.trackTitle !== "" && p.playbackState !== MprisPlaybackState.Stopped)
                paused = paused || p;
        return paused;
    }
    onPlayerChanged: if (player && player.isPlaying) _lastPlaying = player
    readonly property bool available: player !== null
    readonly property bool playing: player !== null && player.isPlaying
    readonly property string title: player ? (player.trackTitle || player.identity) : ""
    readonly property string artist: player ? (player.trackArtist || "") : ""
    readonly property string album: player ? (player.trackAlbum || "") : ""
    readonly property string art: player ? (player.trackArtUrl || "") : ""
    readonly property string appName: player ? (player.desktopEntry ? Apps.displayName(player.desktopEntry) : player.identity) : ""
    readonly property string appIcon: {
        if (!player || !player.desktopEntry)
            return "";
        const d = Apps.desktopEntry(player.desktopEntry);
        return d && d.icon ? Quickshell.iconPath(d.icon, true) : "";
    }

    function toggle() {
        if (player && player.canTogglePlaying)
            player.togglePlaying();
    }
    function next() {
        if (player && player.canGoNext)
            player.next();
    }
    function previous() {
        if (player && player.canGoPrevious)
            player.previous();
    }
    function raise() {
        if (player && player.canRaise)
            player.raise();
    }

    Connections {
        target: root.player
        ignoreUnknownSignals: true
        function onIsPlayingChanged() {
            if (root.player && root.player.isPlaying)
                root._lastPlaying = root.player;
        }
    }
}
