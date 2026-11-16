// SPDX-License-Identifier: GPL-3.0-or-later
// German or English, following the system language (KRISTALL_LANG overrides, for tests).
pragma Singleton
import QtQuick

QtObject {
    readonly property string lang: {
        const forced = System.env("KRISTALL_LANG", "");
        const name = forced !== "" ? forced : Qt.locale().name;
        return name.startsWith("de") ? "de" : "en";
    }
    function t(de, en) { return lang === "de" ? de : en; }
    // a setting, as a binding that follows changes (reading Settings.data makes it a dependency)
    function setting(path, fallback) {
        Settings.data;
        return Settings.value(path, fallback);
    }
    function pick(o) {
        if (!o)
            return "";
        if (typeof o === "string")
            return o;
        return o[lang] || o.en || "";
    }
}
