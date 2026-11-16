// SPDX-License-Identifier: GPL-3.0-or-later
// Last row of an expanded module: a separator and "<…> Settings …" that opens System Settings.
import QtQuick
import qs.core
import qs.services

Column {
    id: ft
    property string text: ""
    property string scheme: Theme.scheme
    property string kcm: ""
    signal activated()
    width: PanelMetrics.ccInner
    spacing: 4
    KSeparator { width: parent.width; scheme: ft.scheme }
    KListRow {
        objectName: "cc.settings"
        width: parent.width
        compact: true
        title: ft.text + Strings.t("common.ellipsis")
        scheme: ft.scheme
        onActivated: {
            ft.activated();
            if (ft.kcm !== "")
                Session.openSystemSettings(ft.kcm);
        }
    }
}
