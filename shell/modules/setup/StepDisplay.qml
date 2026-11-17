// SPDX-License-Identifier: GPL-3.0-or-later
// Display size as a human choice — larger text ↔ more space — never a percentage. The sizes are
// worked out for this panel (kristall-setup-helper displays: the density a Mac uses for its
// default "looks like" size); choosing one sets the output's scale at once, so this card and
// everything around it change size while the owner watches.
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    icon: "text-aa"
    title: Strings.t("setup.display.title")
    subtitle: Strings.t("setup.display.subtitle")
    cardWidth: 640
    implicitHeight: col.implicitHeight

    readonly property var out: ctl && ctl.helper.displays.length > 0 ? ctl.helper.displays[0] : null
    readonly property var choices: out ? out.choices : []
    property real chosen: -1
    readonly property real current: chosen > 0 ? chosen : (out ? out.scale : 1)
    function nearest() {
        let best = -1, d = 1e9;
        for (let i = 0; i < choices.length; ++i) {
            const x = Math.abs(choices[i].scale - current);
            if (x < d) { d = x; best = i; }
        }
        return best;
    }
    readonly property int currentIndex: { choices; current; return nearest(); }
    function label(i) {
        if (i === 0)
            return Strings.t("setup.display.larger");
        if (i === choices.length - 1)
            return Strings.t("setup.display.space");
        if (out && Math.abs(choices[i].scale - out.recommended) < 0.01)
            return Strings.t("setup.display.default");
        return "";
    }
    function choose(i) {
        const c = choices[i];
        if (!c || !out)
            return;
        chosen = c.scale;
        ctl.helper.run([ctl.helper.tool, "display-scale", out.name, String(c.scale)], r => {
            ctl.helper.run([ctl.helper.tool, "displays"], r2 => { if (r2 && r2.outputs) ctl.helper.displays = r2.outputs; });
        });
    }
    // the output may have changed since the Setup Assistant opened (another display, a scale set
    // elsewhere): ask again whenever this step is shown
    onCtlChanged: if (ctl)
        ctl.helper.run([ctl.helper.tool, "displays"], r => { if (r && r.outputs) ctl.helper.displays = r.outputs; })
    function keyPressed(ev) {
        if (ev.key === Qt.Key_Left || ev.key === Qt.Key_Right) {
            choose(Math.max(0, Math.min(choices.length - 1, currentIndex + (ev.key === Qt.Key_Left ? -1 : 1))));
            return true;
        }
        return false;
    }

    Column {
        id: col
        width: parent.width
        spacing: 16
        KText {
            visible: st.choices.length === 0
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: Strings.t("setup.display.unavailable")
            level: "secondaryLabel"
            scheme: st.scheme
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 12
            Repeater {
                model: st.choices
                ChoiceTile {
                    required property var modelData
                    required property int index
                    objectName: "setup.display." + index
                    selected: index === st.currentIndex
                    label: st.label(index)
                    scheme: st.scheme
                    previewWidth: 96
                    previewHeight: 62
                    previewRadius: 8
                    MiniDesktop {
                        anchors.fill: parent
                        dark: st.scheme === "dark"
                        radius: 8
                        zoom: st.out ? Math.max(0.6, Math.min(1.5, modelData.scale / st.out.recommended)) : 1
                    }
                    onChosen: st.choose(index)
                }
            }
        }
        KText {
            visible: st.choices.length > 0
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: st.out && st.currentIndex >= 0 && Math.abs(st.choices[st.currentIndex].scale - st.out.recommended) < 0.01 ? Strings.t("setup.display.recommended") : " "
            textStyle: "caption1"
            level: "secondaryLabel"
            scheme: st.scheme
        }
    }
}
