// SPDX-License-Identifier: GPL-3.0-or-later
// One notification as the panels keep it: a snapshot of the server's Notification object (which
// goes away when the app or we close it) that lives on in Notification Centre and across a shell
// restart. While the live object exists every change (a progress update, replaced text) is copied
// at once, so banners and the centre update in place.
import QtQuick
import Quickshell
import Quickshell.Services.Notifications
import qs.services

QtObject {
    id: entry

    property int key: 0                    // our id (stable for the session, persisted)
    property Notification n: null          // the live server object, null once it is closed
    property int serverId: 0
    property string appName: ""
    property string desktopEntry: ""
    property string appIconName: ""        // freedesktop icon name or path the app sent
    property string summary: ""
    property string body: ""
    property string image: ""
    property var actions: []               // [{id, text}] without "default"
    property bool hasDefault: false
    property int urgency: NotificationUrgency.Normal
    property real time: Date.now()
    property real expireTimeout: -1
    property int progress: -1              // 0..100 from the "value" hint, else -1
    property bool hasReply: false
    property string replyPlaceholder: ""
    property bool resident: false
    property bool isTransient: false
    property int senderPid: 0
    property bool live: n !== null

    // group / app identity: the desktop entry when the app names one (that is also how the Dock and
    // the bridge know it), else the application name
    readonly property string appKey: desktopEntry !== "" ? desktopEntry.replace(/\.desktop$/, "").toLowerCase() : appName.toLowerCase()
    readonly property string displayName: {
        Strings.revision;
        const id = desktopEntry.replace(/\.desktop$/, "");
        if (id !== "" && (Apps.entry(id) || Apps.desktopEntry(id)))
            return Apps.displayName(id);
        return appName !== "" ? appName : Strings.t("panels.notifications.unknownApp");
    }
    readonly property string iconSource: {
        const name = appIconName;
        if (name.startsWith("/"))
            return "file://" + name;
        if (name.startsWith("file://") || name.startsWith("image://"))
            return name;
        if (name !== "") {
            const p = Quickshell.iconPath(name, true);
            if (p !== "")
                return p;
        }
        const id = desktopEntry.replace(/\.desktop$/, "");
        const de = id !== "" ? Apps.desktopEntry(id) : null;
        if (de && de.icon)
            return Quickshell.iconPath(de.icon, true);
        return "";
    }
    readonly property bool critical: urgency === NotificationUrgency.Critical

    function _stripMarkup(s) {
        // apps send simple markup even when the server says it does not render it
        return String(s || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "")
            .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&apos;/g, "'").replace(/&amp;/g, "&");
    }

    // Quickshell reports an icon *name* sent as app_icon (libnotify/Flatpak apps) as the
    // notification's image ("image://icon/<name>") with an empty appIcon. It is the app's icon, not
    // content: shown as an image it became the icon theme's magenta "missing" checkerboard whenever
    // the name did not resolve (integration walkthrough). It goes to the app-icon slot instead.
    function _iconFromImage(img) {
        return img.startsWith("image://icon/") ? decodeURIComponent(img.slice("image://icon/".length).split("?")[0]) : "";
    }

    function sync() {
        if (!n)
            return;
        serverId = n.id;
        appName = n.appName || "";
        desktopEntry = n.desktopEntry || "";
        appIconName = n.appIcon || "";
        summary = _stripMarkup(n.summary);
        body = _stripMarkup(n.body);
        const asIcon = _iconFromImage(n.image || "");
        if (asIcon !== "" && appIconName === "")
            appIconName = asIcon;
        image = asIcon !== "" ? "" : (n.image || "");
        urgency = n.urgency;
        expireTimeout = n.expireTimeout;
        resident = n.resident;
        isTransient = n.transient;
        hasReply = n.hasInlineReply;
        replyPlaceholder = n.inlineReplyPlaceholder || "";
        const h = n.hints || {};
        progress = h.value !== undefined ? Math.max(0, Math.min(100, Number(h.value))) : -1;
        senderPid = h["sender-pid"] !== undefined ? Number(h["sender-pid"]) : senderPid;
        const acts = [];
        let def = false;
        for (const a of n.actions) {
            if (a.identifier === "default")
                def = true;
            else if (a.text !== "")
                acts.push({ id: a.identifier, text: a.text });
        }
        actions = acts;
        hasDefault = def;
    }

    // persisted form (images from the server's memory cannot survive a restart)
    function snapshot() {
        return { key: key, appName: appName, desktopEntry: desktopEntry, appIconName: appIconName, summary: summary, body: body,
                 image: image.startsWith("image://") ? "" : image, urgency: urgency, time: time, progress: progress, senderPid: senderPid };
    }

    function invoke(id) {
        if (!n)
            return false;
        for (const a of n.actions) {
            if (a.identifier === id) {
                a.invoke();
                return true;
            }
        }
        return false;
    }

    property Connections _live: Connections {
        target: entry.n
        ignoreUnknownSignals: true
        function onSummaryChanged() { entry.sync(); }
        function onBodyChanged() { entry.sync(); }
        function onHintsChanged() { entry.sync(); }
        function onActionsChanged() { entry.sync(); }
        function onImageChanged() { entry.sync(); }
        function onAppIconChanged() { entry.sync(); }
        function onUrgencyChanged() { entry.sync(); }
        function onClosed(reason) { Notifs._closed(entry, reason); }
    }
}
