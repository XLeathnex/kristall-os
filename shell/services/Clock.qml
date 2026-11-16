// SPDX-License-Identifier: GPL-3.0-or-later
// Wall clock for the menu bar in the Mac format of the system locale. Wakes once a minute,
// on the minute (once a second only while bar.showSeconds is on); re-aligns after resume or a
// time-zone change (helper event), so it never polls.
pragma Singleton
import QtQuick
import Quickshell

Singleton {
    id: root

    readonly property bool seconds: Settings.get("bar.showSeconds", false)
    readonly property var date: clock.date
    readonly property var locale: Strings.locale
    // 24-hour clock unless the locale uses AM/PM; bar.clock "12h"/"24h" overrides
    readonly property bool use24h: {
        const pref = Settings.get("bar.clock", "auto");
        if (pref === "12h") return false;
        if (pref === "24h") return true;
        return locale.timeFormat(Locale.ShortFormat).indexOf("AP") < 0 && locale.timeFormat(Locale.ShortFormat).indexOf("ap") < 0;
    }
    readonly property bool dayFirst: locale.dateFormat(Locale.ShortFormat).search(/d/i) < locale.dateFormat(Locale.ShortFormat).search(/M/)

    // "Mo. 16. Nov. 09:41" (de), "Mon Nov 16 9:41 AM" (en_US), "Mon 16 Nov 09:41" (en_GB)
    function barText(d) {
        const parts = [];
        if (Settings.get("bar.showDayOfWeek", true))
            parts.push(locale.toString(d, "ddd"));
        if (Settings.get("bar.showDate", true))
            parts.push(dayFirst ? locale.toString(d, Strings.lang === "de" ? "d. MMM" : "d MMM") : locale.toString(d, "MMM d"));
        let t = locale.toString(d, use24h ? (seconds ? "HH:mm:ss" : "HH:mm") : (seconds ? "h:mm:ss AP" : "h:mm AP"));
        parts.push(t);
        return parts.join(" ");
    }

    function longDate(d) {
        return locale.toString(d, Locale.LongFormat).replace(/ \d\d?:\d\d.*$/, "");
    }

    SystemClock {
        id: clock
        precision: root.seconds ? SystemClock.Seconds : SystemClock.Minutes
    }

    Connections {
        target: Helper
        function onEvent(ev) {
            if (ev.event === "time.changed") {
                clock.enabled = false;
                clock.enabled = true;
            }
        }
    }
}
