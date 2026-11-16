// SPDX-License-Identifier: GPL-3.0-or-later
// Put inside any control: shows `text` below it after 0.7 s of hovering (at once while another
// tooltip was just visible). originX/originY = the surface's offset on its output (0,0 for
// surfaces anchored top-left).
import QtQuick

Item {
    id: tip
    property string text: ""
    property real originX: 0
    property real originY: 0
    readonly property Item target: parent
    anchors.fill: parent

    function _show() {
        if (!target || text === "" || !target.Window.window)
            return;
        Tooltips.show(target.Window.window.screen.name, Menus.itemRect(target, originX, originY), text);
    }
    HoverHandler {
        id: hover
        onHoveredChanged: {
            if (hovered && tip.text !== "") {
                if (Tooltips.warm())
                    tip._show();
                else
                    delay.restart();
            } else {
                delay.stop();
                if (Tooltips.current && Tooltips.current.text === tip.text)
                    Tooltips.hide();
            }
        }
    }
    TapHandler {
        gesturePolicy: TapHandler.DragThreshold
        grabPermissions: PointerHandler.ApprovesTakeOverByAnything
        onPressedChanged: if (pressed) { delay.stop(); Tooltips.hide(); }
    }
    Timer {
        id: delay
        interval: 700
        onTriggered: tip._show()
    }
}
