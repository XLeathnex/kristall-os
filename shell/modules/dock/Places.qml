// SPDX-License-Identifier: GPL-3.0-or-later
// The Dock's Downloads folder and Trash: state from the file system (inotify through
// FolderListModel — no polling), opening them in Files, emptying the Trash.
import QtQuick
import Qt.labs.folderlistmodel
import Quickshell
import Quickshell.Io

Scope {
    id: places
    readonly property string home: Quickshell.env("HOME")
    readonly property string dataHome: Quickshell.env("XDG_DATA_HOME") || (home + "/.local/share")
    readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") || (home + "/.config")
    readonly property string trashFiles: dataHome + "/Trash/files"
    readonly property bool trashFull: trashModel.count > 0
    readonly property int trashCount: trashModel.count

    // XDG_DOWNLOAD_DIR from user-dirs.dirs (localised folder names), else ~/Downloads
    readonly property string downloads: {
        const t = userDirs.text();
        const m = t.match(/^XDG_DOWNLOAD_DIR="([^"]*)"/m);
        return m ? m[1].replace("$HOME", home) : home + "/Downloads";
    }
    FileView {
        id: userDirs
        path: places.configHome + "/user-dirs.dirs"
        blockLoading: true
        printErrors: false
    }

    FolderListModel {
        id: trashModel
        folder: "file://" + places.trashFiles
        showHidden: true
        showDirs: true
        showDotAndDotDot: false
    }
    FolderListModel {
        id: downloadsModel
        folder: "file://" + places.downloads
        showDirs: true
        showHidden: false
        sortField: FolderListModel.Time
    }
    // newest first: [{name, path}]
    function recentDownloads(n) {
        const out = [];
        for (let i = 0; i < Math.min(n, downloadsModel.count); ++i)
            out.push({ name: downloadsModel.get(i, "fileName"), path: downloadsModel.get(i, "filePath") });
        return out;
    }

    function open(path) {
        Quickshell.execDetached(["xdg-open", path]);
    }
    // Files with the item selected (org.freedesktop.FileManager1, implemented by Dolphin)
    function reveal(path) {
        Quickshell.execDetached(["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                                 "--object-path", "/org/freedesktop/FileManager1", "--method",
                                 "org.freedesktop.FileManager1.ShowItems", "['file://" + encodeURI(path).replace(/'/g, "%27") + "']", ""]);
    }
    function openTrash() {
        Quickshell.execDetached(["sh", "-c", "command -v dolphin >/dev/null && exec dolphin trash:/ || exec xdg-open trash:///"]);
    }
    // KDE's own tool (kde-cli-tools, part of Plasma), else GIO; both follow the trash spec
    function emptyTrash() {
        Quickshell.execDetached(["sh", "-c", "command -v ktrash6 >/dev/null && exec ktrash6 --empty || exec gio trash --empty"]);
    }
}
