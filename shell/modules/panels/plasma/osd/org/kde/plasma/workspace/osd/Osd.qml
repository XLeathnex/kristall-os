// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall: replaces Plasma's on-screen display (volume, brightness, keyboard layout …) with
// nothing. plasmashell (6.8) creates its OSD from the QML module org.kde.plasma.workspace.osd;
// our plasmashell unit drop-in puts this directory first on QML_IMPORT_PATH, so this object is
// created instead of Plasma's window. Plasma still handles the keys and still announces every OSD
// on D-Bus (org.kde.osdService signals osdProgress/osdText), which the Kristall shell's panels
// module turns into its own HUD. Nothing here draws or allocates a window.
import QtQuick

QtObject {
    // the properties plasmashell's Osd sets on its root object
    property bool visible: false
    property bool animateOpacity: false
    property real opacity: 1
    property int timeout: 0
    property var osdValue: 0
    property int osdMaxValue: 100
    property string osdAdditionalText: ""
    property string icon: ""
    property bool showingProgress: false
}
