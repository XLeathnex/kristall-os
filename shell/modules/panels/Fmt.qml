// SPDX-License-Identifier: GPL-3.0-or-later
// See the comment below the imports.
pragma Singleton
import QtQuick
import Quickshell
import qs.services


// Small formatting helpers for the panels (times, durations, relative times) in the system
// language and clock style.
Singleton {
    function time(d) {
        return Strings.locale.toString(d, Clock.use24h ? "HH:mm" : "h:mm AP");
    }
    // "3:20" for seconds
    function duration(sec) {
        const m = Math.round(sec / 60);
        return Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0");
    }
    // "3:07" for a position in a track (seconds)
    function clock(sec) {
        const s = Math.max(0, Math.floor(sec));
        const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, r = s % 60;
        return (h > 0 ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(r).padStart(2, "0");
    }
    function sameDay(a, b) {
        return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }
    // when a notification arrived, as the Mac shows it: "jetzt", "vor 5 Min.", "14:02", "Gestern", "12.11."
    function ago(ms, now) {
        const n = now ? now.getTime() : Date.now();
        const diff = Math.max(0, n - ms);
        if (diff < 60 * 1000)
            return Strings.t("panels.notifications.now");
        if (diff < 60 * 60 * 1000)
            return Strings.t("panels.notifications.minutesAgo", { n: Math.floor(diff / 60000) });
        const d = new Date(ms);
        const today = now || new Date(n);
        if (sameDay(d, today))
            return time(d);
        const y = new Date(today.getTime() - 24 * 3600 * 1000);
        if (sameDay(d, y))
            return Strings.t("panels.notifications.yesterday");
        return Strings.locale.toString(d, Strings.lang === "de" ? "d.M." : "d MMM");
    }
    // "Bis 15:30" / "Bis morgen, 7:00" for Do Not Disturb
    function until(ms) {
        if (ms === -1)
            return Strings.t("panels.focus.on");
        const d = new Date(ms);
        if (sameDay(d, new Date()))
            return Strings.t("panels.focus.until", { time: time(d) });
        return Strings.t("panels.focus.untilTomorrow", { time: time(d) });
    }
}
