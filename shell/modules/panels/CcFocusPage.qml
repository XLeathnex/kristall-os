// SPDX-License-Identifier: GPL-3.0-or-later
// Expanded Focus module: Do Not Disturb with the Mac's durations. While it is on, banners stay
// away (critical ones still come); everything is collected in Notification Centre.
import QtQuick
import qs.core
import qs.services

Column {
    id: fp
    property string scheme: Theme.scheme
    property var cc: null
    width: PanelMetrics.ccInner
    spacing: 4

    readonly property date now: Clock.date
    function at(h, dayOffset) {
        const d = new Date();
        d.setDate(d.getDate() + dayOffset);
        d.setHours(h, 0, 0, 0);
        return d.getTime();
    }
    readonly property var options: {
        now;
        const hour = new Date().getHours();
        const list = [{ key: "hour", label: Strings.t("panels.focus.hour"), until: () => Date.now() + 3600 * 1000 }];
        if (hour < 18)
            list.push({ key: "evening", label: Strings.t("panels.focus.evening"), until: () => fp.at(19, 0) });
        list.push({ key: "morning", label: Strings.t("panels.focus.morning"), until: () => fp.at(7, hour < 5 ? 0 : 1) });
        list.push({ key: "forever", label: Strings.t("panels.focus.forever"), until: () => -1 });
        return list;
    }

    CcHeader {
        title: Strings.t("panels.focus.title")
        scheme: fp.scheme
        hasToggle: true
        toggleName: "cc.focus.switch"
        checked: Notifs.dnd
        onToggled: on => Notifs.setDnd(on ? -1 : 0)
        onBack: fp.cc.back()
    }
    CcItemRow {
        width: PanelMetrics.ccInner
        icon: "fill/moon"
        on: Notifs.dnd
        title: Strings.t("panels.focus")
        subtitle: Notifs.dnd ? Fmt.until(Notifs.dndUntil) : Strings.t("panels.focus.hint")
        scheme: fp.scheme
        objectName: "cc.focus.dnd"
        onActivated: Notifs.setDnd(Notifs.dnd ? 0 : -1)
    }
    KSeparator { x: 10; width: parent.width - 20; scheme: fp.scheme }
    Repeater {
        model: fp.options
        CcItemRow {
            required property var modelData
            objectName: "cc.focus." + modelData.key
            width: PanelMetrics.ccInner
            circle: false
            icon: "clock"
            title: modelData.label
            scheme: fp.scheme
            onActivated: {
                Notifs.setDnd(modelData.until());
                fp.cc.back();
            }
        }
    }
    Item { width: 1; height: 2 }
}
