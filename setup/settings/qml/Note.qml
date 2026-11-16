// SPDX-License-Identifier: GPL-3.0-or-later
// A line of explanation under a control: secondary colour, wraps, never jargon.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Label {
    Layout.maximumWidth: Kirigami.Units.gridUnit * 26
    Layout.fillWidth: true
    wrapMode: Text.WordWrap
    color: Kirigami.Theme.disabledTextColor
    font: Kirigami.Theme.smallFont
}
